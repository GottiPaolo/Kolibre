from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import database
from ..schemas_risposte import (
    ImpostazioneContoPagine, ImpostazionePaginazione, Interruttore,
    SogliaDelleSessioni, TettoDellIndice,
)
from ..services import app_settings, stats_service

router = APIRouter(prefix="/api/kolibre/settings", tags=["settings"])


@router.get(
    "/page-count",
    responses={200: {"model": ImpostazioneContoPagine}},
)
def get_page_count_settings(db: Session = Depends(database.get_db)):
    return app_settings.get_page_count_settings(db)


@router.put(
    "/page-count",
    responses={200: {"model": ImpostazioneContoPagine}},
)
def update_page_count_settings(payload: dict, db: Session = Depends(database.get_db)):
    return app_settings.set_page_count_settings(db, payload)


@router.get(
    "/auto-wiki-scrape",
    responses={200: {"model": Interruttore}},
)
def get_auto_wiki_scrape_setting(db: Session = Depends(database.get_db)):
    return {"enabled": app_settings.is_auto_wiki_scrape_enabled(db)}


@router.put(
    "/auto-wiki-scrape",
    responses={200: {"model": Interruttore}},
)
def update_auto_wiki_scrape_setting(payload: dict, db: Session = Depends(database.get_db)):
    return {"enabled": app_settings.set_auto_wiki_scrape_enabled(db, payload.get("enabled", True))}


@router.get(
    "/opds-feed",
    responses={200: {"model": Interruttore}},
)
def get_opds_feed_setting(db: Session = Depends(database.get_db)):
    return {"enabled": app_settings.is_opds_feed_enabled(db)}


@router.put(
    "/opds-feed",
    responses={200: {"model": Interruttore}},
)
def update_opds_feed_setting(payload: dict, db: Session = Depends(database.get_db)):
    return {"enabled": app_settings.set_opds_feed_enabled(db, payload.get("enabled", False))}


@router.get(
    "/web-reader-tracking",
    responses={200: {"model": Interruttore}},
)
def get_web_reader_tracking_setting(db: Session = Depends(database.get_db)):
    return {"enabled": app_settings.is_web_reader_tracking_enabled(db)}


@router.put(
    "/web-reader-tracking",
    responses={200: {"model": Interruttore}},
)
def update_web_reader_tracking_setting(payload: dict, db: Session = Depends(database.get_db)):
    # Il valore di ripiego e' il DEFAULT, non `True`: una richiesta senza campo
    # non deve accendere la raccolta dei dati. Era l'unico posto dove l'acceso
    # di una volta restava scritto a mano.
    predefinito = app_settings.DEFAULT_WEB_READER_TRACKING["enabled"]
    return {"enabled": app_settings.set_web_reader_tracking_enabled(db, payload.get("enabled", predefinito))}


@router.get(
    "/library-pagination",
    responses={200: {"model": ImpostazionePaginazione}},
)
def get_library_pagination_setting(db: Session = Depends(database.get_db)):
    return app_settings.get_library_pagination(db)


@router.put(
    "/library-pagination",
    responses={200: {"model": ImpostazionePaginazione}},
)
def update_library_pagination_setting(payload: dict, db: Session = Depends(database.get_db)):
    return app_settings.set_library_pagination(db, payload)


@router.get(
    "/fulltext-limit",
    responses={200: {"model": TettoDellIndice}},
)
def get_fulltext_limit_setting(db: Session = Depends(database.get_db)):
    return {"max_gb": app_settings.get_fulltext_limit_gb(db)}


@router.put(
    "/fulltext-limit",
    responses={200: {"model": TettoDellIndice}},
)
def update_fulltext_limit_setting(payload: dict, db: Session = Depends(database.get_db)):
    return {"max_gb": app_settings.set_fulltext_limit_gb(db, payload.get("max_gb", 10.0))}


@router.get(
    "/ingest-pagination",
    responses={200: {"model": ImpostazionePaginazione}},
)
def get_ingest_pagination_setting(db: Session = Depends(database.get_db)):
    return app_settings.get_ingest_pagination(db)


@router.put(
    "/ingest-pagination",
    responses={200: {"model": ImpostazionePaginazione}},
)
def update_ingest_pagination_setting(payload: dict, db: Session = Depends(database.get_db)):
    return app_settings.set_ingest_pagination(db, payload)


@router.get(
    "/authors-pagination",
    responses={200: {"model": ImpostazionePaginazione}},
)
def get_authors_pagination_setting(db: Session = Depends(database.get_db)):
    return app_settings.get_authors_pagination(db)


@router.put(
    "/authors-pagination",
    responses={200: {"model": ImpostazionePaginazione}},
)
def update_authors_pagination_setting(payload: dict, db: Session = Depends(database.get_db)):
    return app_settings.set_authors_pagination(db, payload)


@router.get(
    "/stats-session-threshold",
    responses={200: {"model": SogliaDelleSessioni}},
)
def get_stats_session_threshold(db: Session = Depends(database.get_db)):
    return {"seconds": app_settings.get_soglia_sessione(db)}


@router.put(
    "/stats-session-threshold",
    responses={200: {"model": SogliaDelleSessioni}},
)
def update_stats_session_threshold(payload: dict, db: Session = Depends(database.get_db)):
    """Sotto questa durata una sessione non entra nelle statistiche. Il
    cruscotto legge una cache, quindi si rinfresca subito: altrimenti la
    soglia sembrerebbe non avere effetto fino al giorno dopo."""
    valore = app_settings.set_soglia_sessione(db, payload.get("seconds", 0))
    stats_service.refresh_stats_cache(db)
    return {"seconds": valore}
