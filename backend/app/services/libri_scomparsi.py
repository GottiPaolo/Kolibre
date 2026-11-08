"""
Le righe di dispositivo che parlano di un libro che non esiste piu'.

**Cos'e' una riga di dispositivo.** Per ogni (libro, formato) che un lettore
deve avere, Kolibre tiene una riga (`models.DeviceBook`) che dice cosa il
server vuole su quel dispositivo e cosa il dispositivo ha confermato.
L'elenco "libri su questo lettore" nella scheda del dispositivo e' il
conteggio di quelle righe.

**Come nasce il difetto.** Quando un libro si cancella DA Kolibre, le sue
righe di dispositivo diventano `pending_delete`: e' cosi' che il lettore sa
di togliere la sua copia (`book_records.release_book`). Ma un libro puo'
uscire da Calibre per un'altra strada — cancellato da Calibre desktop,
perso in uno spostamento di biblioteca — e in quel caso nessuno tocca le
righe: restano `synced`, cioe' "il server e il dispositivo sono d'accordo
che il file c'e'", parlando di un libro che in biblioteca non esiste piu'.

C'e' anche una terza strada, e il modulo la copre senza saperlo: una
cancellazione chiesta per bene e **rifiutata** dal lettore lascia la riga in
`delete_declined`, e anche quella parla di un libro che non c'e' piu'. La
differenza e' che lei non mente sul conto — i lettori mostrano solo i
`synced` — ma e' comunque una riga da chiudere, e per lei «toglilo dal
lettore» vuol dire richiedere quello che era stato rifiutato.

Misurato sull'impianto reale il 04/11/2026, dispositivo `kindle_af`: 215
righe `synced` su 213 percorsi distinti, piu' 1 `delete_declined` e 2
`removed_by_device`. Le tre righe senza libro sono quelle: calibre 721 e
1186, che rivendicano il percorso di due libri vivi (1033 e 1218 — il file
era stato riabbinato al libro nuovo da "Inizializza libreria" e la riga del
vecchio e' rimasta la'), e calibre 1169, rifiutata dal lettore il 02/11, con
percorso tutto suo. Le prime due non hanno ne' note ne' sessioni di lettura;
la terza ne ha 15, per 170 minuti, ed e' la dimostrazione dell'altra regola:
quelle sessioni restano, senza un libro a cui attaccarsi.

**La regola che questo modulo rifiuta di infrangere.** Una biblioteca che
non si riesce ad aprire non dice NIENTE sui suoi libri. Se "non trovato
nell'elenco" valesse anche quando l'elenco non si e' potuto leggere, un
disco scollegato o una cartella rinominata farebbero dichiarare scomparsi
tutti i libri di quella biblioteca in un colpo — e l'azione che segue e'
cancellare righe. Quindi: elenco letto -> gli id che mancano sono davvero
spariti; elenco non letto -> su quelle righe non si afferma nulla.

**Cosa fa l'azione di riparazione, e perche' in quest'ordine.** *(Deciso da
Paolo il 03/11/2026: «se elimino un libro dalla biblioteca verosimilmente lo
voglio eliminare anche dai lettori».)* La strada normale e' **farlo
cancellare dal lettore**: la riga va in `pending_delete`, il dispositivo
toglie la sua copia alla sincronizzazione successiva secondo la politica che
ha (`Device.delete_policy`: chiedere, fare, mai), e quando conferma la riga
sparisce da se'. Un libro che la biblioteca non ha piu' non ha valore sul
lettore; le sue note e le sue sessioni di lettura restano, senza un libro a
cui attaccarsi, e quella e' un'altra voce.

**L'unica eccezione, e non e' una preferenza.** Se quel percorso e'
rivendicato anche da una riga BUONA, il file sul lettore e' la copia di un
libro vivo — succede quando il file viene riabbinato al libro nuovo da
«Inizializza libreria» e la riga del vecchio resta indietro. Cancellarlo
porterebbe via un libro che c'e'. E non e' evitabile scegliendo meglio cosa
mandare al lettore: il plugin risolve il percorso da cancellare prima dal suo
manifesto e poi da `expected_path` (`main.lua:_applyDeletions`), e in questo
caso **le due strade portano allo stesso file vivo**. Per quelle righe resta
solo «dimentica», e il modulo lo rifiuta invece di fidarsi di chi chiama.

Quando invece il file e' davvero una copia orfana, dimenticare la riga senza
cancellare lo rende "non abbinato", e a quel punto e' "Inizializza libreria"
sul lettore a proporre cosa farne: resta la seconda scelta, per chi quel file
lo vuole tenere.
"""

from collections import defaultdict

from sqlalchemy.orm import Session

from .. import config, models
from ..istanti import quando
from ..calibre.library import CalibreLibrary


def libri_vivi(nomi_biblioteche) -> dict:
    """nome biblioteca -> set degli id dei libri che esistono, o None.

    `None` vuol dire "non si e' potuto leggere", che e' diverso da `set()`
    ("letta, ed e' vuota"): chi usa questo risultato deve distinguerli, ed e'
    il motivo per cui questa funzione non ripiega su un insieme vuoto.
    """
    fuori = {}
    for nome in nomi_biblioteche:
        try:
            lib = CalibreLibrary(config.library_path(nome))
            fuori[nome] = {b["id"] for b in lib.list_books()}
        except Exception:
            fuori[nome] = None
    return fuori


def righe_senza_libro(db: Session, utente: models.User) -> list:
    """Le righe dei dispositivi DI QUESTO UTENTE il cui libro non c'e' piu'.

    Ogni voce porta con se' il dispositivo, la biblioteca, lo stato della
    riga e il percorso sul lettore. `percorso_di_un_libro_vivo` dice che
    quel percorso e' rivendicato anche da una riga buona: e' il caso in cui
    il file NON va toccato, e serve a dirlo in pagina invece di lasciarlo
    capire.
    """
    dispositivi = db.query(models.Device).filter(
        models.Device.user_id == utente.id).all()
    if not dispositivi:
        return []
    per_id = {d.id: d for d in dispositivi}

    righe = db.query(models.DeviceBook).filter(
        models.DeviceBook.device_id.in_(list(per_id))).all()
    if not righe:
        return []

    vivi = libri_vivi({r.library for r in righe if r.library})

    # I percorsi che una riga BUONA rivendica, dispositivo per dispositivo:
    # lo stesso percorso su due lettori diversi non c'entra niente.
    percorsi_buoni = defaultdict(set)
    for r in righe:
        if r.device_path and vivi.get(r.library) and r.calibre_book_id in vivi[r.library]:
            percorsi_buoni[r.device_id].add(r.device_path)

    fuori = []
    for r in righe:
        elenco = vivi.get(r.library)
        if elenco is None:
            continue  # biblioteca illeggibile: non si afferma niente
        if r.calibre_book_id in elenco:
            continue
        d = per_id[r.device_id]
        fuori.append({
            "id": r.id,
            "device_id": d.id,
            "device_name": d.name,
            # Serve alla pagina per non promettere una cancellazione che non
            # avverra': a un lettore con politica "mai" il server non
            # nomina nemmeno le rimozioni (devices._build_removes).
            "delete_policy": d.delete_policy,
            "library": r.library,
            "calibre_book_id": r.calibre_book_id,
            "format": r.format,
            "status": r.status,
            "device_path": r.device_path,
            "percorso_di_un_libro_vivo": bool(
                r.device_path and r.device_path in percorsi_buoni[r.device_id]),
            "created_at": quando(r.created_at),
            "updated_at": quando(r.updated_at),
        })
    fuori.sort(key=lambda v: (v["device_name"], v["library"], v["calibre_book_id"]))
    return fuori


def dimentica_righe(db: Session, utente: models.User, ids) -> int:
    """Cancella le righe indicate, e solo quelle che sono davvero da buttare.

    Si ricalcola l'elenco invece di fidarsi degli id che arrivano: fra il
    momento in cui la pagina li ha letti e questa chiamata un libro puo'
    essere tornato (un'importazione, una biblioteca ricollegata), e in quel
    caso la riga e' buona e cancellarla farebbe sparire un libro dal lettore
    nel conto del server. Un id che non e' piu' nell'elenco si salta, non
    fallisce: chi ha premuto il pulsante non ha fatto niente di sbagliato.
    """
    voluti = {int(i) for i in (ids or [])}
    if not voluti:
        return 0
    da_buttare = [v["id"] for v in righe_senza_libro(db, utente) if v["id"] in voluti]
    if not da_buttare:
        return 0
    quante = db.query(models.DeviceBook).filter(
        models.DeviceBook.id.in_(da_buttare)).delete(synchronize_session=False)
    db.commit()
    return quante


def fai_cancellare_dal_lettore(db: Session, utente: models.User, ids) -> dict:
    """Mette in coda la rimozione del file sul lettore. Torna cosa ha fatto.

    Non cancella la riga: la porta a `pending_delete`, che e' l'unico modo che
    il server ha di farsi togliere un file da un dispositivo
    (`devices._build_removes` la mette in `removes[]` al prossimo handshake, e
    l'ack che conferma la rimozione cancella la riga). Un libro che non c'e'
    piu' in Calibre non rompe niente la': il titolo nella richiesta diventa
    `None` e il lettore ripiega sul nome del file.

    Le righe il cui percorso e' di un libro vivo si RIFIUTANO, e si dice
    quante: cancellare quel file porterebbe via il libro vivo, e chi ha
    premuto il pulsante non puo' saperlo dall'elenco.
    """
    voluti = {int(i) for i in (ids or [])}
    if not voluti:
        return {"in_coda": 0, "rifiutate": 0, "rifiutate_politica": 0,
                "dimenticabili": []}

    candidate = [v for v in righe_senza_libro(db, utente) if v["id"] in voluti]
    # Due rifiuti, contati separatamente perche' vogliono dire cose diverse a
    # chi legge la pagina: il file e' di un libro vivo (non si cancella mai),
    # oppure il lettore ha la politica "mai" e al server non chiede nulla —
    # `devices._build_removes` per lui torna una lista vuota, quindi mettere
    # la riga in attesa la lascerebbe la' per sempre promettendo una rimozione
    # che non arriva.
    rifiutate = [v for v in candidate if v["percorso_di_un_libro_vivo"]]
    per_politica = [v for v in candidate
                    if not v["percorso_di_un_libro_vivo"]
                    and v.get("delete_policy") == "never"]
    da_togliere = [v["id"] for v in candidate
                   if not v["percorso_di_un_libro_vivo"]
                   and v.get("delete_policy") != "never"]

    if da_togliere:
        db.query(models.DeviceBook).filter(
            models.DeviceBook.id.in_(da_togliere)).update(
                {"status": "pending_delete"}, synchronize_session=False)
        db.commit()

    return {
        "in_coda": len(da_togliere),
        "rifiutate": len(rifiutate),
        "rifiutate_politica": len(per_politica),
        # Gli id rifiutati tornano a chi chiama, cosi' la pagina puo' offrire
        # l'unica cosa che su quelle righe si puo' fare.
        "dimenticabili": [v["id"] for v in rifiutate + per_politica],
    }
