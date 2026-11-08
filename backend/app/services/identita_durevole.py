"""
Il nome di una nota che non cambia mai.

**Il contesto, da zero.** Ogni evidenziazione ha una colonna `id`: 1, 2, 3.
Quel numero e' il nome con cui tutti gli altri la chiamano — il marcatore
dentro un file di Obsidian, un link in un appunto, le chiamate dell'API. Ma
non e' una proprieta' della nota: e' il **numero di riga della tabella**, e lo
assegna SQLite quando la riga nasce. Descrive dove sta, non cos'e'.

E si muove in tre modi, tutti verificati nel codice il 05/11/2026:

1. **promozione di un'orfana** (`_migrate_orphan_highlights_to_book`): la riga
   orfana viene cancellata e ne nasce una nuova. Stesso brano, numero nuovo.
2. **fusione di due note** (`_migrate_device_highlights_to_new_book`): se al
   libro nuovo quella posizione c'e' gia', le due diventano una e una delle
   due righe viene cancellata. Chi aveva scritto quel numero punta al vuoto.
3. **il numero viene riusato.** `DELETE /annotations/{id}?permanent=true`
   cancella la riga per davvero, e la colonna e' `INTEGER PRIMARY KEY` senza
   `AUTOINCREMENT` — cioe' il rowid di SQLite, che **riassegna i numeri
   liberi**. E' il caso cattivo perche' e' silenzioso: il marcatore
   corrisponde ancora a qualcosa, solo che quel qualcosa e' un altro brano.

`id_durevole` e' invece un nome che appartiene alla nota: nasce con lei, non
cambia, non si riusa, e **viaggia con lei** — nella promozione si copia, in
una fusione si registra un rimando (`RimandoDiNota`) perche' un link scritto
in un appunto due anni prima continui ad aprirsi.

**Dieci caratteri, non un uuid.** Un uuid sono trentasei caratteri, e questo
nome finisce dentro un link che una persona legge e a volte ripara a mano.
L'alfabeto non ha caratteri ambigui — niente `0`/`o`, niente `1`/`l`/`i` — e
sta in `models.ALFABETO_DUREVOLE`, accanto alla colonna che lo usa.
"""

from typing import Optional

from sqlalchemy.orm import Session

from .. import models

#: Il sorteggio sta accanto alla colonna (`models.sorteggia_id_durevole`),
#: perche' e' il suo `default=`: il nome lo mette il database e nessun punto
#: di creazione puo' dimenticarsene. Qui ci sono le cose che hanno bisogno di
#: una sessione — e il controllo che il nome sia libero.


def nuovo(db: Session) -> str:
    """
    Un nome libero. Ricontrolla sul database invece di fidarsi dei numeri
    grandi — e guarda **entrambe** le tabelle, perche' un'orfana diventa una
    nota vera portandosi dietro il suo nome, e due nomi uguali nelle due
    tabelle diventerebbero un doppione nel momento della promozione.
    """
    for _ in range(50):
        candidato = models.sorteggia_id_durevole()
        if db.query(models.Highlight).filter(models.Highlight.id_durevole == candidato).first():
            continue
        if db.query(models.OrphanHighlight).filter(
            models.OrphanHighlight.id_durevole == candidato
        ).first():
            continue
        return candidato
    # Cinquanta sorteggi andati tutti male non e' sfortuna, e' un difetto:
    # meglio fermarsi che restituire un nome che qualcuno usa.
    raise RuntimeError("Could not find a free durable id: check the table.")


def assegna_mancanti(db: Session) -> int:
    """
    Da' un nome alle righe che non ce l'hanno. Serve una volta, sulla
    migrazione di un database che esisteva prima della colonna, e non fa
    niente tutte le altre volte.

    Non si puo' fare con un `DEFAULT` nell'`ALTER TABLE`: un valore
    predefinito e' lo stesso per tutte le righe, e qui ogni riga ne vuole uno
    suo.
    """
    quante = 0
    for tabella in (models.Highlight, models.OrphanHighlight):
        for riga in db.query(tabella).filter(tabella.id_durevole.is_(None)).all():
            riga.id_durevole = nuovo(db)
            # Il flush serve a ogni giro: `nuovo()` interroga il database per
            # sapere quali nomi sono presi, e senza flush i nomi assegnati in
            # questo stesso ciclo non si vedrebbero ancora.
            db.flush()
            quante += 1
    if quante:
        db.commit()
    return quante


def risolvi(db: Session, id_durevole: str) -> Optional[models.Highlight]:
    """
    La nota che quel nome indica **adesso**, seguendo i rimandi.

    Un rimando nasce quando due note diventano una: il nome della morta
    continua a significare qualcosa, e significa la sopravvissuta. Si segue a
    catena (una nota fusa due volte) con un tetto, perche' un anello
    chiuso — che non dovrebbe esistere — non deve diventare un giro infinito
    dentro una richiesta web.
    """
    visti = set()
    nome = id_durevole
    for _ in range(10):
        if not nome or nome in visti:
            return None
        visti.add(nome)
        nota = db.query(models.Highlight).filter(
            models.Highlight.id_durevole == nome
        ).first()
        if nota:
            return nota
        rimando = db.query(models.RimandoDiNota).filter(
            models.RimandoDiNota.vecchio == nome
        ).first()
        if not rimando:
            return None
        nome = rimando.nuovo
    return None


def registra_rimando(db: Session, vecchio: str, nuovo_nome: str) -> None:
    """Da adesso `vecchio` significa `nuovo_nome`. Idempotente: registrarlo
    due volte non e' un errore, e un rimando di un nome su se stesso non si
    scrive (sarebbe l'anello che `risolvi` deve poi scansare)."""
    if not vecchio or not nuovo_nome or vecchio == nuovo_nome:
        return
    gia = db.query(models.RimandoDiNota).filter(
        models.RimandoDiNota.vecchio == vecchio
    ).first()
    if gia:
        gia.nuovo = nuovo_nome
        return
    db.add(models.RimandoDiNota(vecchio=vecchio, nuovo=nuovo_nome))
