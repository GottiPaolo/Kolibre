"""
Le entita' della biblioteca: elencarle, trovare le grafie doppie, unirle.

Perche' una pagina a se' e non una sezione di Interventi o una scheda di
Operazioni di massa: le entita' non sono ne' una decisione in sospeso ne'
un ricalcolo, sono **un oggetto da curare**, e sono quattro con le stesse
azioni.

Il lavoro pesante c'era gia': dal 21/09/2026 cambiare l'autore di un libro
sposta anche i file e le cartelle sul disco. Unire due grafie, qui, e'
scrivere il nome giusto su ogni libro che aveva quello sbagliato — il resto
lo fa quel meccanismo.

**Tutte le biblioteche insieme** (`library=*`, dal 28/09/2026): il disordine
dei nomi non si ferma al confine di una biblioteca, e uniformare gli autori e'
proprio la ragione per cui questa pagina esiste. Guardandone una per volta,
"Svetlana Aleksievič" in una biblioteca e "Svetlana Aleksievic" in un'altra
non si incontrano mai.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import auth, config, database, models
from ..calibre.library import CalibreLibrary
from ..calibre.write_queue import CalibreWriteQueue
from ..deps import get_write_queue
from ..logging_utils import log_message
from ..services import entita, author_stats_service, permessi
from .libraries import default_library_param

router = APIRouter(prefix="/api/kolibre/entita", tags=["entita"])

# Il valore di `library` che significa "tutte quelle che posso vedere".
OVUNQUE = "*"


def _tipo(tipo: str) -> dict:
    forma = entita.TIPI.get(tipo)
    if not forma:
        raise HTTPException(status_code=404, detail=f"Tipo di entità sconosciuto: '{tipo}'")
    return forma


def _biblioteche(
    library: str,
    db: Session,
    utente: models.User,
    scrivibili: bool = False,
) -> list:
    """Le biblioteche su cui lavorare: una sola, o tutte quelle permesse.

    Il filtro dei permessi passa da `permessi`, non da una query a mano: con
    `library=*` il rischio e' proprio quello di scavalcare il cancello unico
    di lettura facendo un giro diverso.
    """
    if library != OVUNQUE:
        # Una sola, e se non si apre l'errore e' pertinente: e' quella che hai
        # chiesto.
        return [(library, CalibreLibrary(config.library_path(library)))]

    righe = permessi.biblioteche_visibili(db, utente)
    if scrivibili:
        righe = [r for r in righe if permessi.puo_modificare(db, utente, r)]

    aperte = []
    for r in righe:
        try:
            aperte.append((r.folder_name, CalibreLibrary(config.library_path(r.folder_name))))
        except Exception as exc:
            # Una biblioteca su un disco smontato, o una cartella sparita, non
            # deve far cadere la pagina intera: si lavora sulle altre e lo si
            # dice nei log. Guardandole tutte insieme, basterebbe una rotta
            # per rendere inutilizzabile tutto il resto.
            log_message("warning", "entita", f"Biblioteca '{r.folder_name}' saltata: {exc}")
    return aperte


def _nomi_con_dati(tipo: str, db: Session) -> set:
    """I nomi per cui il recupero online ha trovato qualcosa.

    Solo per gli autori: e' l'unica entita' di cui Kolibre scarichi dei dati.
    Serve una voce vera — una pagina Wikipedia o una biografia — e non il
    semplice fatto di aver provato: `author_metadata` contiene anche le righe
    dei tentativi andati a vuoto, e quelle non dicono niente su come si
    scrive un nome.
    """
    if tipo != "autori":
        return set()
    return {
        nome for (nome,) in db.query(models.AuthorMetadata.author_name).filter(
            (models.AuthorMetadata.wikipedia_url_it.isnot(None))
            | (models.AuthorMetadata.wikipedia_url_en.isnot(None))
            | (models.AuthorMetadata.bio_it.isnot(None))
            | (models.AuthorMetadata.bio_en.isnot(None))
        ).all()
    }


# Gli stati in cui puo' trovarsi la scheda di un autore.
#
# La distinzione che conta, fissata esplicitamente il 28/09/2026, e' fra
# **mai cercato** e **cercato e non trovato**: si somigliano
# (in entrambi i casi la scheda e' vuota) e si trattano in modo opposto. Sul
# primo una ricerca ha ottime probabilita' di funzionare; sul secondo
# rilanciarla e' quasi sempre bussare due volte alla stessa porta chiusa —
# e nel frattempo Wikipedia comincia a rifiutare le richieste per tutti gli
# altri, che e' il difetto che `scrape-missing` gia' evita con le sue attese.
STATO_MAI_CERCATO = "mai_cercato"
STATO_NON_TROVATO = "non_trovato"      # cercato, nessuna voce
STATO_PARZIALE = "parziale"            # qualcosa c'e', ma non tutto
STATO_COMPLETO = "completo"            # biografia, immagine e anagrafica


def _stato_dati_autori(tipo: str, db: Session) -> dict:
    """Per ogni autore con una scheda: cosa c'e', cosa manca, e se e' mai
    stato cercato.

    Torna un dizionario nome → dettaglio. Gli autori **assenti** dal
    dizionario sono quelli senza nessuna riga: mai cercati, e sono
    tipicamente i piu' numerosi su una biblioteca cresciuta per importazioni.
    """
    if tipo != "autori":
        return {}
    stato = {}
    for riga in db.query(models.AuthorMetadata).all():
        bio = bool(riga.bio_it or riga.bio_en)
        immagine = bool(riga.image_cached)
        anagrafica = riga.wikidata_fetched_at is not None
        if riga.last_scraped_at is None and not (bio or immagine or anagrafica):
            qualita = STATO_MAI_CERCATO
        elif not bio and not immagine and not anagrafica:
            qualita = STATO_NON_TROVATO
        elif bio and immagine and anagrafica:
            qualita = STATO_COMPLETO
        else:
            qualita = STATO_PARZIALE
        stato[riga.author_name] = {
            "stato": qualita,
            "bio": bio,
            "immagine": immagine,
            "anagrafica": anagrafica,
            # L'esito grezzo dell'ultimo tentativo ('no_page', 'blocked',
            # 'error'…): dice PERCHE' non c'e' niente, che e' l'unica cosa
            # che distingue "non esiste" da "ci hanno rifiutato le richieste".
            "esito": riga.scrape_status,
            "cercato_il": riga.last_scraped_at.isoformat() if riga.last_scraped_at else None,
        }
    return stato


@router.get("/{tipo}")
def elenca_entita(
    tipo: str,
    library: str = OVUNQUE,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    Tutti i valori di questo tipo, con quanti libri ciascuno.

    Per gli autori porta anche lo stato della scheda — cosa c'e', cosa manca,
    e se e' mai stata cercata — piu' un riepilogo per stato, che e' quello
    che serve per decidere se lanciare un recupero e su chi.
    """
    _tipo(tipo)
    if library != OVUNQUE:
        library = default_library_param(library, db, current_user)
    biblioteche = _biblioteche(library, db, current_user)
    valori = entita.segna_conosciuti(
        entita.elenca_ovunque(biblioteche, tipo), _nomi_con_dati(tipo, db)
    )

    per_nome = _stato_dati_autori(tipo, db)
    riepilogo = {STATO_MAI_CERCATO: 0, STATO_NON_TROVATO: 0, STATO_PARZIALE: 0, STATO_COMPLETO: 0}
    if tipo == "autori":
        for voce in valori:
            # Assente dalla tabella = mai cercato: la riga nasce al primo
            # tentativo, quindi non averla e' gia' l'informazione.
            dettaglio = per_nome.get(voce["valore"], {"stato": STATO_MAI_CERCATO})
            voce["dati"] = dettaglio
            riepilogo[dettaglio["stato"]] = riepilogo.get(dettaglio["stato"], 0) + 1

    return {"tipo": tipo, "valori": valori, "riepilogo_dati": riepilogo}


@router.get("/{tipo}/affini")
def entita_affini(
    tipo: str,
    library: str = OVUNQUE,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    I valori che sembrano la stessa cosa scritta in modi diversi.

    Propone, non decide: unire due entita' non si disfa se non rifacendolo a
    mano, e "Mario Rossi" e "Dario Rossi" si somigliano molto pur essendo due
    persone. Il primo di ogni gruppo e' la destinazione suggerita — chi ha una
    voce su Wikipedia, e a parita' chi ha piu' libri — ma e' un suggerimento,
    e la scelta vera si fa dalla pagina.

    I gruppi che qualcuno ha dichiarato "cose diverse" non compaiono: vedi
    POST /{tipo}/distinti.
    """
    _tipo(tipo)
    if library != OVUNQUE:
        library = default_library_param(library, db, current_user)
    biblioteche = _biblioteche(library, db, current_user)
    valori = entita.segna_conosciuti(
        entita.elenca_ovunque(biblioteche, tipo), _nomi_con_dati(tipo, db)
    )
    gruppi = entita.gruppi_affini(valori, distinte=entita.coppie_distinte(db, tipo))
    return {
        "tipo": tipo,
        "gruppi": [
            {"suggerito": g[0]["valore"], "valori": g, "libri": sum(v["libri"] for v in g)}
            for g in gruppi
        ],
    }


def _puo_curare(db: Session, utente: models.User) -> bool:
    """Chi puo' dire "questi due sono diversi".

    Serve almeno una biblioteca modificabile, e la ragione e' che la decisione
    e' condivisa: cancella un suggerimento per tutti. Chi ha soltanto accesso
    in lettura non deve poter accorciare la coda di lavoro di chi possiede la
    biblioteca. Non si aprono le biblioteche per saperlo — basta il permesso.
    """
    righe = permessi.biblioteche_visibili(db, utente)
    return any(permessi.puo_modificare(db, utente, r) for r in righe)


@router.get("/{tipo}/distinti")
def elenca_distinti(
    tipo: str,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Le coppie dichiarate diverse, le piu' recenti per prime."""
    _tipo(tipo)
    righe = (
        db.query(models.EntitaDistinte)
        .filter(models.EntitaDistinte.tipo == tipo)
        .order_by(models.EntitaDistinte.id.desc())
        .all()
    )
    return {
        "tipo": tipo,
        "coppie": [
            {
                "valori": [r.valore_a, r.valore_b],
                "deciso_da": r.deciso_da,
                "deciso_il": r.deciso_il.isoformat() if r.deciso_il else None,
            }
            for r in righe
        ],
    }


@router.post("/{tipo}/distinti")
def segna_distinti(
    tipo: str,
    payload: dict,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    "Questi non sono la stessa cosa." Body: {"valori": ["A", "B", ...]}.

    Il rovescio dell'unione, e serve esattamente quanto lei: l'algoritmo
    riconosce che due grafie si somigliano, non che siano la stessa persona.
    "Giuseppe Berta" e "Giuseppe Berto" sono uno storico e un romanziere, e
    senza un posto dove ricordare il "no" la coppia torna a ogni apertura
    della pagina — una coda di lavoro che non si accorcia si smette di usare.

    Non tocca la biblioteca: non riscrive nessun libro, non sposta nessun file.
    Si disfa con /distinti/annulla.
    """
    _tipo(tipo)
    if not _puo_curare(db, current_user):
        raise HTTPException(
            status_code=403,
            detail="Non hai nessuna biblioteca che tu possa modificare.",
        )
    valori = [v for v in (payload.get("valori") or []) if isinstance(v, str) and v.strip()]
    if len(valori) < 2:
        raise HTTPException(status_code=400, detail="Servono almeno due valori.")
    quante = entita.dichiara_distinte(db, tipo, valori, current_user.username)
    log_message(
        "info", "entita",
        f"{_tipo(tipo)['etichetta']}: {quante} coppie dichiarate diverse ({', '.join(valori)}).",
    )
    return {"status": "ok", "registrate": quante}


@router.post("/{tipo}/distinti/annulla")
def annulla_distinti(
    tipo: str,
    payload: dict,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Torna a proporre una coppia. Body: {"valori": ["A", "B"]}."""
    _tipo(tipo)
    if not _puo_curare(db, current_user):
        raise HTTPException(
            status_code=403,
            detail="Non hai nessuna biblioteca che tu possa modificare.",
        )
    valori = [v for v in (payload.get("valori") or []) if isinstance(v, str) and v.strip()]
    if len(valori) < 2:
        raise HTTPException(status_code=400, detail="Servono i due valori della coppia.")
    tolte = entita.dimentica_distinte(db, tipo, valori)
    return {"status": "ok", "tolte": tolte}


@router.post("/{tipo}/unisci")
async def unisci_entita(
    tipo: str,
    payload: dict,
    library: str = OVUNQUE,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
    write_queue: CalibreWriteQueue = Depends(get_write_queue),
):
    """
    Body: {"da": ["grafia sbagliata", ...], "a": "grafia giusta"}.

    Fa due lavori con lo stesso gesto, e la differenza e' solo in quanti nomi
    ci sono in `da`: con piu' d'uno **unisce**, con uno solo **rinomina**. Per
    chi guarda sono due cose diverse; per i libri sono la stessa — riscrivere
    un valore su ogni libro che aveva il vecchio.

    Per gli **autori** la stringa puo' contenerne piu' d'uno, quindi si
    sostituisce il nome dentro la stringa invece di rimpiazzarla — e i file
    seguono da soli, perche' cambiare l'autore di un libro sposta anche le
    cartelle (21/09/2026).

    Non crea il valore di destinazione: lo crea Calibre alla prima scrittura,
    come per qualunque altro nome nuovo.
    """
    forma = _tipo(tipo)
    grezzo_a = payload.get("a")
    da = [v for v in (payload.get("da") or []) if isinstance(v, str) and v.strip()]
    a = grezzo_a.strip() if isinstance(grezzo_a, str) else ""
    if not da or not a:
        raise HTTPException(status_code=400, detail="Servono 'da' (elenco) e 'a' (valore di destinazione)")
    da = [v for v in da if v != a]
    if not da:
        return {"status": "ok", "libri_toccati": 0}

    # I permessi PRIMA di aprire qualunque cosa: un rifiuto deve arrivare
    # prima che si cominci a leggere, non a meta' strada.
    if library != OVUNQUE:
        library = default_library_param(library, db, current_user)
        riga = db.query(models.Library).filter(models.Library.folder_name == library).first()
        if riga is not None and not permessi.puo_modificare(db, current_user, riga):
            raise HTTPException(status_code=403, detail=f"Non puoi modificare la biblioteca '{riga.name}'.")
    biblioteche = _biblioteche(library, db, current_user, scrivibili=True)
    if not biblioteche:
        raise HTTPException(status_code=403, detail="Non hai nessuna biblioteca che tu possa modificare.")

    toccati = 0
    corrette = 0
    for nome, lib in biblioteche:
        percorso = config.library_path(nome)
        for libro in lib.list_books():
            if tipo == "autori":
                attuale = libro.get("author") or ""
                nuovo = attuale
                for vecchio in da:
                    nuovo = entita.sostituisci_in_stringa(nuovo, vecchio, a)
                if nuovo != attuale:
                    await write_queue.submit(
                        "update_book", {"book_id": libro["id"], "fields": {"author": nuovo}}, percorso
                    )
                    toccati += 1
            elif tipo == "tag":
                attuali = libro.get("tags") or []
                if not any(t in da for t in attuali):
                    continue
                nuovi = []
                for t in attuali:
                    candidato = a if t in da else t
                    if candidato not in nuovi:
                        nuovi.append(candidato)
                await write_queue.submit("set_book_tags", {"book_id": libro["id"], "tags": nuovi}, percorso)
                toccati += 1
            elif tipo == "serie":
                if (libro.get("series") or "") in da:
                    await write_queue.submit(
                        "set_book_series", {"book_id": libro["id"], "series_name": a}, percorso
                    )
                    toccati += 1
            elif tipo == "editori":
                if (libro.get("publisher") or "") in da:
                    await write_queue.submit("set_publisher", {"book_id": libro["id"], "name": a}, percorso)
                    toccati += 1

        # Riscrivere il valore su ogni libro non basta: `name` e' COLLATE
        # NOCASE con UNIQUE, quindi unire "Aa. Vv." in "AA. VV." ritrovava la
        # riga vecchia e la lasciava com'era — l'unione diceva di essere
        # riuscita senza cambiare niente (30/09/2026). Questa passata
        # scrive la grafia scelta nella tabella, e va DOPO i libri: prima
        # devono essere passati tutti sulla riga di destinazione.
        esiti = await write_queue.submit(
            "rinomina_entita", {"tipo": tipo, "da": da, "a": a}, percorso
        )
        corrette += (esiti or {}).get("rinominate", 0) + (esiti or {}).get("unite", 0)

    # Unire due grafie che erano state dichiarate diverse ritira quel rifiuto:
    # tenerlo scritto sarebbe conservare un'affermazione già smentita, e la
    # coppia resterebbe invisibile nei suggerimenti per sempre.
    entita.dimentica_distinte_fra(db, tipo, [*da, a])

    if tipo == "autori" and (toccati or corrette):
        # Le pagine per autore sono in cache: unire due grafie ne cambia il
        # totale, e lasciarla ferma farebbe sembrare che l'unione non abbia
        # funzionato.
        author_stats_service.safe_mark_author_pages_dirty(db)
    dove = "tutte le biblioteche" if library == OVUNQUE else f"'{library}'"
    log_message(
        "info", "entita",
        f"{forma['etichetta']}: {len(da)} grafie → '{a}' su {dove}, "
        f"{toccati} libri, {corrette} righe corrette.",
    )
    return {
        "status": "ok",
        "libri_toccati": toccati,
        "grafie_corrette": corrette,
        "unite": da,
        "in": a,
    }


@router.get("")
def tipi_disponibili():
    """Quali entita' esistono, per costruire il selettore senza indovinare."""
    return {
        "tipi": [
            {"id": chiave, "etichetta": forma["etichetta"]}
            for chiave, forma in entita.TIPI.items()
        ]
    }


@router.post("/{tipo}/pulisci")
async def pulisci_orfane(
    tipo: str,
    library: str = OVUNQUE,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
    write_queue: CalibreWriteQueue = Depends(get_write_queue),
):
    """
    Toglie le voci rimaste senza libri.

    Sono il residuo degli accorpamenti: unendo "eleuthera" in "eleuthera" con
    l'accento, i libri passano alla seconda e la prima resta nella tabella di
    Calibre senza piu' collegamenti. Calibre Desktop fa questa pulizia da solo
    dopo ogni modifica; Kolibre scrive sulle stesse tabelle e non lo faceva,
    cosi' quelle righe si accumulavano e tornavano a galla nei suggerimenti.

    Non e' automatica dopo ogni unione, ed e' una scelta: cancellare righe
    dalla biblioteca di qualcuno non deve essere l'effetto collaterale di
    un'altra operazione. Qui e' un gesto suo, con un numero davanti.
    """
    _tipo(tipo)
    if library != OVUNQUE:
        library = default_library_param(library, db, current_user)
    biblioteche = _biblioteche(library, db, current_user, scrivibili=True)
    if not biblioteche:
        raise HTTPException(status_code=403, detail="Non hai nessuna biblioteca che tu possa modificare.")

    tolte, nomi = 0, []
    for nome, _lib in biblioteche:
        esito = await write_queue.submit(
            "pulisci_entita_orfane", {"tipo": tipo}, config.library_path(nome)
        )
        if isinstance(esito, dict):
            tolte += esito.get("tolte", 0)
            nomi.extend(esito.get("nomi") or [])
    log_message("info", "entita", f"Pulite {tolte} voci senza libri ({tipo}).")
    return {"status": "ok", "tolte": tolte, "nomi": nomi[:50]}


@router.post("/serie/sciogli")
async def sciogli_serie(
    payload: dict,
    library: str = OVUNQUE,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
    write_queue: CalibreWriteQueue = Depends(get_write_queue),
):
    """
    Body: {"serie": ["nome", ...], "in_tag": bool}

    Toglie una serie dai suoi libri **senza toccare i libri**. Con
    `in_tag: true` il nome della serie diventa un tag invece di sparire.

    Sono due bisogni diversi e li ha la stessa persona: una raccolta che non
    e' davvero una serie — l'opera omnia di un autore, una collana — toglie ai
    libri un ordinamento che non hanno mai avuto; ma quel nome spesso vale
    ancora come etichetta, e buttarlo vuol dire perdere un'informazione che
    qualcuno aveva inserito a mano.

    Il numero di serie resta scritto sui libri: senza serie non lo mostra
    nessuno, e un ripensamento ritrova l'ordine giusto invece di un elenco
    tutto a 1.
    """
    serie = [s for s in (payload.get("serie") or []) if isinstance(s, str) and s.strip()]
    in_tag = bool(payload.get("in_tag"))
    if not serie:
        raise HTTPException(status_code=400, detail="Serve 'serie' (elenco di nomi)")

    if library != OVUNQUE:
        library = default_library_param(library, db, current_user)
    biblioteche = _biblioteche(library, db, current_user, scrivibili=True)
    if not biblioteche:
        raise HTTPException(status_code=403, detail="Non hai nessuna biblioteca che tu possa modificare.")

    toccati = 0
    for nome, lib in biblioteche:
        percorso = config.library_path(nome)
        for libro in lib.list_books():
            if (libro.get("series") or "") not in serie:
                continue
            if in_tag:
                tag = libro.get("tags") or []
                if libro["series"] not in tag:
                    await write_queue.submit(
                        "set_book_tags", {"book_id": libro["id"], "tags": tag + [libro["series"]]}, percorso
                    )
            await write_queue.submit(
                "set_book_series", {"book_id": libro["id"], "series_name": ""}, percorso
            )
            toccati += 1

    log_message(
        "info", "entita",
        f"Sciolte {len(serie)} serie su {toccati} libri" + (" (convertite in tag)" if in_tag else ""),
    )
    return {"status": "ok", "libri_toccati": toccati, "in_tag": in_tag}
