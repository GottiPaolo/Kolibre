"""
Indirizzi condivisibili: comporli, e risolverli.

**Da zero.** Un link incollato in un appunto deve aprirsi fra un anno. La
forma (`/k/<biblioteca>/<titolo>-<corto>/n/<nota>`) e come si scrive stanno in
`services/link_condivisibile.py`, che e' solo stringhe. Qui c'e' la parte che
ha bisogno del database e del disco: **a chi** corrisponde un indirizzo, e
cosa si apre quando quello che indica non c'e' piu'.

**Il principio: un link si risolve nel server, non nel browser.** Ogni
ripiego — nota sparita, libro spostato, biblioteca ambigua — e' una regola sui
dati, e scritta qui vale per il browser, per il plugin di Obsidian e per
qualunque client futuro. Scritta nel frontend andrebbe riscritta in ognuno,
e un link vecchio diventerebbe una pagina bianca invece di una spiegazione.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from .. import auth, config, database, models
from ..calibre.library import CalibreLibrary
from ..schemas_risposte import LinkGenerato, LinkRisolto
from ..services import identita_durevole, link_condivisibile as L, permessi

router = APIRouter(prefix="/api/kolibre/link", tags=["link"])


def _libri_della_biblioteca(cartella: str) -> list:
    """I libri di una biblioteca, o un elenco vuoto se non si riesce ad
    aprirla. Una biblioteca che non c'e' piu' sul disco non deve far morire
    la risoluzione di un link che punta a un'altra."""
    try:
        return CalibreLibrary(config.library_path(cartella)).list_books()
    except Exception:
        return []


def _biblioteca_dallo_slug(db: Session, utente: models.User, pezzo: str):
    """
    La biblioteca che quel pezzo di indirizzo indica, fra quelle che questa
    persona puo' vedere. Torna `(biblioteca, motivo)`.

    **Si guarda prima il nome esatto della cartella**, e solo dopo lo slug, e
    non e' pignoleria: Paolo ha due biblioteche che differiscono solo per la
    maiuscola (`libreria` e `Libreria`), e lo slug le appiattisce sulla stessa
    parola. Se dopo il confronto esatto restano due candidate, si dice
    «ambigua» invece di scegliere a caso — per un LIBRO non succede comunque
    niente di male, perche' l'uuid di Calibre risolve da solo e la biblioteca
    e' solo un suggerimento.
    """
    visibili = permessi.biblioteche_visibili(db, utente)
    for b in visibili:
        if b.folder_name == pezzo:
            return b, None
    candidate = [b for b in visibili if L.slug(b.folder_name) == pezzo]
    if len(candidate) == 1:
        return candidate[0], None
    if len(candidate) > 1:
        return None, "biblioteca_ambigua"
    candidate = [b for b in visibili if L.slug(b.name) == pezzo]
    if len(candidate) == 1:
        return candidate[0], None
    return None, "biblioteca_sparita"


def _libro_dal_corto(db: Session, utente: models.User, corto: Optional[str], suggerita):
    """
    Il libro il cui `uuid` di Calibre comincia con `corto`. Torna
    `(biblioteca, libro, motivo)`.

    Si guarda prima nella biblioteca suggerita dall'indirizzo, poi in tutte le
    altre che la persona puo' vedere: l'uuid e' unico di per se', quindi un
    libro **spostato** in un'altra biblioteca si ritrova comunque e il link
    continua a funzionare. Se due libri cominciassero uguali in due
    biblioteche diverse, vince quella suggerita; se sono nella stessa, si dice
    «ambiguo» invece di aprirne uno a caso.
    """
    if not corto:
        return None, None, "indirizzo_senza_libro"
    corto = corto.lower()
    ordine = ([suggerita] if suggerita else []) + [
        b for b in permessi.biblioteche_visibili(db, utente)
        if not suggerita or b.id != suggerita.id
    ]
    for biblioteca in ordine:
        trovati = [
            libro for libro in _libri_della_biblioteca(biblioteca.folder_name)
            if (libro.get("uuid") or "").lower().startswith(corto)
        ]
        if len(trovati) == 1:
            return biblioteca, trovati[0], None
        if len(trovati) > 1:
            return biblioteca, None, "libro_ambiguo"
    return None, None, "libro_sparito"


def _con_la_base(richiesta: Request, percorso: str) -> dict:
    """La risposta di un link: il percorso, la base di questa installazione, e
    i due attaccati. La base la ricava il server — vedi
    `link_condivisibile.indirizzo_base` per i tre modi, in ordine."""
    base = L.indirizzo_base(
        host=richiesta.headers.get("host"),
        schema=richiesta.url.scheme,
        porta_del_frontend=config.PUBLIC_FRONTEND_PORT,
        host_inoltrato=richiesta.headers.get("x-forwarded-host"),
        schema_inoltrato=richiesta.headers.get("x-forwarded-proto"),
        scritto_a_mano=config.PUBLIC_BASE_URL,
    )
    return {"percorso": percorso, "base": base,
            "indirizzo": f"{base}{percorso}" if base else None}


def _apri_il_libro(cartella: str, calibre_book_id: int) -> str:
    """L'indirizzo interno di una scheda libro. Porta la biblioteca **nella
    query**: `/libri/1033` da solo non dice in quale biblioteca sta quel 1033,
    e aperto a freddo puo' mostrare il libro sbagliato."""
    return f"/libri/{calibre_book_id}?library={cartella}"


@router.get("/risolvi", responses={200: {"model": LinkRisolto}})
def risolvi_un_link(
    percorso: str = Query(..., description="The shareable address, e.g. /k/library/les-miserables-39e1f730"),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    A cosa corrisponde un indirizzo condivisibile, e cosa aprire.

    Risponde sempre 200 con `trovato` e `motivo`, anche quando la cosa non
    c'e' piu': un link in un appunto merita una spiegazione e un ripiego, non
    un 404. L'unico 400 e' per un indirizzo che non e' di questa forma, che
    non e' un link rotto ma una richiesta sbagliata.
    """
    letto = L.leggi(percorso)
    if not letto:
        raise HTTPException(status_code=400, detail="This is not a Kolibre shareable address.")

    risposta = {
        "tipo": letto["tipo"], "trovato": False, "apri": None, "ripiego": None,
        "motivo": None, "biblioteca": None, "calibre_book_id": None, "titolo": None,
        "nota_id": None, "id_durevole": None, "autore": None,
    }

    if letto["tipo"] == "autore":
        # Un autore e' un nome, non una riga: non c'e' niente da risolvere
        # nel database, e lo slug basta al frontend per cercarlo. Chi non
        # esiste lo scopre la' con un elenco vuoto, che e' piu' utile di un
        # «non trovato» qui.
        risposta.update({"trovato": True, "autore": letto["autore"],
                         "apri": f"/autori/{letto['autore']}"})
        return risposta

    biblioteca, motivo_bib = _biblioteca_dallo_slug(db, current_user, letto["biblioteca"])
    if biblioteca:
        risposta["biblioteca"] = biblioteca.folder_name

    if letto["tipo"] == "biblioteca":
        if not biblioteca:
            risposta["motivo"] = motivo_bib
            return risposta
        risposta.update({"trovato": True, "apri": f"/?library={biblioteca.folder_name}"})
        return risposta

    # Da qui e' un libro o una nota: il libro si cerca per uuid, e la
    # biblioteca dell'indirizzo e' solo il primo posto dove guardare.
    bib_del_libro, libro, motivo_libro = _libro_dal_corto(
        db, current_user, letto["libro"]["corto"], biblioteca)
    if libro:
        risposta["biblioteca"] = bib_del_libro.folder_name
        risposta["calibre_book_id"] = libro["id"]
        risposta["titolo"] = libro.get("title")

    if letto["tipo"] == "libro":
        if not libro:
            risposta["motivo"] = motivo_libro
            if biblioteca:
                # Il libro non c'e' piu' ma la biblioteca si': meglio aprire
                # quella che niente.
                risposta.update({"ripiego": "biblioteca",
                                 "apri": f"/?library={biblioteca.folder_name}"})
            return risposta
        risposta.update({"trovato": True,
                         "apri": _apri_il_libro(bib_del_libro.folder_name, libro["id"])})
        return risposta

    # Una nota. Si cerca per nome durevole, seguendo i rimandi (due note
    # fuse in una, o un'orfana diventata nota vera).
    risposta["id_durevole"] = letto["nota"]
    nota = identita_durevole.risolvi(db, letto["nota"])
    if nota is not None and nota.user_id != current_user.id:
        # Le note di un'altra persona non esistono, per chi guarda.
        nota = None
    if nota is None or nota.deleted_at is not None:
        risposta["motivo"] = "nota_sparita"
        if libro:
            risposta.update({"ripiego": "libro",
                             "apri": _apri_il_libro(bib_del_libro.folder_name, libro["id"])})
        elif biblioteca:
            risposta.update({"ripiego": "biblioteca",
                             "apri": f"/?library={biblioteca.folder_name}"})
        return risposta

    risposta.update({
        "trovato": True, "nota_id": nota.id, "biblioteca": nota.library,
        "calibre_book_id": nota.calibre_book_id,
        # `?nota=<id>` e' quello che il lettore sa gia' aprire: risolve la
        # nota, apre il libro giusto e ci va sopra.
        "apri": f"/reader.html?nota={nota.id}",
    })
    if not risposta["titolo"]:
        for libro_vero in _libri_della_biblioteca(nota.library):
            if libro_vero["id"] == nota.calibre_book_id:
                risposta["titolo"] = libro_vero.get("title")
                break
    return risposta


def _percorso_di_un_libro(cartella: str, libri: list, calibre_book_id: int) -> Optional[str]:
    questo = next((b for b in libri if b["id"] == calibre_book_id), None)
    if not questo or not questo.get("uuid"):
        return None
    quanti = L.caratteri_che_bastano(questo["uuid"], [b.get("uuid") for b in libri])
    return L.percorso_del_libro(cartella, questo.get("title"), questo["uuid"], quanti)


@router.get("/di-un-libro", responses={200: {"model": LinkGenerato}})
def link_di_un_libro(
    richiesta: Request,
    id: int,
    library: Optional[str] = None,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """L'indirizzo condivisibile di un libro. 404 se non si riesce a comporlo
    (il libro non c'e', o la sua riga di Calibre non ha un `uuid` — succede
    solo su biblioteche fabbricate a mano)."""
    cartella = library
    if not cartella:
        visibili = permessi.biblioteche_visibili(db, current_user)
        if not visibili:
            raise HTTPException(status_code=404, detail="You do not have access to any library.")
        cartella = visibili[0].folder_name
    biblioteca, _motivo = _biblioteca_dallo_slug(db, current_user, cartella)
    if not biblioteca:
        raise HTTPException(status_code=404, detail="Library not found.")
    percorso = _percorso_di_un_libro(biblioteca.folder_name,
                                    _libri_della_biblioteca(biblioteca.folder_name), id)
    if not percorso:
        raise HTTPException(status_code=404, detail="Book not found.")
    return _con_la_base(richiesta, percorso)


@router.get("/di-un-autore", responses={200: {"model": LinkGenerato}})
def link_di_un_autore(
    richiesta: Request,
    nome: str,
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    L'indirizzo condivisibile di un autore.

    **Non guarda nel database**, e non e' una scorciatoia: un autore in
    Kolibre *e'* un nome (le schede autore si aprono per nome, non per id), e
    l'indirizzo e' quel nome ridotto a slug. Passa da qui comunque, invece di
    essere composto nel browser, perche' la regola «come un nome diventa uno
    slug» deve stare in un posto solo — altrimenti il browser, il plugin
    Obsidian e un client futuro la scriverebbero in tre modi che divergono
    alla prima lettera accentata.
    """
    if not (nome or "").strip():
        raise HTTPException(status_code=400, detail="A name is required.")
    return _con_la_base(richiesta, L.percorso_dell_autore(nome))


@router.get("/di-una-biblioteca", responses={200: {"model": LinkGenerato}})
def link_di_una_biblioteca(
    richiesta: Request,
    library: str,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """L'indirizzo condivisibile di una biblioteca, se questa persona la
    vede. 404 altrimenti: una biblioteca che non si puo' guardare non ha un
    link, e dire «non trovata» e' il modo giusto di dirlo — non si rivela
    nemmeno che esiste."""
    biblioteca, _motivo = _biblioteca_dallo_slug(db, current_user, library)
    if not biblioteca:
        raise HTTPException(status_code=404, detail="Library not found.")
    return _con_la_base(richiesta, L.percorso_della_biblioteca(biblioteca.folder_name))


@router.get("/di-una-nota", responses={200: {"model": LinkGenerato}})
def link_di_una_nota(
    richiesta: Request,
    id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    L'indirizzo condivisibile di una nota.

    **Un'orfana non ce l'ha**, e la risposta lo dice con un 409 invece di un
    404: la nota esiste, ma il suo indirizzo contiene il libro, e un file non
    ancora accoppiato non ha un libro. Si accoppia e il link c'e'.
    """
    nota = db.query(models.Highlight).filter(
        models.Highlight.id == id, models.Highlight.user_id == current_user.id
    ).first()
    if not nota:
        raise HTTPException(status_code=404, detail="Annotation not found.")
    if not nota.id_durevole:
        raise HTTPException(status_code=409, detail="This highlight does not have a durable name yet.")
    libri = _libri_della_biblioteca(nota.library)
    questo = next((b for b in libri if b["id"] == nota.calibre_book_id), None)
    if not questo or not questo.get("uuid"):
        raise HTTPException(status_code=409, detail="This highlight's book has no shareable address.")
    quanti = L.caratteri_che_bastano(questo["uuid"], [b.get("uuid") for b in libri])
    return _con_la_base(richiesta, L.percorso_della_nota(
        nota.library, questo.get("title"), questo["uuid"], nota.id_durevole, quanti))
