from typing import NamedTuple, Optional

from sqlalchemy import tuple_
from sqlalchemy.orm import Session

from .. import models
from . import koreader_hash, text_fingerprint, widowed_highlights


class BookMatch(NamedTuple):
    """
    Deliberately exposes the same three attribute names a models.BookHash row
    does (library / calibre_book_id / format): every call site in devices.py
    used to hold a BookHash instance, and this lets them switch to the
    three-tier resolver without touching the code that reads the result.
    """
    library: str
    calibre_book_id: int
    format: Optional[str]


def resolve_by_identity(db: Session, library, calibre_book_id, format=None) -> Optional[BookMatch]:
    """
    Il libro detto per NOME: biblioteca, id Calibre, formato. Nessun confronto
    di contenuti.

    **Perche' questa esiste.** Fino al 06/10/2026 un dispositivo diceva quale
    libro intendeva mandando l'impronta parziale del file, e il server la
    risolveva all'indietro con tre livelli di ripiego (vedi
    resolve_book_matches). Ma il dispositivo l'identita' ce l'ha gia': il
    plugin tiene un elenco dei libri che Kolibre gli ha consegnato, indicizzato
    proprio per (biblioteca, id, formato). Mandava l'impronta e buttava via il
    nome — e quando l'impronta era stantia da tutte e tre le parti, la nota
    diventava orfana pur sapendo benissimo a quale libro apparteneva.

    L'identita' non si rompe quando un file viene riscritto, da nessuno dei due
    lati, perche' non guarda i byte. L'impronta resta e serve, ma per l'altro
    lavoro: accoppiare i libri che sul dispositivo ci sono gia' e in Kolibre
    no, dove un'identita' condivisa non esiste e confrontare i contenuti e'
    l'unica strada.

    Si controlla che il libro esista davvero: un'identita' che punta a un libro
    cancellato non vale piu' di un'impronta che punta a un id morto, e lasciarla
    passare rifarebbe le note vedove da un'altra porta.
    """
    if not library or calibre_book_id is None:
        return None
    try:
        calibre_book_id = int(calibre_book_id)
    except (TypeError, ValueError):
        return None
    match = BookMatch(str(library), calibre_book_id, format.upper() if isinstance(format, str) else format)
    return match if _vivo(match) else None


def _identita_da(item: dict):
    """I tre campi dell'identita' come li manda il plugin, se ci sono."""
    if not isinstance(item, dict):
        return None, None, None
    return item.get("library"), item.get("calibre_book_id"), item.get("format")


def resolve_from_item(db: Session, item: dict, device_id: Optional[int] = None) -> Optional[BookMatch]:
    """
    Da quello che il dispositivo manda al libro: **prima il nome, poi
    l'impronta**.

    E' il punto unico attraverso cui passano tutti gli endpoint del
    dispositivo (annotazioni, posizione, pagine, elenco dei libri gestiti).
    L'ordine non e' una preferenza: un'identita' che risolve e' certa, una
    impronta che risolve e' una deduzione — e abbiamo misurato il 04/10 che
    quella deduzione sbaglia.

    Se l'identita' non c'e' (plugin vecchio, o un libro che Kolibre non ha mai
    consegnato) si ricade sull'impronta esattamente come prima: nessun
    comportamento cambia per chi non manda i campi nuovi.
    """
    library, calibre_book_id, formato = _identita_da(item)
    per_nome = resolve_by_identity(db, library, calibre_book_id, formato)
    if per_nome:
        return per_nome
    file_hash = item.get("hash") if isinstance(item, dict) else None
    if not file_hash:
        return None
    return resolve_first_book_match(db, file_hash, device_id=device_id)


def resolve_identities_from_item(db: Session, item: dict, device_id: Optional[int] = None) -> list:
    """
    Come resolve_from_item ma restituisce la lista di (library,
    calibre_book_id) — per i chiamanti che devono applicare la stessa cosa a
    tutte le copie dello stesso file in piu' biblioteche.

    Con l'identita' la lista ha sempre un elemento solo, ed e' giusto cosi':
    il dispositivo ha detto QUALE, non «un libro con questi byte».
    """
    library, calibre_book_id, formato = _identita_da(item)
    per_nome = resolve_by_identity(db, library, calibre_book_id, formato)
    if per_nome:
        return [(per_nome.library, per_nome.calibre_book_id)]
    file_hash = item.get("hash") if isinstance(item, dict) else None
    if not file_hash:
        return []
    return resolve_book_identities(db, file_hash, device_id=device_id)


def resolve_book_matches(db: Session, file_hash: str, device_id: Optional[int] = None) -> list:
    """
    Da un hash KOReader ai BookMatch(library, calibre_book_id, format) che
    rappresenta. Normalmente uno solo, ma lo STESSO file caricato in più
    librerie produce lo stesso hash, quindi vale per tutte.

    Tre livelli, dal più affidabile al più indiretto:

    1. BookHash vivo: l'hash del file così com'è adesso sul server.
    2. BookHashHistory: il server riscrive i file quando incorpora metadati,
       copertina o conteggio pagine (opf_metadata.py), e questo cambia i byte
       campionati dall'hash parziale pur senza toccare il contenuto del
       libro. Un dispositivo che aveva scaricato e hashato la copia
       PRECEDENTE resterebbe altrimenti con un hash che il server non
       riconosce più.
    3. Solo se `device_id` è dato: l'hash che abbiamo REGISTRATO di avere
       consegnato a quel dispositivo (DeviceBook.delivery_hash). Copre i
       libri riscritti prima che BookHashHistory esistesse, per i quali non
       c'è nulla da archiviare a posteriori. Ci si fida solo dell'hash
       consegnato a QUEL dispositivo, non di una corrispondenza globale.

    Non è un caso di scuola: su un impianto reale, dopo una riscrittura in
    blocco, 129 dei 232 libri presenti su un Kindle avevano un hash non più
    vivo — e la posizione di lettura che il dispositivo mandava per quei
    libri veniva rifiutata con 404 e persa (vedi push_reading_progress).

    Sopra i tre livelli c'è un filtro che vale per tutti (_preferisci_vivi):
    una corrispondenza può puntare a un libro che non esiste più, ed è così
    che nascono le note vedove. Le corrispondenze morte si scartano se ce
    n'è una viva, e se sono tutte morte si tenta il salto per impronta di
    contenuto — il caso del libro cancellato per correggerne l'EPUB e
    reimportato con un id nuovo.
    """
    rows = db.query(
        models.BookHash.library, models.BookHash.calibre_book_id, models.BookHash.format
    ).filter(models.BookHash.file_hash == file_hash).order_by(
        models.BookHash.library, models.BookHash.calibre_book_id
    ).distinct().all()
    if rows:
        return _preferisci_vivi(db, [BookMatch(r.library, r.calibre_book_id, r.format) for r in rows])

    history_rows = db.query(
        models.BookHashHistory.library, models.BookHashHistory.calibre_book_id,
        models.BookHashHistory.format,
    ).filter(models.BookHashHistory.file_hash == file_hash).order_by(
        models.BookHashHistory.library, models.BookHashHistory.calibre_book_id
    ).distinct().all()
    if history_rows:
        return _preferisci_vivi(db, [BookMatch(r.library, r.calibre_book_id, r.format) for r in history_rows])

    if device_id is None:
        return []
    delivered = db.query(
        models.DeviceBook.library, models.DeviceBook.calibre_book_id, models.DeviceBook.format
    ).filter(
        models.DeviceBook.device_id == device_id, models.DeviceBook.delivery_hash == file_hash
    ).order_by(models.DeviceBook.library, models.DeviceBook.calibre_book_id).distinct().all()
    return _preferisci_vivi(db, [BookMatch(r.library, r.calibre_book_id, r.format) for r in delivered])


def _vivo(match: BookMatch) -> bool:
    """None (libreria non leggibile) vale VIVO: nel dubbio non si scarta."""
    ids = widowed_highlights.ids_libri_esistenti(match.library)
    return ids is None or match.calibre_book_id in ids


def _preferisci_vivi(db: Session, matches: list) -> list:
    """
    Un hash puo' risolvere a un libro che non esiste piu': le righe BookHash
    dei libri cancellati prima che esistesse la cascata di release_book sono
    rimaste li', e continuano a rispondere. E' cosi' che nascono le note
    vedove (vedi services/widowed_highlights.py) — il dispositivo manda una
    nota, l'hash "risolve", e la nota si attacca a un id morto.

    Se almeno una corrispondenza e' viva si tengono solo quelle. Se sono
    tutte morte si prova il salto per IMPRONTA DI CONTENUTO: il caso tipico
    e' un libro cancellato per correggerne l'EPUB e reimportato, che ha id e
    byte nuovi ma lo stesso testo, quindi la stessa impronta. E' l'unico
    livello che non si fida dei byte, ed e' il motivo per cui l'impronta
    viene calcolata: finora stava nel database senza che nessuno la
    interrogasse, tranne /identify-file, che pretende dal dispositivo il
    caricamento dell'intero EPUB.

    Se anche il salto fallisce si restituiscono le corrispondenze morte, come
    prima: meglio una nota vedova — che ora ha un nome e si ricollega — che
    una nota scartata.
    """
    if not matches:
        return matches
    vivi = [m for m in matches if _vivo(m)]
    if vivi:
        return vivi
    gemelli = _per_impronta(db, matches)
    return gemelli or matches


def _per_impronta(db: Session, morti: list) -> list:
    impronte = {
        r[0] for r in db.query(models.BookHash.content_fingerprint).filter(
            models.BookHash.content_fingerprint.isnot(None),
            tuple_(models.BookHash.library, models.BookHash.calibre_book_id).in_(
                [(m.library, m.calibre_book_id) for m in morti]
            ),
        ).all()
    }
    if not impronte:
        return []
    morti_ids = {(m.library, m.calibre_book_id) for m in morti}
    candidati = db.query(
        models.BookHash.library, models.BookHash.calibre_book_id, models.BookHash.format
    ).filter(
        models.BookHash.content_fingerprint.in_(impronte)
    ).order_by(models.BookHash.library, models.BookHash.calibre_book_id).distinct().all()
    return [
        BookMatch(r.library, r.calibre_book_id, r.format)
        for r in candidati
        if (r.library, r.calibre_book_id) not in morti_ids
        and _vivo(BookMatch(r.library, r.calibre_book_id, r.format))
    ]


def resolve_first_book_match(db: Session, file_hash: str, device_id: Optional[int] = None):
    """
    Come resolve_book_matches ma per i call site che ne vogliono uno solo —
    sostituto diretto di `db.query(BookHash).filter(file_hash == ...).first()`,
    con in più i due livelli di fallback (storico degli hash e hash consegnato
    a QUEL dispositivo).
    """
    matches = resolve_book_matches(db, file_hash, device_id=device_id)
    return matches[0] if matches else None


def resolve_book_identities(db: Session, file_hash: str, device_id: Optional[int] = None) -> list:
    """
    Come resolve_book_matches, ridotto alle coppie (library, calibre_book_id)
    per i chiamanti a cui il formato non serve.
    """
    return [(m.library, m.calibre_book_id) for m in resolve_book_matches(db, file_hash, device_id=device_id)]


def _get_or_create_book_hash(
    db: Session, library: str, calibre_book_id: int, format: str, file_hash: str,
    verified: bool = True, content_fingerprint: Optional[str] = None,
) -> Optional[str]:
    # **Un'impronta vuota non si scrive mai.** Da quando un dispositivo puo'
    # identificare un libro per nome (resolve_by_identity), un messaggio puo'
    # arrivare senza impronta del tutto — e questa funzione, con `None`,
    # archiviava quella buona nello storico e poi azzerava la riga viva. Cioe'
    # perdeva il riconoscimento di un libro proprio nel momento in cui lo si
    # era appena riconosciuto benissimo.
    if not file_hash:
        return None
    existing = db.query(models.BookHash).filter(
        models.BookHash.library == library, models.BookHash.calibre_book_id == calibre_book_id,
        models.BookHash.format == format,
    ).first()
    if existing:
        if existing.file_hash and existing.file_hash != file_hash:
            # The live row is about to lose this hash forever — archive it
            # first so a device that already hashed this OLDER copy can
            # still resolve (see BookHashHistory's own docstring for why
            # this matters: metadata/cover/page-count embedding rewrites
            # the file's bytes without the book actually changing).
            db.add(models.BookHashHistory(
                library=library, calibre_book_id=calibre_book_id, format=format,
                file_hash=existing.file_hash,
            ))
        existing.file_hash = file_hash
        existing.verified = verified
        # Only overwrite when a new fingerprint was actually computed —
        # record_device_hash calls this with content_fingerprint=None and
        # must never blank out a fingerprint upsert_book_hash already stored
        # for this same row.
        if content_fingerprint is not None:
            existing.content_fingerprint = content_fingerprint
    else:
        db.add(models.BookHash(
            library=library, calibre_book_id=calibre_book_id, format=format,
            file_hash=file_hash, verified=verified, content_fingerprint=content_fingerprint,
        ))
    return file_hash


def upsert_book_hash(db: Session, library: str, calibre_book_id: int, format: str, file_path: str) -> Optional[str]:
    """
    Computes file_path's KOReader-compatible partial-MD5 and get-or-creates the
    matching BookHash row — shared by ingest confirm, libraries.py's
    recompute-hashes, and rescan (previously the only path with zero BookHash
    logic at all: a device's push_device_annotations resolves its own reported
    hash against this table, and a book indexed only through rescan had no row
    to match against, so every annotation for it was silently dropped into the
    'unresolved' counter — see devices.py's push_device_annotations).

    Also computes and stores the content-level fingerprint (text_fingerprint.py)
    alongside the byte hash, for the same three call sites — this is how the
    whole library gets backfilled with fingerprints for free as each book is
    imported/rescanned/recomputed, no separate migration step needed.

    Caller commits, matching each existing call site's own commit timing.
    """
    file_hash = koreader_hash.partial_md5(file_path)
    if not file_hash:
        return None
    fingerprint = text_fingerprint.compute_fingerprint(file_path, format)
    return _get_or_create_book_hash(db, library, calibre_book_id, format, file_hash, verified=True, content_fingerprint=fingerprint)


def record_device_hash(db: Session, library: str, calibre_book_id: int, format: str, file_hash: str) -> str:
    """
    Records a hash the DEVICE reported (not recomputed from the server's own
    copy of the file) against a book — used by the manual "pair" actions
    (devices.py's queue_flagged_book_action and pair_device_book) when a
    local file was matched to a book by the user (or by fuzzy title/author
    guess) rather than by hash. Deliberately does NOT verify this hash
    against the server's actual file: the whole point of manual pairing is
    to make it stick even when the two copies aren't byte-identical (e.g.
    a Kindle that re-packages EPUBs on transfer — confirmed as a real case,
    not hypothetical, while investigating a book that wouldn't auto-pair).

    verified=False is the whole point of this function existing separately
    from upsert_book_hash: it's read back by devices.py's list_devices to
    show a "non verificato per checksum" badge on the resulting DeviceBook
    row — including on a LATER sync, once this same (now-forced) hash flows
    through the ordinary hash-adoption path (_adopt_managed_books), which
    otherwise has no way to tell a forced hash from a genuinely verified one.

    Caller commits, matching upsert_book_hash's own commit timing.
    """
    return _get_or_create_book_hash(db, library, calibre_book_id, format, file_hash, verified=False)


def chiudi_i_formati(
    db: Session, library_path: str, library: str, calibre_book_id: int,
    percorsi_per_formato: dict, pagine: Optional[int] = None,
    formato_preferito: Optional[str] = None,
) -> dict:
    """
    L'ultimo atto dell'ingresso di un libro: si finisce di scrivere nei suoi
    file, e SOLO DOPO si registrano le impronte.

    **Perche' esiste, invece di due righe nel chiamante.** L'impronta serve a
    riconoscere un libro quando un lettore ne parla, e descrive i byte del
    file. Kolibre, pero', scrive dentro gli EPUB: il conteggio pagine finisce
    nell'OPF, e quella scrittura ricostruisce lo zip da zero
    (`opf_metadata.embed_custom_column`), quindi cambia tutti i byte.
    Calcolare l'impronta prima vuol dire registrare quella di un file che un
    istante dopo non esiste piu' — e il libro non si riconosce piu'.

    Non e' un'ipotesi: il 04/11/2026, su 8251 impronte registrate, due non
    descrivevano il proprio file, ed erano due libri entrati dal percorso che
    faceva le due cose nell'ordine sbagliato (il caricamento dal plugin
    Calibre). Nessuna delle due aveva una vecchia impronta archiviata, perche'
    una riscrittura fatta fuori da `_get_or_create_book_hash` non archivia
    niente: il valore giusto non era perso, era mai stato scritto.

    **E perche' una funzione e non una riga spostata.** La regola «l'impronta
    si calcola per ultima» viveva nella testa di chi scriveva, in due punti
    diversi, e in uno dei due si era persa. Spostare la riga aggiusta oggi;
    questa funzione impedisce che l'ordine torni a divergere, perche' l'ordine
    sta scritto una volta sola, qui dentro.

    `pagine` a `None` significa «non c'e' niente da incorporare», non «zero
    pagine»: si registrano le impronte dei file come stanno. E
    `formato_preferito` e' quello su cui si scrive — gli altri non si toccano,
    ma la loro impronta si registra comunque, altrimenti un lettore che avesse
    scaricato il PDF non lo vedrebbe riconosciuto.

    Non fa commit, come `upsert_book_hash`: committa chi chiama, perche' qui
    siamo dentro la transazione che crea il libro e un commit a meta' la
    spezzerebbe.
    """
    from . import opf_metadata  # locale: opf_metadata carica CalibreLibrary

    incorporato = False
    if pagine is not None and formato_preferito:
        percorso = percorsi_per_formato.get(formato_preferito)
        if percorso:
            # Best-effort per scelta, come alla sua chiamata precedente: un
            # OPF strano non deve fermare l'ingresso di un libro. Quello che
            # NON e' best-effort e' l'ordine — l'impronta viene dopo in
            # entrambi i casi, riuscito o fallito, perche' «fallito» qui vuol
            # dire anche «ha riscritto a meta'».
            incorporato = opf_metadata.embed_page_count(
                library_path, percorso, formato_preferito, pagine)

    impronte = {}
    for formato, percorso in percorsi_per_formato.items():
        impronta = upsert_book_hash(db, library, calibre_book_id, formato, percorso)
        if impronta:
            impronte[formato] = impronta
    return {"incorporato": incorporato, "impronte": impronte}
