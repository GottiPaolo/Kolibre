"""
Le userpatch di KOReader che questo server sa consegnare, e come stanno sui
dispositivi.

**Cos'e' una userpatch.** Un file Lua che KOReader esegue a ogni avvio,
preso dalla sua cartella `patches/`. Serve a cambiare il suo comportamento
dall'esterno — e' il meccanismo con cui si aggiunge una misura che il
programma non fa, senza ricompilarlo. Le nostre stanno nel repository in
`plugins/koreader/patches/` e si installano dal plugin, senza cavo (vedi
api/tools.py per gli endpoint e main.lua per il menu').

**Perche' questo modulo esiste** invece di stare dentro api/tools.py, dov'era
nato: la stessa informazione serve in due posti che non si devono importare a
vicenda — gli endpoint che consegnano le patch, e la pagina dei dispositivi
che dice se su quel lettore sono installate.
"""

import hashlib
import os
import re

# repo_root/plugins/koreader/patches — tre livelli sopra questo file
# (backend/app/services -> backend/app -> backend -> radice).
CARTELLA = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "plugins", "koreader", "patches")
)

# KOReader esegue solo i file il cui nome comincia con la cifra della
# priorita', poi altre cifre, poi un trattino (vedi frontend/userpatch.lua:
# `entry:match("^" .. priority .. "%d*%-")`). Un file che non rispetta quel
# nome non verrebbe mai eseguito, e offrirlo sarebbe offrire qualcosa che non
# funziona: quindi non si elenca.
_NOME_DI_PATCH = re.compile(r"^(\d)\d*-[A-Za-z0-9._-]+\.lua$")

# La descrizione di una patch sta DENTRO la patch, in tre righe di commento
# dichiarate. L'alternativa — un file di metadati accanto — si scollerebbe dal
# codice al primo rinomino, e un elenco che descrive male il codice che
# installa e' peggio di un elenco senza descrizioni.
_ETICHETTA = re.compile(r"^--\s*@kolibre-(nome|descrizione|versione)\s*:\s*(.+?)\s*$")


def patch(nome_file: str):
    """Una patch, come la vede il dispositivo: cos'e', quanto pesa, e la sua
    impronta per accorgersi di un download troncato."""
    corrispondenza = _NOME_DI_PATCH.match(nome_file)
    if not corrispondenza:
        return None
    percorso = os.path.join(CARTELLA, nome_file)
    if not os.path.isfile(percorso):
        return None
    with open(percorso, "rb") as f:
        dati = f.read()
    etichette = {}
    for riga in dati.decode("utf-8", "replace").splitlines():
        trovata = _ETICHETTA.match(riga.strip())
        if trovata:
            etichette[trovata.group(1)] = trovata.group(2)
    return {
        "file": nome_file,
        # Senza etichetta si ripiega sul nome del file: meglio una riga brutta
        # che una voce di menu' vuota.
        "nome": etichette.get("nome") or nome_file,
        "descrizione": etichette.get("descrizione") or "",
        "versione": etichette.get("versione") or "",
        "priorita": int(corrispondenza.group(1)),
        "dimensione": len(dati),
        "sha256": hashlib.sha256(dati).hexdigest(),
    }


def elenco() -> list:
    if not os.path.isdir(CARTELLA):
        return []
    trovate = []
    for nome_file in sorted(os.listdir(CARTELLA)):
        p = patch(nome_file)
        if p:
            trovate.append(p)
    return trovate


def stato_sul_dispositivo(installate) -> list:
    """
    Per ogni patch che il server ha, com'e' su QUEL dispositivo.

    `installate` e' quello che il plugin manda nell'handshake: una lista di
    `{file, sha256}`. Si confronta l'impronta e non la data ne' la versione
    dichiarata, per un motivo pratico: una patch modificata senza cambiarle
    nome o numero di versione — cioe' il caso normale mentre la si sviluppa —
    deve risultare **da aggiornare**, e solo l'impronta lo dice.

    Tre stati, e nessuno e' «forse»:
    - `aggiornata`: c'e', ed e' identica a quella del server;
    - `da_aggiornare`: c'e', ma e' un'altra versione;
    - `assente`: non c'e'.

    `None` (non la lista vuota) significa **«il dispositivo non lo ha
    detto»**: un plugin piu' vecchio non manda il campo, e una lista vuota
    direbbe «nessuna patch installata», che e' un'affermazione diversa e
    potrebbe essere falsa. In quel caso si torna una lista vuota e chi la
    mostra dice «non riportato», come fa gia' per lo spazio su disco.
    """
    if installate is None:
        return []
    per_file = {}
    for voce in installate:
        if isinstance(voce, dict) and voce.get("file"):
            per_file[voce["file"]] = voce.get("sha256")
    fuori = []
    for p in elenco():
        impronta = per_file.get(p["file"])
        if impronta is None:
            stato = "assente"
        elif impronta == p["sha256"]:
            stato = "aggiornata"
        else:
            stato = "da_aggiornare"
        fuori.append({
            "file": p["file"],
            "nome": p["nome"],
            "descrizione": p["descrizione"],
            "versione": p["versione"],
            "stato": stato,
        })
    return fuori
