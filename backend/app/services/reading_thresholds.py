"""
Le soglie delle statistiche di lettura: un posto solo, ricalcolate dai dati.

Decisioni di Paolo del 23/11/2026, dallo studio sul database vero:

- **niente secondi fissi**: sfoglio e pagina-lasciata-aperta si riconoscono
  dalla VELOCITA' (caratteri della pagina / secondi sulla pagina), tarata
  sulla velocita' tipica di chi legge — non su numeri scolpiti nel codice;
- **sfoglio** = velocita' oltre `SKIM_MULTIPLIER` volte quella tipica
  (misurata il 23/11: tipica 18,4 car/s, quindi soglia ~55);
- **tetto della pagina aperta** = larghezza della pagina divisa per la
  velocita' lenta (il 5° percentile), mai sotto `PAGE_TIME_FLOOR_SECONDS`.
  Il minimo fisso protegge le pagine corte (poesie, aperture di capitolo):
  pochi caratteri su un tempo di sguardo normale danno una velocita'
  bassissima che NON e' una pagina abbandonata. 120 secondi e' lo stesso
  tetto che il canale del tempo di KOReader applica da sempre (`max_sec`);
- le soglie **si ricalcolano da sole** a ogni giro di derivazione e col giro
  quotidiano, su una finestra mobile di `WINDOW_DAYS` giorni (tutta la
  storia finche' i dati sono pochi), e si conservano in `app_settings` con
  la data del calcolo — cosi' si leggono da un posto solo e si vede quando
  sono state riviste l'ultima volta.

**Chi le usa**: la derivazione delle sessioni ripulite (passo 3 del piano
del 23/11) e, in sola lettura, il pannello Statistiche che le mostra in
piccolo. Nessun altro posto deve conoscere questi numeri.

**Quando i dati non bastano** (`rows_used` < MIN_ROWS_ABSOLUTE) le velocita'
restano vuote: meglio nessuna pulizia che una pulizia tarata sul rumore.
Il minimo fisso del tetto vale comunque, perche' non dipende dai dati.
"""

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from .. import models
from . import app_settings

THRESHOLDS_KEY = "reading_thresholds"

#: Sfoglio = velocita' oltre questo multiplo della tipica (scelta di Paolo
#: fra 2x, 3x e 5x provate sui dati veri: la 3x taglia lo sfoglio senza
#: mangiarsi le consultazioni rapide ma vere).
SKIM_MULTIPLIER = 3.0
#: Il minimo fisso del tetto, in secondi: lo stesso max_sec del canale del
#: tempo. Una pagina letta davvero non ci rimette mai (la piu' lenta dei
#: dati veri sta sotto), e lo storico resta coerente col canale vecchio.
PAGE_TIME_FLOOR_SECONDS = 120
#: La «velocita' lenta» e' questo percentile della velocita' per pagina.
SLOW_PERCENTILE = 0.05
#: La finestra mobile del calcolo. Si allarga a tutto lo storico quando le
#: righe dentro la finestra sono meno di MIN_ROWS.
WINDOW_DAYS = 90
MIN_ROWS = 50
#: Sotto questa quantita' di righe le velocita' non si calcolano affatto.
MIN_ROWS_ABSOLUTE = 20
#: Le pagine fino a questa durata sono sfoglio per definizione (velocita'
#: dell'ordine delle centinaia di caratteri al secondo, o infinita con
#: durata zero) e NON entrano nel calcolo delle soglie: la velocita' tipica
#: e' quella di chi sta leggendo, non di chi sta cercando una pagina.
SKIM_MIN_DURATION_SECONDS = 2


def _righe_di_lettura(db: Session, da: Optional[datetime]) -> list:
    """Le coppie (larghezza, durata) delle pagine esatte lette davvero."""
    q = (
        db.query(models.LetturaDiPagina.carattere_inizio,
                 models.LetturaDiPagina.carattere_fine,
                 models.LetturaDiPagina.durata)
        .filter(
            models.LetturaDiPagina.genere == models.LetturaDiPagina.PAGINA,
            models.LetturaDiPagina.stato_conversione == "exact",
            models.LetturaDiPagina.carattere_inizio.isnot(None),
            models.LetturaDiPagina.carattere_fine.isnot(None),
            models.LetturaDiPagina.durata > SKIM_MIN_DURATION_SECONDS,
        )
    )
    if da is not None:
        q = q.filter(models.LetturaDiPagina.istante >= da)
    coppie = []
    for inizio, fine, durata in q.all():
        larghezza = (fine or 0) - (inizio or 0)
        if larghezza > 0 and durata > 0:
            coppie.append((larghezza, durata))
    return coppie


def _percentile(valori: list, quota: float) -> float:
    """Il percentile con interpolazione lineare (come numpy, e come il
    notebook del 23/11: cosi' i numeri tornano confrontabili)."""
    ordinati = sorted(valori)
    if not ordinati:
        raise ValueError("no values")
    posizione = quota * (len(ordinati) - 1)
    sotto = int(posizione)
    sopra = min(sotto + 1, len(ordinati) - 1)
    peso = posizione - sotto
    return ordinati[sotto] * (1 - peso) + ordinati[sopra] * peso


def compute(db: Session) -> dict:
    """Calcola le soglie dai dati, senza scrivere niente."""
    da = datetime.utcnow() - timedelta(days=WINDOW_DAYS)
    finestra_giorni: Optional[int] = WINDOW_DAYS
    coppie = _righe_di_lettura(db, da)
    if len(coppie) < MIN_ROWS:
        # Pochi dati recenti: si allarga a tutto lo storico, e lo si dichiara.
        coppie = _righe_di_lettura(db, None)
        finestra_giorni = None

    esito = {
        "typical_speed_cps": None,
        "slow_speed_cps": None,
        "skim_threshold_cps": None,
        "rows_used": len(coppie),
        "window_days": finestra_giorni,
        "computed_at": datetime.utcnow().isoformat(timespec="seconds"),
    }
    if len(coppie) < MIN_ROWS_ABSOLUTE:
        return esito

    caratteri = sum(l for l, _ in coppie)
    secondi = sum(d for _, d in coppie)
    # La tipica e' pesata sui caratteri (totale/totale), non una media di
    # medie: una pagina lunga pesa per quanto testo porta.
    tipica = caratteri / secondi
    lenta = _percentile([l / d for l, d in coppie], SLOW_PERCENTILE)
    esito["typical_speed_cps"] = round(tipica, 2)
    esito["slow_speed_cps"] = round(lenta, 2)
    esito["skim_threshold_cps"] = round(SKIM_MULTIPLIER * tipica, 2)
    return esito


def refresh(db: Session) -> dict:
    """Ricalcola e conserva. Chiamata dal giro quotidiano e prima di ogni
    derivazione: il costo e' una query sulle righe esatte."""
    soglie = compute(db)
    app_settings.set_setting(db, THRESHOLDS_KEY, soglie)
    return soglie


def current(db: Session) -> dict:
    """Le soglie conservate; se non ci sono ancora, le calcola una volta."""
    vuote = {"typical_speed_cps": None, "slow_speed_cps": None,
             "skim_threshold_cps": None, "rows_used": 0,
             "window_days": None, "computed_at": None}
    conservate = app_settings.get_setting(db, THRESHOLDS_KEY, vuote)
    if conservate.get("computed_at") is None:
        return refresh(db)
    return conservate
