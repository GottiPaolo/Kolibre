"""
Un invito di accoppiamento fatto nascere **dal terminale del server**.

    docker compose exec backend python3 -m backend.app.invita
    docker compose exec backend python3 -m backend.app.invita --nome "il portatile"
    docker compose exec backend python3 -m backend.app.invita --utente paolo --minuti 30

**Da zero: a che cosa serve, e perche' non basta il sito.** Un invito di
accoppiamento e' un codice usa e getta che un programma — il client nativo di
Kolibre, uno script — scambia col server per avere una credenziale sua, senza
che nessuno gli consegni la password dell'account. Normalmente lo si crea dal
sito, in Dispositivi ▸ «Collega un client». Questo comando fa la stessa cosa
da una riga di comando, e l'ha chiesto Paolo il 17/11/2026: *«il collegamento
di nuovi device dovrebbe poter essere effettuato anche senza frontend»*.

Non e' un capriccio. Un server appena installato, o un server la cui
interfaccia web non parte, o un server che si amministra da `ssh` e basta,
resta collegabile. **E' la stessa cosa**, non una seconda versione: il lavoro
lo fa `api.accoppiamento.crea_invito`, lo stesso codice che chiama la rotta
del sito, con le stesse regole — quindici minuti, un codice che vale una
volta, l'impronta in database e non il codice.

────────────────────────────────────────────────────────────────────────────
CHI PUO' ESEGUIRE QUESTO COMANDO
────────────────────────────────────────────────────────────────────────────

Chi ha la riga di comando del server. Non c'e' nessun controllo in piu', ed
e' giusto che non ci sia: chi puo' fare `docker exec` sul container puo' anche
leggere il database, cioe' **puo' gia' tutto**. Un controllo qui non
aggiungerebbe una difesa, aggiungerebbe l'illusione di una difesa.

**Quello che il comando non fa** e' stampare segreti che non siano il codice:
non l'indirizzo del database, non il token che nascera' (quello non esiste
ancora: nasce al riscatto, dentro la risposta al programma), non le password
di nessuno. Il codice si stampa, perche' il codice e' il motivo del comando;
chi ha quel terminale lo vedrebbe comunque.

────────────────────────────────────────────────────────────────────────────
A NOME DI CHI
────────────────────────────────────────────────────────────────────────────

Un invito dice **a nome di quale account parlera' il programma**. Se sul
server c'e' un solo account, e' quello e non si chiede niente. Se ce ne sono
piu' di uno, il comando **si ferma** e vuole `--utente`: scegliere da se'
vorrebbe dire consegnare la biblioteca di una persona al programma di
un'altra, che e' il tipo di errore che non si vede subito e non si disfa.
"""

import argparse
import os
import sys
from datetime import timedelta


def _prepara_i_percorsi() -> None:
    """
    Fa in modo che `import backend.app...` funzioni anche lanciando il file
    per nome.

    Dentro il container si lancia come modulo (`python3 -m backend.app.invita`
    da `/app`) e questo non serve. Ma qualcuno lo lancera' per percorso —
    `python3 backend/app/invita.py` — e in quel caso Python non ha nel suo
    cammino la radice del progetto. Due righe per non far sembrare rotto un
    comando che funziona.
    """
    qui = os.path.dirname(os.path.abspath(__file__))
    radice = os.path.dirname(os.path.dirname(qui))
    if radice not in sys.path:
        sys.path.insert(0, radice)


if __package__ in (None, ""):
    _prepara_i_percorsi()
    from backend.app import database, models           # noqa: E402
    from backend.app.api import accoppiamento          # noqa: E402
else:
    from . import database, models
    from .api import accoppiamento


def _scegli_lutente(db, chiesto: str | None):
    """L'account a nome del quale nascera' il token, o un errore chiaro."""
    if chiesto:
        utente = db.query(models.User).filter(models.User.username == chiesto).first()
        if not utente:
            raise SystemExit(f"Non c'e' nessun account di nome «{chiesto}».")
        return utente

    utenti = db.query(models.User).order_by(models.User.id).all()
    if not utenti:
        raise SystemExit(
            "Su questo server non c'e' ancora nessun account: un invito non "
            "saprebbe a nome di chi parlare.\nCreane uno dal sito, o fai "
            "partire il server una prima volta con ADMIN_USERNAME e "
            "ADMIN_PASSWORD."
        )
    if len(utenti) > 1:
        nomi = ", ".join(u.username for u in utenti)
        raise SystemExit(
            "Su questo server ci sono piu' account, quindi va detto a nome di "
            f"chi:\n    --utente <nome>\nFra questi: {nomi}"
        )
    return utenti[0]


def main(argv=None) -> int:
    pezzi = argparse.ArgumentParser(
        prog="python3 -m backend.app.invita",
        description="Crea un codice di accoppiamento per un programma "
                    "(il client nativo di Kolibre, uno script).",
    )
    pezzi.add_argument(
        "--nome", default=None,
        help="Come chiamare questo collegamento: «il portatile», «lo script "
             "dei backup». E' il nome che il token avra' nell'elenco dei "
             "token dell'account, cioe' quello che si legge il giorno in cui "
             "si decide se spegnerlo.",
    )
    pezzi.add_argument(
        "--utente", default=None,
        help="A nome di quale account. Si puo' omettere solo se sul server "
             "c'e' un account solo.",
    )
    pezzi.add_argument(
        "--minuti", type=int, default=None,
        help=f"Quanto deve vivere il codice. Per difetto "
             f"{int(accoppiamento.DURATA.total_seconds() // 60)}; al massimo "
             f"{int(accoppiamento.DURATA_MASSIMA.total_seconds() // 60)}.",
    )
    scelte = pezzi.parse_args(argv)

    # La tabella, se il server non e' ancora mai partito con questa versione.
    # `checkfirst` e **solo questa tabella**: non e' il posto da cui si crea un
    # database, e un comando che si mette a fabbricare tabelle che non gli
    # appartengono e' un comando di cui poi non si sa piu' cosa ha fatto.
    models.InvitoDiAccoppiamento.__table__.create(
        bind=database.engine, checkfirst=True,
    )

    db = database.SessionLocal()
    try:
        utente = _scegli_lutente(db, scelte.utente)
        durata = (timedelta(minutes=scelte.minuti) if scelte.minuti
                  else accoppiamento.DURATA)
        riga, codice = accoppiamento.crea_invito(
            db, utente, nome=scelte.nome, durata=durata, origine="terminal",
        )
    finally:
        db.close()

    minuti = max(1, int((riga.scade_il - riga.creato_il).total_seconds() // 60))
    print()
    print(f"    CODICE:  {accoppiamento.con_i_gruppi(codice)}")
    print()
    print(f"    vale per l'account «{utente.username}»")
    if riga.nome:
        print(f"    nome del collegamento: {riga.nome}")
    print(f"    scade fra {minuti} minuti "
          f"({riga.scade_il.strftime('%Y-%m-%d %H:%M')} UTC)")
    print()
    print("    Nel programma: l'indirizzo di questo server e questo codice.")
    print("    Si usa UNA volta sola, e questa e' la sola volta in cui si")
    print("    vede: il server ne conserva solo l'impronta.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
