import base64
import io
import os
import shutil
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response
from PIL import Image
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from .. import config, models, database, auth
from ..logging_utils import log_message
from ..services.immagini_remote import scarica_immagine
from ..services import cover_builder, converter, metadata_scraper, page_counter, toc_editor, stats_service, author_ingest_hook, app_settings, opf_metadata, author_stats_service, book_records
from ..calibre.library import CalibreLibrary
from ..calibre.functions import string_to_authors
from ..calibre.connection import READ_FLAG_COLUMN_LABEL, page_count_fields
from ..calibre.write_queue import CalibreWriteQueue
from ..deps import get_write_queue
from .libraries import biblioteca_scrivibile, default_library_param, library_display_name

router = APIRouter(prefix="/api/kolibre/books", tags=["books"])

# Endpoint deliberatamente SENZA autenticazione: sono URL che il
# browser (o il plugin KOReader) carica senza poter allegare un header
# Authorization — <img src>, @font-face, self-update del plugin. Tutto
# il resto di questo modulo passa da `router`, che main.py include con
# la dipendenza di autenticazione. Se aggiungi qui un endpoint, stai
# scegliendo di renderlo pubblico: fallo solo se e' in sola lettura.
public_router = APIRouter(prefix="/api/kolibre/books", tags=["books"])

# Router per i pochi endpoint che devono rispondere SIA a una persona SIA a
# un dispositivo registrato. Non e' una terza via d'accesso: e' l'unione
# delle due che esistono gia' (vedi auth.get_user_or_device). Oggi ci vive
# un endpoint solo, il download del file di un libro — che il server stesso
# indica al dispositivo come `download_url`, e che dalla chiusura delle API
# gli rispondeva 401 perche' stava dietro l'autenticazione utente.
device_or_user_router = APIRouter(
    prefix="/api/kolibre/books", tags=["books"],
    dependencies=[Depends(auth.get_user_or_device)],
)

# Reused by both directions of the reading-position endpoints below —
# distinguishes a web-reader-origin CFI (exact, directly usable by epub.js
# again) from a KOReader-origin xpointer or page number (opaque outside
# KOReader) stored in the very same ReadingPosition.progress column, without
# a schema migration or a separate "which kind of device" column.
_CFI_PROGRESS_PREFIX = "cfi:"


# Every book's full comments/description used to ride along in the bulk
# list response even though only two places in the frontend ever show it:
# the List view's inline snippet (already visually clipped to a couple of
# lines by CSS) and the full book-detail page. For a library with long,
# real descriptions this can add real MBs to a 1200-book response for text
# that's 95% never read at that length. Truncated here; the detail page
# fetches the untruncated text on demand via GET /{id}/description below.
_LIST_DESCRIPTION_EXCERPT_CHARS = 400


@router.get("")
def list_books(
    library: str = Depends(default_library_param),
    db: Session = Depends(database.get_db),
    limit: int = None,
    offset: int = 0,
    sort: str = "date_added",
    order: str = "desc",
    q: str = "",
):
    """
    Senza `limit` restituisce l'elenco completo, come ha sempre fatto: e'
    quello che serve alle pagine che ragionano sull'intera biblioteca
    (Statistiche, Serie, i selettori di libro) e a qualunque client gia'
    scritto.

    Con `limit` restituisce una pagina — {items, total, offset, limit} —
    ordinata e filtrata da SQLite. Serve alle biblioteche grandi: misurato
    su 100.000 libri, l'elenco completo costa 9,4 secondi e 66 MB di
    risposta, e il costo cresce lineare con i libri. Quando si passa
    all'una o all'altra modalita' lo decide l'impostazione
    "library_pagination" (vedi services/app_settings.py), non questo
    endpoint: qui si serve quello che viene chiesto.
    """
    lib = CalibreLibrary(config.library_path(library))
    display_name = library_display_name(db, library)
    if limit is not None:
        books, totale = lib.list_books_page(limit=limit, offset=offset, sort=sort, order=order, q=q)
    else:
        books, totale = lib.list_books(), None

    result = []
    for b in books:
        timestamp = b["timestamp"]
        # Custom column values are dynamic (CalibreLibrary.list_books adds one
        # "#<label>" key per column that actually exists in this library, not
        # just the two seeded demo columns), so pass all of them through as-is.
        custom_values = {k: v for k, v in b.items() if k.startswith("#")}
        description = b["description"]
        if description and len(description) > _LIST_DESCRIPTION_EXCERPT_CHARS:
            description = description[:_LIST_DESCRIPTION_EXCERPT_CHARS].rstrip() + "…"
        result.append({
            "id": b["id"],
            "title": b["title"],
            "author": b["author"] or "Autore Sconosciuto",
            "series": b["series"],
            "series_index": b["series_index"],
            "tags": b["tags"],
            "identifiers": b["identifiers"],
            "publisher": b["publisher"],
            "language": b["language"],
            "description": description,
            "title_sort": b["title_sort"],
            "author_sort": b["author_sort"],
            "uuid": b["uuid"],
            "pubdate": (b["pubdate"] or "").split(" ")[0] if b["pubdate"] else None,
            "last_modified": (b["last_modified"] or "").split(" ")[0] if b["last_modified"] else None,
            "formats": b["formats"],
            "size": b["size"],
            "rating": b["rating"],
            "date_added": timestamp.split(" ")[0] if timestamp else None,
            # /cover/thumbnail, non /cover: questo campo finisce SOLO in
            # <img> di elenco, griglia e pannelli laterali, dove l'immagine
            # viene disegnata fra i 32 e i 200 px. La copertina originale di
            # Calibre e' tipicamente 1000-2500 px sul lato lungo (137 KB di
            # media in libreria, fino a 539 KB): su 1.200 libri erano ~160 MB
            # di immagini scaricate e decodificate per mostrare francobolli.
            # L'endpoint ridimensionato esisteva gia' — lo usava solo il
            # plugin KOReader — ed e' anche il solo con ETag e 304.
            # Nessuna vista disegna la copertina piu' grande di 400x600:
            # il dettaglio libro la mette in una colonna da 160 px, il
            # pannello Quickview in una da ~250. /cover resta comunque
            # esposto per chi voglia l'originale.
            # Sempre valorizzato, anche senza copertina sul disco: da li' in
            # poi risponde quella costruita (vedi _copertina_costruita). Chi
            # deve sapere se la copertina e' VERA guarda has_cover.
            "cover_url": f"/api/kolibre/books/{b['id']}/cover/thumbnail?library={library}",
            "has_cover": bool(b["cover_path"]),
            **custom_values,
            "_library": display_name,
        })
    if totale is None:
        return result
    return {"items": result, "total": totale, "offset": max(0, offset), "limit": limit}


@router.get("/valori")
def valori_dei_campi(
    library: str = Depends(default_library_param),
    q: str = "",
):
    """
    I valori distinti di ogni campo, coi conteggi, sull'intera biblioteca.

    Il Navigatore costruiva il suo albero dai libri CARICATI: sopra la soglia
    di impaginazione erano duecento, e l'albero elencava i valori di quella
    pagina spacciandoli per quelli della biblioteca — una tendina "Autore"
    con dodici nomi su quattromila. Da qui arrivano quelli veri, contati da
    SQLite con un GROUP BY per tabella di collegamento.

    `q` e' la stessa query della barra di ricerca, cosi' i valori si
    restringono insieme ai libri: e' il comportamento che ci si aspetta da un
    navigatore a faccette, e senza, dopo il primo filtro l'albero mostrerebbe
    ancora valori che non esistono piu' nella selezione.
    """
    lib = CalibreLibrary(config.library_path(library))
    return {"campi": lib.valori_dei_campi(q=q)}


@router.get("/pagination")
def get_pagination_mode(
    library: str = Depends(default_library_param),
    db: Session = Depends(database.get_db),
):
    """
    Se per QUESTA biblioteca si impagina, e con che pagina. La decisione sta
    qui e non nel client: dipende da un'impostazione del server e dal numero
    di libri, due cose che il client non conosce senza chiederle — e
    chiederle significherebbe comunque scaricare tutto per contare.

    Dichiarato apposta come endpoint a se': conta i libri con un COUNT(*),
    non leggendoli.
    """
    lib = CalibreLibrary(config.library_path(library))
    totale = lib.count_books()
    conf = app_settings.get_library_pagination(db)
    return {
        "total": totale,
        "paginated": app_settings.pagination_applies(db, totale),
        "page_size": conf["page_size"],
        "mode": conf["mode"],
        "threshold": conf["threshold"],
    }


@router.get("/{id}/description")
def get_book_description(id: int, library: str = Depends(default_library_param)):
    """Untruncated companion to the excerpt list_books() above sends in bulk
    — fetched on demand only by the book-detail page, which is the one place
    that needs the full text. A single targeted query (CalibreLibrary
    .get_description), not the whole list_books() machinery, for one field
    of one book."""
    lib = CalibreLibrary(config.library_path(library))
    return {"description": lib.get_description(id)}


@router.get("/convert-info")
def get_convert_info():
    """Availability of the ebook-convert engine, for GUI gating of the
    conversion modal. Registered BEFORE any /{id} route on purpose — with
    an `int` path param FastAPI would 422 on /convert-info otherwise."""
    return converter.converter_info()


# Covers change rarely (a manual metadata edit, a re-scrape) and never
# silently go stale for a repeat visitor even at this max-age: every
# response below also carries an ETag off the cover FILE's own mtime+size,
# so a client whose cached copy is still valid gets a cheap 304 (no Pillow
# resize, no response body) instead of blindly trusting the age window —
# the age window just means "don't even ask" for a good while, the ETag is
# what keeps that safe.
_IMAGE_CACHE_MAX_AGE_SECONDS = 86400


def _file_etag(path: str) -> str:
    st = os.stat(path)
    return f'"{int(st.st_mtime)}-{st.st_size}"'


def _etag_matches(request: Request, etag: str) -> bool:
    if_none_match = request.headers.get("if-none-match")
    if not if_none_match:
        return False
    candidates = [v.strip().removeprefix("W/").strip('"') for v in if_none_match.split(",")]
    return etag.strip('"') in candidates


def _copertina_costruita(lib: CalibreLibrary, id: int) -> Response:
    """
    Il ripiego per un libro senza copertina: una generata al volo da titolo e
    autore (vedi `services/cover_builder.py`). Non viene mai scritta nella
    biblioteca — e' un ripiego visivo, non un dato, e una copertina finta
    salvata dentro `cover.jpg` diventerebbe indistinguibile da una vera.
    Deterministica, quindi la cache del browser lavora come su una vera.
    """
    libro = lib.get_book(id)
    if not libro:
        raise HTTPException(status_code=404, detail="Libro non trovato")
    # get_book legge la sola tabella `books`, che l'autore non ce l'ha: sta
    # nella tabella collegata, e get_book_author e' la query che la
    # attraversa. author_sort ("Rossi, Mario") c'e' anche qui, ma e' la forma
    # d'ordinamento e su una copertina si legge male.
    contenuto = cover_builder.costruisci(libro.get("title") or "", lib.get_book_author(id) or "")
    return Response(
        content=contenuto, media_type="image/jpeg",
        headers={"Cache-Control": f"public, max-age={_IMAGE_CACHE_MAX_AGE_SECONDS}",
                 "X-Kolibre-Cover": "costruita"},
    )


@public_router.get("/{id}/cover", dependencies=[Depends(auth.utente_o_dispositivo)])
def get_book_cover(id: int, library: str = Depends(default_library_param)):
    lib = CalibreLibrary(config.library_path(library))
    cover_path = lib.get_cover_path(id)
    if not cover_path:
        return _copertina_costruita(lib, id)
    return FileResponse(
        cover_path,
        headers={"Cache-Control": f"public, max-age={_IMAGE_CACHE_MAX_AGE_SECONDS}"},
    )


# Deliberately small: this is what the KOReader plugin's cover-grid catalog
# (kolibre_catalog.lua) fetches for every visible tile instead of the full
# route above — a real Calibre cover is routinely 1000-2500px on the long
# edge, and decoding several of those at once for a 3x3 grid is what crashed
# a real Kindle (confirmed after the fact: the plugin had no size-limited
# cover route to use). Same resize pattern already proven in this codebase
# for author folder icons (authors.py's get_author_photo_thumbnail), just
# with a portrait cap sized for book covers instead of a square one — 400x600
# mirrors what BookOrbit (a more mature KOReader library plugin) already
# ships for the identical use case.
_COVER_THUMBNAIL_MAX_SIZE = (400, 600)
_COVER_THUMBNAIL_JPEG_QUALITY = 85


@public_router.get("/{id}/cover/thumbnail", dependencies=[Depends(auth.utente_o_dispositivo)])
def get_book_cover_thumbnail(id: int, request: Request, library: str = Depends(default_library_param)):
    lib = CalibreLibrary(config.library_path(library))
    cover_path = lib.get_cover_path(id)
    if not cover_path:
        # Gia' a 400x600, la stessa misura della miniatura: non c'e' niente
        # da ridurre.
        return _copertina_costruita(lib, id)

    etag = _file_etag(cover_path)
    headers = {"Cache-Control": f"public, max-age={_IMAGE_CACHE_MAX_AGE_SECONDS}", "ETag": etag}
    if _etag_matches(request, etag):
        return Response(status_code=304, headers=headers)

    try:
        img = Image.open(cover_path)
        img.thumbnail(_COVER_THUMBNAIL_MAX_SIZE)
        if img.mode != "RGB":
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=_COVER_THUMBNAIL_JPEG_QUALITY)
    except Exception:
        raise HTTPException(status_code=500, detail="Errore nella generazione della miniatura")
    return Response(content=buf.getvalue(), media_type="image/jpeg", headers=headers)


@router.get("/{id}/reading-position")
def get_reading_position(
    id: int,
    library: str = Depends(default_library_param),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user_flexible),
):
    """
    The web reader's counterpart to devices.py's kosync-style /sync/progress
    — same ReadingPosition table (a single universal "latest position" per
    book, shared with KOReader), but identified directly by calibre_book_id
    + library (which the web reader already knows) instead of by file hash
    (which only makes sense for a device syncing an actual file it has on
    disk). Returns `cfi` only when the LAST write came from a web reader
    (see _CFI_PROGRESS_PREFIX) — a KOReader-origin xpointer or page number is
    meaningless to epub.js, so the caller should fall back to `percentage`
    (via book.locations.cfiFromPercentage) whenever `cfi` is null.
    """
    # Filtrata per utente: la posizione e' dove e' arrivata UNA persona.
    # Prima la chiave era (biblioteca, libro) e basta, quindi su una
    # biblioteca condivisa due lettori si restituivano a vicenda il
    # segnalibro dell'altro.
    pos = db.query(models.ReadingPosition).filter(
        models.ReadingPosition.user_id == current_user.id,
        models.ReadingPosition.library == library,
        models.ReadingPosition.calibre_book_id == id,
    ).first()
    if not pos:
        return {"percentage": None, "cfi": None, "device_name": None, "updated_at": None}
    cfi = pos.progress[len(_CFI_PROGRESS_PREFIX):] if pos.progress and pos.progress.startswith(_CFI_PROGRESS_PREFIX) else None
    return {
        "percentage": pos.percentage,
        "cfi": cfi,
        "device_name": pos.device_name,
        "updated_at": pos.updated_at.isoformat() if pos.updated_at else None,
    }


@router.put("/{id}/reading-position")
def put_reading_position(
    id: int,
    payload: dict,
    library: str = Depends(default_library_param),  # non biblioteca_scrivibile: la posizione di lettura e' un dato
    # PERSONALE di chi legge, non il contenuto della biblioteca. Chi ha
    # accesso in sola lettura deve poter segnare dove e' arrivato.
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user_flexible),
):
    """Body: {"percentage": float, "cfi": str|null}. `percentage` is always
    required (a position without it would be useless to a KOReader device
    reading the same row back). `cfi` is only meaningful for the EPUB web
    reader; the PDF web reader has no CFI at all, so it sends percentage
    alone — for it, `progress` stores the bare percentage (the same
    "universal, any-reader-can-seek-to-it" value kosync clients fall back to
    when the exact position isn't same-kind)."""
    percentage = payload.get("percentage")
    cfi = payload.get("cfi")
    if percentage is None:
        raise HTTPException(status_code=400, detail="percentage è obbligatorio")

    # Il reader web puo' essere escluso da posizioni e statistiche
    # (Impostazioni ▸ Lettura). Non e' un rifiuto: la richiesta e' valida e
    # riceve 200, semplicemente non lascia traccia. Il perche' sta in
    # app_settings.WEB_READER_TRACKING_KEY — in breve, aprire un libro sul
    # computer per controllare una frase non deve spostare il segnalibro del
    # Kindle di duecento pagine.
    #
    # Il controllo sta QUI e non nel frontend perche' e' il punto in cui il
    # dato verrebbe scritto: un reader piu' vecchio, o una scheda rimasta
    # aperta, continuerebbero a spingere comunque.
    if not app_settings.is_web_reader_tracking_enabled(db):
        return {"status": "ignored", "reason": "web_reader_tracking_disabled"}

    progress = f"{_CFI_PROGRESS_PREFIX}{cfi}" if cfi else str(percentage)

    existing = db.query(models.ReadingPosition).filter(
        models.ReadingPosition.user_id == current_user.id,
        models.ReadingPosition.library == library,
        models.ReadingPosition.calibre_book_id == id,
    ).first()
    # Prima di sovrascriverla: serve a sapere QUANTO si e' avanzato, che e'
    # la differenza fra una lettura e un salto (vedi segna_lettura_web).
    percentuale_prima = existing.percentage if existing else None
    if existing:
        existing.device_id = None
        existing.device_name = "Web Reader"
        existing.percentage = percentage
        existing.progress = progress
        existing.updated_at = datetime.utcnow()
    else:
        db.add(models.ReadingPosition(
            user_id=current_user.id, library=library, calibre_book_id=id,
            device_id=None, device_name="Web Reader",
            percentage=percentage, progress=progress,
        ))
    db.commit()

    # Live counterpart to stats_service's batch KOReader path — this is the
    # ONLY signal the web reader ever gives us, so it's also the only hook
    # available to close the "web reader has no reading-session/duration
    # data at all" gap. No per-tick pages_read estimate on purpose: it would
    # need a book-metadata lookup (page count) on every single push, and
    # this endpoint already fires every ~2s while reading — not worth the
    # extra cost on a hot path. "Pages read" for a web session can still be
    # derived on demand from ReadingPosition.percentage × #pages elsewhere.
    stats_service.record_live_tick(db, current_user.id, library, id, None, "web", datetime.utcnow())

    # La copertura si riempiva solo dai backup di KOReader: leggere dentro
    # Kolibre non la muoveva, e un libro letto per intero sul computer
    # risultava non visto. Sta dopo il gate dell'impostazione apposta —
    # spento il reader web per le statistiche, non lascia traccia da nessuna
    # parte, che e' la coerenza chiesta il 28/09.
    stats_service.segna_lettura_web(db, current_user.id, library, id, percentuale_prima, percentage)
    db.commit()

    return {"status": "ok"}


@router.get("/reading-progress")
def list_reading_progress(
    library: str = Depends(default_library_param),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user_flexible),
):
    """
    Bulk counterpart of GET /{id}/reading-position, for the Libreria table's
    progress-bar column — one request for the whole library instead of one
    per visible row. Same universal ReadingPosition table already shared by
    KOSync devices and the web reader (whichever pushed most recently wins),
    so a book read from more than one device already resolves to a single
    combined value here — no extra merging needed on top.
    """
    rows = db.query(models.ReadingPosition).filter(
        models.ReadingPosition.user_id == current_user.id,
        models.ReadingPosition.library == library,
    ).all()
    return [
        {
            "calibre_book_id": r.calibre_book_id,
            "percentage": r.percentage,
            "device_name": r.device_name,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]


@router.get("/{id}/stats")
def get_book_stats(
    id: int,
    library: str = Depends(default_library_param),
    db: Session = Depends(database.get_db),
    # Aggiunta il 27/09/2026: il pannello parla della TUA lettura di questo
    # libro. Mancava, e dal 24/09 — quando la copertura e' diventata per
    # utente — questo endpoint rispondeva 500 su ogni libro, perche' la
    # query sulla copertura citava un `current_user` che qui non c'era.
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    Per-book reading-stats panel payload (book-detail page) — mirrors
    KoServer's own /books/{id}/stats: total time/sessions, first/last read,
    a day-by-day time breakdown for the panel's chart, and the highlight
    count already tracked elsewhere (Highlight, unified across web/KOReader/
    Calibre-import sources).
    """
    # Per utente come tutto il resto delle statistiche di lettura: su un
    # libro condiviso, il tempo di un'altra persona non e' il tuo.
    sessions = db.query(models.ReadingSession).filter(
        models.ReadingSession.user_id == current_user.id,
        models.ReadingSession.library == library,
        models.ReadingSession.calibre_book_id == id,
    ).order_by(models.ReadingSession.start_time.asc()).all()

    highlights_count = db.query(models.Highlight).filter(
        models.Highlight.user_id == current_user.id,
        models.Highlight.library == library,
        models.Highlight.calibre_book_id == id,
        models.Highlight.deleted_at.is_(None),
    ).count()

    if not sessions:
        return {
            "total_time_seconds": 0, "total_sessions": 0, "total_pages_read": 0,
            "fraction_read": None, "chars_read": None, "coverage": None,
            "first_read": None, "last_read": None, "daily_sessions": [],
            "highlights_count": highlights_count,
        }

    # Quanto LIBRO e' stato letto, invece di quante pagine — una pagina di
    # KOReader dipende dal corpo del carattere, e su libri riletti con
    # impostazioni diverse le pagine non si possono nemmeno sommare fra loro
    # (vedi ReadingSession.fraction_read). `None` quando nessuna sessione
    # porta la frazione: sessioni vecchie, o lettura dal web reader.
    frazioni = [s.fraction_read for s in sessions if s.fraction_read]
    frazione = sum(frazioni) if frazioni else None
    testo = db.query(models.BookTextStats).filter(
        models.BookTextStats.library == library,
        models.BookTextStats.calibre_book_id == id,
    ).first()
    caratteri = round(frazione * testo.chars) if (frazione is not None and testo) else None
    # Quanta PARTE del libro e' stata vista, che e' un'altra domanda rispetto
    # a quanto si e' letto: rileggendo, la seconda supera il 100% e la prima
    # no. Vedi models.BookReadingCoverage.
    cop = db.query(models.BookReadingCoverage).filter(
        models.BookReadingCoverage.user_id == current_user.id,
        models.BookReadingCoverage.library == library,
        models.BookReadingCoverage.calibre_book_id == id,
    ).first()

    by_day = {}
    for s in sessions:
        day = s.start_time.date().isoformat()
        by_day[day] = by_day.get(day, 0) + s.duration

    return {
        "total_time_seconds": sum(s.duration for s in sessions),
        "total_sessions": len(sessions),
        "total_pages_read": sum(s.pages_read or 0 for s in sessions),
        "fraction_read": frazione,
        "chars_read": caratteri,
        "coverage": cop.coverage if cop else None,
        "first_read": sessions[0].start_time.isoformat(),
        "last_read": sessions[-1].start_time.isoformat(),
        "daily_sessions": [{"date": d, "total_seconds": secs} for d, secs in sorted(by_day.items())],
        "highlights_count": highlights_count,
    }


@router.post("/{id}/recompute-pages")
async def recompute_book_page_count(
    id: int,
    library: str = Depends(biblioteca_scrivibile),
    db: Session = Depends(database.get_db),
    write_queue: CalibreWriteQueue = Depends(get_write_queue),
):
    """
    Single-book counterpart of POST /libraries/{name}/recompute-pages — for
    when just one book's estimate is stale (e.g. after swapping its file, or
    changing the global word/char-per-page ratio and not wanting to touch
    the whole library) rather than re-running the count for every book.
    Same settings/format-picking/OPF-embedding logic as the bulk version.
    """
    library_path = config.library_path(library)
    lib = CalibreLibrary(library_path)
    formats = lib.get_formats(id)
    if not formats:
        raise HTTPException(status_code=404, detail="Libro non trovato o senza formati")

    settings = app_settings.get_page_count_settings(db)
    fmt = page_counter.pick_preferred_format([f["format"] for f in formats])
    file_path = lib.get_format_file_path(id, fmt)
    if not file_path:
        raise HTTPException(status_code=404, detail="File del formato non trovato su disco")

    pages = page_counter.count_pages(file_path, fmt, settings["mode"], settings["words_per_page"], settings["chars_per_page"])
    # Il testo e' gia' stato estratto per contare le pagine: se ne ricava
    # anche il conteggio caratteri, che serve alle statistiche di lettura.
    stats_service.registra_conteggio_testo(db, library, id, file_path, fmt)
    db.commit()
    if pages is None:
        raise HTTPException(status_code=422, detail="Impossibile calcolare le pagine per questo formato")

    await write_queue.submit("update_book", {"book_id": id, "fields": page_count_fields(pages)}, library_path)
    try:
        opf_metadata.embed_page_count(library_path, file_path, fmt, pages)
    except Exception as e:
        log_message("warning", "books", f"Embedding pagine nell'OPF fallito per '{file_path}': {e}")

    log_message("info", "books", f"Recompute pages: book {id} in library '{library}' -> {pages}")
    return {"status": "ok", "pages": pages}


@device_or_user_router.get("/{id}/download")
def download_book_format(id: int, format: str = None, library: str = Depends(default_library_param)):
    """
    Downloads one format of a book. If `format` isn't given, downloads
    whichever format is listed first for that book (its "primary" format).
    """
    lib = CalibreLibrary(config.library_path(library))
    fmt = format
    if not fmt:
        formats = lib.get_formats(id)
        if not formats:
            raise HTTPException(status_code=404, detail="Nessun formato disponibile per questo libro")
        fmt = formats[0]["format"]
    file_path = lib.get_format_file_path(id, fmt)
    if not file_path:
        raise HTTPException(status_code=404, detail=f"Formato {fmt} non disponibile per questo libro")
    return FileResponse(file_path, filename=os.path.basename(file_path), media_type="application/octet-stream")


@router.delete("/{id}/formats/{format}")
async def delete_book_format(
    id: int,
    format: str,
    library: str = Depends(biblioteca_scrivibile),
    write_queue: CalibreWriteQueue = Depends(get_write_queue),
):
    library_path = config.library_path(library)
    try:
        await write_queue.submit("remove_format", {"book_id": id, "fmt": format}, library_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    log_message("info", "books", f"Removed format {format} from book ID {id} in library '{library}'")
    return {"status": "ok"}


# Spuntare un libro come letto cambia una STATISTICA, non solo un metadato:
# da quando "completato" vuol dire spuntato (vedi
# stats_service.compute_summary), il contatore sul cruscotto dipende da
# questa colonna. Ma il cruscotto legge StatsCache, che si rinfresca
# all'avvio e ogni 24 ore — quindi confermando duecento libri dalla pagina
# Interventi il numero sarebbe rimasto quello di ieri fino al giorno dopo,
# senza che niente lo spiegasse.
#
# Si rinfresca solo quando quel campo e' davvero fra quelli scritti: e'
# un'operazione che tocca tutte le biblioteche, e farla ad ogni modifica di
# metadati sarebbe sproporzionato.
def _forse_rinfresca_statistiche(fields: dict, db: Session) -> None:
    if f"#{READ_FLAG_COLUMN_LABEL}" not in fields:
        return
    try:
        stats_service.refresh_stats_cache(db)
    except Exception:
        # Un cruscotto momentaneamente vecchio non deve far fallire la
        # scrittura del metadato, che e' gia' andata a buon fine.
        pass


@router.post("/bulk-update")
async def bulk_update_books(
    payload: dict,
    library: str = Depends(biblioteca_scrivibile),
    write_queue: CalibreWriteQueue = Depends(get_write_queue),
    db: Session = Depends(database.get_db),
):
    """
    Gli stessi metadati su molti libri in un colpo solo.

    Nasce dal caso che l'ha chiesto: un autore memorizzato male ("Rossi
    Mario"), tutti i suoi libri da correggere insieme. Farlo dal browser
    voleva dire una richiesta PUT per libro — centinaia di richieste, un
    giro di coda di scrittura ciascuna, e l'operazione che muore a meta' se
    si cambia scheda. Qui e' una richiesta sola, e sotto una transazione
    sola (vedi CalibreLibrary.bulk_update_books).

    `fields` contiene SOLO i campi che l'utente ha davvero toccato: quelli
    assenti non vengono scritti, cosi' una modifica di massa non appiattisce
    su un valore comune i campi che nessuno ha chiesto di cambiare.
    """
    ids = [int(i) for i in (payload.get("ids") or [])]
    fields = dict(payload.get("fields") or {})
    tags_add = list(payload.get("tags_add") or [])
    tags_remove = list(payload.get("tags_remove") or [])
    if not ids:
        raise HTTPException(status_code=400, detail="Nessun libro selezionato")
    if not fields and not tags_add and not tags_remove:
        raise HTTPException(status_code=400, detail="Nessun campo da modificare")

    library_path = config.library_path(library)
    toccati = await write_queue.submit(
        "bulk_update_books",
        {"book_ids": ids, "fields": fields, "tags_add": tags_add, "tags_remove": tags_remove},
        library_path,
    )

    if fields.get("author"):
        author_ingest_hook.maybe_trigger_wiki_scrape(string_to_authors(fields["author"]))
    if "author" in fields:
        # Stesso motivo del PUT sul singolo libro: senza questo la cache
        # "Pagine" della pagina Autori resta col vecchio autore gonfiato e
        # il nuovo a zero.
        author_stats_service.safe_mark_author_pages_dirty(db)

    _forse_rinfresca_statistiche(fields, db)

    log_message(
        "info", "books",
        f"Modifica metadati in blocco su {toccati} libri (di {len(ids)} richiesti) in '{library}'",
    )
    return {"status": "ok", "updated": toccati, "requested": len(ids)}


@router.put("/{id}")
async def update_book(
    id: int,
    payload: dict,
    library: str = Depends(biblioteca_scrivibile),
    write_queue: CalibreWriteQueue = Depends(get_write_queue),
    db: Session = Depends(database.get_db),
):
    """
    `identifiers`/`tags`/`series`(name)/`publisher`/`language`/`description`/
    `rating` each live in their own relation table (identifiers/tags/series/
    publishers/languages/comments/ratings), not a plain `books` column —
    CalibreLibrary.update_book only ever touches `books` itself (+ custom
    columns), so passing these through unchanged used to make them vanish
    silently on save. Popped out here and routed to their own write-queue
    ops instead; whatever's left (title/author/series_index/#custom) still
    goes through update_book exactly as before.
    """
    library_path = config.library_path(library)
    payload = dict(payload)

    # Sentinel, not `.pop(key, None)` + `is not None`: the editor UI always
    # sends these keys, using JSON null for "user cleared this field" (e.g.
    # series/publisher/language/rating go back to unset). `.pop(key, None)`
    # can't tell "key absent" from "key present with value null" apart —
    # both looked like None, so the `is not None` guard below silently
    # skipped the clearing write-queue op and a cleared field just stayed
    # at its old value forever (the actual "l'edit non persiste mai" bug:
    # setting a NEW value worked fine, only clearing one didn't).
    _unset = object()
    identifiers = payload.pop("identifiers", _unset)
    tags = payload.pop("tags", _unset)
    series_name = payload.pop("series", _unset)
    publisher = payload.pop("publisher", _unset)
    language = payload.pop("language", _unset)
    description = payload.pop("description", _unset)
    rating = payload.pop("rating", _unset)

    if payload:
        await write_queue.submit("update_book", {"book_id": id, "fields": payload}, library_path)
    if identifiers is not _unset:
        await write_queue.submit("set_identifiers", {"book_id": id, "identifiers": identifiers}, library_path)
    if tags is not _unset:
        await write_queue.submit("set_book_tags", {"book_id": id, "tags": tags}, library_path)
    if series_name is not _unset:
        await write_queue.submit("set_book_series", {"book_id": id, "series_name": series_name}, library_path)
    if publisher is not _unset:
        await write_queue.submit("set_publisher", {"book_id": id, "name": publisher}, library_path)
    if language is not _unset:
        await write_queue.submit("set_language", {"book_id": id, "lang_code": language}, library_path)
    if description is not _unset:
        await write_queue.submit("set_comments", {"book_id": id, "text": description}, library_path)
    if rating is not _unset:
        await write_queue.submit("set_rating", {"book_id": id, "stars": rating}, library_path)

    if payload.get("author"):
        author_ingest_hook.maybe_trigger_wiki_scrape(string_to_authors(payload["author"]))

    if "author" in payload:
        # Difetto riscontrato in uso: cambiare l'autore di un libro qui
        # (a differenza di import/delete/rescan/copy — vedi
        # author_stats_service.py per l'elenco completo) non invalidava mai
        # la cache "Pagine" della tabella Autori — il vecchio autore restava
        # con un totale gonfiato e il nuovo non veniva mai accreditato,
        # finché non capitava per caso un'altra mutazione che la invalidasse.
        author_stats_service.safe_mark_author_pages_dirty(db)

    _forse_rinfresca_statistiche(payload, db)

    log_message("info", "books", f"Updated metadata for book ID: {id} in library '{library}'")
    return {"status": "ok"}


@router.delete("/{id}")
async def delete_book(
    id: int,
    library: str = Depends(biblioteca_scrivibile),
    write_queue: CalibreWriteQueue = Depends(get_write_queue),
    db: Session = Depends(database.get_db),
):
    library_path = config.library_path(library)
    await write_queue.submit("delete_book", {"book_id": id}, library_path)

    # Calibre's metadata.db is only half the story — see book_records for what
    # happens to the Kolibre-side rows (positions, sessions, hashes, device
    # state) and why each one is dropped, repointed or left alone.
    book_records.release_book(db, library, id)
    db.commit()

    author_stats_service.safe_mark_author_pages_dirty(db)
    log_message("info", "books", f"Deleted book ID: {id} from library '{library}'")
    return {"status": "ok"}


@router.get("/{id}/metadata-search")
def search_book_metadata_online(id: int, library: str = Depends(default_library_param)):
    """Cerca su Open Library, Google Books e Wikidata, dal titolo e
    dall'autore che il libro ha adesso.

    Torna anche com'e' andata ogni fonte: una lista corta puo' voler dire
    "questo libro non e' nei cataloghi" oppure "una delle tre oggi non
    risponde", e dai risultati le due cose sono indistinguibili."""
    lib = CalibreLibrary(config.library_path(library))
    book = next((b for b in lib.list_books() if b["id"] == id), None)
    if not book:
        raise HTTPException(status_code=404, detail="Libro non trovato")
    return metadata_scraper.cerca_metadati_con_esito(book["title"], book["author"] or "")


@router.post("/{id}/apply-metadata")
async def apply_online_metadata(
    id: int,
    payload: dict,
    library: str = Depends(biblioteca_scrivibile),
    write_queue: CalibreWriteQueue = Depends(get_write_queue),
):
    """Applies a subset of fields from a metadata-search candidate to a book."""
    library_path = config.library_path(library)

    book_fields = {k: payload[k] for k in ("title", "author", "pubdate") if payload.get(k)}
    if book_fields:
        await write_queue.submit("update_book", {"book_id": id, "fields": book_fields}, library_path)

    # `identifiers` (new, multi-type dict — a candidate can expose isbn AND
    # google AND amazon at once) takes precedence; `isbn` (old, single
    # scalar) stays supported for any caller still on the old shape. Both go
    # through set_identifier per-type (merge into whatever's already saved),
    # never set_identifiers (which would wipe out any OTHER identifier the
    # user already had that this candidate doesn't happen to also report).
    identifiers = payload.get("identifiers")
    if isinstance(identifiers, dict) and identifiers:
        for id_type, value in identifiers.items():
            if id_type and value:
                await write_queue.submit(
                    "set_identifier", {"book_id": id, "id_type": id_type, "value": value}, library_path
                )
    elif payload.get("isbn"):
        await write_queue.submit(
            "set_identifier", {"book_id": id, "id_type": "isbn", "value": payload["isbn"]}, library_path
        )

    if payload.get("description"):
        await write_queue.submit("set_comments", {"book_id": id, "text": payload["description"]}, library_path)

    if payload.get("publisher"):
        await write_queue.submit("set_publisher", {"book_id": id, "name": payload["publisher"]}, library_path)

    if payload.get("language"):
        await write_queue.submit("set_language", {"book_id": id, "lang_code": payload["language"]}, library_path)

    if payload.get("tags"):
        # Merge into whatever tags the book already has, same reasoning as
        # `identifiers` above — set_book_tags REPLACES the whole tag set, and
        # a metadata-search candidate only ever reports a handful of tags
        # from one source, never the book's full existing tag set.
        lib = CalibreLibrary(library_path)
        current_book = next((b for b in lib.list_books() if b["id"] == id), None)
        merged_tags = list((current_book or {}).get("tags") or [])
        for tag in payload["tags"]:
            if tag not in merged_tags:
                merged_tags.append(tag)
        await write_queue.submit("set_book_tags", {"book_id": id, "tags": merged_tags}, library_path)

    if payload.get("cover_url"):
        try:
            # Passa da services/immagini_remote: prima questa riga faceva una
            # httpx.get nuda, con follow_redirects=True e nessun controllo
            # sull'indirizzo. Era una finestra sulla rete di casa — e aperta
            # in lettura, perche' la risposta veniva salvata come copertina e
            # si poteva rileggere con GET /books/{id}/cover. La stessa
            # protezione esisteva gia' per le foto degli autori, con
            # ventiquattro righe di commento sul perche': questo endpoint non
            # l'aveva mai ricevuta.
            #
            # run_in_threadpool: una richiesta bloccante qui (la rotta e'
            # async) fermerebbe l'unico event loop di Uvicorn — e con lui ogni
            # altra richiesta in corso — per tutta la durata del timeout.
            contenuto, _ext = await run_in_threadpool(scarica_immagine, payload["cover_url"])
            image_b64 = base64.b64encode(contenuto).decode("ascii")
            await write_queue.submit("set_cover", {"book_id": id, "image_b64": image_b64}, library_path)
        except HTTPException as e:
            # Una copertina che non si scarica non deve far fallire tutto il
            # resto dei metadati: si annota e si va avanti.
            log_message("warning", "books", f"Cover download refused for book {id}: {e.detail}")
        except httpx.HTTPError:
            pass  # cover fetch failing shouldn't block the rest of the metadata apply

    log_message("info", "books", f"Applied online metadata to book ID {id} in library '{library}'")
    return {"status": "ok"}


@router.post("/{id}/convert")
async def convert_book_format(
    id: int,
    payload: dict,
    library: str = Depends(biblioteca_scrivibile),
    write_queue: CalibreWriteQueue = Depends(get_write_queue),
):
    """
    Real conversion via ebook-convert (services/converter.py). Body:
    {"target_format": "html"|"mobi"|"pdf"|"txt" (case-insensitive),
     "source_format"?: str, "add_as_format"?: bool}.

    Without `add_as_format` the converted file streams straight back as the
    response body (Content-Disposition: <Title>.<ext>) — the current
    frontend modal sends {source_format, target_format} and ignores the
    response entirely, so this stays compatible with it. With
    `add_as_format` the result is copied into the book's own folder and
    registered as a new Calibre format instead, returning {status, format,
    size}. `html` is registered as HTMLZ (a legitimate Calibre format —
    ebook-convert's "web page" output; not readable by our web reader).

    Synchronous by design (personal server, no job queue — see
    converter.py); the blocking subprocess runs in the threadpool so this
    async endpoint never stalls the event loop.
    """
    info = converter.converter_info()
    if not info["available"]:
        raise HTTPException(
            status_code=501,
            detail="Conversione non disponibile: ebook-convert non trovato sul server. "
                   "Installa Calibre oppure imposta KOLIBRE_EBOOK_CONVERT.",
        )

    target_format = (payload.get("target_format") or "").lower()
    if target_format not in converter.TARGET_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"target_format non supportato: {payload.get('target_format')!r} "
                   f"(supportati: {', '.join(sorted(converter.TARGET_EXTENSIONS))})",
        )
    target_ext = converter.TARGET_EXTENSIONS[target_format]

    lib = CalibreLibrary(config.library_path(library))
    formats = lib.get_formats(id)
    if not formats:
        raise HTTPException(status_code=404, detail="Nessun formato disponibile per questo libro")
    source_format = (payload.get("source_format") or "").upper() or page_counter.pick_preferred_format(
        [f["format"] for f in formats]
    )
    if source_format == target_ext.upper():
        raise HTTPException(status_code=400, detail="Il formato di destinazione coincide con quello di origine")
    source_path = lib.get_format_file_path(id, source_format)
    if not source_path:
        raise HTTPException(status_code=404, detail=f"Formato {source_format} non disponibile per questo libro")

    try:
        # Blocking subprocess (up to 5 min) → threadpool, not the event loop.
        output_path = await run_in_threadpool(converter.convert_file, source_path, target_format)
    except converter.ConversionError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    tmp_dir = os.path.dirname(output_path)

    if payload.get("add_as_format"):
        try:
            # Same naming convention as the book's existing format files
            # (data.name + lowercase extension in the book's own folder) —
            # the pattern ingest.py / library_transfer.py follow too.
            base_name = os.path.splitext(os.path.basename(source_path))[0]
            dest_path = os.path.join(os.path.dirname(source_path), f"{base_name}.{target_ext}")
            shutil.copyfile(output_path, dest_path)
            size_bytes = os.path.getsize(dest_path)
            await write_queue.submit(
                "add_format",
                {"book_id": id, "fmt": target_ext.upper(), "size_bytes": size_bytes, "name": base_name},
                config.library_path(library),
            )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        log_message(
            "info", "books",
            f"Converted book ID {id} ({source_format} -> {target_ext.upper()}) and added it as a format in library '{library}'",
        )
        return {"status": "ok", "format": target_ext.upper(), "size": size_bytes}

    book_row = lib.get_book(id)
    title = (book_row or {}).get("title") or os.path.splitext(os.path.basename(source_path))[0]
    filename = f"{title}.{target_ext}"
    log_message("info", "books", f"Converted book ID {id} ({source_format} -> {target_ext.upper()}) for download")
    # FileResponse handles non-ASCII filenames itself (RFC 5987 filename*
    # encoding), same as the /download endpoint above. The temp dir can't be
    # removed in a try/finally here — the file streams AFTER this returns —
    # so cleanup rides a BackgroundTask that runs once the response is sent.
    return FileResponse(
        output_path,
        filename=filename,
        media_type="application/octet-stream",
        background=BackgroundTask(shutil.rmtree, tmp_dir, ignore_errors=True),
    )


def _resolve_toc_target(lib: CalibreLibrary, book_id: int, requested_format: str = None):
    """Picks which format's TOC to read/write: the one asked for, or — same
    reflowable-first rule as page counting — whichever's preferred among the
    book's available formats. Only EPUB (NCX) and PDF (outline) are supported."""
    formats = lib.get_formats(book_id)
    if not formats:
        raise HTTPException(status_code=404, detail="Nessun formato disponibile per questo libro")
    fmt = requested_format or page_counter.pick_preferred_format([f["format"] for f in formats])
    if fmt not in ("EPUB", "PDF"):
        raise HTTPException(status_code=400, detail=f"Modifica TOC non supportata per il formato {fmt}")
    file_path = lib.get_format_file_path(book_id, fmt)
    if not file_path:
        raise HTTPException(status_code=404, detail=f"Formato {fmt} non trovato su disco")
    return fmt, file_path


@router.get("/{id}/toc")
def get_book_toc(id: int, library: str = Depends(default_library_param), format: str = None):
    lib = CalibreLibrary(config.library_path(library))
    fmt, file_path = _resolve_toc_target(lib, id, format)
    entries = toc_editor.get_epub_toc(file_path) if fmt == "EPUB" else toc_editor.get_pdf_toc(file_path)
    return {"format": fmt, "entries": entries}


@router.get("/{id}/toc/destinations")
def get_book_toc_destinations(id: int, library: str = Depends(default_library_param), format: str = None):
    """
    Real, existing destinations inside the book — feeds the TOC editor's
    "change destination" picker so the user can only pick a place that
    actually exists, instead of typing a raw href/page number by hand.
    """
    lib = CalibreLibrary(config.library_path(library))
    fmt, file_path = _resolve_toc_target(lib, id, format)
    if fmt == "EPUB":
        return {"format": fmt, "files": toc_editor.list_epub_destinations(file_path)}
    return {"format": fmt, "page_count": toc_editor.get_pdf_page_count(file_path)}


@router.get("/{id}/toc/destinations/content")
def get_book_toc_destination_content(id: int, href: str, library: str = Depends(default_library_param), format: str = None):
    """
    Raw HTML of one spine file, rendered in the TOC editor's interactive
    destination picker so the user can click the exact spot they mean
    instead of only picking a whole file/anchor from a dropdown. EPUB only —
    a PDF destination is just a page number, no content preview needed.
    """
    lib = CalibreLibrary(config.library_path(library))
    fmt, file_path = _resolve_toc_target(lib, id, format)
    if fmt != "EPUB":
        raise HTTPException(status_code=400, detail="Anteprima disponibile solo per EPUB")
    content = toc_editor.get_epub_file_content(file_path, href)
    if not content:
        raise HTTPException(status_code=404, detail="File non trovato")
    return PlainTextResponse(content.decode("utf-8", errors="ignore"), media_type="text/html")


@router.post("/{id}/toc/anchor")
def create_book_toc_anchor(id: int, payload: dict, library: str = Depends(biblioteca_scrivibile), format: str = None):
    """
    Resolves a click inside the destination picker's preview to a real
    anchor id — reusing the clicked element's own id if it has one, minting
    and injecting a new one otherwise. `path` is the element-index path from
    <body>, computed identically in the browser (see ReaderView-independent
    click handler in the TOC editor modal).
    """
    lib = CalibreLibrary(config.library_path(library))
    fmt, file_path = _resolve_toc_target(lib, id, format)
    if fmt != "EPUB":
        raise HTTPException(status_code=400, detail="Disponibile solo per EPUB")
    href = payload.get("href")
    path = payload.get("path")
    if not href or not isinstance(path, list):
        raise HTTPException(status_code=400, detail="href e path sono obbligatori")
    anchor_id = toc_editor.resolve_or_create_anchor(file_path, href, path)
    if not anchor_id:
        raise HTTPException(status_code=422, detail="Impossibile risolvere una destinazione per il punto selezionato")
    return {"anchor_id": anchor_id}


@router.post("/{id}/toc/generate")
def generate_book_toc(id: int, payload: dict, library: str = Depends(biblioteca_scrivibile), format: str = None):
    """
    Auto-builds a TOC from the book's own structure — the entries are
    returned for the editor's tree to show for review, NOT written to the
    NCX until the user hits Salva there (same contract as a manual edit).
    `mode`: "major_headings" (h1 only), "all_headings" (h1-h6), or "files"
    (one entry per spine file). Unlike the read-only generation modes,
    heading-based generation DOES write to the book's content files right
    away if a heading has no existing id — a real anchor id has to exist
    somewhere for the generated destination to be valid at all.
    """
    lib = CalibreLibrary(config.library_path(library))
    fmt, file_path = _resolve_toc_target(lib, id, format)
    if fmt != "EPUB":
        raise HTTPException(status_code=400, detail="Generazione automatica disponibile solo per EPUB")
    mode = payload.get("mode")
    if mode == "major_headings":
        entries = toc_editor.generate_toc_from_headings(file_path, max_level=1)
    elif mode == "all_headings":
        entries = toc_editor.generate_toc_from_headings(file_path, max_level=6)
    elif mode == "files":
        entries = toc_editor.generate_toc_from_files(file_path)
    else:
        raise HTTPException(status_code=400, detail="mode non valido")
    return {"format": fmt, "entries": entries}


@router.post("/{id}/toc")
def edit_book_toc(id: int, payload: dict, library: str = Depends(biblioteca_scrivibile)):
    lib = CalibreLibrary(config.library_path(library))
    fmt, file_path = _resolve_toc_target(lib, id, payload.get("format"))
    entries = payload.get("toc", [])

    if fmt == "EPUB":
        ok = toc_editor.set_epub_toc(file_path, entries)
    else:
        pdf_entries = [{"title": e.get("title", ""), "page": int(e.get("dest") or 1)} for e in entries]
        ok = toc_editor.edit_pdf_toc(file_path, pdf_entries)

    if not ok:
        raise HTTPException(status_code=500, detail="Errore durante la scrittura del TOC")
    lib.touch_last_modified(id)
    log_message("info", "books", f"Updated {fmt} TOC for book ID {id} in library '{library}'")
    return {"status": "ok", "format": fmt}
