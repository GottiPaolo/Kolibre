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

**La terza strada: un invito.** Dal server nasce un **codice usa e getta** a
vita breve. La persona lo porta nel programma, il programma lo scambia con un
token suo, e il codice e' bruciato. La password non passa dal programma, e
nessuno copia a mano niente che duri.

────────────────────────────────────────────────────────────────────────────
L'INVITO PARTE DAL SERVER. IL 16/11 PARTIVA DAL PROGRAMMA, ED ERA SBAGLIATO
────────────────────────────────────────────────────────────────────────────

La prima versione andava nell'altro verso: il programma bussava a una rotta
aperta, nasceva una «richiesta in attesa», e nel sito compariva una riga da
confermare. Paolo l'ha fermata il giorno dopo: *«non mi piace l'idea che
qualsiasi client puo' mandarmi una richiesta… tutto deve partire dal
server»*. Aveva ragione, e la differenza e' concreta:

  * **in quel verso, chiunque raggiungesse il server poteva far comparire una
    riga nel pannello di Paolo.** Da sola non apriva niente — ci voleva la
    conferma — ma il modo di far sbagliare una persona e' precisamente quello:
    metterle davanti qualcosa da confermare nel momento in cui si aspetta di
    dover confermare qualcosa. Il tetto alle richieste in attesa che quella
    versione aveva era una toppa su un verso sbagliato;
  * **in questo verso non c'e' niente da confermare.** Chi non e' gia' entrato
    non puo' far nascere un invito, quindi non puo' far comparire niente da
    nessuna parte. La sola rotta aperta che resta — il riscatto — **non scrive
    niente** se il codice non e' uno di quelli nati qui dentro.

E poi la seconda richiesta di Paolo, dello stesso giorno: *«il collegamento di
nuovi device dovrebbe poter essere effettuato anche senza frontend»*. Un
invito che nasce dal server nasce anche da **una riga di comando sul server**
— `python3 -m backend.app.invita`, che e' lo stesso codice di qui dentro
(`crea_invito`) con un'altra faccia. Un server con l'interfaccia web rotta
resta collegabile.

────────────────────────────────────────────────────────────────────────────
IL TOKEN CHE NASCE QUI E' UN TOKEN D'APPLICAZIONE, NON DI DISPOSITIVO
────────────────────────────────────────────────────────────────────────────

Nasce un `kolibre_app_…` (`models.TokenApplicazione`) e non un
`kolibre_tok_…`, e la ragione e' misurata nel codice, non di gusto:

  1. **Un token di dispositivo non apre la biblioteca.** `main.py` protegge
     i router veri — books, authors, libraries, stats — con
     `auth.get_current_user_flexible`, che accetta un JWT o un token
     d'applicazione e **rifiuta** un `kolibre_tok_…`. Un token di dispositivo
     apre soltanto il protocollo di sincronizzazione di KOReader, il download
     di un file e le immagini. Il client non potrebbe nemmeno elencare i
     libri: `GET /api/kolibre/books` risponderebbe 401.
  2. **Allargare i token di dispositivo a tutta l'API sarebbe un
     peggioramento vero.** Quei token stanno **in chiaro dentro un file del
     plugin** su ogni Kindle (dal 20/11/2026 il server, per parte sua, ne
     conserva solo l'impronta in `devices.device_token_hash`): oggi valgono
     per la sincronizzazione, e un lettore perso costa quella. Se valessero
     per tutta l'API, un lettore perso costerebbe l'intero account.
  3. **Il mattone giusto esiste e dice di se' questa cosa**: la docstring di
     `models.TokenApplicazione`, scritta il 05/11, elenca chi lo usera' —
     «il plugin Obsidian, uno script, **un domani un client nativo**». Si
     tiene come impronta e non in chiaro, non scade, si revoca da un elenco,
     e vale su ogni indirizzo che l'account puo' usare.

Per il client la differenza e' di tre caratteri nel prefisso: il token resta
una stringa opaca da mettere nell'header `Authorization`. Quello che cambia
davvero e' dove si spegne — nell'elenco dei token dell'account, non fra i
dispositivi. **Approvato da Paolo il 16/11/2026.**

────────────────────────────────────────────────────────────────────────────
LA SOLA ROTTA SENZA AUTENTICAZIONE, E COSA LA TIENE STRETTA
────────────────────────────────────────────────────────────────────────────

`POST /api/pairing/redeem` risponde **a chiunque**, perche' deve: un programma
che non ha ancora nessuna credenziale non puo' autenticarsi. E' l'unica.
Queste sono le cose che la tengono piccola:

  * **il codice e' lungo dieci caratteri** su un alfabeto di ventinove, cioe'
    circa 4·10^14 possibilita' (quasi 49 bit). Non e' una strada che si
    percorre a macchina, e questa e' la difesa vera: non dipende da quanto
    veloce sia il server ne' da quanti tentativi riusciamo a contare;
  * **vale quindici minuti**, poi non apre piu' niente;
  * **vale una volta sola**: al riscatto la riga si segna, e un secondo
    riscatto trova la porta chiusa;
  * **in database non c'e' il codice ma la sua impronta** (vedi
    `models.InvitoDiAccoppiamento`): un database che finisse in mano a
    qualcuno non regala nessun accesso funzionante;
  * **un codice che non si trova e' sempre 404**, con la stessa frase per
    «non e' mai esistito», «e' scaduto», «e' stato revocato» e «e' gia' stato
    usato»: la differenza direbbe a chi prova codici che ne ha trovato uno
    vero;
  * **un freno ai tentativi sbagliati per indirizzo**, che non e' la difesa
    (quella sono i dieci caratteri) ma tiene pulito il registro e fa rumore
    quando qualcuno prova;
  * **creare un invito vuole una sessione vera**, non un token: un token non
    puo' fabbricare un token, altrimenti chi ne rubasse uno se ne farebbe
    dieci e revocare quello rubato non servirebbe a niente. E' la stessa
    regola di `POST /api/users/me/tokens`.

**E una cosa che questo verso NON ha bisogno di dichiarare**, al contrario di
quello del 16/11: non esiste nessuna finestra in cui un token stia in chiaro
da qualche parte aspettando che qualcuno lo venga a prendere. Il programma
chiede e riceve nella stessa richiesta, che e' la sua.
"""

import hashlib
import secrets
import threading
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .. import auth, database, models
from ..istanti import quando
from ..logging_utils import log_message
from ..schemas_risposte import (
    AccoppiamentoRiscattato, Esito, InvitiDiAccoppiamento, InvitoCreato,
)

#: La sola rotta che risponde a chi non ha ancora nessuna credenziale. Non
#: passa dalla dipendenza di autenticazione che `main.py` mette su `router`:
#: e' una scelta, non una dimenticanza, ed e' il motivo dei limiti qui sotto.
public_router = APIRouter(prefix="/api/pairing", tags=["pairing"])

#: Gli endpoint del sito, che `main.py` include con l'autenticazione.
router = APIRouter(prefix="/api/pairing", tags=["pairing"])

#: Quanto vive un invito. Quindici minuti sono il tempo di portare dieci
#: caratteri da uno schermo a un altro — anche camminando da una stanza
#: all'altra — e non il tempo di dimenticarselo acceso.
DURATA = timedelta(minutes=15)

#: Il massimo che si puo' chiedere dalla riga di comando (`--minuti`). Serve
#: al caso vero di chi prepara un computer che non ha davanti: un'ora e'
#: lunga, ma e' ancora una finestra che si chiude da se' entro la giornata.
DURATA_MASSIMA = timedelta(hours=1)

#: L'alfabeto del codice: **niente 0/O, 1/I/L, 8/B**. Chi legge dieci
#: caratteri su uno schermo e li riscrive su un altro non deve dover
#: indovinare quale dei due fosse, e un codice che si sbaglia a leggere e' un
#: codice che si riprova tre volte.
ALFABETO = "23456789ACDEFGHJKMNPQRTUVWXYZ"

#: **Dieci, non sei.** Il perche' sta per esteso nel modello: qui il codice e'
#: l'unica credenziale del giro, quindi deve reggere da solo. Dieci caratteri
#: su ventinove sono quasi 49 bit; sei erano 594 milioni, un numero che con un
#: server lento e' tanto e con uno veloce no — e una difesa che dipende da
#: quanto e' veloce il server non e' una difesa.
LUNGHEZZA_CODICE = 10

#: Si mostra a gruppi di cinque, con un trattino in mezzo. Il trattino **non
#: fa parte del codice**: il riscatto lo butta via insieme a spazi e a
#: qualunque altra cosa non sia dell'alfabeto, cosi' chi lo riscrive a mano
#: puo' metterlo o non metterlo.
GRUPPO = 5
SEPARATORE = "-"

#: Quanti inviti vivi puo' avere **una persona** nello stesso momento. Non
#: protegge il server (una riga non costa niente): tiene il conto a uno che
#: clicca due volte e poi si chiede quale dei codici sia buono.
MASSIMO_VIVI_PER_UTENTE = 10

#: Il freno ai tentativi sbagliati, per indirizzo. **Non e' la difesa** — la
#: difesa sono i dieci caratteri — ed e' per questo che sta in memoria e non
#: in una tabella: serve a non far scrivere al registro diecimila righe
#: identiche e a far comparire un avviso quando qualcuno prova. Riparte a ogni
#: riavvio, e va bene cosi'.
MASSIMO_TENTATIVI_FALLITI = 20
FINESTRA_DEI_TENTATIVI = timedelta(minutes=10)
#: Quanti indirizzi si ricordano al massimo. Senza questo tetto, chi provasse
#: da indirizzi sempre diversi farebbe crescere il dizionario per sempre: un
#: freno che si mangia la memoria del server e' peggio di nessun freno.
MASSIMO_INDIRIZZI_RICORDATI = 1024

#: Dopo quanto una riga morta si butta. Non subito: un invito riscattato dice
#: **quando e da dove** un programma e' entrato, ed e' l'unico posto in cui
#: quella risposta esiste.
TIENI_LE_RIGHE_MORTE_PER = timedelta(days=7)

#: Il nome di un invito, e quello che il programma dichiara di se' al
#: riscatto: testo che il sito mostra, quindi si taglia qui e non a schermo.
MASSIMO_NOME = 60

_tentativi_falliti: dict[str, list[datetime]] = {}
_serratura = threading.Lock()


def impronta_del_codice(codice: str) -> str:
    """L'impronta con cui un invito si cerca. Vedi il modello: in database il
    codice non c'e', c'e' questa."""
    return hashlib.sha256(codice.encode("utf-8")).hexdigest()


def normalizza(codice) -> str:
    """
    Il codice come l'ha scritto una persona, ridotto a quello che e'.

    Maiuscolo, e **via tutto quello che non e' dell'alfabeto**: i trattini con
    cui lo mostriamo, gli spazi, un ritorno a capo rimasto attaccato
    all'incollatura. Quello che resta e' il codice o non lo e'.
    """
    grezzo = str(codice or "").upper()
    return "".join(c for c in grezzo if c in ALFABETO)


def con_i_gruppi(codice: str) -> str:
    """`ABCDEFGHJK` → `ABCDE-FGHJK`, per mostrarlo e per riscriverlo."""
    pezzi = [codice[i:i + GRUPPO] for i in range(0, len(codice), GRUPPO)]
    return SEPARATORE.join(pezzi)


def _ripulisci(testo, massimo: int) -> str:
    """
    Una riga di testo scritta da altri, resa innocua **come testo**.

    Via i caratteri di controllo (un «a capo» dentro un nome rompe in due una
    riga dell'elenco e si porta dietro la meta' di sotto), e poi si taglia.
    Non e' una difesa dalle iniezioni — di quelle rispondono React, che mostra
    testo, e SQLAlchemy, che non concatena query — e' il rispetto di una riga
    che deve stare su una riga.
    """
    grezzo = str(testo or "")
    pulito = "".join(c for c in grezzo if c.isprintable()).strip()
    return pulito[:massimo]


def _butta_le_righe_vecchie(db: Session, adesso: datetime) -> None:
    """Le righe morte da piu' di una settimana. Si fa qui perche' e' l'unico
    momento in cui si sa che qualcuno sta usando questa parte."""
    db.query(models.InvitoDiAccoppiamento).filter(
        models.InvitoDiAccoppiamento.creato_il
        < adesso - TIENI_LE_RIGHE_MORTE_PER,
    ).delete(synchronize_session=False)


def stato(riga: models.InvitoDiAccoppiamento, adesso: datetime) -> str:
    """
    Lo stato di un invito, nell'ordine in cui le cose contano.

    **Il riscatto e la revoca vengono prima della scadenza**, perche' sono
    fatti avvenuti: un invito usato resta usato anche dopo un quarto d'ora, e
    chiamarlo «scaduto» racconterebbe all'elenco una storia diversa da quella
    che e' andata.
    """
    if riga.riscattato_il is not None:
        return "redeemed"
    if riga.revocato_il is not None:
        return "revoked"
    if riga.scade_il <= adesso:
        return "expired"
    return "pending"


def _nuovo_codice(db: Session) -> str:
    """
    Un codice che nessun invito sta usando.

    Il controllo c'e' per scrupolo, non perche' serva: con quasi 49 bit un
    doppione non lo si vede in una vita. Ma `codice_hash` e' unico, e un
    `INSERT` che fallisce per un doppione sarebbe un errore 500 al posto di un
    codice — meglio guardare prima.
    """
    for _tentativo in range(20):
        codice = "".join(secrets.choice(ALFABETO) for _ in range(LUNGHEZZA_CODICE))
        gia_in_uso = db.query(models.InvitoDiAccoppiamento).filter(
            models.InvitoDiAccoppiamento.codice_hash == impronta_del_codice(codice),
        ).first()
        if not gia_in_uso:
            return codice
    # Arrivare qui vuol dire che qualcosa non va nel generatore di casualita',
    # e in quel caso e' meglio non consegnare un codice che indovinarne uno.
    raise HTTPException(
        status_code=503,
        detail="Could not generate a pairing code. Try again.",
    )


def crea_invito(
    db: Session,
    utente: models.User,
    nome: str | None = None,
    durata: timedelta = DURATA,
    origine: str = "site",
) -> tuple[models.InvitoDiAccoppiamento, str]:
    """
    Fabbrica un invito e torna **(la riga, il codice in chiaro)**.

    Il codice in chiaro esiste solo qui, nel valore di ritorno: sulla riga ne
    va l'impronta. Chi chiama lo mostra una volta e poi nessuno — nemmeno il
    server — e' in grado di ridirlo.

    Sta in questo file e non dentro la rotta perche' **ha due facce**: la rotta
    del sito e il comando da terminale (`backend/app/invita.py`). Due strade
    per la stessa cosa vanno tenute dallo stesso codice, altrimenti una delle
    due resta indietro di una regola.
    """
    adesso = datetime.utcnow()
    _butta_le_righe_vecchie(db, adesso)

    vivi = db.query(models.InvitoDiAccoppiamento).filter(
        models.InvitoDiAccoppiamento.user_id == utente.id,
        models.InvitoDiAccoppiamento.scade_il > adesso,
        models.InvitoDiAccoppiamento.riscattato_il.is_(None),
        models.InvitoDiAccoppiamento.revocato_il.is_(None),
    ).count()
    if vivi >= MASSIMO_VIVI_PER_UTENTE:
        raise HTTPException(
            status_code=429,
            detail="Too many pairing codes are already waiting to be used. "
                   "Use one, revoke one, or wait for them to expire.",
        )

    if durata > DURATA_MASSIMA:
        durata = DURATA_MASSIMA
    if durata <= timedelta(0):
        durata = DURATA

    codice = _nuovo_codice(db)
    riga = models.InvitoDiAccoppiamento(
        codice_hash=impronta_del_codice(codice),
        nome=_ripulisci(nome, MASSIMO_NOME) or None,
        origine=origine if origine in ("site", "terminal") else "site",
        creato_il=adesso,
        scade_il=adesso + durata,
        user_id=utente.id,
    )
    db.add(riga)
    db.commit()
    db.refresh(riga)
    # **Il codice non si scrive nel registro.** Il registro si legge dal sito
    # e dal terminale, cioe' dai due posti in cui un codice vale: scriverlo
    # li' vorrebbe dire conservarlo in chiaro dopo aver fatto il lavoro di non
    # conservarlo. Il nome si', perche' e' quello che poi si ritrova.
    log_message("info", "auth",
                f"'{utente.username}' created a pairing code"
                f"{f' for {riga.nome!r}' if riga.nome else ''} "
                f"({'terminal' if riga.origine == 'terminal' else 'web'}).")
    return riga, codice


def _troppi_tentativi(ip: str | None, adesso: datetime) -> bool:
    """Il freno: vero se da quell'indirizzo si sta provando troppo."""
    if not ip:
        return False
    with _serratura:
        recenti = [
            q for q in _tentativi_falliti.get(ip, [])
            if q > adesso - FINESTRA_DEI_TENTATIVI
        ]
        if recenti:
            _tentativi_falliti[ip] = recenti
        else:
            _tentativi_falliti.pop(ip, None)
        return len(recenti) >= MASSIMO_TENTATIVI_FALLITI


def _segna_un_tentativo_fallito(ip: str | None, adesso: datetime) -> None:
    if not ip:
        return
    with _serratura:
        # Prima il tetto: un dizionario che cresce per sempre e' un difetto
        # peggiore di quello che sta prevenendo. Si butta tutto quello che e'
        # fuori finestra, e se anche cosi' si e' al tetto si lascia perdere —
        # meglio un freno che smette di frenare che un server senza memoria.
        if len(_tentativi_falliti) >= MASSIMO_INDIRIZZI_RICORDATI:
            for altro, quando_li in list(_tentativi_falliti.items()):
                if not [q for q in quando_li if q > adesso - FINESTRA_DEI_TENTATIVI]:
                    _tentativi_falliti.pop(altro, None)
            if len(_tentativi_falliti) >= MASSIMO_INDIRIZZI_RICORDATI:
                return
        _tentativi_falliti.setdefault(ip, []).append(adesso)


def _dimentica_i_tentativi(ip: str | None) -> None:
    """Dopo un riscatto riuscito, da quell'indirizzo il conto riparte."""
    if not ip:
        return
    with _serratura:
        _tentativi_falliti.pop(ip, None)


# ── Quello che fa il programma: una sola richiesta, la sua ───────────────


@public_router.post("/redeem", responses={200: {"model": AccoppiamentoRiscattato}})
def riscatta_invito(
    payload: dict,
    request: Request,
    db: Session = Depends(database.get_db),
):
    """
    «Ecco il codice»: torna il token, una volta sola.

    Risponde **senza autenticazione**, perche' chi scambia il codice non ha
    ancora nessuna credenziale — e' il punto di tutto. Tutto quello che la
    tiene stretta e' in testa al file.

    **Un codice che non apre e' sempre 404, con la stessa frase.** Che non sia
    mai esistito, che sia scaduto, che Paolo l'abbia revocato o che sia gia'
    stato usato: distinguere direbbe a chi prova codici che ne ha trovato uno
    vero, e la differenza non serve a nessuno che abbia il codice giusto.
    """
    adesso = datetime.utcnow()
    # L'indirizzo **come il server lo vede**. `X-Forwarded-For` non si guarda
    # di proposito: lo scrive chi chiama, quindi chiunque potrebbe dichiarare
    # l'indirizzo che gli pare e il freno non frenerebbe niente. Dietro un
    # proxy qui comparira' l'indirizzo del proxy: un'informazione inutile e'
    # meglio di una che inganna.
    ip = request.client.host if request.client else None

    if _troppi_tentativi(ip, adesso):
        raise HTTPException(
            status_code=429,
            detail="Too many wrong pairing codes from this address. "
                   "Wait a few minutes.",
        )

    codice = normalizza(payload.get("code"))
    if len(codice) != LUNGHEZZA_CODICE:
        # Un codice della forma sbagliata e' un errore di chi lo riscrive, non
        # un tentativo: si dice com'e' fatto (la forma e' pubblica, sta nella
        # documentazione) e **non si conta nel freno**, altrimenti due errori
        # di battitura chiuderebbero la porta a chi ha il codice buono.
        raise HTTPException(
            status_code=400,
            detail=f"A pairing code is {LUNGHEZZA_CODICE} characters long "
                   f"(dashes and spaces are ignored).",
        )

    riga = db.query(models.InvitoDiAccoppiamento).filter(
        models.InvitoDiAccoppiamento.codice_hash == impronta_del_codice(codice),
    ).first()
    if riga is None or stato(riga, adesso) != "pending":
        _segna_un_tentativo_fallito(ip, adesso)
        log_message("warning", "auth",
                    f"A wrong pairing code was offered from "
                    f"{ip or 'an unknown address'}.")
        raise HTTPException(status_code=404, detail="Unknown or expired pairing code")

    utente = db.query(models.User).filter(models.User.id == riga.user_id).first()
    if utente is None:
        # L'account non c'e' piu'. La riga sarebbe caduta con lui
        # (`ondelete="CASCADE"`), quindi qui non si arriva: se ci si arriva,
        # un token a nome di nessuno non si fabbrica.
        raise HTTPException(status_code=404, detail="Unknown or expired pairing code")

    nome_client = _ripulisci(payload.get("name"), MASSIMO_NOME) or None
    piattaforma = _ripulisci(payload.get("platform"), MASSIMO_NOME) or None

    # **Il nome del token: quello che ha scritto Paolo, se l'ha scritto.** Il
    # nome e' quello che si legge fra sei mesi nell'elenco dei token, cioe'
    # quando si deve decidere se spegnerlo: fra «il portatile» (scelto da chi
    # sa) e «Kolibre client (MacBook-di-Paolo.local)» (dichiarato dal
    # programma), il primo vale di piu'. Se nessuno dei due c'e', un nome che
    # almeno dice da dove viene.
    nome_token = riga.nome or nome_client or "Programma accoppiato"
    token = auth.crea_token_applicazione(db, utente, nome_token)
    nato = db.query(models.TokenApplicazione).filter(
        models.TokenApplicazione.token_hash == auth.impronta_del_token(token),
    ).first()

    riga.riscattato_il = adesso
    riga.nome_client = nome_client
    riga.piattaforma = piattaforma
    riga.ip_riscatto = ip
    riga.token_applicazione_id = nato.id if nato else None
    db.commit()
    _dimentica_i_tentativi(ip)
    log_message("info", "auth",
                f"A pairing code of '{utente.username}' was redeemed by "
                f"{nome_client or 'a program'} from {ip or 'an unknown address'}.")
    return {"token": token, "user": utente.username, "token_name": nome_token}


# ── Quello che fa il sito: creare un invito, e guardare gli inviti ───────


@router.post("/invites", responses={200: {"model": InvitoCreato}})
def crea_un_invito(
    payload: dict | None = None,
    db: Session = Depends(database.get_db),
    chi: models.User = Depends(auth.get_current_user),
):
    """
    «Collega un client»: nasce il codice da portare nel programma.

    **Vuole una sessione vera, non un token.** E' la stessa regola di
    `POST /api/users/me/tokens` e per la stessa ragione: se un token potesse
    fabbricarne un altro, chi ne rubasse uno se ne farebbe dieci, e spegnere
    quello rubato non chiuderebbe niente.

    **Il codice torna una volta sola.** Da qui in avanti il server ne ha solo
    l'impronta, e non e' in grado di ridirlo nemmeno volendo: vedi
    `models.InvitoDiAccoppiamento`. Chi lo perde ne fa un altro.
    """
    if getattr(chi, "_da_token_applicazione", False):
        raise HTTPException(
            status_code=403,
            detail="A pairing code is created by signing in with your "
                   "password, not with another token.",
        )
    nome = (payload or {}).get("name")
    riga, codice = crea_invito(db, chi, nome=nome, origine="site")
    return {
        "id": riga.id,
        "code": con_i_gruppi(codice),
        "name": riga.nome,
        "expires_at": quando(riga.scade_il),
        "expires_in_seconds": int(DURATA.total_seconds()),
    }


@router.get("/invites", responses={200: {"model": InvitiDiAccoppiamento}})
def elenco_degli_inviti(
    db: Session = Depends(database.get_db),
    chi: models.User = Depends(auth.get_current_user),
):
    """
    Gli inviti di **chi guarda**, dal piu' recente.

    **Solo i propri**, al contrario della versione del 16/11: la' una
    richiesta arrivata da fuori non era di nessuno finche' qualcuno non la
    confermava, e la conseguenza era che chiunque fosse entrato vedeva il nome
    e l'indirizzo del programma di un altro account. Un invito invece ha un
    padrone dal primo istante.

    **Il codice non c'e'**, in nessuna di queste righe: in database c'e'
    soltanto la sua impronta. Quello che c'e' basta a rispondere alle due
    domande di chi guarda — «quale di questi aspetta ancora?» e «quello di
    stamattina e' stato usato, e da dove?».
    """
    adesso = datetime.utcnow()
    righe = db.query(models.InvitoDiAccoppiamento).filter(
        models.InvitoDiAccoppiamento.user_id == chi.id,
    ).order_by(models.InvitoDiAccoppiamento.id.desc()).limit(20).all()
    return {"items": [
        {"id": r.id, "name": r.nome, "origin": r.origine,
         "status": stato(r, adesso),
         "created_at": quando(r.creato_il), "expires_at": quando(r.scade_il),
         "redeemed_at": quando(r.riscattato_il),
         "client_name": r.nome_client, "platform": r.piattaforma,
         "ip": r.ip_riscatto}
        for r in righe
    ]}


@router.post("/invites/{invite_id}/revoke", responses={200: {"model": Esito}})
def revoca_un_invito(
    invite_id: int,
    db: Session = Depends(database.get_db),
    chi: models.User = Depends(auth.get_current_user),
):
    """
    «Quel codice non lo uso piu'»: si spegne subito, anche prima di scadere.

    **Solo i propri inviti.** Un invito di un altro account risponde 404 e non
    403: dire «c'e' ma non e' tuo» direbbe a chi prova numeri quanti inviti
    esistono.
    """
    adesso = datetime.utcnow()
    riga = db.query(models.InvitoDiAccoppiamento).filter(
        models.InvitoDiAccoppiamento.id == invite_id,
        models.InvitoDiAccoppiamento.user_id == chi.id,
    ).first()
    if not riga:
        raise HTTPException(status_code=404, detail="Unknown pairing code")
    attuale = stato(riga, adesso)
    if attuale != "pending":
        # 409 e non 404: l'invito c'e', ed e' importante dire **perche'** non
        # si puo' piu' spegnere — chi guardava l'elenco di mezzo minuto fa
        # deve capire che nel frattempo e' stato usato, non che ha sbagliato.
        raise HTTPException(
            status_code=409,
            detail=f"This pairing code is no longer waiting: it is {attuale}.",
        )
    riga.revocato_il = adesso
    db.commit()
    log_message("info", "auth",
                f"'{chi.username}' revoked a pairing code"
                f"{f' for {riga.nome!r}' if riga.nome else ''}.")
    return {"status": "ok"}
