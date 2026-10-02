import io
import json
import os
from datetime import datetime
from urllib.parse import quote

import httpx
from PIL import Image

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from .. import auth, config, models, database
from ..logging_utils import log_message
from ..services.immagini_remote import scarica_immagine
from ..calibre.connection import get_connection, DELETED_LIBRARY_MARKER
from ..calibre.functions import string_to_authors
from ..calibre.library import CalibreLibrary
from ..services import author_scrape_job, author_scraper, author_stats_service, author_wikidata, permessi, stats_service

router = APIRouter(prefix="/api/kolibre/authors", tags=["authors"])

# Endpoint deliberatamente SENZA autenticazione: sono URL che il
# browser (o il plugin KOReader) carica senza poter allegare un header
# Authorization — <img src>, @font-face, self-update del plugin. Tutto
# il resto di questo modulo passa da `router`, che main.py include con
# la dipendenza di autenticazione. Se aggiungi qui un endpoint, stai
# scegliendo di renderlo pubblico: fallo solo se e' in sola lettura.
public_router = APIRouter(prefix="/api/kolibre/authors", tags=["authors"])


def _serialize(row: models.AuthorMetadata) -> dict:
    return {
        "name": row.author_name,
        "bio_it": row.bio_it,
        "bio_en": row.bio_en,
        "wikipedia_url_it": row.wikipedia_url_it,
        "wikipedia_url_en": row.wikipedia_url_en,
        "photo_url": f"/api/kolibre/authors/{quote(row.author_name)}/photo" if row.image_cached else None,
        "last_scraped_at": row.last_scraped_at.isoformat() if row.last_scraped_at else None,
        **_anagrafica(row),
    }


def _anagrafica(row: models.AuthorMetadata) -> dict:
    """
    Campi da Wikidata, nella stessa forma per l'elenco e per la scheda.
    `nationality` e `occupations` sono liste appiattite con "; " nel database
    (vedi models.AuthorMetadata) e tornano qui come array, che e' cio' che
    serve al frontend per contarli.
    """
    def lista(v):
        return [x.strip() for x in (v or "").split(";") if x.strip()]
    return {
        "gender": row.gender,
        "nationality": lista(row.nationality),
        "birth_date": row.birth_date,
        "death_date": row.death_date,
        "occupations": lista(row.occupations),
        "wikidata_qid": row.wikidata_qid,
    }


def _author_book_counts(solo_libreria: str = None) -> dict:
    """
    Nome autore -> numero di libri, sommato su tutte le librerie vive.
    Estratta da list_authors perche' ora la usa anche scrape_missing_authors
    per sapere su CHI lavorare: il server deve poter calcolare da solo
    l'elenco degli autori senza dati, invece di riceverlo dal browser.
    """
    counts: dict[str, int] = {}
    if not os.path.exists(config.LIBRARIES_DIR):
        return counts
    for d in os.listdir(config.LIBRARIES_DIR):
        if solo_libreria and d != solo_libreria:
            continue
        library_dir = config.library_path(d)
        if os.path.exists(os.path.join(library_dir, DELETED_LIBRARY_MARKER)):
            continue
        db_path = os.path.join(library_dir, "metadata.db")
        if not os.path.exists(db_path):
            continue
        try:
            conn = get_connection(db_path)
            rows = conn.execute(
                "SELECT a.name AS name, COUNT(bal.book) AS book_count "
                "FROM authors a LEFT JOIN books_authors_link bal ON bal.author = a.id "
                "GROUP BY a.id"
            ).fetchall()
            conn.close()
        except Exception:
            continue
        for row in rows:
            counts[row["name"]] = counts.get(row["name"], 0) + row["book_count"]
    return counts


@router.get("")
def list_authors(library: str = None, db: Session = Depends(database.get_db)):
    """
    Distinct author names across every known library, with their total book
    count, total estimated page count and (if already scraped) their cached
    Wikipedia photo — without the photo, the grid view showed every card
    blank until you opened the author, since this endpoint used to return
    name+count only.

    total_pages is read from models.AuthorPagesCache (see its own docstring
    and services/author_stats_service.py) rather than computed inline here —
    kept fresh by cheap dirty-marking at every book-add/remove call site,
    with the actual (expensive) recompute happening lazily, right here, at
    most once per batch of changes: only when the cache is missing or
    dirty, never on every request.
    """
    counts = _author_book_counts(library)

    if library:
        # Con un filtro non si usa la cache: quella somma TUTTE le
        # biblioteche, ed e' proprio la somma che qui non si vuole. Il conto
        # diretto costa quanto ricostruire la cache per quella sola
        # biblioteca, cioe' poco.
        pages_totals = author_stats_service.compute_author_total_pages(library)
    else:
        pages_cache = db.query(models.AuthorPagesCache).first()
        pages_totals = (
            json.loads(pages_cache.pages_json)
            if pages_cache and not pages_cache.dirty
            else author_stats_service.refresh_author_pages_cache(db)
        )

    # Una query sola per tutti: l'anagrafica serve sia alle colonne della
    # tabella autori sia alle statistiche, e prenderla per nome uno alla volta
    # sarebbe un N+1 su seicento righe.
    meta = {row.author_name: row for row in db.query(models.AuthorMetadata).all()}
    return [
        {
            "name": name,
            "book_count": count,
            "total_pages": pages_totals.get(name, 0),
            "photo_url": (
                f"/api/kolibre/authors/{quote(name)}/photo"
                if name in meta and meta[name].image_cached else None
            ),
            **(_anagrafica(meta[name]) if name in meta else {
                "gender": None, "nationality": [], "birth_date": None,
                "death_date": None, "occupations": [], "wikidata_qid": None,
            }),
        }
        for name, count in sorted(counts.items())
    ]


# Anche questi due PRIMA delle rotte /{name}, per la stessa ragione scritta
# qui sotto per image-search: "scrape-missing" verrebbe altrimenti letto come
# il nome di un autore.
@router.post("/scrape-missing")
def scrape_missing_authors(force: bool = False, db: Session = Depends(database.get_db)):
    """
    Avvia sul SERVER il recupero Wikipedia, scegliendo su CHI vale la pena
    lavorare adesso.

    Prima i bersagli erano "tutti quelli senza foto": significava ripetere a
    ogni giro le stesse centinaia di richieste per autori di cui sapevamo gia'
    che una foto libera non esiste, e in cambio farsi rifiutare da Wikipedia
    proprio mentre si provavano quelli recuperabili. Ora ogni autore porta con
    se' l'esito dell'ultimo tentativo e un `next_retry_at`, e qui si prende
    solo chi non e' ancora stato provato o la cui attesa e' scaduta:

      mai provato    -> sempre
      bloccato       -> dopo un'ora (raddoppiando se il blocco persiste)
      errore         -> dopo sei ore
      senza foto     -> dopo trenta giorni (le foto vengono aggiunte, ma piano)
      senza voce     -> dopo novanta giorni (una voce puo' nascere, raramente)
      completo       -> mai, salvo force

    `force=true` rifa' tutti ignorando le attese — e' il tasto destro sul
    pulsante, e resta il modo per dire "so io che qualcosa e' cambiato".

    Risponde 409 se un giro e' gia' in corso: la guardia sta sul server, dove
    ne' un cambio pagina ne' una seconda scheda possono azzerarla.
    """
    now = datetime.utcnow()
    all_names = sorted(_author_book_counts().keys())
    meta = {
        row.author_name: row
        for row in db.query(models.AuthorMetadata).filter(
            models.AuthorMetadata.author_name.in_(all_names)
        ).all()
    }

    def worth_trying(name: str) -> bool:
        row = meta.get(name)
        if row is None or row.last_scraped_at is None:
            return True  # mai provato
        if row.scrape_status == author_scraper.STATUS_OK:
            return False
        if row.next_retry_at is None:
            # Riga anteriore a questo meccanismo e senza esito dedotto:
            # meglio riprovarla una volta che lasciarla ferma per sempre.
            return row.scrape_status is None
        return row.next_retry_at <= now

    names = all_names if force else [n for n in all_names if worth_trying(n)]
    skipped = len(all_names) - len(names)

    # L'anagrafica Wikidata e' una ragione valida per partire anche quando non
    # c'e' nessuna biografia da scaricare. Sono due cose con tempi diversi: la
    # biografia si prende una volta e basta, l'anagrafica e' arrivata dopo e va
    # recuperata su tutto il pregresso. Senza questo controllo, su una
    # biblioteca gia' completa il pulsante rispondeva "niente da fare" e
    # l'anagrafica non arrivava mai — capitato su una biblioteca reale.
    anagrafica_mancante = db.query(models.AuthorMetadata).filter(
        models.AuthorMetadata.wikidata_fetched_at.is_(None),
        (models.AuthorMetadata.wikipedia_url_it.isnot(None))
        | (models.AuthorMetadata.wikipedia_url_en.isnot(None)),
    ).count()

    if not names and not anagrafica_mancante:
        return {"status": "nothing_to_do", "skipped": skipped, **author_scrape_job.status()}
    if not author_scrape_job.start(names, skipped=skipped):
        raise HTTPException(status_code=409, detail="Un recupero e' gia' in corso")
    log_message(
        "info", "authors",
        f"Avviato recupero per {len(names)} autori "
        f"({skipped} saltati perche' gia' completi o in attesa, force={force}); "
        f"anagrafica Wikidata da recuperare per {anagrafica_mancante}",
    )
    return {"status": "started", **author_scrape_job.status()}


@router.get("/scrape-status")
def scrape_authors_status():
    """
    A che punto e' il recupero. Leggibile da qualsiasi scheda e in qualsiasi
    momento — e' questo che permette alla pagina Autori di ritrovare
    un'operazione lasciata in corso invece di fingere che non esista.
    """
    return author_scrape_job.status()


# NB: declared before the /{name} routes below — FastAPI matches in
# declaration order, and a path parameter would otherwise swallow the
# literal "image-search" segment as an author named "image-search".
@router.get("/image-search")
def search_author_images(q: str):
    """
    Image candidates for an author photo, from Wikimedia Commons' keyless
    search API (File namespace) — same free-and-legal sourcing philosophy as
    the Open Library/Google Books metadata search. Returns thumbnails for
    the picker grid plus the full-size URL the photo-from-url endpoint below
    actually downloads.
    """
    try:
        resp = httpx.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "generator": "search",
                "gsrsearch": q,
                "gsrnamespace": 6,  # File:
                "gsrlimit": 12,
                "prop": "imageinfo",
                "iiprop": "url|mime",
                # 600px rendition: what the picker grid shows AND what
                # photo-from-url actually saves — Commons ORIGINALS are
                # often 20+MB scans that would blow the 5MB cap for no
                # benefit at author-avatar display sizes.
                "iiurlwidth": 600,
                "format": "json",
            },
            timeout=httpx.Timeout(connect=3.0, read=8.0, write=5.0, pool=5.0),
            headers={"User-Agent": "Kolibre/1.0 (self-hosted library server)"},
        )
        if resp.status_code != 200:
            return []
        pages = (resp.json().get("query") or {}).get("pages") or {}
    except httpx.HTTPError:
        return []

    results = []
    for page in pages.values():
        infos = page.get("imageinfo") or []
        if not infos:
            continue
        info = infos[0]
        if not (info.get("mime") or "").startswith("image/"):
            continue  # Commons file search also returns PDFs/videos
        results.append({
            "title": (page.get("title") or "").removeprefix("File:"),
            "thumb_url": info.get("thumburl") or info.get("url"),
            "url": info.get("url"),
        })
    return results


@router.get("/{name}/books")
def get_author_books(name: str, library: str = None):
    """
    An author's books across every library on the server — the "Autori" page
    is a single global view (list_authors above already aggregates this way),
    so opening one author must show all their books too, not just whichever
    library happens to be active in the UI at that moment.
    """
    results = []
    if not os.path.exists(config.LIBRARIES_DIR):
        return results
    for folder_name in os.listdir(config.LIBRARIES_DIR):
        # Con un filtro attivo la scheda dell'autore mostra solo i libri di
        # quella biblioteca: chi ha scelto "autori di X" non si aspetta di
        # trovare, aprendo un autore, libri che in X non ci sono.
        if library and folder_name != library:
            continue
        library_dir = config.library_path(folder_name)
        if os.path.exists(os.path.join(library_dir, DELETED_LIBRARY_MARKER)):
            continue
        db_path = os.path.join(library_dir, "metadata.db")
        if not os.path.exists(db_path):
            continue
        try:
            lib = CalibreLibrary(library_dir)
            books = lib.list_books()
        except Exception:
            continue
        for b in books:
            # Membership, not equality: b["author"] is the display string
            # ("A & B" for a two-author book), and this endpoint receives ONE
            # author's name — an exact match would hide every co-authored
            # book from both of its authors' pages.
            if name not in string_to_authors(b["author"] or ""):
                continue
            results.append({
                "id": b["id"],
                "title": b["title"],
                # Sempre valorizzato: senza copertina sul disco risponde
                # quella costruita (books.py::_copertina_costruita).
                "cover_url": f"/api/kolibre/books/{b['id']}/cover?library={folder_name}",
                "library": folder_name,
            })
    return results


@router.get("/{name}/reading-stats")
def get_author_reading_stats(
    name: str,
    library: str = None,
    db: Session = Depends(database.get_db),
):
    """
    Quanto e' stato letto DI questo autore.

    La scheda di un autore non conteneva un solo dato di lettura, mentre
    quella di un libro ne ha un pannello intero: si sapeva tutto della sua
    vita e niente del tempo passato insieme. Era l'asimmetria piu' evidente
    del sistema e la meno costosa da togliere, perche' i dati c'erano gia'
    tutti — bastava raggrupparli per autore invece che per libro.

    Attraversa tutte le biblioteche, o una sola quando l'ambito degli autori
    e' ristretto (stesso parametro e stesso motivo di get_author_books qui
    sopra: chi ha scelto "autori di X" non si aspetta numeri che vengono da
    altrove).

    Su questa striscia resta un dubbio di fondo — la scheda di un autore
    dovrebbe essere informativa e oggettiva, non personalizzata sulla
    lettura di chi guarda — e per questo e' stata tenuta removibile: vive
    in un endpoint suo e non dentro get_author_detail, cosi' toglierla e'
    cancellare due file, non districare un campo da una risposta che serve
    ad altro.
    """
    libri = get_author_books(name, library)
    if not libri:
        return {
            "books_owned": 0, "books_read": 0, "books_marked_read": 0,
            "total_time_seconds": 0, "chars_read": 0, "sessions": 0,
            "first_read": None, "last_read": None, "highlights": 0,
        }

    per_biblioteca = {}
    for b in libri:
        per_biblioteca.setdefault(b["library"], set()).add(b["id"])

    tempo = caratteri = sessioni = evidenziazioni = 0
    letti = set()
    primo = ultimo = None
    spuntati = 0

    for folder, ids in per_biblioteca.items():
        caratteri_per_libro = stats_service._chars_map(db, folder)
        for s in db.query(models.ReadingSession).filter(
            models.ReadingSession.library == folder,
            models.ReadingSession.calibre_book_id.in_(ids),
        ).all():
            tempo += s.duration or 0
            sessioni += 1
            letti.add((folder, s.calibre_book_id))
            caratteri += stats_service._chars_read(
                s.fraction_read, caratteri_per_libro.get(s.calibre_book_id)
            )
            if primo is None or s.start_time < primo:
                primo = s.start_time
            if ultimo is None or s.start_time > ultimo:
                ultimo = s.start_time

        evidenziazioni += db.query(models.Highlight).filter(
            models.Highlight.library == folder,
            models.Highlight.calibre_book_id.in_(ids),
        ).count()

        # "Letto" e' una spunta umana, e vale piu' di qualunque sessione:
        # un libro di questo autore finito su carta conta qui e in nessun
        # altro dei numeri di questa striscia.
        meta = stats_service._book_meta_map(folder)
        spuntati += sum(1 for i in ids if (meta.get(i) or {}).get("letto"))

    return {
        "books_owned": len(libri),
        "books_read": len(letti),
        "books_marked_read": spuntati,
        "total_time_seconds": tempo,
        "chars_read": caratteri,
        "sessions": sessioni,
        "first_read": primo.isoformat() if primo else None,
        "last_read": ultimo.isoformat() if ultimo else None,
        "highlights": evidenziazioni,
    }


@router.get("/{name}")
def get_author_detail(name: str, db: Session = Depends(database.get_db)):
    row = db.query(models.AuthorMetadata).filter(models.AuthorMetadata.author_name == name).first()
    if not row:
        return {
            "name": name, "bio_it": None, "bio_en": None,
            "wikipedia_url_it": None, "wikipedia_url_en": None,
            "photo_url": None, "last_scraped_at": None,
        }
    return _serialize(row)


# Campi che l'utente puo' correggere a mano. `nationality` e `occupations`
# arrivano come liste e si salvano appiattiti con "; " (vedi
# models.AuthorMetadata): la forma sul filo e' quella che serve al frontend,
# la forma nel database quella che basta a una colonna di testo.
_CAMPI_TESTO = ("bio_it", "bio_en", "gender", "birth_date", "death_date", "wikidata_qid")
_CAMPI_LISTA = ("nationality", "occupations")


@router.put("/{name}")
def update_author_bio(
    name: str,
    payload: dict,
    db: Session = Depends(database.get_db),
    # Gli autori sono UNA tabella per tutte le biblioteche (decisione del
    # 28/09: l'autore e' un fatto del mondo, non della tua biblioteca),
    # quindi modificarli e' un permesso dell'account e non della
    # condivisione.
    _chi: models.User = Depends(permessi.richiede_modificare_autori),
):
    """
    Correzione manuale dei dati di un autore.

    Prima accettava solo bio_it e bio_en: genere, nazionalita', nascita, morte
    e occupazione si potevano leggere ma non aggiustare, e quando Wikidata
    sbagliava non c'era rimedio (nell'indagine del 19/09, "L'errore di
    Cartesio" risultava di genere letterario "Neolitico").

    Quello che si scrive qui RESTA: il recupero automatico riempie solo i
    campi vuoti e non sovrascrive mai (author_wikidata.apply). Per far
    riprendere a Wikidata un campo, lo si svuota.

    Un campo assente dal payload non viene toccato; un campo presente e vuoto
    viene azzerato, ed e' voluto — e' il modo per dire "questo l'ho sbagliato
    io, riprendilo".
    """
    row = db.query(models.AuthorMetadata).filter(models.AuthorMetadata.author_name == name).first()
    if not row:
        row = models.AuthorMetadata(author_name=name)
        db.add(row)

    for campo in _CAMPI_TESTO:
        if campo in payload:
            valore = payload[campo]
            setattr(row, campo, (valore or "").strip() or None if isinstance(valore, str) else None)
    for campo in _CAMPI_LISTA:
        if campo in payload:
            valore = payload[campo]
            if isinstance(valore, str):
                valore = [v for v in valore.split(";")]
            voci = [str(v).strip() for v in (valore or []) if str(v).strip()]
            setattr(row, campo, "; ".join(voci) or None)

    db.commit()
    log_message("info", "authors", f"Dati corretti a mano per '{name}'")
    return _serialize(row)


def _arricchisci_da_wikidata(row) -> bool:
    """
    Dall'indirizzo Wikipedia di questa riga ai dati anagrafici di Wikidata.

    Wikipedia e Wikidata sono due cose diverse e finora venivano prese in due
    momenti diversi: il ritratto e la biografia qui, subito, e l'anagrafica
    solo dal giro di massa in sottofondo. Il risultato, riscontrato in uso:
    dai un indirizzo Wikipedia a un autore e il pannello Wikidata resta
    vuoto. Ma l'indirizzo Wikipedia E' la chiave per Wikidata — la query
    SPARQL parte proprio da quello — quindi averlo e non usarlo subito era
    solo un passaggio mancante.

    Una sola richiesta, per un solo autore: e' un atto esplicito su un
    autore, non un giro di massa, e non c'e' niente da limitare.
    """
    url = row.wikipedia_url_it or row.wikipedia_url_en
    if not url:
        return False
    dati, _non_interrogati = author_wikidata.fetch_for_urls({row.author_name: url})
    author_wikidata.apply(row, dati.get(row.author_name), datetime.utcnow())
    return bool(dati.get(row.author_name))


@router.post("/{name}/refresh")
def refresh_author_from_wikipedia(
    name: str,
    db: Session = Depends(database.get_db),
    # Stesso permesso di update_author_bio: modificare un autore e' un
    # permesso dell'account. Ce l'aveva solo quella rotta su sette, e le
    # altre sei erano la strada per aggirarla — DELETE /{name} cancella
    # bio, anagrafica corretta a mano e foto, e POST /{name}/refresh la
    # riempie con quello che decide Wikipedia.
    _chi: models.User = Depends(permessi.richiede_modificare_autori),
):
    """Scrapes (or re-scrapes) this author's bio/photo from Wikipedia (IT, falling back to EN)."""
    scraped = author_scraper.scrape_author(name)
    row = db.query(models.AuthorMetadata).filter(models.AuthorMetadata.author_name == name).first()
    if not row:
        row = models.AuthorMetadata(author_name=name)
        db.add(row)
    # Una sola regola per scrivere dati ed esito, condivisa con il gancio
    # sull'import e con il giro di massa: vedi author_scraper.apply_outcome.
    author_scraper.apply_outcome(row, scraped, datetime.utcnow())
    _arricchisci_da_wikidata(row)
    db.commit()
    return _serialize(row)


@router.post("/{name}/refresh-from-url")
def refresh_author_from_wikipedia_url(
    name: str,
    payload: dict,
    db: Session = Depends(database.get_db),
    # Stesso permesso di update_author_bio: modificare un autore e' un
    # permesso dell'account. Ce l'aveva solo quella rotta su sette, e le
    # altre sei erano la strada per aggirarla — DELETE /{name} cancella
    # bio, anagrafica corretta a mano e foto, e POST /{name}/refresh la
    # riempie con quello che decide Wikipedia.
    _chi: models.User = Depends(permessi.richiede_modificare_autori),
):
    """
    Scrapes bio/photo from a Wikipedia article URL the caller pastes in
    explicitly — for when /refresh's by-name auto-search picks the wrong
    homonym or finds nothing. `target_lang` says which of the two bio slots
    (it/en) the scraped text lands in; the model has no slot for other
    languages, so a French/German/... article still has to pick one.
    """
    url = (payload.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL mancante")
    target_lang = "en" if payload.get("target_lang") == "en" else "it"

    scraped = author_scraper.scrape_author_from_url(name, url)
    if not scraped:
        raise HTTPException(status_code=422, detail="URL Wikipedia non valido o pagina non trovata")

    row = db.query(models.AuthorMetadata).filter(models.AuthorMetadata.author_name == name).first()
    if not row:
        row = models.AuthorMetadata(author_name=name)
        db.add(row)
    if target_lang == "it":
        row.bio_it = scraped["bio"] or row.bio_it
        row.wikipedia_url_it = scraped["wikipedia_url"]
    else:
        row.bio_en = scraped["bio"] or row.bio_en
        row.wikipedia_url_en = scraped["wikipedia_url"]
    row.image_cached = scraped["image_cached"] or row.image_cached
    row.last_scraped_at = datetime.utcnow()
    trovato = _arricchisci_da_wikidata(row)
    db.commit()
    log_message(
        "info", "authors",
        f"Indirizzo Wikipedia dato a mano per '{name}': anagrafica Wikidata "
        + ("aggiornata" if trovato else "non trovata per quella voce"),
    )
    return _serialize(row)


# Same "age window + ETag off the source file" caching as books.py's cover
# routes — see that file's own comment for why both together (an ETag alone
# still costs a round trip per load; max-age alone risks a stale local copy
# after a re-scrape/manual photo change).
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


@public_router.get("/{name}/photo", dependencies=[Depends(auth.utente_o_dispositivo)])
def get_author_photo(name: str, db: Session = Depends(database.get_db)):
    row = db.query(models.AuthorMetadata).filter(models.AuthorMetadata.author_name == name).first()
    if not row or not row.image_cached:
        raise HTTPException(status_code=404, detail="Foto non disponibile")
    path = os.path.join(config.AUTHORS_DIR, row.image_cached)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Foto non disponibile")
    return FileResponse(
        path,
        headers={"Cache-Control": f"public, max-age={_IMAGE_CACHE_MAX_AGE_SECONDS}"},
    )


# Deliberately small: this is only ever used as the KOReader plugin's
# on-device per-author folder icon (.folder.jpg, written once per author dir
# — see main.lua's write_folder_cover handling and devices.py's
# folder_cover_url), never shown at any size in the web UI. The full-size
# photo (route above) can be an arbitrary upload up to 5MB; multiplied by
# every author folder on a device with a large library, that adds up fast
# on e-ink hardware with limited storage.
_FOLDER_COVER_MAX_DIM = 200
_FOLDER_COVER_JPEG_QUALITY = 60


@public_router.get("/{name}/photo/thumbnail", dependencies=[Depends(auth.utente_o_dispositivo)])
def get_author_photo_thumbnail(name: str, request: Request, db: Session = Depends(database.get_db)):
    row = db.query(models.AuthorMetadata).filter(models.AuthorMetadata.author_name == name).first()
    if not row or not row.image_cached:
        raise HTTPException(status_code=404, detail="Foto non disponibile")
    path = os.path.join(config.AUTHORS_DIR, row.image_cached)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Foto non disponibile")

    etag = _file_etag(path)
    headers = {"Cache-Control": f"public, max-age={_IMAGE_CACHE_MAX_AGE_SECONDS}", "ETag": etag}
    if _etag_matches(request, etag):
        return Response(status_code=304, headers=headers)

    try:
        img = Image.open(path)
        img.thumbnail((_FOLDER_COVER_MAX_DIM, _FOLDER_COVER_MAX_DIM))
        if img.mode != "RGB":
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=_FOLDER_COVER_JPEG_QUALITY)
    except Exception:
        raise HTTPException(status_code=500, detail="Errore nella generazione della miniatura")
    return Response(content=buf.getvalue(), media_type="image/jpeg", headers=headers)


@router.post("/{name}/photo")
async def upload_author_photo(
    name: str,
    file: UploadFile = File(...),
    db: Session = Depends(database.get_db),
    # Stesso permesso di update_author_bio: modificare un autore e' un
    # permesso dell'account. Ce l'aveva solo quella rotta su sette, e le
    # altre sei erano la strada per aggirarla — DELETE /{name} cancella
    # bio, anagrafica corretta a mano e foto, e POST /{name}/refresh la
    # riempie con quello che decide Wikipedia.
    _chi: models.User = Depends(permessi.richiede_modificare_autori),
):
    """Manually replace an author's photo — for when the Wikipedia scrape got the wrong person/image."""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        raise HTTPException(status_code=400, detail="Formato immagine non supportato (usa jpg, png, webp o gif)")
    content = await file.read()
    if len(content) > 5_000_000:
        raise HTTPException(status_code=400, detail="Il file supera il limite di 5MB")

    row = db.query(models.AuthorMetadata).filter(models.AuthorMetadata.author_name == name).first()
    if not row:
        row = models.AuthorMetadata(author_name=name)
        db.add(row)

    os.makedirs(config.AUTHORS_DIR, exist_ok=True)
    if row.image_cached:
        old_path = os.path.join(config.AUTHORS_DIR, row.image_cached)
        if os.path.exists(old_path):
            os.remove(old_path)
    filename = f"{quote(name, safe='')}{ext}"
    with open(os.path.join(config.AUTHORS_DIR, filename), "wb") as f:
        f.write(content)
    row.image_cached = filename
    db.commit()
    return _serialize(row)

@router.post("/{name}/photo-from-url")
def set_author_photo_from_url(
    name: str,
    payload: dict,
    db: Session = Depends(database.get_db),
    # Stesso permesso di update_author_bio: modificare un autore e' un
    # permesso dell'account. Ce l'aveva solo quella rotta su sette, e le
    # altre sei erano la strada per aggirarla — DELETE /{name} cancella
    # bio, anagrafica corretta a mano e foto, e POST /{name}/refresh la
    # riempie con quello che decide Wikipedia.
    _chi: models.User = Depends(permessi.richiede_modificare_autori),
):
    """
    Scarica la foto di un autore da un indirizzo, invece di caricare un file.

    La usa sia la griglia di ricerca immagini (che propone Wikimedia Commons)
    sia chi incolla a mano l'indirizzo di una qualunque immagine. Vedi il
    commento sopra `_indirizzo_raggiungibile` per il perche' di ogni controllo.
    """
    url = (payload.get("url") or "").strip()
    contenuto, ext = scarica_immagine(url)

    row = db.query(models.AuthorMetadata).filter(models.AuthorMetadata.author_name == name).first()
    if not row:
        row = models.AuthorMetadata(author_name=name)
        db.add(row)

    os.makedirs(config.AUTHORS_DIR, exist_ok=True)
    if row.image_cached:
        old_path = os.path.join(config.AUTHORS_DIR, row.image_cached)
        if os.path.exists(old_path):
            os.remove(old_path)
    filename = f"{quote(name, safe='')}{ext}"
    with open(os.path.join(config.AUTHORS_DIR, filename), "wb") as f:
        f.write(contenuto)
    row.image_cached = filename
    db.commit()
    return _serialize(row)


@router.delete("/{name}/photo")
def delete_author_photo(
    name: str,
    db: Session = Depends(database.get_db),
    # Stesso permesso di update_author_bio: modificare un autore e' un
    # permesso dell'account. Ce l'aveva solo quella rotta su sette, e le
    # altre sei erano la strada per aggirarla — DELETE /{name} cancella
    # bio, anagrafica corretta a mano e foto, e POST /{name}/refresh la
    # riempie con quello che decide Wikipedia.
    _chi: models.User = Depends(permessi.richiede_modificare_autori),
):
    row = db.query(models.AuthorMetadata).filter(models.AuthorMetadata.author_name == name).first()
    if not row or not row.image_cached:
        raise HTTPException(status_code=404, detail="Nessuna foto da eliminare")
    path = os.path.join(config.AUTHORS_DIR, row.image_cached)
    if os.path.exists(path):
        os.remove(path)
    row.image_cached = None
    db.commit()
    return _serialize(row)


@router.delete("/{name}")
def reset_author_data(
    name: str,
    db: Session = Depends(database.get_db),
    # Stesso permesso di update_author_bio: modificare un autore e' un
    # permesso dell'account. Ce l'aveva solo quella rotta su sette, e le
    # altre sei erano la strada per aggirarla — DELETE /{name} cancella
    # bio, anagrafica corretta a mano e foto, e POST /{name}/refresh la
    # riempie con quello che decide Wikipedia.
    _chi: models.User = Depends(permessi.richiede_modificare_autori),
):
    """Wipes everything scraped/entered for this author (bio, links, photo) —
    for when the Wikipedia scrape matched the wrong person entirely and just
    editing individual fields wouldn't be enough. The author itself (and
    their books) isn't touched, only this metadata sidecar row."""
    row = db.query(models.AuthorMetadata).filter(models.AuthorMetadata.author_name == name).first()
    if not row:
        return {"status": "ok"}
    if row.image_cached:
        path = os.path.join(config.AUTHORS_DIR, row.image_cached)
        if os.path.exists(path):
            os.remove(path)
    db.delete(row)
    db.commit()
    return {"status": "ok"}
