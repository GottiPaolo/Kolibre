"""
Le cose che aspettano una decisione umana, raccolte in un posto solo.

Nascono sparse per forza di cose — una sessione di lettura che non trova il
suo libro salta fuori sincronizzando un dispositivo, un libro da spuntare
come letto salta fuori leggendolo — ma finivano tutte in pagine che si
aprono per GUARDARE: il pannello delle sessioni orfane stava in cima alle
Statistiche di lettura, cioe' davanti agli occhi ogni volta che si apriva
la pagina per vedere quanto si aveva letto. Una coda di lavoro in mezzo a un
cruscotto e' fastidiosa quando c'e' e invisibile quando serve.

Qui c'e' il lato server della pagina Interventi. Le sessioni orfane hanno
gia' i loro endpoint in api/stats.py e restano li': questo modulo aggiunge
solo quello che non esisteva.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from fastapi import HTTPException

from .. import models, database, auth, config
from ..calibre.connection import READ_FLAG_COLUMN_LABEL
from ..calibre.library import CalibreLibrary
from ..calibre.write_queue import CalibreWriteQueue
from ..deps import get_write_queue
from ..schemas_risposte import (
    ControlloAvviato, DistintiRegistrati, DoppioniAccorpati, Esito,
    IdenticiAccorpati, ImpronteRifatte, RicercaDoppioni, RigheDimenticate,
    RigheSenzaFileDimenticate, RigheSenzaLibro, RimozioniAccodate,
    StatoDelLegame, SuggerimentiDaSegnareLetto, SuggerimentoRipreso,
)
from ..services import duplicates, author_stats_service, libri_scomparsi, salute_dei_lettori
from ..services import permessi
from ..logging_utils import log_message
from .libraries import biblioteca_scrivibile, default_library_param

router = APIRouter(prefix="/api/kolibre/interventions", tags=["interventions"])

# Sopra quanta parte di libro "vista" ha senso chiedere se e' finito. La
# copertura e' misurata su posizione normalizzata e non supera mai il 100%,
# ma ha buchi noti (il lettore web non contribuisce, le sessioni orfane
# nemmeno), quindi un libro davvero finito puo' fermarsi sotto. Misurato
# su una biblioteca reale: al 90% sono 3 libri, all'80% sono 9, e nessun libro
# supera il 98,1%.
SOGLIA_COPERTURA = 0.9


def _vero(valore) -> bool:
    """Calibre tiene i bool come 0/1; il lettore puo' gia' convertirli."""
    return valore is True or valore == 1


@router.get(
    "/books-to-mark-read",
    responses={200: {"model": SuggerimentiDaSegnareLetto}},
)
def books_to_mark_read(
    library: str = Depends(default_library_param),
    threshold: float = SOGLIA_COPERTURA,
    column: str = None,
    values: str = None,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(database.get_db),
):
    """
    I libri che RISULTANO letti ma non sono ancora spuntati.

    Due sorgenti, dichiarate una per una nella risposta perche' valgono
    cose diverse:

    - `copertura`: quanto del libro e' stato attraversato, dedotto dalle
      sessioni di KOReader. E' una deduzione, e sbaglia per difetto (vedi
      SOGLIA_COPERTURA).
    - `colonna`: una colonna personalizzata che l'utente gia' compila a
      mano. Vale molto di piu' — e' gia' una decisione umana, presa una
      volta e mai importata. In una biblioteca reale se ne trovano tre
      (stato_lettura su 192 libri, data_inizio_lettura su 143,
      data_fine_lettura su 125), scritte negli anni prima che Kolibre
      esistesse.

    `column` e' l'etichetta della colonna (senza '#'); `values` restringe a
    certi valori separati da virgola, che serve per le enumerazioni — in
    "StatoLettura" il valore che interessa e' "letto", non "in lettura".
    Senza `values` basta che la colonna sia valorizzata, che e' il caso
    giusto per una data di fine lettura: se c'e' una data, il libro e'
    finito.

    Non scrive niente e non spunta niente: torna un elenco da confermare.
    La spunta passa dal solito POST /books/bulk-update, che e' gia' il modo
    con cui si scrive una colonna personalizzata su piu' libri.
    """
    valori_ammessi = None
    if values:
        valori_ammessi = {v.strip().casefold() for v in values.split(",") if v.strip()}

    try:
        lib = CalibreLibrary(config.library_path(library))
        libri = lib.list_books()
    except Exception:
        return {"candidates": [], "already_marked": 0}

    coperture = {
        r.calibre_book_id: r.coverage
        for r in db.query(models.BookReadingCoverage).filter(
            # "Questi libri li hai quasi finiti, vuoi spuntarli?" e' una
            # domanda rivolta a UNA persona: la copertura di qualcun altro
            # sullo stesso libro condiviso non la riguarda.
            models.BookReadingCoverage.user_id == current_user.id,
            models.BookReadingCoverage.library == library,
            models.BookReadingCoverage.coverage >= threshold,
        ).all()
    }

    # I suggerimenti che questa persona ha gia' rifiutato. Senza, l'elenco non
    # si accorcia mai: si ricalcola a ogni apertura, quindi un libro che non si
    # vuole spuntare tornerebbe per sempre. Per utente, come la copertura:
    # «l'ho letto» e' di chi legge.
    rifiutati = {
        r.calibre_book_id
        for r in db.query(models.SuggerimentoRifiutato).filter(
            models.SuggerimentoRifiutato.user_id == current_user.id,
            models.SuggerimentoRifiutato.library == library,
            models.SuggerimentoRifiutato.tipo == "da_segnare_letto",
        ).all()
    }

    chiave_colonna = f"#{column}" if column else None
    candidati = []
    gia_spuntati = 0

    for b in libri:
        if _vero(b.get(f"#{READ_FLAG_COLUMN_LABEL}")):
            gia_spuntati += 1
            continue
        # Un rifiuto non e' «questo libro e' spuntato»: non si conta fra i
        # gia' segnati, si tace e basta. Confonderli direbbe a chi guarda una
        # cosa falsa sul proprio conto dei libri letti.
        if b["id"] in rifiutati:
            continue

        motivi = []
        copertura = coperture.get(b["id"])
        if copertura is not None:
            motivi.append({"tipo": "copertura", "valore": round(copertura, 3)})

        if chiave_colonna:
            valore = b.get(chiave_colonna)
            # Una data, un numero o un testo: basta che ci sia qualcosa.
            # `False` e 0 NON contano come "valorizzato" — su una colonna
            # booleana "non letto" e' proprio la risposta contraria.
            if valore not in (None, "", False, 0):
                if valori_ammessi is None or str(valore).casefold() in valori_ammessi:
                    motivi.append({"tipo": "colonna", "colonna": column, "valore": str(valore)})

        if motivi:
            candidati.append({
                "id": b["id"],
                "title": b["title"],
                "author": b.get("author") or "Unknown Author",
                "reasons": motivi,
            })

    # Prima quelli che hanno una decisione umana alle spalle, poi i dedotti:
    # se la lista e' lunga, quelli piu' sicuri stanno in cima.
    candidati.sort(key=lambda c: (
        not any(m["tipo"] == "colonna" for m in c["reasons"]),
        c["title"].casefold(),
    ))
    return {"candidates": candidati, "already_marked": gia_spuntati}


# ── Doppioni ─────────────────────────────────────────────────────────────


@router.get(
    "/duplicates",
    responses={200: {"model": RicercaDoppioni}},
)
def doppioni_conservati(
    library: str = Depends(default_library_param),
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(database.get_db),
):
    """
    L'ultima ricerca di doppioni di QUESTA biblioteca, senza rifarla.

    Cercare costa: si leggono i file dal disco per calcolarne lo SHA-256.
    Qui si restituisce cio' che era stato trovato, con la data; per
    rifarla c'e' POST /duplicates/scan.

    Una biblioteca per volta, per scelta: lo stesso libro in due
    biblioteche diverse non e' un problema da segnalare — fra una
    personale e un magazzino la sovrapposizione e' il funzionamento
    normale.
    """
    dati = duplicates.leggi_scansione(db, library)
    if dati is None:
        return {"gruppi": [], "gruppi_totali": 0, "non_mostrati": 0,
                "calcolato_il": None, "mai_cercato": True}
    return {**dati, "mai_cercato": False}


@router.post(
    "/duplicates/scan",
    responses={200: {"model": RicercaDoppioni}},
)
def cerca_doppioni(
    library: str = Depends(biblioteca_scrivibile),
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(database.get_db),
):
    """Rifa' la ricerca e la conserva. E' l'operazione cara."""
    return {**duplicates.cerca_e_conserva(db, library), "mai_cercato": False}


@router.post(
    "/duplicates/distinct",
    responses={200: {"model": DistintiRegistrati}},
)
def segna_distinti(
    payload: dict,
    library: str = Depends(biblioteca_scrivibile),
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(database.get_db),
):
    """
    "Questi non sono lo stesso libro." Body: {coppie: [...], chiave}.

    La `chiave` del gruppo serve a toglierlo subito dal risultato
    conservato: senza, l'elenco resterebbe identico finche' non si rifa'
    la ricerca, e l'azione sembrerebbe non aver fatto niente.
    """
    quante = duplicates.dichiara_distinti(db, payload.get("coppie") or [])
    if payload.get("chiave"):
        duplicates.togli_gruppo(db, library, payload["chiave"])
    return {"status": "ok", "registrate": quante}


@router.post(
    "/duplicates/merge",
    responses={200: {"model": DoppioniAccorpati}},
)
async def accorpa_doppioni(
    payload: dict,
    library: str = Depends(biblioteca_scrivibile),
    write_queue: CalibreWriteQueue = Depends(get_write_queue),
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(database.get_db),
):
    """
    Accorpa uno o piu' libri su quello da tenere.

    Body: {tenere: {library, id}, scartare: [{library, id}]}.

    Ogni accorpamento e' esplicito: il chiamante dice cosa tenere e cosa
    assorbire, e questo endpoint non ridecide niente. Le regole di
    sicurezza (mai un libro con note o sessioni) valgono per cio' che
    viene PROPOSTO; qui una persona ha gia' scelto, e se decide di
    accorpare un libro annotato e' una sua decisione — le note comunque
    non si perdono, migrano.
    """
    tenere = payload.get("tenere") or {}
    scartare = payload.get("scartare") or []
    if not tenere.get("library") or not tenere.get("id") or not scartare:
        raise HTTPException(status_code=400, detail="One book to keep and at least one to merge in are required")

    lib_a, id_a = tenere["library"], int(tenere["id"])

    # Le biblioteche arrivano dal BODY, non dal parametro `library` della
    # rotta: il cancello di scrittura sopra protegge quella, non queste. Senza
    # questo controllo bastava chiedere {"scartare":[{"library":"di_un_altro",
    # "id":42}]} per far cancellare un libro da una biblioteca che il
    # chiamante non puo' nemmeno leggere.
    for cartella in {lib_a} | {s.get("library") for s in scartare if isinstance(s, dict)}:
        riga = db.query(models.Library).filter(models.Library.folder_name == cartella).first()
        if riga is None:
            raise HTTPException(status_code=404, detail=f"Library '{cartella}' not found")
        if not permessi.puo_modificare(db, current_user, riga):
            raise HTTPException(status_code=403, detail=f"You cannot edit the '{riga.name}' library.")

    note_totali, tolti = 0, []
    for s in scartare:
        if not isinstance(s, dict) or s.get("library") is None or s.get("id") is None:
            raise HTTPException(status_code=400, detail="Every book to merge needs library and id")
        lib_da, id_da = s["library"], int(s["id"])
        if (lib_da, id_da) == (lib_a, id_a):
            continue
        # Prima si sposta cio' che era attaccato al libro, poi lo si toglie
        # dal catalogo: al contrario, release_book non troverebbe piu' il
        # libro da cui migrare.
        note_totali += duplicates.accorpa(db, (lib_a, id_a), (lib_da, id_da))["note_migrate"]
        await write_queue.submit("delete_book", {"book_id": id_da}, config.library_path(lib_da))
        tolti.append(id_da)
    db.commit()

    duplicates.togli_libri(db, library, tolti)
    author_stats_service.safe_mark_author_pages_dirty(db)
    log_message(
        "info", "duplicates",
        f"Merged {len(tolti)} books in {lib_a}:{id_a} ({note_totali} notes migrated)",
    )
    return {"status": "ok", "accorpati": len(tolti), "note_migrate": note_totali}


@router.post(
    "/duplicates/merge-identical",
    responses={200: {"model": IdenticiAccorpati}},
)
async def accorpa_identici(
    library: str = Depends(biblioteca_scrivibile),
    write_queue: CalibreWriteQueue = Depends(get_write_queue),
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(database.get_db),
):
    """
    Accorpa in un colpo TUTTI e SOLI i gruppi di file identici.

    Solo quelli: due file con lo stesso SHA-256 sono lo stesso file, e
    tenerne uno e' una constatazione, non un giudizio. Dove i file
    differiscono l'automatismo non entra — anche col punteggio piu' netto,
    perche' la prova che siano lo stesso libro e' una somiglianza di
    titolo, e un falso positivo li' dentro farebbe sparire un libro che non
    c'entra niente.

    Lavora sul risultato gia' conservato, non su una ricerca nuova: cosi'
    accorpa esattamente quello che l'utente ha visto sullo schermo.
    """
    dati = duplicates.leggi_scansione(db, library)
    if not dati:
        return {"status": "ok", "accorpati": 0, "note_migrate": 0, "lasciati": 0}

    fatti, note_totali, saltati, tolti = 0, 0, 0, []
    for g in dati.get("gruppi", []):
        azioni = g.get("azioni") or {}
        if not azioni.get("automatico"):
            saltati += 1
            continue
        per_id = {m["id"]: m for m in g["membri"]}
        lib_a = per_id[azioni["tenere"]]["library"]
        for book_id in azioni["scartare"]:
            note_totali += duplicates.accorpa(
                db, (lib_a, azioni["tenere"]), (per_id[book_id]["library"], book_id)
            )["note_migrate"]
            await write_queue.submit(
                "delete_book", {"book_id": book_id},
                config.library_path(per_id[book_id]["library"]),
            )
            tolti.append(book_id)
            fatti += 1
    db.commit()

    if fatti:
        duplicates.togli_libri(db, library, tolti)
        author_stats_service.safe_mark_author_pages_dirty(db)
    log_message("info", "duplicates", f"Merged {fatti} file identici, {saltati} groups left for a person to decide")
    return {"status": "ok", "accorpati": fatti, "note_migrate": note_totali, "lasciati": saltati}


# ── Righe di dispositivo senza libro ─────────────────────────────────────


@router.get(
    "/device-books-gone",
    responses={200: {"model": RigheSenzaLibro}},
)
def righe_di_libri_scomparsi(
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(database.get_db),
):
    """
    I libri che un lettore ha in carico, ma che in biblioteca non ci sono piu'.

    Non e' lo stesso difetto delle note vedove: quelle sono annotazioni
    rimaste senza libro, queste sono RIGHE DI CONSEGNA rimaste senza libro —
    il server crede ancora di avere quel libro su quel dispositivo, lo conta
    fra i suoi, e nessuno lo contraddice perche' il lettore non ha modo di
    sapere che in biblioteca e' stato cancellato.

    Perche' succede, e cosa NON si tocca: vedi services/libri_scomparsi.py,
    che e' anche il posto dove sta la regola di prudenza sulle biblioteche
    che non si riescono ad aprire.
    """
    righe = libri_scomparsi.righe_senza_libro(db, current_user)
    return {"righe": righe, "totale": len(righe)}


@router.post(
    "/device-books-gone/forget",
    responses={200: {"model": RigheDimenticate}},
)
def dimentica_righe_di_libri_scomparsi(
    payload: dict,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(database.get_db),
):
    """
    Toglie dal conto del server le righe indicate. Body: {ids: [...]}.

    Il file sul lettore non si tocca — e in un caso visto davvero toccarlo
    sarebbe un danno, perche' quel file e' la copia di un libro vivo
    riabbinata dal lettore stesso. Se invece il file e' una copia orfana,
    dimenticare la riga lo rende "non abbinato" e sara' «Inizializza
    libreria» a proporre cosa farne: una decisione in piu', non una in meno.
    """
    quante = libri_scomparsi.dimentica_righe(db, current_user, payload.get("ids") or [])
    log_message("info", "devices",
                f"Forgotten {quante} device rows whose book no longer exists")
    return {"status": "ok", "dimenticate": quante}


@router.post(
    "/device-books-gone/delete-on-device",
    responses={200: {"model": RimozioniAccodate}},
)
def cancella_dal_lettore_i_libri_scomparsi(
    payload: dict,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(database.get_db),
):
    """
    Fa togliere dal lettore il file di un libro che la biblioteca non ha piu'.
    Body: {ids: [...]}.

    E' la strada normale, non quella eccezionale: un libro cancellato dalla
    biblioteca non ha valore sul dispositivo. La riga va in attesa di
    rimozione e il lettore la esegue alla sincronizzazione successiva, con la
    conferma che la sua politica prevede; quando conferma, la riga sparisce
    da se'.

    Le righe il cui file e' la copia di un libro ancora in biblioteca si
    rifiutano, e la risposta dice quante e quali: la' l'unica cosa che si puo'
    fare e' dimenticare la riga (vedi services/libri_scomparsi.py).
    """
    esito = libri_scomparsi.fai_cancellare_dal_lettore(
        db, current_user, payload.get("ids") or [])
    log_message("info", "devices",
                f"Queued {esito['in_coda']} removals of books no longer in the library"
                + (f", {esito['rifiutate']} refused because the file belongs to a live book"
                   if esito["rifiutate"] else "")
                + (f", {esito['rifiutate_politica']} on readers that do not accept removals"
                   if esito["rifiutate_politica"] else ""))
    return {"status": "ok", **esito}


# ── Il legame coi lettori: un controllo che si chiede ─────────────────────
#
# Perche' non e' un conteggio come le altre voci di questa pagina. Verificare
# un'impronta vuol dire aprire il file e ricamparlo: 8217 file in 24 secondi,
# misurati sull'impianto vero. Le altre voci di Interventi si contano a ogni
# apertura della pagina; questa no — sarebbero 24 secondi di lettura disco per
# aprire una pagina, e inutili, perche' il risultato non cambia da solo fra
# un'apertura e l'altra.
#
# Quindi: un controllo che si lancia, il suo avanzamento, e un risultato che
# resta (in memoria del server, come gli altri giri lunghi — vedi il modulo).
# E ogni riparazione passa per una conferma: deciso da Paolo il 04/11/2026,
# «la metterei in interventi e chiede sempre».


@router.get(
    "/device-link",
    responses={200: {"model": StatoDelLegame}},
)
def stato_del_legame_coi_lettori(
    current_user: models.User = Depends(auth.get_current_user),
):
    """Com'e' andato l'ultimo controllo, o a che punto e' quello in corso."""
    return salute_dei_lettori.stato()


@router.post(
    "/device-link/check",
    responses={200: {"model": ControlloAvviato}},
)
def avvia_il_controllo_del_legame(
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(database.get_db),
):
    """
    Avvia il controllo su tutte le biblioteche.

    Risponde `avviato: false` se ce n'e' gia' uno in corso, invece di
    accodarne un secondo: la guardia sta nel servizio, cosi' due schede del
    browser aperte sulla stessa pagina non possono far partire due giri sugli
    stessi file.
    """
    nomi = [l.folder_name for l in db.query(models.Library).all()]
    avviato = salute_dei_lettori.avvia(nomi)
    if avviato:
        log_message("info", "devices",
                    f"Reader-link check started on {len(nomi)} libraries")
    return {"avviato": avviato, "stato": salute_dei_lettori.stato()}


@router.post(
    "/device-link/recompute",
    responses={200: {"model": ImpronteRifatte}},
)
def rifai_le_impronte(
    payload: dict,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(database.get_db),
):
    """
    Rifa' le impronte indicate. Body: {voci: [{library, calibre_book_id, format}]}.

    E' la riparazione sicura: riscrive soltanto il server, e la vecchia
    impronta viene archiviata invece di buttata — cosi' un lettore che aveva
    scaricato la copia precedente continua a riconoscersi. Non tocca niente
    su nessun dispositivo.
    """
    esito = salute_dei_lettori.ricalcola(db, payload.get("voci") or [])
    return {"status": "ok", **esito}


@router.post(
    "/device-link/forget-missing",
    responses={200: {"model": RigheSenzaFileDimenticate}},
)
def dimentica_le_righe_senza_file(
    payload: dict,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(database.get_db),
):
    """
    Toglie le righe che parlano di un file che non c'e' piu'.
    Body: {voci: [{library, calibre_book_id, format}]}.

    Innocue per il riconoscimento, ma gonfiano il conto e nascondono i casi
    veri. Una riga il cui file e' RICOMPARSO non si cancella, e la risposta lo
    dice: succede con una biblioteca su un disco esterno ricollegato.
    """
    esito = salute_dei_lettori.dimentica_righe_senza_file(db, payload.get("voci") or [])
    log_message("info", "devices",
                f"Removed {esito['tolte']} fingerprint rows with no file"
                + (f", {esito['tornate']} left alone because the file came back"
                   if esito["tornate"] else ""))
    return {"status": "ok", **esito}


@router.post(
    "/books-to-mark-read/reject",
    responses={200: {"model": Esito}},
)
def rifiuta_suggerimento_da_segnare_letto(
    payload: dict,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(database.get_db),
):
    """
    «Questo libro non suggerirmelo piu'.» Body: {library, calibre_book_id}.

    Serve perche' quell'elenco non e' una lista salvata: si ricalcola a ogni
    apertura della pagina da quanto del libro risulta attraversato, quindi un
    suggerimento che non si vuole torna per sempre. E i falsi positivi sono
    comuni e legittimi — un saggio di cui si leggono tre capitoli su dieci puo'
    superare la soglia senza essere stato letto.

    Non spunta il libro come letto, che e' un'altra cosa e sarebbe falsa: lo
    toglie solo dai suggerimenti di chi lo chiede. Idempotente — chiederlo due
    volte non raddoppia niente.
    """
    library = payload.get("library")
    calibre_book_id = payload.get("calibre_book_id")
    if not library or calibre_book_id is None:
        raise HTTPException(status_code=400, detail="library and calibre_book_id are required")

    esistente = db.query(models.SuggerimentoRifiutato).filter(
        models.SuggerimentoRifiutato.user_id == current_user.id,
        models.SuggerimentoRifiutato.library == library,
        models.SuggerimentoRifiutato.calibre_book_id == int(calibre_book_id),
        models.SuggerimentoRifiutato.tipo == "da_segnare_letto",
    ).first()
    if not esistente:
        db.add(models.SuggerimentoRifiutato(
            user_id=current_user.id, library=library,
            calibre_book_id=int(calibre_book_id), tipo="da_segnare_letto",
        ))
        db.commit()
    return {"status": "ok"}


@router.post(
    "/books-to-mark-read/unreject",
    responses={200: {"model": SuggerimentoRipreso}},
)
def riprendi_suggerimento_da_segnare_letto(
    payload: dict,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(database.get_db),
):
    """
    Disfa il rifiuto: il libro torna fra i suggerimenti, se la sua copertura
    lo merita ancora. Body: {library, calibre_book_id}.

    Esiste per la stessa accortezza dei doppioni, dove «non sono lo stesso
    libro» si puo' disfare: un «no» detto per sbaglio non deve essere
    definitivo, e senza questo lo sarebbe — la riga non e' raggiungibile da
    nessun'altra parte dell'interfaccia.
    """
    library = payload.get("library")
    calibre_book_id = payload.get("calibre_book_id")
    if not library or calibre_book_id is None:
        raise HTTPException(status_code=400, detail="library and calibre_book_id are required")

    quante = db.query(models.SuggerimentoRifiutato).filter(
        models.SuggerimentoRifiutato.user_id == current_user.id,
        models.SuggerimentoRifiutato.library == library,
        models.SuggerimentoRifiutato.calibre_book_id == int(calibre_book_id),
        models.SuggerimentoRifiutato.tipo == "da_segnare_letto",
    ).delete(synchronize_session=False)
    db.commit()
    return {"status": "ok", "ripresi": quante}
