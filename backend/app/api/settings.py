"""
Le impostazioni del server, e **chi le ha cambiate**.

**Da zero: perche' questo file ha un registro e prima no.** Qui vivono le nove
impostazioni che cambiano il comportamento del server: come si contano le
pagine di un libro, se il feed OPDS risponde, se il lettore web raccoglie i
tempi di lettura, da quanti libri in su la biblioteca si impagina. Sono le
cose che si cambiano una volta e poi non si ricorda di aver cambiato — ed e'
esattamente la ragione per cui un registro serve: la domanda non e' «com'e'
impostato?» (lo dice la pagina) ma **«perche' da ieri si comporta cosi'?»**.

Fino al 17/11/2026 questo modulo aveva **nove scritture e zero righe di
registro**: il piu' silenzioso di tutto il backend, misurato. Paolo:
*«scrive decisamente troppi pochi log… andrebbero aggiunti un po' ovunque»*.

**La regola, decisa con lui**: si scrive quando il server **decide** o
**cambia** qualcosa, non quando risponde. Qui vuol dire due cose:

  * **INFO quando un valore cambia davvero**, col prima e il dopo. Il «prima»
    non e' un ornamento: senza di lui una riga dice «qualcuno ha toccato la
    paginazione» e non «l'ha portata da 10000 a 50», che e' la differenza fra
    sapere e indovinare.
  * **WARNING quando il server stringe quello che gli e' stato chiesto.**
    Tutti questi valori passano per un `max(min(...))` nei loro setter: chi
    chiede una pagina da cinquantamila libri ne ottiene una da duemila, e
    fino a oggi **non restava scritto da nessuna parte** — ne' nella risposta,
    che torna il valore vero senza dire che e' un altro, ne' a schermo. E' il
    caso in cui il registro e' la sola traccia che qualcosa non e' andato come
    chiesto.

**Un PUT che non cambia niente non si scrive.** Il sito rimanda l'impostazione
intera anche quando una persona ne ha toccato un pezzo, e certe pagine la
rimandano all'apertura: scrivere una riga per ognuna vorrebbe dire un registro
in cui le righe vere non si trovano piu'. «Si scrive quando si cambia» va
preso alla lettera.

**Chi**: il nome dell'account, che qui e' l'identificatore (non c'e' altro
nome di persona in una riga di questo registro, e il contenuto di
un'impostazione non e' un dato personale).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import auth, database, models
from ..logging_utils import log_message
from ..schemas_risposte import (
    ImpostazioneContoPagine, ImpostazionePaginazione,
    Interruttore, SogliaDelleSessioni, TettoDellIndice,
)
from ..services import app_settings, stats_service

router = APIRouter(prefix="/api/kolibre/settings", tags=["settings"])


def _chi(utente) -> str:
    """Il nome dell'account che ha fatto la richiesta, o un segnaposto."""
    return getattr(utente, "username", None) or "?"


def _breve(valore, massimo: int = 120) -> str:
    """
    Un valore reso leggibile su una riga sola.

    Le impostazioni sono numeri, interruttori e dizionari di tre campi: ci
    stanno. Il taglio c'e' perche' un registro in cui una riga va a capo e'
    un registro che non si legge piu' con `grep`.
    """
    testo = repr(valore)
    return testo if len(testo) <= massimo else testo[:massimo - 1] + "…"


def _diverso(chiesto, ottenuto) -> bool:
    """
    Vero se il server ha tenuto un valore diverso da quello chiesto.

    **Il confronto e' morbido di proposito.** Il sito manda JSON, e un campo
    numerico puo' arrivare come testo («"500"») oppure come numero: confrontare
    con `!=` farebbe comparire un avviso per ogni richiesta andata benissimo —
    cioe' avvisi falsi, che sono peggio di nessun avviso perche' si impara a
    ignorarli.
    """
    if chiesto == ottenuto:
        return False
    try:
        if isinstance(ottenuto, bool):
            return bool(chiesto) is not ottenuto
        if isinstance(ottenuto, (int, float)):
            return float(chiesto) != float(ottenuto)
    except (TypeError, ValueError):
        return True
    return str(chiesto) != str(ottenuto)


def _annota_le_strette(chi: str, nome: str, chiesto, ottenuto) -> None:
    """I campi che il server ha stretto nei suoi limiti, uno per riga."""
    if isinstance(chiesto, dict) and isinstance(ottenuto, dict):
        for campo, valore in chiesto.items():
            if campo in ottenuto and _diverso(valore, ottenuto[campo]):
                log_message(
                    "warning", "settings",
                    f"'{chi}' asked {nome}.{campo} = {_breve(valore)}, "
                    f"the server kept {_breve(ottenuto[campo])}")
        return
    if chiesto is not None and _diverso(chiesto, ottenuto):
        log_message(
            "warning", "settings",
            f"'{chi}' asked {nome} = {_breve(chiesto)}, "
            f"the server kept {_breve(ottenuto)}")


def _annota(chi: str, nome: str, prima, dopo, chiesto=None) -> None:
    """
    Il cambio di un'impostazione: una riga se e' cambiata, nessuna se no.

    `chiesto` e' quello che e' arrivato nella richiesta, quando c'e': serve
    solo a dire se il server l'ha stretto. Vedi in testa al file.
    """
    _annota_le_strette(chi, nome, chiesto, dopo)
    if prima == dopo:
        return
    log_message("info", "settings",
                f"'{chi}' changed {nome}: {_breve(prima)} -> {_breve(dopo)}")


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
def update_page_count_settings(
    payload: dict,
    db: Session = Depends(database.get_db),
    chi: models.User = Depends(auth.get_current_user_flexible),
):
    prima = app_settings.get_page_count_settings(db)
    dopo = app_settings.set_page_count_settings(db, payload)
    _annota(_chi(chi), "page-count", prima, dopo, payload)
    return dopo


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
def update_auto_wiki_scrape_setting(
    payload: dict,
    db: Session = Depends(database.get_db),
    chi: models.User = Depends(auth.get_current_user_flexible),
):
    prima = app_settings.is_auto_wiki_scrape_enabled(db)
    dopo = app_settings.set_auto_wiki_scrape_enabled(db, payload.get("enabled", True))
    _annota(_chi(chi), "auto-wiki-scrape", prima, dopo)
    return {"enabled": dopo}


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
def update_opds_feed_setting(
    payload: dict,
    db: Session = Depends(database.get_db),
    chi: models.User = Depends(auth.get_current_user_flexible),
):
    # **Questa accende o spegne una porta aperta**: il feed OPDS risponde con
    # la sua autenticazione (HTTP Basic) e lo leggono programmi di fuori.
    # Accenderlo e' una decisione, ed e' fra le prime cose da ritrovare in un
    # registro se un giorno qualcosa arriva da dove non te l'aspetti.
    prima = app_settings.is_opds_feed_enabled(db)
    dopo = app_settings.set_opds_feed_enabled(db, payload.get("enabled", False))
    _annota(_chi(chi), "opds-feed", prima, dopo)
    return {"enabled": dopo}


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
def update_web_reader_tracking_setting(
    payload: dict,
    db: Session = Depends(database.get_db),
    chi: models.User = Depends(auth.get_current_user_flexible),
):
    # Il valore di ripiego e' il DEFAULT, non `True`: una richiesta senza campo
    # non deve accendere la raccolta dei dati. Era l'unico posto dove l'acceso
    # di una volta restava scritto a mano.
    predefinito = app_settings.DEFAULT_WEB_READER_TRACKING["enabled"]
    # **Questa decide se si raccolgono dati di lettura**, quindi e' la riga
    # che si va a cercare per sapere da quando (o se) i tempi del lettore web
    # finiscono nelle statistiche.
    prima = app_settings.is_web_reader_tracking_enabled(db)
    dopo = app_settings.set_web_reader_tracking_enabled(db, payload.get("enabled", predefinito))
    _annota(_chi(chi), "web-reader-tracking", prima, dopo)
    return {"enabled": dopo}


@router.get(
    "/incorpora-pagine",
    responses={200: {"model": Interruttore}},
)
def get_incorpora_pagine_setting(db: Session = Depends(database.get_db)):
    return {"enabled": app_settings.is_incorpora_pagine_enabled(db)}


@router.put(
    "/incorpora-pagine",
    responses={200: {"model": Interruttore}},
)
def update_incorpora_pagine_setting(
    payload: dict,
    db: Session = Depends(database.get_db),
    chi: models.User = Depends(auth.get_current_user_flexible),
):
    # **Questa decide se Kolibre riscrive i tuoi file EPUB**, e per questo il
    # ripiego e' il default (spento) e non `True`: una richiesta senza campo
    # non deve mettersi a riscrivere una biblioteca.
    #
    # E' anche la riga che si va a cercare quando un'impronta non torna: da
    # quando questo interruttore e' acceso, ogni stima nuova cambia i byte
    # del file a cui si riferisce. Il nome, il prima e il dopo bastano —
    # chi ha acceso e quando sono esattamente la domanda che ci si fa.
    predefinito = app_settings.DEFAULT_INCORPORA_PAGINE["enabled"]
    prima = app_settings.is_incorpora_pagine_enabled(db)
    dopo = app_settings.set_incorpora_pagine_enabled(db, payload.get("enabled", predefinito))
    _annota(_chi(chi), "incorpora-pagine", prima, dopo)
    return {"enabled": dopo}


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
def update_library_pagination_setting(
    payload: dict,
    db: Session = Depends(database.get_db),
    chi: models.User = Depends(auth.get_current_user_flexible),
):
    prima = app_settings.get_library_pagination(db)
    dopo = app_settings.set_library_pagination(db, payload)
    _annota(_chi(chi), "library-pagination", prima, dopo, payload)
    return dopo


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
def update_fulltext_limit_setting(
    payload: dict,
    db: Session = Depends(database.get_db),
    chi: models.User = Depends(auth.get_current_user_flexible),
):
    prima = app_settings.get_fulltext_limit_gb(db)
    dopo = app_settings.set_fulltext_limit_gb(db, payload.get("max_gb", 10.0))
    _annota(_chi(chi), "fulltext-limit-gb", prima, dopo, payload.get("max_gb"))
    return {"max_gb": dopo}


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
def update_ingest_pagination_setting(
    payload: dict,
    db: Session = Depends(database.get_db),
    chi: models.User = Depends(auth.get_current_user_flexible),
):
    prima = app_settings.get_ingest_pagination(db)
    dopo = app_settings.set_ingest_pagination(db, payload)
    _annota(_chi(chi), "ingest-pagination", prima, dopo, payload)
    return dopo


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
def update_authors_pagination_setting(
    payload: dict,
    db: Session = Depends(database.get_db),
    chi: models.User = Depends(auth.get_current_user_flexible),
):
    prima = app_settings.get_authors_pagination(db)
    dopo = app_settings.set_authors_pagination(db, payload)
    _annota(_chi(chi), "authors-pagination", prima, dopo, payload)
    return dopo


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
def update_stats_session_threshold(
    payload: dict,
    db: Session = Depends(database.get_db),
    chi: models.User = Depends(auth.get_current_user_flexible),
):
    """Sotto questa durata una sessione non entra nelle statistiche. Il
    cruscotto legge una cache, quindi si rinfresca subito: altrimenti la
    soglia sembrerebbe non avere effetto fino al giorno dopo."""
    prima = app_settings.get_soglia_sessione(db)
    valore = app_settings.set_soglia_sessione(db, payload.get("seconds", 0))
    # **Questa cambia i numeri delle statistiche senza toccare i dati**: le
    # sessioni restano tutte, ma alcune smettono di essere contate. Un
    # cruscotto che da ieri dice meno ore ha qui la sua spiegazione, e senza
    # questa riga non l'avrebbe in nessun altro posto.
    _annota(_chi(chi), "stats-session-threshold-seconds", prima, valore,
            payload.get("seconds"))
    stats_service.refresh_stats_cache(db)
    return {"seconds": valore}
