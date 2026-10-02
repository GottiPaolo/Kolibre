import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, Optional

logger = logging.getLogger("kolibre.calibre.write_queue")

# Registry mapping op_type -> handler(library_path, payload) -> result.
# CalibreLibrary registers its own mutating methods here (see calibre/library.py)
# so that a failed write can be persisted as (op_type, payload) and rebuilt/retried
# later without needing to serialize a Python closure.
_OP_REGISTRY: Dict[str, Callable[[str, dict], object]] = {}


def register_op(op_type: str):
    def decorator(fn: Callable[[str, dict], object]):
        _OP_REGISTRY[op_type] = fn
        return fn
    return decorator


def get_registered_op(op_type: str) -> Callable[[str, dict], object]:
    if op_type not in _OP_REGISTRY:
        raise KeyError(f"Nessun operatore registrato per op_type={op_type!r}")
    return _OP_REGISTRY[op_type]


@dataclass
class WriteJob:
    library_path: str
    op_type: str
    payload: dict
    attempts: int = 0
    result_future: Optional["asyncio.Future"] = field(default=None, repr=False)
    # Set for jobs re-submitted from the pending_calibre_writes table itself
    # (see retry_pending): the caller already owns a durable row for this
    # write and updates it directly on failure, so the queue must not also
    # call on_permanent_failure and insert *another* row for the same retry —
    # that is exactly what caused a failing write to double its pending row
    # count on every drain cycle (an unbounded, exponentially growing table).
    skip_persist_on_failure: bool = False


class CalibreWriteQueue:
    """
    Single-worker serial queue for all metadata.db mutations.

    Every write to a given Calibre library goes through here rather than opening
    a connection directly, guaranteeing writes never run concurrently across request
    handlers (WAL + concurrent writers is still one-writer-at-a-time under the hood;
    serializing them ourselves avoids SQLITE_BUSY entirely instead of just tolerating
    it via busy_timeout). Jobs that still fail after `max_attempts` retries are handed
    to `on_permanent_failure` for durable persistence (see calibre/library.py's
    `pending_calibre_writes` fallback).
    """

    def __init__(
        self,
        max_attempts: int = 5,
        retry_delay_seconds: float = 1.0,
        on_permanent_failure: Optional[Callable[[WriteJob, Exception], None]] = None,
    ):
        self._queue: "asyncio.Queue[WriteJob]" = asyncio.Queue()
        self._max_attempts = max_attempts
        self._retry_delay_seconds = retry_delay_seconds
        self._on_permanent_failure = on_permanent_failure
        self._worker_task: Optional[asyncio.Task] = None

    def start(self) -> None:
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._worker_task is not None:
            self._worker_task.cancel()
            self._worker_task = None

    async def submit(self, op_type: str, payload: dict, library_path: str, _skip_persist_on_failure: bool = False):
        """Enqueue a write and wait until it has been applied, returning the
        handler's return value (or re-raising if it permanently failed)."""
        loop = asyncio.get_running_loop()
        job = WriteJob(
            library_path=library_path, op_type=op_type, payload=payload,
            skip_persist_on_failure=_skip_persist_on_failure,
        )
        job.result_future = loop.create_future()
        await self._queue.put(job)
        return await job.result_future

    async def _run(self) -> None:
        """Il ciclo del lavoratore. Non deve morire MAI.

        Se un'eccezione sfugge da qui, il task si spegne e da quel momento ogni
        scrittura su metadata.db — metadati, import, cancellazioni — resta
        appesa per sempre: `submit()` aspetta un future che nessuno risolvera'
        piu', e non ha timeout. `_worker_task` resterebbe non-None, quindi
        nemmeno `start()` lo farebbe ripartire.

        Due modi in cui succedeva davvero. `get_registered_op` stava FUORI dal
        try di `_execute`: una riga di `pending_calibre_writes` con un
        `op_type` non piu' registrato (quella tabella sopravvive agli
        aggiornamenti, le op no) alzava KeyError e uccideva il lavoratore. E
        `_on_permanent_failure` veniva chiamato DENTRO l'except: se anche lui
        falliva — per esempio «database is locked» mentre salva la scrittura
        in sospeso — la sua eccezione usciva dal gestore.
        """
        while True:
            job = await self._queue.get()
            try:
                await self._execute(job)
            except Exception as exc:
                # Rete di sicurezza ultima: qualunque cosa sia successa, il
                # chiamante deve ricevere una risposta e il ciclo deve
                # continuare. Un errore su una scrittura non puo' diventare
                # un'applicazione che non scrive piu'.
                logger.exception("Lavoratore della coda di scrittura: errore non previsto")
                if job.result_future and not job.result_future.done():
                    job.result_future.set_exception(exc)

    async def _execute(self, job: WriteJob) -> None:
        loop = asyncio.get_running_loop()
        try:
            handler = get_registered_op(job.op_type)
        except Exception as exc:
            # Op non registrata: e' un errore di questa scrittura, non del
            # lavoratore. Vedi _run per com'e' successo.
            logger.error("Operazione di scrittura sconosciuta: %s", job.op_type)
            if job.result_future and not job.result_future.done():
                job.result_future.set_exception(exc)
            return
        while True:
            job.attempts += 1
            try:
                result = await loop.run_in_executor(None, handler, job.library_path, job.payload)
                if job.result_future and not job.result_future.done():
                    job.result_future.set_result(result)
                return
            except ValueError as exc:
                # A validation/business-logic rejection raised by the
                # CalibreLibrary method itself (e.g. "can't remove the only
                # remaining format") — not a transient DB issue, so surface it
                # immediately rather than treating it as a write that needs
                # retrying/persisting to pending_calibre_writes.
                if job.result_future and not job.result_future.done():
                    job.result_future.set_exception(exc)
                return
            except Exception as exc:
                is_locked = "locked" in str(exc).lower()
                if job.attempts >= self._max_attempts or not is_locked:
                    logger.error(
                        "Scrittura Calibre fallita definitivamente (%s/%s): %s",
                        job.op_type, job.library_path, exc,
                    )
                    if self._on_permanent_failure and not job.skip_persist_on_failure:
                        try:
                            self._on_permanent_failure(job, exc)
                        except Exception:
                            # Non riuscire a REGISTRARE il fallimento non deve
                            # diventare un fallimento peggiore: si annota e si
                            # va avanti a rispondere al chiamante.
                            logger.exception(
                                "Impossibile salvare la scrittura fallita in pending_calibre_writes"
                            )
                    if job.result_future and not job.result_future.done():
                        job.result_future.set_exception(exc)
                    return
                logger.warning(
                    "metadata.db locked, ritento (%s/%s) op=%s lib=%s",
                    job.attempts, self._max_attempts, job.op_type, job.library_path,
                )
                await asyncio.sleep(self._retry_delay_seconds * job.attempts)


def serialize_pending(job: WriteJob, error: Exception) -> dict:
    return {
        "library_path": job.library_path,
        "op_type": job.op_type,
        "payload_json": json.dumps(job.payload),
        "attempts": job.attempts,
        "last_error": str(error),
        "created_at": datetime.utcnow(),
    }


async def retry_one_pending(queue: CalibreWriteQueue, op_type: str, payload_json: str, library_path: str) -> None:
    """
    Re-submits a single job read from the `pending_calibre_writes` table.
    Raises on failure — the caller (owning that row) is responsible for
    updating its attempts/last_error or deleting it on success; this must
    NOT cause the queue to persist a *new* pending row for the same retry
    (see WriteJob.skip_persist_on_failure).
    """
    await queue.submit(op_type, json.loads(payload_json), library_path, _skip_persist_on_failure=True)
