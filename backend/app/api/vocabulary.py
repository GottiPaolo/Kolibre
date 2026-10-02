from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import auth, config, database, models
from ..calibre.library import CalibreLibrary
from ..services import dictionary_service

router = APIRouter(prefix="/api/kolibre/vocabulary", tags=["vocabulary"])


def _book_title(library: str, calibre_book_id: int):
    try:
        book = CalibreLibrary(config.library_path(library)).get_book(calibre_book_id)
        return book["title"] if book else None
    except Exception:
        return None


def _serialize_device_entry(v: models.VocabularyEntry, device_name: str) -> dict:
    return {
        "id": f"device:{v.id}",
        "source": "device",
        "source_label": device_name,
        "word": v.word,
        "highlight": v.highlight,
        "book_title": v.book_title,
        "library": None,
        "calibre_book_id": None,
        "context_before": v.context_before,
        "context_after": v.context_after,
        "create_time": v.create_time.isoformat() if v.create_time else None,
        "definition": v.definition,
        "definition_source": v.definition_source,
        "definition_fetched_at": v.definition_fetched_at.isoformat() if v.definition_fetched_at else None,
    }


def _serialize_web_entry(v: models.WebVocabularyEntry) -> dict:
    return {
        "id": f"web:{v.id}",
        "source": "web",
        # Vuoto di proposito, non "Lettore Web": il nome di un DISPOSITIVO lo
        # sceglie chi lo registra e non si traduce, ma "lettore web" è
        # un'etichetta d'interfaccia, e il server non sa in che lingua la sta
        # leggendo. Il frontend la scrive da sé partendo da `source`.
        "source_label": "",
        "word": v.word,
        "highlight": v.highlight,
        "book_title": _book_title(v.library, v.calibre_book_id),
        "library": v.library,
        "calibre_book_id": v.calibre_book_id,
        "context_before": v.context_before,
        "context_after": v.context_after,
        "create_time": v.create_time.isoformat() if v.create_time else None,
        "definition": v.definition,
        "definition_source": v.definition_source,
        "definition_fetched_at": v.definition_fetched_at.isoformat() if v.definition_fetched_at else None,
    }


@router.get("")
def list_vocabulary(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    Centralized Vocabulary Builder: merges every KOReader device's own
    vocabulary_entries (see that model's docstring) with this user's
    web-reader lookups (web_vocabulary_entries) into one flat, newest-first
    list — the "one page for all your looked-up words, wherever they came
    from" view, instead of hunting through each device's own tab.
    """
    device_rows = (
        db.query(models.VocabularyEntry, models.Device.name)
        .join(models.Device, models.Device.id == models.VocabularyEntry.device_id)
        .filter(models.Device.user_id == current_user.id)
        .all()
    )
    web_rows = db.query(models.WebVocabularyEntry).filter(
        models.WebVocabularyEntry.user_id == current_user.id
    ).all()

    items = [_serialize_device_entry(v, name) for v, name in device_rows]
    items += [_serialize_web_entry(v) for v in web_rows]
    items.sort(key=lambda item: item["create_time"] or "", reverse=True)
    return {"items": items}


@router.get("/sovrapposizioni")
def vocabulary_overlaps(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    Quali dispositivi hanno le stesse identiche parole, e quante.

    Versione d'insieme di quello che era il riquadro dentro la scheda di ogni
    singolo dispositivo: la sovrapposizione e' una relazione **fra** due
    lettori, e chiedersela un dispositivo alla volta significava non vederla
    mai tutta. Da qui si vede in un colpo solo chi ha copiato da chi.

    Non e' di per se' un difetto: KOReader tiene una riga per parola per
    dispositivo, e due lettori possono legittimamente avere vocabolari
    propri. Lo diventa quando i due hanno lo stesso
    `vocabulary_builder.sqlite3` perche' qualcuno li ha sincronizzati fra
    loro — cosa che fra due dispositivi dello stesso utente e' gia' costata
    743 sessioni di lettura mai avvenute.

    Si conta e basta: togliere resta una decisione di chi guarda
    (`DELETE /api/devices/{id}/vocabulary`).
    """
    parole_per_dispositivo: dict[int, set] = {}
    nomi: dict[int, str] = {}
    for device_id, nome, parola in (
        db.query(models.Device.id, models.Device.name, models.VocabularyEntry.word)
        .join(models.VocabularyEntry, models.VocabularyEntry.device_id == models.Device.id)
        .filter(models.Device.user_id == current_user.id)
    ):
        nomi[device_id] = nome
        parole_per_dispositivo.setdefault(device_id, set()).add(parola)

    dispositivi = [
        {
            "id": device_id,
            "nome": nomi[device_id],
            "parole": len(parole),
            # Le parole che esistono identiche su almeno un ALTRO dispositivo:
            # e' questo il numero che dice se il vocabolario e' una copia.
            "in_comune": [
                {"id": altro_id, "nome": nomi[altro_id], "parole": len(parole & altre)}
                for altro_id, altre in sorted(parole_per_dispositivo.items())
                if altro_id != device_id and parole & altre
            ],
        }
        for device_id, parole in sorted(parole_per_dispositivo.items())
    ]
    return {"dispositivi": dispositivi}


@router.post("")
def add_word_from_reader(
    payload: dict,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    "Aggiungi al vocabolario" from the web reader's word-lookup popup. Looking
    the same word up again just updates its context in place (same "one row
    per unique word" identity as VocabularyEntry itself, see that model's
    docstring) — never creates a duplicate.

    `definition`/`definition_source` are optional: the reader popup already
    calls GET /api/kolibre/dictionaries/lookup to show the definition before
    the user decides to add the word, so passing it here avoids fetching it
    a second time right after creating the row.
    """
    library = payload.get("library")
    calibre_book_id = payload.get("calibre_book_id")
    word = (payload.get("word") or "").strip()
    if not library or not calibre_book_id or not word:
        raise HTTPException(status_code=400, detail="library, calibre_book_id e word sono obbligatori")

    definition = payload.get("definition")
    definition_source = payload.get("definition_source")

    entry = db.query(models.WebVocabularyEntry).filter(
        models.WebVocabularyEntry.user_id == current_user.id,
        models.WebVocabularyEntry.word == word,
    ).first()
    if entry:
        entry.library = library
        entry.calibre_book_id = calibre_book_id
        entry.highlight = payload.get("highlight")
        entry.context_before = payload.get("context_before")
        entry.context_after = payload.get("context_after")
    else:
        entry = models.WebVocabularyEntry(
            user_id=current_user.id,
            library=library,
            calibre_book_id=calibre_book_id,
            word=word,
            highlight=payload.get("highlight"),
            context_before=payload.get("context_before"),
            context_after=payload.get("context_after"),
            create_time=datetime.utcnow(),
        )
        db.add(entry)
    if definition:
        entry.definition = definition
        entry.definition_source = definition_source
        entry.definition_fetched_at = datetime.utcnow()
    db.commit()
    db.refresh(entry)
    return _serialize_web_entry(entry)


def _resolve_entry(db: Session, current_user: models.User, composite_id: str):
    source, _, raw_id = composite_id.partition(":")
    if not raw_id.isdigit():
        raise HTTPException(status_code=404, detail="Parola non trovata")
    numeric_id = int(raw_id)

    if source == "web":
        entry = db.query(models.WebVocabularyEntry).filter(
            models.WebVocabularyEntry.id == numeric_id, models.WebVocabularyEntry.user_id == current_user.id
        ).first()
        if not entry:
            raise HTTPException(status_code=404, detail="Parola non trovata")
        return entry, _serialize_web_entry
    if source == "device":
        entry = (
            db.query(models.VocabularyEntry)
            .join(models.Device, models.Device.id == models.VocabularyEntry.device_id)
            .filter(models.VocabularyEntry.id == numeric_id, models.Device.user_id == current_user.id)
            .first()
        )
        if not entry:
            raise HTTPException(status_code=404, detail="Parola non trovata")
        device_name = db.query(models.Device.name).filter(models.Device.id == entry.device_id).scalar()
        return entry, lambda v: _serialize_device_entry(v, device_name)
    raise HTTPException(status_code=404, detail="Parola non trovata")


@router.post("/{composite_id}/fetch-definition")
def fetch_definition_unified(
    composite_id: str,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Same on-demand lookup as the per-device endpoint (devices.py's
    fetch_vocabulary_definition), reused here for the centralized page so
    both a device-origin and a web-origin word can be looked up from one
    unified list without the frontend needing to know which table a word
    lives in beyond the `source` prefix already in its id."""
    entry, serialize = _resolve_entry(db, current_user, composite_id)

    result = dictionary_service.fetch_definition(entry.word)
    if not result:
        raise HTTPException(status_code=404, detail=f"Nessuna definizione trovata per '{entry.word}'")

    entry.definition = result["definition"]
    entry.definition_source = result["source"]
    entry.definition_fetched_at = datetime.utcnow()
    db.commit()
    db.refresh(entry)
    return serialize(entry)
