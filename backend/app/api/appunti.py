"""
Appunti: il ponte verso un client che tiene le note fuori da Kolibre.

**Da zero.** Il plugin Obsidian scrive un file per libro nel vault di Paolo, e
lui ci scrive attorno. Perche' quel file si possa aggiornare senza mai toccare
quello che ha scritto lui, servono due cose: che il plugin **racconti** cosa
ha (l'inventario), e che il server **dica** com'e' la situazione e cosa fare
(lo stato, e le istruzioni).

**Il principio, che decide la forma di tutto il resto: il server non puo'
scrivere nel vault.** Il plugin sincronizza solo quando Paolo premé il
comando (sua decisione). Quindi niente di quello che si sceglie nella pagina
e' un'azione immediata: e' un'istruzione che il plugin esegue al prossimo
giro, e la pagina deve dirlo — altrimenti chi blocca un libro si aspetta che
succeda subito.

Il calcolo degli stati non e' qui: e' in `services/appunti_nel_vault.py`, che
non parla col database e ha le sue quarantasei prove. Qui c'e' solo il giro
dei dati.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .. import auth, database, models
from ..istanti import quando
from ..schemas_risposte import (Esito, InventarioDegliAppunti, StatoDegliAppunti,
                                ClienteSeCeNe, DettaglioDiUnLibro)
from ..services import appunti_nel_vault as V
from .annotations import righe_esportate, _indirizzo_base

router = APIRouter(prefix="/api/kolibre/appunti", tags=["appunti"])


def _cliente(db: Session, utente: models.User, crea: bool = False):
    """
    Il client **che sta parlando**, riconosciuto dal token con cui parla.

    Nessuna registrazione: il token d'applicazione ha gia' un nome, quello che
    Paolo gli ha dato creandolo. Chi accede con nome e password non ha un
    token e ricade su una riga sola per account.

    **Serve solo a chi racconta**, cioe' all'inventario. Per leggere — la
    pagina, la barra laterale — si usa `_clienti_dell_account`: vedi il
    perche' scritto la', ed e' un difetto che e' costato una serata.
    """
    token_id = getattr(utente, "_token_applicazione_id", None)
    riga = db.query(models.ClienteDiAppunti).filter(
        models.ClienteDiAppunti.user_id == utente.id,
        models.ClienteDiAppunti.token_id == token_id,
    ).first()
    if riga or not crea:
        return riga
    riga = models.ClienteDiAppunti(user_id=utente.id, token_id=token_id)
    db.add(riga)
    db.flush()
    return riga


def _clienti_dell_account(db: Session, utente: models.User) -> list:
    """
    Tutti i client di questo account, **da quello che ha raccontato piu' di
    recente**.

    **Il difetto da cui nasce** (06/11/2026). Il client e' riconosciuto dal
    token con cui parla, e va benissimo per l'inventario: a raccontare e' il
    plugin, col suo token d'applicazione. Ma **la pagina la guarda Paolo dal
    browser**, con un token di sessione, e cercare il client per il token
    della richiesta non lo trovava mai: la voce «Appunti» non compariva
    nemmeno, e lo stato diceva «file mai creato» per tutti i libri mentre nel
    database c'erano 72 file e 1083 blocchi raccontati la sera prima.

    La fotografia appartiene all'**account**: il token dice chi racconta, non
    chi guarda. Se un giorno ci fossero due vault si sceglie quale guardare
    (`?cliente=`), e senza scelta si guarda quello piu' fresco — che e' la
    risposta giusta quando ce n'e' uno solo, cioe' sempre, per ora.
    """
    return db.query(models.ClienteDiAppunti).filter(
        models.ClienteDiAppunti.user_id == utente.id
    ).order_by(models.ClienteDiAppunti.visto_il.desc()).all()


def _da_guardare(db: Session, utente: models.User, scelto: Optional[int] = None):
    """Il client che la pagina sta guardando, e l'elenco di tutti."""
    tutti = _clienti_dell_account(db, utente)
    if scelto is not None:
        cliente = next((c for c in tutti if c.id == scelto), None)
        if cliente is None:
            raise HTTPException(status_code=404, detail="No client with that number.")
    else:
        cliente = tutti[0] if tutti else None
    return cliente, tutti


def _descrivi(db: Session, cliente) -> Optional[dict]:
    if cliente is None:
        return None
    return {
        "id": cliente.id,
        "nome": _nome_del_cliente(db, cliente),
        "visto_il": quando(cliente.visto_il),
        "file_visti": cliente.file_visti or 0,
        "note_viste": cliente.note_viste or 0,
    }


def _nome_del_cliente(db: Session, cliente) -> Optional[str]:
    if cliente is None or not cliente.token_id:
        return None
    token = db.query(models.TokenApplicazione).filter(
        models.TokenApplicazione.id == cliente.token_id
    ).first()
    return token.nome if token else None


def _bloccati(db: Session, utente: models.User) -> list:
    return [
        (d.library, d.titolo)
        for d in db.query(models.DecisioneDiAppunti).filter(
            models.DecisioneDiAppunti.user_id == utente.id,
            models.DecisioneDiAppunti.bloccato.is_(True),
        ).all()
    ]


def _da_rifare(db: Session, utente: models.User) -> list:
    return [
        (d.library, d.titolo)
        for d in db.query(models.DecisioneDiAppunti).filter(
            models.DecisioneDiAppunti.user_id == utente.id,
            models.DecisioneDiAppunti.rifai_dal.isnot(None),
            models.DecisioneDiAppunti.bloccato.is_(False),
        ).all()
    ]


def _scelte(db: Session, utente: models.User) -> dict:
    return {
        d.id_durevole: d.scelta
        for d in db.query(models.DecisioneDiNota).filter(
            models.DecisioneDiNota.user_id == utente.id
        ).all()
    }


def _registra_le_consegne(db: Session, cliente, nomi: list) -> int:
    """
    Segna come consegnate le note appena raccontate.

    **La consegna e' provata dalla fotografia**: se una nota compare in un
    racconto, quel vault l'ha ricevuta. Quindi questo registro e' l'unione di
    tutte le fotografie nel tempo, e non serve che il plugin dichiari niente
    in piu'.

    Si scrive solo quello che manca: una nota raccontata mille volte ha una
    riga sola, e la data e' quella della **prima** volta che si e' vista.
    """
    if not nomi:
        return 0
    gia = {
        r.id_durevole for r in db.query(models.NotaConsegnata).filter(
            models.NotaConsegnata.cliente_id == cliente.id,
            models.NotaConsegnata.id_durevole.in_(nomi),
        ).all()
    }
    adesso = datetime.utcnow()
    nuove = [n for n in nomi if n not in gia]
    for nome in nuove:
        db.add(models.NotaConsegnata(cliente_id=cliente.id, id_durevole=nome,
                                     consegnata_il=adesso))
    return len(nuove)


def _consegnate(db: Session, cliente) -> set:
    if cliente is None:
        return set()
    return {
        r.id_durevole for r in db.query(models.NotaConsegnata).filter(
            models.NotaConsegnata.cliente_id == cliente.id
        ).all()
    }


def _non_rimettere(db: Session, cliente) -> list:
    """
    Le note che il plugin **non deve riscrivere**: consegnate, e non piu' nel
    vault.

    E' la sola cosa che serve al plugin per fare quello che Paolo ha chiesto,
    e copre tutti due i casi con una regola sola:

    - una nota togliata da dentro un file che resta non si rimette;
    - un file cancellato non si ricrea, perche' quando il plugin esclude
      queste note **non gli resta niente da scriverci** — e un file senza
      niente da scrivere non si crea.

    Se invece fra le note di quel libro ce n'e' una mai consegnata, il file
    nasce con dentro **solo quella**: scelta di Paolo del 06/11/2026.
    """
    if cliente is None:
        return []
    nel_vault = {
        b.id_durevole for b in db.query(models.BloccoDiAppunti).filter(
            models.BloccoDiAppunti.cliente_id == cliente.id
        ).all()
    }
    return sorted(_consegnate(db, cliente) - nel_vault)


def _istruzioni(db: Session, utente: models.User, cliente=None) -> dict:
    """
    Quello che il plugin deve fare al prossimo giro.

    Arriva nella **stessa risposta dell'inventario** perche' il plugin ha
    appena finito di raccontare ed e' il momento in cui sta per lavorare: un
    secondo giro di rete per chiederle sarebbe sprecato.

    Un libro bloccato non compare fra quelli da rifare: le due istruzioni si
    contraddicono, e «non toccarlo» vince sempre — e' la piu' prudente.
    """
    return {
        "non_mandare": [
            {"library": l, "titolo": t} for l, t in _bloccati(db, utente)
        ],
        "rifai": [
            {"library": d.library, "calibre_book_id": d.calibre_book_id, "titolo": d.titolo}
            for d in db.query(models.DecisioneDiAppunti).filter(
                models.DecisioneDiAppunti.user_id == utente.id,
                models.DecisioneDiAppunti.rifai_dal.isnot(None),
                models.DecisioneDiAppunti.bloccato.is_(False),
            ).all()
        ],
        "conflitti": [
            {"id_durevole": d.id_durevole, "scelta": d.scelta}
            for d in db.query(models.DecisioneDiNota).filter(
                models.DecisioneDiNota.user_id == utente.id
            ).all()
        ],
        "non_rimettere": _non_rimettere(db, cliente),
    }


def _spegni_le_istruzioni_eseguite(db: Session, utente: models.User, payload: dict) -> dict:
    """
    Il plugin dice cosa ha eseguito, e quelle istruzioni si spengono.

    **Si spengono qui e non quando vengono mandate**: il server non sa se il
    plugin e' arrivato in fondo. Spegnendole all'invio, un plugin interrotto a
    meta' lascerebbe il file come l'ha trovato e l'istruzione consumata — cioe'
    una decisione di Paolo persa in silenzio. Spegnendole al racconto
    successivo, un plugin che crolla fa solo riprovare al giro dopo.
    """
    rifatti = payload.get("rifatti") or []
    spenti = 0
    for r in rifatti:
        library = ((r or {}).get("library") or "").strip()
        libro = (r or {}).get("calibre_book_id")
        if not library:
            continue
        riga = db.query(models.DecisioneDiAppunti).filter(
            models.DecisioneDiAppunti.user_id == utente.id,
            models.DecisioneDiAppunti.library == library,
            models.DecisioneDiAppunti.calibre_book_id == libro,
        ).first()
        if riga is not None and riga.rifai_dal is not None:
            riga.rifai_dal = None
            spenti += 1

    risolti = [n for n in (payload.get("conflitti_risolti") or []) if n]
    cancellati = 0
    if risolti:
        cancellati = db.query(models.DecisioneDiNota).filter(
            models.DecisioneDiNota.user_id == utente.id,
            models.DecisioneDiNota.id_durevole.in_(risolti),
        ).delete(synchronize_session=False)

    return {"rifacimenti_spenti": spenti, "conflitti_chiusi": cancellati or 0}


@router.post("/inventario", responses={200: {"model": InventarioDegliAppunti}})
def ricevi_inventario(
    payload: dict,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    Il plugin racconta cosa ha nel vault. **Sostituisce** la fotografia
    precedente invece di aggiungersi: un racconto nuovo non si somma a uno
    vecchio, lo rimpiazza — altrimenti un file cancellato da Paolo resterebbe
    nei conti per sempre, che e' esattamente il difetto da cui viene tutto
    questo disegno.

    Forma attesa:

        {"file": [{"percorso": "Libri/I miserabili.md",
                   "blocchi": [{"id_durevole": "n7k2p4m9qt",
                                "impronta_base": "6b2138ef69352299",
                                "impronta_attuale": "6b2138ef69352299",
                                "testo_attuale": "..."}]}]}

    `testo_attuale` va mandato **solo** quando le due impronte non
    corrispondono: serve alla pagina per mostrare i due testi affiancati, e
    mandarlo per milleduecento blocchi a ogni giro sarebbe sprecato.
    """
    file = payload.get("file")
    if not isinstance(file, list):
        raise HTTPException(status_code=400, detail="The list of files is required: {\"file\": [...]}")

    cliente = _cliente(db, current_user, crea=True)
    eseguite = _spegni_le_istruzioni_eseguite(db, current_user, payload)
    db.query(models.BloccoDiAppunti).filter(
        models.BloccoDiAppunti.cliente_id == cliente.id
    ).delete(synchronize_session=False)

    adesso = datetime.utcnow()
    visti, scartati = 0, 0
    nomi_visti = set()
    for f in file:
        percorso = (f or {}).get("percorso")
        if not percorso:
            scartati += 1
            continue
        for b in (f.get("blocchi") or []):
            nome = (b or {}).get("id_durevole")
            # Un blocco senza nome durevole non e' raccontabile: non si sa di
            # quale nota parli. Si conta fra gli scartati invece di essere
            # ignorato in silenzio.
            if not nome or nome in nomi_visti:
                scartati += 1
                continue
            nomi_visti.add(nome)
            db.add(models.BloccoDiAppunti(
                cliente_id=cliente.id, percorso=percorso, id_durevole=nome,
                impronta_base=b.get("impronta_base"),
                impronta_attuale=b.get("impronta_attuale"),
                testo_attuale=b.get("testo_attuale"),
                visto_il=adesso,
            ))
            visti += 1

    cliente.visto_il = adesso
    cliente.file_visti = len([f for f in file if (f or {}).get("percorso")])
    cliente.note_viste = visti
    # **Il registro delle consegne si riempie qui**, da quello che il plugin
    # ha appena raccontato: vedi models.NotaConsegnata per il perche'.
    consegnate_adesso = _registra_le_consegne(db, cliente, sorted(nomi_visti))
    db.commit()

    libri = V.stato_dei_libri(righe_esportate(db, current_user), _blocchi(db, cliente),
                              _bloccati(db, current_user), _da_rifare(db, current_user),
                              _scelte(db, current_user), _consegnate(db, cliente))
    return {
        "ricevuti": visti, "scartati": scartati,
        "file": cliente.file_visti,
        "consegne_nuove": consegnate_adesso,
        "eseguite": eseguite,
        "riassunto": V.riassunto(libri),
        "istruzioni": _istruzioni(db, current_user, cliente),
    }


def _blocchi(db: Session, cliente) -> list:
    if cliente is None:
        return []
    return [
        {"id_durevole": b.id_durevole, "percorso": b.percorso,
         "impronta_base": b.impronta_base, "impronta_attuale": b.impronta_attuale,
         "testo_attuale": b.testo_attuale}
        for b in db.query(models.BloccoDiAppunti).filter(
            models.BloccoDiAppunti.cliente_id == cliente.id
        ).all()
    ]


@router.get("/stato", responses={200: {"model": StatoDegliAppunti}})
def stato_degli_appunti(
    richiesta: Request,
    cliente: Optional[int] = None,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    Quello che la pagina mostra: in testa i libri che hanno bisogno di Paolo,
    e i conti dei gruppi tranquilli.

    **Risponde anche quando non c'e' nessun client**: `cliente` nullo e tutti
    i libri «non creati». E' la verita' — nessuno ha mai raccontato niente — e
    serve all'interfaccia per decidere di non mostrare affatto la voce nella
    barra, come fa Dispositivi per chi non ha lettori.

    **La fotografia e' dell'account, non del token con cui si chiede**: qui
    legge il browser di Paolo, non il plugin. Con `?cliente=<numero>` si
    guarda un client preciso, senza si guarda quello che ha raccontato piu'
    di recente.
    """
    guardato, tutti = _da_guardare(db, current_user, cliente)
    note = righe_esportate(db, current_user, base=_indirizzo_base(richiesta))
    libri = V.stato_dei_libri(note, _blocchi(db, guardato), _bloccati(db, current_user),
                              _da_rifare(db, current_user), _scelte(db, current_user),
                              _consegnate(db, guardato))
    return {
        "cliente": _descrivi(db, guardato),
        # Tutti i client dell'account: con due vault la pagina deve poter
        # dire quale sta guardando, invece di nasconderne uno in silenzio.
        "clienti": [_descrivi(db, c) for c in tutti],
        "riassunto": V.riassunto(libri),
        "libri": libri,
    }


@router.get("/libro", responses={200: {"model": DettaglioDiUnLibro}})
def un_libro_negli_appunti(
    richiesta: Request,
    library: str,
    calibre_book_id: Optional[int] = None,
    titolo: Optional[str] = None,
    cliente: Optional[int] = None,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    Le evidenziazioni di un libro, una per riga, con lo stato di ognuna nel
    vault.

    **Perche' e' una rotta a parte da `/stato`.** Quella risponde una riga per
    libro e serve alla tabella: settantanove righe di conteggi. Questa
    risponde una riga per nota e serve alla pagina di un libro: il brano, il
    capitolo, il link, e per i conflitti i due testi affiancati. Mettere
    tutto in una sola rotta vorrebbe dire mandare il testo di milleottanta
    note per disegnare una tabella — e averne troppo poche per disegnare la
    pagina di un libro.

    Il libro si indica con la biblioteca e il suo id. Un file **non ancora
    accoppiato** non ha un id: quello si indica col titolo, che e' la sola
    cosa che lo distingue (e' la stessa chiave con cui il plugin raggruppa i
    file, vedi `chiave_del_libro`).
    """
    guardato, _ = _da_guardare(db, current_user, cliente)
    tutte = righe_esportate(db, current_user, base=_indirizzo_base(richiesta))
    note = [
        n for n in tutte
        if (n.get("library") or "") == library
        and (calibre_book_id is None or n.get("calibre_book_id") == calibre_book_id)
        and (titolo is None or (n.get("book_title") or "") == titolo)
    ]
    if not note:
        raise HTTPException(status_code=404, detail="This book has no highlights in Kolibre.")

    blocchi = _blocchi(db, guardato)
    consegnate = _consegnate(db, guardato)
    scelte = _scelte(db, current_user)
    # Lo stato del libro si calcola con la stessa funzione della tabella, su
    # queste note sole: due strade diverse per lo stesso numero sono due
    # strade che un giorno divergono.
    righe = V.stato_dei_libri(note, blocchi, _bloccati(db, current_user),
                              _da_rifare(db, current_user), scelte, consegnate)
    return {
        "libro": righe[0],
        "note": V.note_di_un_libro(note, blocchi, consegnate, scelte),
    }


@router.get("/cliente", responses={200: {"model": ClienteSeCeNe}})
def c_e_un_cliente(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    Solo «c'e' un client, e come si chiama».

    Esiste separata da `/stato` perche' **la chiede la barra laterale**, a
    ogni pagina che si apre: la voce «Appunti» non si mostra affatto se
    nessun client ha mai raccontato niente (decisione di Paolo, come fa
    Dispositivi per chi non ha lettori). Far calcolare lo stato di
    settantanove libri per sapere se mostrare una voce di menu sarebbe
    lavoro buttato — `/stato` esporta le note, le raggruppa e ne calcola le
    impronte, qui si legge una riga.
    """
    guardato, tutti = _da_guardare(db, current_user)
    return {"cliente": _descrivi(db, guardato), "clienti": [_descrivi(db, c) for c in tutti]}


@router.put("/blocco", responses={200: {"model": Esito}})
def cambia_il_blocco(
    payload: dict,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    «Questo libro non mandarlo» (o il contrario).

    **Non cancella niente dal vault**: il file che c'e' resta dov'e'. Bloccare
    vuol dire «smetti di aggiornarlo», e il plugin lo sapra' al prossimo giro
    — il server non puo' scrivere nel vault.
    """
    library = (payload.get("library") or "").strip()
    libro = payload.get("calibre_book_id")
    if not library or libro is None:
        raise HTTPException(status_code=400,
                            detail="The library and the book id are both required. "
                                   "A file that is not paired yet cannot be blocked.")
    riga = db.query(models.DecisioneDiAppunti).filter(
        models.DecisioneDiAppunti.user_id == current_user.id,
        models.DecisioneDiAppunti.library == library,
        models.DecisioneDiAppunti.calibre_book_id == libro,
    ).first()
    if riga is None:
        riga = models.DecisioneDiAppunti(
            user_id=current_user.id, library=library, calibre_book_id=libro)
        db.add(riga)
    riga.bloccato = bool(payload.get("bloccato", True))
    riga.titolo = payload.get("titolo") or riga.titolo
    riga.deciso_il = datetime.utcnow()
    db.commit()
    return {"status": "ok"}


@router.put("/rifai", responses={200: {"model": Esito}})
def rimanda_da_zero(
    payload: dict,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    «Rimanda questo libro da zero».

    **Cosa fa davvero**: al prossimo giro il plugin riscrive il file di quel
    libro partendo dalle note del server, invece di aggiungerci solo le
    novita'. Serve quando il file e' andato per conto suo — intestazioni
    sbagliate, blocchi doppi, un rimaneggiamento di cui si e' perso il filo.

    **Cosa si perde**: quello che Paolo ha scritto **dentro** i blocchi di
    quel file. E' il senso del comando e non un effetto collaterale, quindi
    la pagina lo dice prima di chiederlo. Il resto del vault non si tocca.

    **Non e' un'azione, e' un'istruzione.** Il server non puo' scrivere nel
    vault: fino alla prossima sincronizzazione il file e' esattamente quello
    di adesso, e la pagina mostra il libro «in attesa».

    `annulla: true` ritira l'istruzione, finche' il plugin non e' passato.
    """
    library = (payload.get("library") or "").strip()
    libro = payload.get("calibre_book_id")
    if not library or libro is None:
        raise HTTPException(status_code=400,
                            detail="The library and the book id are both required. "
                                   "A file that is not paired yet cannot be rebuilt.")
    riga = db.query(models.DecisioneDiAppunti).filter(
        models.DecisioneDiAppunti.user_id == current_user.id,
        models.DecisioneDiAppunti.library == library,
        models.DecisioneDiAppunti.calibre_book_id == libro,
    ).first()
    if riga is None:
        riga = models.DecisioneDiAppunti(
            user_id=current_user.id, library=library, calibre_book_id=libro)
        db.add(riga)
    annulla = bool(payload.get("annulla", False))
    riga.rifai_dal = None if annulla else datetime.utcnow()
    riga.titolo = payload.get("titolo") or riga.titolo
    riga.deciso_il = datetime.utcnow()
    db.commit()
    return {"status": "ok"}


@router.put("/conflitto", responses={200: {"model": Esito}})
def risolvi_un_conflitto(
    payload: dict,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    Chi vince, fra il brano nel vault e quello sul server.

    **Da zero.** Un conflitto vero e' quando lo stesso brano e' cambiato in
    tutte due le parti rispetto all'ultima volta che Kolibre l'ha scritto.
    Qui non si scrive un testo nuovo: si dice **quale delle due versioni
    vince**, e il plugin al prossimo giro fa la cosa che ne segue —
    `kolibre` riscrive la parte sopra il marcatore col testo del server,
    `mio` lascia il testo dov'e' e sposta solo la base, cosi' il conflitto
    non si ripresenta ogni volta.

    Quello che Paolo ha scritto **sotto** il marcatore non si tocca in nessuno
    dei due casi: e' il senso del confine.

    `annulla: true` ritira la decisione, finche' il plugin non e' passato.
    """
    nome = (payload.get("id_durevole") or "").strip()
    scelta = (payload.get("scelta") or "").strip()
    if not nome:
        raise HTTPException(status_code=400, detail="The highlight's durable name is required.")

    if bool(payload.get("annulla", False)):
        db.query(models.DecisioneDiNota).filter(
            models.DecisioneDiNota.user_id == current_user.id,
            models.DecisioneDiNota.id_durevole == nome,
        ).delete(synchronize_session=False)
        db.commit()
        return {"status": "ok"}

    # Insieme chiuso: una scelta che non vuol dire niente non entra nel
    # database, dove poi nessuno saprebbe cosa farne.
    if scelta not in models.SCELTE_DI_CONFLITTO:
        raise HTTPException(
            status_code=400,
            detail="The choice can only be «%s»." % "» or «".join(models.SCELTE_DI_CONFLITTO))

    riga = db.query(models.DecisioneDiNota).filter(
        models.DecisioneDiNota.user_id == current_user.id,
        models.DecisioneDiNota.id_durevole == nome,
    ).first()
    if riga is None:
        riga = models.DecisioneDiNota(user_id=current_user.id, id_durevole=nome, scelta=scelta)
        db.add(riga)
    else:
        riga.scelta = scelta
    riga.deciso_il = datetime.utcnow()
    db.commit()
    return {"status": "ok"}
