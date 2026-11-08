"""
Che cosa cambia in un aggiornamento, detto a chi deve decidere se farlo.

*Paolo, 08/11/2026: «non mi e' chiaro cosa sia cambiato dall'ultima
userpatch».*

**Perche' il testo sta FUORI dai file che descrive.** L'impronta di una
patch e' il modo in cui il dispositivo decide se aggiornare. Un testo dentro
il file, tradotto in due lingue, sarebbe due file con due impronte diverse:
a ogni cambio di lingua il lettore si sentirebbe proporre un aggiornamento
che non cambia niente. E' lo stesso principio per cui la lingua del plugin
si cuce al momento dello scarico e il manifest e' per lingua (07/11): il
testo che una persona legge e i byte che una macchina confronta devono poter
cambiare separatamente.

**Due lingue per il plugin, solo inglese per le patch.** Deciso da Paolo:
«la patch NON ha bisogno di una traduzione, e' e deve essere un unico file
in inglese per sempre e per tutti, tanto non e' un menu' con cui qualcuno
deve interagire e rimane silenziosa in background».

**Nulla e' un errore.** Una versione senza novita' scritte torna `None`, non
solleva niente: una finestra che dice che c'e' un aggiornamento deve
comparire anche quando nessuno ha scritto cosa cambia. Meglio una riga in
meno che un aggiornamento che non si puo' fare.
"""

import json
import os
from typing import Optional

PERCORSO = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "plugins", "koreader", "novita.json")
)

LINGUE = ("it", "en")
LINGUA_DI_RIPIEGO = "en"


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
    except (OSError, ValueError):
        return {}
    return dati if isinstance(dati, dict) else {}


def per_il_plugin(versione: Optional[str], lingua: Optional[str] = None) -> Optional[str]:
    """Le novita' di UNA versione del plugin, nella lingua chiesta."""
    if not versione:
        return None
    voce = (_leggi().get("plugin") or {}).get(str(versione))
    if not isinstance(voce, dict):
        return None
    codice = lingua if lingua in LINGUE else LINGUA_DI_RIPIEGO
    testo = voce.get(codice) or voce.get(LINGUA_DI_RIPIEGO)
    return testo or None


def per_la_patch(nome_file: Optional[str]) -> Optional[str]:
    """Le novita' di una patch. **Solo inglese**, per decisione di Paolo:
    vedi la testa di questo file."""
    if not nome_file:
        return None
    testo = (_leggi().get("patch") or {}).get(str(nome_file))
    return testo if isinstance(testo, str) and testo else None
