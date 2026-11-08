from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import auth, database, models
from ..logging_utils import log_message
from ..schemas_risposte import (
    DefinizioneTrovata, DizionariConosciuti, DizionarioInstallato, Esito,
)
from ..services import dictionary_service, preferenze_utente, stardict_service

router = APIRouter(prefix="/api/kolibre/dictionaries", tags=["dictionaries"])


@router.get(
    "/lookup",
    responses={200: {"model": DefinizioneTrovata}},
)
def lookup_word(
    word: str,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Ricerca al volo (locale se il dizionario è installato, altrimenti
    Wiktionary online) SENZA persistere nulla — usata dal popup di selezione
    testo nel reader web per mostrare la definizione di una parola PRIMA che
    l'utente scelga se aggiungerla al vocabolario: aggiungerla a
    WebVocabularyEntry solo per mostrare un'anteprima (vedi vocabulary.py)
    riempirebbe il vocabolario di parole solo guardate, mai davvero salvate."""
    word = (word or "").strip()
    if not word:
        raise HTTPException(status_code=400, detail="The 'word' parameter is required")
    # La lingua dell'account decide solo l'ORDINE in cui si guardano le
    # lingue: vedi dictionary_service.lingue_preferite. Questo router e' gia'
    # autenticato (main.py lo include con `dependencies=_AUTH`), quindi
    # chiedere chi sta cercando non cambia chi puo' cercare.
    result = dictionary_service.fetch_definition(
        word, preferenze_utente.lingua_di(db, current_user.id)
    )
    if not result:
        raise HTTPException(status_code=404, detail=f"No definition found for '{word}'")
    return result


@router.get(
    "",
    responses={200: {"model": DizionariConosciuti}},
)
def list_dictionaries():
    """Impostazioni → Integrazioni: elenca sia i dizionari conosciuti
    (installabili) sia il loro stato di installazione — così il frontend
    può mostrare un unico elenco con azione Installa/Rimuovi per riga,
    senza dover incrociare due liste diverse."""
    installed = {d["lang"]: d for d in stardict_service.list_installed()}
    return {
        "items": [
            {
                "lang": lang,
                "display_name": meta["display_name"],
                "attribution": meta["attribution"],
                "installed": lang in installed,
                "bookname": installed.get(lang, {}).get("bookname"),
                "wordcount": installed.get(lang, {}).get("wordcount"),
            }
            for lang, meta in stardict_service.KNOWN_DICTIONARIES.items()
        ]
    }


@router.post(
    "/{lang}/install",
    responses={200: {"model": DizionarioInstallato}},
)
def install_dictionary(lang: str):
    if lang not in stardict_service.KNOWN_DICTIONARIES:
        raise HTTPException(status_code=404, detail=f"Unknown dictionary: '{lang}'")
    try:
        result = stardict_service.install(lang)
    except Exception as e:
        log_message("warning", "dictionaries", f"Installing dictionary '{lang}' failed: {e}")
        raise HTTPException(status_code=502, detail=f"Download or install failed: {e}")
    log_message("info", "dictionaries", f"Dictionary '{lang}' installed: {result.get('wordcount')} words.")
    return {"status": "ok", **result}


@router.delete(
    "/{lang}",
    responses={200: {"model": Esito}},
)
def uninstall_dictionary(lang: str):
    if lang not in stardict_service.KNOWN_DICTIONARIES:
        raise HTTPException(status_code=404, detail=f"Unknown dictionary: '{lang}'")
    stardict_service.uninstall(lang)
    log_message("info", "dictionaries", f"Dictionary '{lang}' removed.")
    return {"status": "ok"}
