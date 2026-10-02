from fastapi import APIRouter, HTTPException

from ..logging_utils import log_message
from ..services import dictionary_service, stardict_service

router = APIRouter(prefix="/api/kolibre/dictionaries", tags=["dictionaries"])


@router.get("/lookup")
def lookup_word(word: str):
    """Ricerca al volo (locale se il dizionario è installato, altrimenti
    Wiktionary online) SENZA persistere nulla — usata dal popup di selezione
    testo nel reader web per mostrare la definizione di una parola PRIMA che
    l'utente scelga se aggiungerla al vocabolario: aggiungerla a
    WebVocabularyEntry solo per mostrare un'anteprima (vedi vocabulary.py)
    riempirebbe il vocabolario di parole solo guardate, mai davvero salvate."""
    word = (word or "").strip()
    if not word:
        raise HTTPException(status_code=400, detail="Parametro 'word' obbligatorio")
    result = dictionary_service.fetch_definition(word)
    if not result:
        raise HTTPException(status_code=404, detail=f"Nessuna definizione trovata per '{word}'")
    return result


@router.get("")
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


@router.post("/{lang}/install")
def install_dictionary(lang: str):
    if lang not in stardict_service.KNOWN_DICTIONARIES:
        raise HTTPException(status_code=404, detail=f"Dizionario sconosciuto: '{lang}'")
    try:
        result = stardict_service.install(lang)
    except Exception as e:
        log_message("warning", "dictionaries", f"Installazione dizionario '{lang}' fallita: {e}")
        raise HTTPException(status_code=502, detail=f"Download/installazione fallita: {e}")
    log_message("info", "dictionaries", f"Dizionario '{lang}' installato: {result.get('wordcount')} parole.")
    return {"status": "ok", **result}


@router.delete("/{lang}")
def uninstall_dictionary(lang: str):
    if lang not in stardict_service.KNOWN_DICTIONARIES:
        raise HTTPException(status_code=404, detail=f"Dizionario sconosciuto: '{lang}'")
    stardict_service.uninstall(lang)
    log_message("info", "dictionaries", f"Dizionario '{lang}' rimosso.")
    return {"status": "ok"}
