"""
L'accoppiamento per codice: come un programma entra senza chiedere la password.

**Da zero, il problema.** Il client nativo di Kolibre e' un programma che gira
sul computer di una persona. Per parlare col server deve avere una credenziale.
Se gli si da' **la password dell'account**, quella password finisce scritta da
qualche parte sul computer — e' esattamente il difetto che il plugin Obsidian
aveva (la conservava dentro il vault, cioe' dentro la cartella che la gente
sincronizza fra computer). Se invece si va a prendere un token dal sito e si
incolla nel programma, si chiede a una persona di maneggiare a mano una
credenziale che non scade: si copia male, resta negli appunti, finisce in un
messaggio.

**La terza strada.** Il programma chiede al server un **codice** di sei
caratteri e lo mostra. La persona apre il sito — dove e' **gia' entrata**, con
la sua sessione — vede la richiesta, riconosce il codice e conferma. Il
programma riceve il token da se'. La password non passa dal programma, e
nessuno copia niente a mano.

────────────────────────────────────────────────────────────────────────────
IL TOKEN CHE NASCE QUI E' UN TOKEN D'APPLICAZIONE, NON DI DISPOSITIVO
────────────────────────────────────────────────────────────────────────────

Il brief del client dice «token di dispositivo `kolibre_tok_…`». **Qui nasce
invece un `kolibre_app_…`** (`models.TokenApplicazione`), e la ragione e'
misurata nel codice, non di gusto:

  1. **Un token di dispositivo non apre la biblioteca.** `main.py` protegge
     i router veri — books, authors, libraries, stats — con
     `auth.get_current_user_flexible`, che accetta un JWT o un token
     d'applicazione e **rifiuta** un `kolibre_tok_…`. Un token di dispositivo
     apre soltanto il protocollo di sincronizzazione di KOReader, il download
     di un file e le immagini. Il client non potrebbe nemmeno elencare i
     libri: `GET /api/kolibre/books` risponderebbe 401.
  2. **Allargare i token di dispositivo a tutta l'API sarebbe un
     peggioramento vero.** Quei token stanno **in chiaro** nella colonna
     `devices.device_token` e **dentro un file del plugin** su ogni Kindle:
     oggi valgono per la sincronizzazione, e un lettore perso costa quella.
     Se valessero per tutta l'API, un lettore perso costerebbe l'intero
     account.
  3. **Il mattone giusto esiste e dice di se' questa cosa**: la docstring di
     `models.TokenApplicazione`, scritta il 05/11, elenca chi lo usera' —
     «il plugin Obsidian, uno script, **un domani un client nativo**». Si
     tiene come impronta e non in chiaro, non scade, si revoca da un elenco,
     e vale su ogni indirizzo che l'account puo' usare.

Per il client la differenza e' di tre caratteri nel prefisso: il token resta
una stringa opaca da mettere nell'header `Authorization`. Quello che cambia
davvero e' dove si spegne — nell'elenco dei token dell'account, non fra i
dispositivi. **La scelta e' ribaltabile**, e sta scritta fra le cose aperte del
progetto.

────────────────────────────────────────────────────────────────────────────
LA ROTTA SENZA AUTENTICAZIONE, TENUTA STRETTA
────────────────────────────────────────────────────────────────────────────

Due di questi indirizzi rispondono **a chiunque**, perche' devono: un
programma che non ha ancora nessuna credenziale non puo' autenticarsi. E'
una superficie nuova, e queste sono le cose che la tengono piccola:

  * **il codice vale cinque minuti**, poi la riga non apre piu' niente;
  * **il codice non ritira**: si ritira col biglietto, trentadue byte che
    nessuno vede (il perche' e' in `models.RichiestaDiAccoppiamento`);
  * **prima della conferma non si impara niente** — la risposta e' lo stato e
    nient'altro: ne' chi sia il padrone del server, ne' se esista;
  * **un biglietto sconosciuto risponde 404**, sempre, senza distinguere fra
    «non esiste» e «non e' piu' buono»;
  * **quante richieste possono aspettare insieme ha un tetto**, e quante ne
    puo' avviare uno stesso indirizzo in un'ora pure: senza, chiunque
    riempirebbe di righe il pannello in cui si conferma — che e' il modo di
    far confermare a una persona distratta la richiesta sbagliata;
  * **confermare vuole una sessione vera**, non un token: un token non puo'
    fabbricare un token, altrimenti chi ne rubasse uno se ne farebbe dieci e
    revocare quello rubato non servirebbe a niente. E' la stessa regola di
    `POST /api/users/me/tokens`.

**Quello che questo disegno NON ferma, detto chiaro.** Chi raggiunge il server
puo' avviare una richiesta e sperare che la persona la confermi credendola
sua. La difesa e' il codice: chi conferma vede sei caratteri e li confronta
con quelli sul proprio schermo. Per questo il pannello mostra il codice in
grande e non solo un pulsante «conferma» — e per questo mostra anche
**l'indirizzo da cui la richiesta arriva**, che e' la sola cosa che il server
sa e che la richiesta non puo' raccontarsi da sola.
"""

import hashlib
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .. import auth, database, models
from ..istanti import quando
from ..logging_utils import log_message
from ..schemas_risposte import (
    AccoppiamentoAvviato, AccoppiamentoConfermato, Esito,
    RichiesteDiAccoppiamento, StatoDellAccoppiamento,
)

#: Gli endpoint che rispondono a chi non ha ancora nessuna credenziale. Non
#: passano dalla dipendenza di autenticazione che `main.py` mette su `router`:
#: e' una scelta, non una dimenticanza, ed e' il motivo di tutti i limiti qui
#: sotto.
public_router = APIRouter(prefix="/api/pairing", tags=["pairing"])

#: Gli endpoint del sito, che `main.py` include con l'autenticazione.
router = APIRouter(prefix="/api/pairing", tags=["pairing"])

#: Quanto vive un codice. Cinque minuti sono il tempo di aprire il sito e
#: guardare: piu' corto diventa una corsa, piu' lungo e' una riga che apre
#: qualcosa e aspetta mezz'ora.
DURATA = timedelta(minutes=5)

#: L'alfabeto del codice: **niente 0/O, 1/I/L, 8/B**. Chi legge sei caratteri
#: su uno schermo e li cerca su un altro non deve dover indovinare quale dei
#: due era, e un codice che si sbaglia a leggere diventa un codice che si
#: conferma a caso.
ALFABETO = "23456789ACDEFGHJKMNPQRTUVWXYZ"
LUNGHEZZA_CODICE = 6

#: Quante richieste possono aspettare **insieme**, in tutto. Il tetto non
#: protegge il server (una riga non costa niente): protegge il pannello in cui
#: si conferma, perche' una persona che ne vede trenta non le confronta piu'
#: una per una.
MASSIMO_IN_ATTESA = 5

#: Quante ne puo' avviare **uno stesso indirizzo** in un'ora. Un programma che
#: si riaccoppia ne fa una o due; dieci sono gia' un errore di chi programma, e
#: cento sono un disturbo.
MASSIMO_PER_ORA_PER_IP = 10

#: Ogni quanto conviene richiedere lo stato. Lo dice il server al client, cosi'
#: non lo sceglie ciascuno per conto suo.
SECONDI_FRA_DUE_DOMANDE = 3

#: Dopo quanto una riga morta si butta. Non si cancella alla scadenza: finche'
#: restano, si puo' contare quante ne ha avviate un indirizzo nell'ultima ora,
#: che e' il solo modo di avere un limite senza inventarsi un'altra tabella.
TIENI_LE_RIGHE_MORTE_PER = timedelta(hours=24)

#: Il nome del client, da `nome_client`: e' testo di uno sconosciuto che il
#: sito mostra, quindi si taglia qui e non a schermo.
MASSIMO_NOME = 60


def impronta_del_biglietto(biglietto: str) -> str:
    """L'impronta con cui un biglietto si cerca. Vedi il modello."""
    return hashlib.sha256(biglietto.encode("utf-8")).hexdigest()


def _ripulisci(testo, massimo: int) -> str:
    """
    Una riga di testo scritta da uno sconosciuto, resa innocua **come testo**.

    Via i caratteri di controllo (un «a capo» dentro un nome rompe in due una
    riga del pannello e si porta dietro la meta' di sotto), e poi si taglia.
    Non e' una difesa dalle iniezioni — di quelle rispondono React, che mostra
    testo, e SQLAlchemy, che non concatena query — e' il rispetto di una riga
    che deve stare su una riga.
    """
    grezzo = str(testo or "")
    pulito = "".join(c for c in grezzo if c.isprintable()).strip()
    return pulito[:massimo]


def _nuovo_codice(db: Session, adesso: datetime) -> str:
    """
    Un codice che nessuna richiesta **viva** sta usando.

    Si guarda solo fra le vive perche' e' solo fra quelle che si cerca: due
    righe morte con lo stesso codice non confondono nessuno.
    """
    for _tentativo in range(20):
        codice = "".join(secrets.choice(ALFABETO) for _ in range(LUNGHEZZA_CODICE))
        gia_in_uso = db.query(models.RichiestaDiAccoppiamento).filter(
            models.RichiestaDiAccoppiamento.codice == codice,
            models.RichiestaDiAccoppiamento.scade_il > adesso,
        ).first()
        if not gia_in_uso:
            return codice
    # Ventinove caratteri alla sesta sono seicento milioni di codici, e le vive
    # sono al massimo cinque: arrivare qui vuol dire che qualcosa non va nel
    # generatore di casualita', e in quel caso e' meglio non consegnare un
    # codice che indovinare.
    raise HTTPException(status_code=503, detail="Could not generate a pairing code. Try again.")


def _butta_le_righe_vecchie(db: Session, adesso: datetime) -> None:
    """Le righe morte da piu' di un giorno. Poche, e si fa qui perche' e'
    l'unico momento in cui si sa che qualcuno sta usando questa parte."""
    db.query(models.RichiestaDiAccoppiamento).filter(
        models.RichiestaDiAccoppiamento.creato_il
        < adesso - TIENI_LE_RIGHE_MORTE_PER,
    ).delete(synchronize_session=False)


def _stato(riga: models.RichiestaDiAccoppiamento, adesso: datetime) -> str:
    """
    Lo stato di una richiesta, nell'ordine in cui le cose contano.

    **Il rifiuto e la conferma vengono prima della scadenza**, perche' sono
    fatti avvenuti: una richiesta rifiutata resta rifiutata anche dopo cinque
    minuti, e dire «scaduta» a chi ha ricevuto un no lo manderebbe a
    riprovare, cioe' a far ricomparire nel pannello la richiesta che la
    persona aveva appena allontanato.
    """
    if riga.rifiutato_il is not None:
        return "refused"
    if riga.ritirato_il is not None:
        return "collected"
    if riga.confermato_il is not None:
        return "confirmed"
    if riga.scade_il <= adesso:
        return "expired"
    return "pending"


# ── Quello che fa il programma: chiedere un codice, e poi aspettare ──────


@public_router.post("/requests", responses={200: {"model": AccoppiamentoAvviato}})
def avvia_accoppiamento(
    payload: dict,
    request: Request,
    db: Session = Depends(database.get_db),
):
    """
    «Voglio collegarmi»: torna il codice da mostrare e il biglietto con cui
    poi si ritira il token.

    Risponde **senza autenticazione**, perche' chi chiede non ha ancora
    nessuna credenziale — e' il punto di tutto. I limiti che la tengono
    stretta sono in testa al file.
    """
    adesso = datetime.utcnow()
    _butta_le_righe_vecchie(db, adesso)

    # L'indirizzo **come il server lo vede**. `X-Forwarded-For` non si guarda
    # di proposito: lo scrive chi chiama, quindi chi volesse farsi confermare
    # una richiesta potrebbe dichiarare l'indirizzo del computer di casa e
    # mostrarlo a chi conferma. Dietro un proxy qui comparira' l'indirizzo del
    # proxy: un'informazione inutile e' meglio di una che inganna.
    ip = request.client.host if request.client else None

    in_attesa = db.query(models.RichiestaDiAccoppiamento).filter(
        models.RichiestaDiAccoppiamento.scade_il > adesso,
        models.RichiestaDiAccoppiamento.confermato_il.is_(None),
        models.RichiestaDiAccoppiamento.rifiutato_il.is_(None),
    ).count()
    if in_attesa >= MASSIMO_IN_ATTESA:
        raise HTTPException(
            status_code=429,
            detail="Too many pairing requests are already waiting. Confirm or "
                   "refuse one from the site, or wait a few minutes.",
        )

    if ip:
        nell_ultima_ora = db.query(models.RichiestaDiAccoppiamento).filter(
            models.RichiestaDiAccoppiamento.ip_richiedente == ip,
            models.RichiestaDiAccoppiamento.creato_il > adesso - timedelta(hours=1),
        ).count()
        if nell_ultima_ora >= MASSIMO_PER_ORA_PER_IP:
            raise HTTPException(
                status_code=429,
                detail="Too many pairing requests from this address. Try again later.",
            )

    nome = _ripulisci(payload.get("name"), MASSIMO_NOME)
    if not nome:
        raise HTTPException(
            status_code=400,
            detail="Say which program is asking: the name is what the person "
                   "confirming sees.",
        )
    piattaforma = _ripulisci(payload.get("platform"), MASSIMO_NOME) or None

    biglietto = secrets.token_urlsafe(32)
    riga = models.RichiestaDiAccoppiamento(
        codice=_nuovo_codice(db, adesso),
        ticket_hash=impronta_del_biglietto(biglietto),
        nome_client=nome,
        piattaforma=piattaforma,
        ip_richiedente=ip,
        creato_il=adesso,
        scade_il=adesso + DURATA,
    )
    db.add(riga)
    db.commit()
    db.refresh(riga)
    # Il codice **non** si scrive nel registro: il registro si legge dal sito,
    # e un codice che compare in due posti e' un codice che si conferma
    # guardando il posto sbagliato. Il nome si, perche' e' quello che poi si
    # ritrova nell'elenco dei token.
    log_message("info", "auth",
                f"A program asked to pair: '{nome}' from {ip or 'an unknown address'}.")
    return {
        "code": riga.codice,
        "ticket": biglietto,
        "expires_at": quando(riga.scade_il),
        "poll_every_seconds": SECONDI_FRA_DUE_DOMANDE,
    }


@public_router.get("/requests/{ticket}", responses={200: {"model": StatoDellAccoppiamento}})
def stato_dell_accoppiamento(
    ticket: str,
    db: Session = Depends(database.get_db),
):
    """
    «Com'e' andata?», chiesto dal programma col suo biglietto.

    **Il token arriva una volta sola.** Alla prima risposta che lo porta la
    riga si segna come ritirata e il token in chiaro si cancella: se quella
    risposta si perde per strada, non c'e' modo di riaverla e si rifa'
    l'accoppiamento. E' la scelta piu' stretta fra le due possibili, e il
    prezzo e' dichiarato — un token rimasto senza padrone si spegne
    dall'elenco dei token, dove compare col nome del programma.
    """
    adesso = datetime.utcnow()
    riga = db.query(models.RichiestaDiAccoppiamento).filter(
        models.RichiestaDiAccoppiamento.ticket_hash == impronta_del_biglietto(ticket),
    ).first()
    # Un biglietto che non si trova e' 404 e nient'altro: non si distingue fra
    # «non e' mai esistito» e «non e' piu' buono», perche' la differenza
    # direbbe a chi prova biglietti che ne ha trovato uno vero.
    if not riga:
        raise HTTPException(status_code=404, detail="Unknown pairing request")

    stato = _stato(riga, adesso)
    risposta = {
        "status": stato,
        "expires_at": quando(riga.scade_il),
        "token": None,
        "user": None,
    }
    if stato != "confirmed":
        return risposta

    token = riga.token_in_chiaro
    utente = db.query(models.User).filter(models.User.id == riga.user_id).first()
    riga.ritirato_il = adesso
    riga.token_in_chiaro = None
    db.commit()
    log_message("info", "auth",
                f"The program '{riga.nome_client}' collected its token.")
    risposta["token"] = token
    risposta["user"] = utente.username if utente else None
    return risposta


# ── Quello che fa il sito: guardare chi aspetta, e dire si' o no ─────────


@router.get("/requests", responses={200: {"model": RichiesteDiAccoppiamento}})
def richieste_in_attesa(
    db: Session = Depends(database.get_db),
    chi: models.User = Depends(auth.get_current_user),
):
    """
    Le richieste che aspettano, per il pannello in cui si confermano.

    **Le vede chiunque sia entrato, non solo chi le ha chieste**, e non e' una
    svista: prima della conferma una richiesta non e' di nessuno — e' un
    programma che ha bussato, e il server non puo' sapere a nome di chi. Chi
    conferma la fa diventare sua. Fra due account dello stesso server questo
    vuol dire vedere il nome e l'indirizzo del programma di un altro: e'
    scritto, ed e' il prezzo di non aver niente da chiedere prima di bussare.
    """
    adesso = datetime.utcnow()
    righe = db.query(models.RichiestaDiAccoppiamento).filter(
        models.RichiestaDiAccoppiamento.scade_il > adesso,
        models.RichiestaDiAccoppiamento.confermato_il.is_(None),
        models.RichiestaDiAccoppiamento.rifiutato_il.is_(None),
    ).order_by(models.RichiestaDiAccoppiamento.id).all()
    return {"items": [
        {"id": r.id, "code": r.codice, "client_name": r.nome_client,
         "platform": r.piattaforma, "ip": r.ip_richiedente,
         "created_at": quando(r.creato_il), "expires_at": quando(r.scade_il)}
        for r in righe
    ]}


def _richiesta_viva(db: Session, request_id: int, adesso: datetime):
    riga = db.query(models.RichiestaDiAccoppiamento).filter(
        models.RichiestaDiAccoppiamento.id == request_id,
    ).first()
    if not riga:
        raise HTTPException(status_code=404, detail="Unknown pairing request")
    stato = _stato(riga, adesso)
    if stato != "pending":
        # 409 e non 404: la richiesta c'e', ed e' importante dire **perche'**
        # non si puo' piu' — chi guardava il pannello di mezzo minuto fa deve
        # capire che il codice e' scaduto, non che ha sbagliato indirizzo.
        raise HTTPException(
            status_code=409,
            detail=f"This pairing request is no longer waiting: it is {stato}.",
        )
    return riga


@router.post("/requests/{request_id}/confirm",
             responses={200: {"model": AccoppiamentoConfermato}})
def conferma_accoppiamento(
    request_id: int,
    db: Session = Depends(database.get_db),
    chi: models.User = Depends(auth.get_current_user),
):
    """
    «Si', quel programma sono io»: nasce il token, e lo ritirera' il programma.

    **Vuole una sessione vera, non un token.** E' la stessa regola di
    `POST /api/users/me/tokens` e per la stessa ragione: se un token potesse
    benedire un programma nuovo, chi ne rubasse uno se ne farebbe altri a
    volonta', e spegnere quello rubato non chiuderebbe niente.

    Il token nasce **a nome di chi conferma**: da quel momento il programma
    puo' fare quello che quell'account puo' fare, e niente di piu'.
    """
    if getattr(chi, "_da_token_applicazione", False):
        raise HTTPException(
            status_code=403,
            detail="Pairing a program is confirmed by signing in with your "
                   "password, not with another token.",
        )
    adesso = datetime.utcnow()
    riga = _richiesta_viva(db, request_id, adesso)

    nome_token = riga.nome_client
    token = auth.crea_token_applicazione(db, chi, nome_token)
    nato = db.query(models.TokenApplicazione).filter(
        models.TokenApplicazione.token_hash == auth.impronta_del_token(token),
    ).first()
    riga.confermato_il = adesso
    riga.user_id = chi.id
    riga.token_applicazione_id = nato.id if nato else None
    riga.token_in_chiaro = token
    db.commit()
    log_message("info", "auth",
                f"'{chi.username}' paired the program '{riga.nome_client}'.")
    return {"status": "ok", "token_id": nato.id if nato else 0,
            "token_name": nome_token}


@router.post("/requests/{request_id}/refuse", responses={200: {"model": Esito}})
def rifiuta_accoppiamento(
    request_id: int,
    db: Session = Depends(database.get_db),
    chi: models.User = Depends(auth.get_current_user),
):
    """
    «No»: la richiesta si spegne subito e nessun token nasce.

    Il rifiuto **resta** anche dopo i cinque minuti (vedi `_stato`): il
    programma riceve un no e non si rimette in coda da solo.
    """
    adesso = datetime.utcnow()
    riga = _richiesta_viva(db, request_id, adesso)
    riga.rifiutato_il = adesso
    db.commit()
    log_message("warning", "auth",
                f"'{chi.username}' refused the program '{riga.nome_client}' "
                f"from {riga.ip_richiedente or 'an unknown address'}.")
    return {"status": "ok"}
