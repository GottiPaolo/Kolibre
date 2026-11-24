"""
Kolibre-side bookkeeping for a book that is about to stop existing at a given
(library, calibre_book_id) — either deleted outright, or moved to another
library by "copia ed elimina l'originale".

Calibre's own metadata.db knows nothing about reading positions, sessions,
highlights, per-device state or hashes: those live only in app.db, keyed by
(library, calibre_book_id). Whoever removes a book from Calibre therefore has
to say what happens to that half, and there is exactly one right answer per
case — which is why this lives here and not inlined at each call site. It used
to be inlined in books.py's delete_book only, and library_transfer.py (the
move) simply didn't do it: the moved book kept its progress, sessions and
highlights pinned to a source id that no longer resolved, every device holding
it was never told to drop its copy, and the endpoint answered 200.
"""

from typing import Optional, Tuple

from sqlalchemy.orm import Session

from .. import models

# Rows keyed by (library, calibre_book_id) that represent work the USER did —
# they follow the book on a move, and are dropped on a real delete.
_READING_MODELS = (
    models.ReadingPosition,
    models.ReadingSession,
    models.StatsHashPairing,
    models.BookHashHistory,
    # Le letture misurate in caratteri (19/11/2026). Stanno qui per la stessa
    # ragione delle sessioni: se accorpando due doppioni le sessioni si
    # spostano e queste no, il libro che resta avrebbe un tempo di lettura e
    # nessuna posizione, e la tabella resterebbe piena di righe che puntano a
    # un libro che non c'e' piu'. Il loro vincolo di unicita' non contiene il
    # libro — e' (dispositivo, genere, istante, pagina) — quindi uno
    # spostamento non puo' scontrarsi, al contrario di `ReadingPosition`.
    models.LetturaDiPagina,
)


def _risolvi_le_posizioni_che_si_scontrano(
    db: Session,
    library: str,
    calibre_book_id: int,
    migrate_to: Tuple[str, int],
) -> int:
    """
    Fa posto, dove due posizioni di lettura finirebbero sulla stessa chiave.

    Gira PRIMA dello spostamento e lascia dietro di se' una situazione in cui
    la `UPDATE` di `release_book` non puo' piu' scontrarsi: per ogni utente
    che ha una posizione su tutti e due i libri resta **una** riga sola, la
    piu' recente per `updated_at`, e sta dalla parte giusta.

    Il perche' della scelta e il difetto che chiude stanno nel docstring di
    `release_book`. Qui le due cose da sapere leggendo:

    * **`user_id` nullo non si scontra.** In SQLite (e nello standard) una
      UNIQUE non vede due NULL come uguali, quindi due posizioni senza utente
      possono convivere e non vanno toccate — toccarle vorrebbe dire
      inventare uno scontro che il database non ha.
    * **Non committa**, come tutto il resto qui dentro: siamo dentro la
      transazione di chi accorpa o sposta.

    Torna quante righe ha risolto, per il registro di chi chiama.
    """
    lib_a, id_a = migrate_to
    risolte = 0

    in_arrivo = db.query(models.ReadingPosition).filter(
        models.ReadingPosition.library == library,
        models.ReadingPosition.calibre_book_id == calibre_book_id,
        models.ReadingPosition.user_id.isnot(None),
    ).all()

    for riga in in_arrivo:
        gia_la = db.query(models.ReadingPosition).filter(
            models.ReadingPosition.library == lib_a,
            models.ReadingPosition.calibre_book_id == id_a,
            models.ReadingPosition.user_id == riga.user_id,
        ).first()
        if gia_la is None or gia_la.id == riga.id:
            continue

        # `updated_at` puo' essere nullo su righe antiche (la colonna ha un
        # default, non un NOT NULL): una data che non c'e' perde, perche'
        # «non so quando» non puo' battere «so quando».
        quando_arriva = riga.updated_at
        quando_c_era = gia_la.updated_at
        arriva_piu_nuova = (
            quando_arriva is not None
            and (quando_c_era is None or quando_arriva > quando_c_era)
        )

        if arriva_piu_nuova:
            # La riga che era sul libro da tenere si toglie, e quella in
            # arrivo le prende il posto con lo spostamento di `release_book`.
            db.delete(gia_la)
        else:
            db.delete(riga)
        risolte += 1

    if risolte:
        db.flush()
    return risolte


def release_book(
    db: Session,
    library: str,
    calibre_book_id: int,
    migrate_to: Optional[Tuple[str, int]] = None,
) -> None:
    """
    Detaches every app.db row from (library, calibre_book_id). Does NOT commit —
    the caller decides when, so this can join an existing transaction.

    migrate_to=(target_library, target_book_id): the book still exists, just
    somewhere else, so reading data is repointed instead of dropped.

    **Lo scontro di due posizioni di lettura, e perche' non era un'ipotesi.**
    Fino al 19/11/2026 qui c'era scritto che lo spostamento era al sicuro
    dagli scontri «perche' l'id di arrivo e' appena stato creato dalla copia
    che precede la cancellazione». Vero per lo spostamento di un libro fra
    biblioteche — falso per l'**accorpamento dei doppioni**
    (`duplicates.accorpa`), dove il libro da tenere esiste da sempre e puo'
    essere stato letto. `ReadingPosition` ha una UNIQUE su
    `(user_id, library, calibre_book_id)`: due libri letti dallo stesso
    utente e la `UPDATE` si schiantava, con un 500 e la transazione
    dell'accorpamento a meta'. Trovato il 19/11/2026 da una prova che era
    diventata capace di vederlo (vedi sotto).

    **Chi vince.** La riga con `updated_at` piu' recente, che non e' una
    regola inventata qui: e' la regola che `ReadingPosition` ha gia' scritta
    addosso — «l'ultimo che scrive, per orologio, si prende il posto di
    quella corrente». Quindi se la posizione del libro assorbito e' piu'
    nuova prende il posto di quella del libro tenuto, e se e' piu' vecchia
    si butta. In entrambi i casi **la posizione piu' avanti nel tempo
    sopravvive**, che e' quella che descrive dove la persona sta leggendo.

    **Perche' una prova lo ha visto solo adesso.** Perche' prima di quel
    giorno Kolibre riscriveva ogni EPUB per incorporarci il conteggio
    pagine, e questo rendeva un libro **diverso dalla propria copia byte per
    byte**: l'accorpamento automatico dei file identici, che e' la strada da
    cui si arriva qui, non scattava mai sulla coppia che avrebbe fatto
    scontrare le due posizioni. Spenta l'incorporazione (19/11/2026, poi
    tolta del tutto il 24/11), i doppioni sono tornati davvero identici e
    il difetto e' venuto fuori al primo giro.

    Highlights are the one exception on the delete path: they are authored
    content, and deleting a book shouldn't silently destroy notes the user
    wrote. They're left dangling on purpose (same call as delete_library's
    cascade), and migrated on the move path where a valid new home exists.
    """
    if migrate_to:
        _risolvi_le_posizioni_che_si_scontrano(
            db, library, calibre_book_id, migrate_to)

    for model in _READING_MODELS:
        q = db.query(model).filter(
            model.library == library, model.calibre_book_id == calibre_book_id
        )
        if migrate_to:
            q.update(
                {"library": migrate_to[0], "calibre_book_id": migrate_to[1]},
                synchronize_session=False,
            )
        else:
            q.delete(synchronize_session=False)

    highlights = db.query(models.Highlight).filter(
        models.Highlight.library == library,
        models.Highlight.calibre_book_id == calibre_book_id,
    )
    if migrate_to:
        highlights.update(
            {"library": migrate_to[0], "calibre_book_id": migrate_to[1]},
            synchronize_session=False,
        )

    # The live hash always goes: it points at a file under the OLD library
    # path. On a move the target book got its own BookHash when its copy was
    # written (library_transfer's upsert_book_hash), so there is nothing to
    # carry over — and leaving this row would make the same hash resolve to
    # two books, one of which is gone.
    db.query(models.BookHash).filter(
        models.BookHash.library == library,
        models.BookHash.calibre_book_id == calibre_book_id,
    ).delete(synchronize_session=False)

    # 'pending_delete' rather than a row deletion, in both cases: it's what
    # makes _build_removes tell every device holding this book to remove its
    # local copy on the next sync (same status the manual "Elimina da
    # dispositivo" action queues). On a move the device re-downloads the
    # book under its new library, which is the correct end state.
    db.query(models.DeviceBook).filter(
        models.DeviceBook.library == library,
        models.DeviceBook.calibre_book_id == calibre_book_id,
    ).update({"status": "pending_delete", "last_error": None}, synchronize_session=False)

    flagged = db.query(models.DeviceFlaggedBook).filter(
        models.DeviceFlaggedBook.candidate_library == library,
        models.DeviceFlaggedBook.candidate_calibre_book_id == calibre_book_id,
    )
    if migrate_to:
        flagged.update(
            {"candidate_library": migrate_to[0], "candidate_calibre_book_id": migrate_to[1]},
            synchronize_session=False,
        )
    else:
        flagged.update({
            "candidate_library": None,
            "candidate_calibre_book_id": None,
            "candidate_title": None,
            "candidate_author": None,
        }, synchronize_session=False)
