"""
Che cosa cambia in un aggiornamento, detto a chi deve decidere se farlo.

*Paolo, 08/11/2026: «non mi e' chiaro cosa sia cambiato dall'ultima
userpatch».*

**Perche' il testo sta FUORI dai file che descrive.** L'impronta di una
patch e' il modo in cui il dispositivo decide se aggiornare. Un testo dentro
il file, tradotto in due lingue, sarebbe due file con due impronte diverse:
a ogni cambio di lingua il lettore si sentirebbe proporre un aggiornamento
che non cambia niente: il testo che una persona legge e i byte che una
macchina confronta devono poter cambiare separatamente.

**Solo inglese, per il plugin e per le patch.** Per le patch da sempre
(Paolo: «la patch NON ha bisogno di una traduzione, e' e deve essere un
unico file in inglese per sempre e per tutti»); per il plugin dal 24/11/2026,
quando Paolo ha deciso che il plugin KOReader, per ora, parla solo inglese.
Le voci di versione fino alla 0.28.0 hanno anche `it`: resta nel file come
storia, non lo legge piu' nessuno, e le voci nuove hanno solo `en`.

**Nulla e' un errore.** Una versione senza novita' scritte torna `None`, non
solleva niente: una finestra che dice che c'e' un aggiornamento deve
comparire anche quando nessuno ha scritto cosa cambia. Meglio una riga in
meno che un aggiornamento che non si puo' fare.
"""

import json
import os
from typing import Optional

from ..logging_utils import log_message

PERCORSO = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "plugins", "koreader", "novita.json")
)

LINGUA_DEL_PLUGIN = "en"


def _leggi() -> dict:
    """Il file, o un dizionario vuoto se non si legge.

    Si rilegge a ogni chiamata invece di tenerlo in memoria: sono due
    chiamate per aggiornamento, il file e' di qualche kilobyte, e una cache
    vorrebbe dire che modificarlo non basta a cambiare quel che si legge —
    cioe' la trappola che si vuole evitare in un file fatto per essere
    modificato a mano.
    """
    try:
        with open(PERCORSO, encoding="utf-8") as f:
            dati = json.load(f)
    except OSError:
        # Il file che non c'e' e' lo stato normale di una versione senza
        # novita' scritte: nessun rumore.
        return {}
    except ValueError as e:
        # Il file c'e' ma non si legge: e' un file scritto a mano, e un
        # errore di battitura spegnerebbe le novita' di TUTTI gli
        # aggiornamenti senza nessun segno. Questo e' il segno.
        log_message("warning", "tools",
                    f"novita.json exists but is not readable JSON ({e}): every update prompt will show no release notes")
        return {}
    return dati if isinstance(dati, dict) else {}


def per_il_plugin(versione: Optional[str]) -> Optional[str]:
    """Le novita' di UNA versione del plugin. **Solo inglese** dal 24/11/2026,
    come il plugin (Paolo: «per ora il plugin e' solo in inglese»): le voci
    vecchie hanno anche `it`, che resta nel file e non si legge piu'."""
    if not versione:
        return None
    voce = (_leggi().get("plugin") or {}).get(str(versione))
    if not isinstance(voce, dict):
        return None
    testo = voce.get(LINGUA_DEL_PLUGIN)
    return testo or None


def per_la_patch(nome_file: Optional[str]) -> Optional[str]:
    """Le novita' di una patch. **Solo inglese**, per decisione di Paolo:
    vedi la testa di questo file."""
    if not nome_file:
        return None
    testo = (_leggi().get("patch") or {}).get(str(nome_file))
    return testo if isinstance(testo, str) and testo else None
