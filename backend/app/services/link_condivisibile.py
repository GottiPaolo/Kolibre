"""
Gli indirizzi da incollare in un appunto: biblioteca, libro, nota, autore.

**Il contesto, da zero.** Un link che finisce in un file di Obsidian ci resta
per anni, e deve aprirsi anche dopo che la biblioteca e' stata reimportata, il
libro rinominato e le note riaccoppiate. Gli indirizzi di oggi non
sopravvivono a niente di tutto questo: `/libri/1033` usa il numero di riga di
Calibre (reimporta e cambia) e **non dice nemmeno in quale biblioteca** sta
quel 1033 — la biblioteca viaggia nello stato interno del browser, quindi
quell'indirizzo aperto a freddo puo' mostrare il libro sbagliato.

La forma, scelta da Paolo il 05/11/2026:

    /k/libreria
    /k/libreria/i-miserabili-39e1f730
    /k/libreria/i-miserabili-39e1f730/n/n7k2p4m9qt
    /k/a/victor-hugo

**Tre decisioni dentro questa forma**, e sono quelle che la fanno durare:

1. **Lo slug e' decorazione.** `i-miserabili` serve a chi legge l'appunto, non
   a chi risolve: a risolvere basta `39e1f730`. Quindi rinominare un libro non
   rompe nessun link — lo slug vecchio continua a funzionare, e chi genera il
   link la volta dopo ne scrive uno nuovo.
2. **L'identita' del libro e' l'`uuid` di Calibre**, non il suo numero di
   riga. Esiste gia' in `metadata.db` (colonna `books.uuid`), lo scrive
   Calibre, e sopravvive alla rinumerazione: verificato sulla biblioteca di
   Paolo, 1220 libri e 1220 uuid distinti, zero vuoti. Se ne usano i primi
   otto caratteri, e **chi genera controlla che siano univoci** nella
   biblioteca: se due libri cominciassero uguali, si allunga (vedi
   `caratteri_che_bastano`).
3. **La biblioteca nel percorso non serve a risolvere.** L'uuid di Calibre e'
   unico di per se', quindi la biblioteca e' un suggerimento e un pezzo di
   gerarchia — serve a dire a chi legge dove sta quel libro, e a poter
   **tagliare** il link per salire: nota → libro → biblioteca. Se un giorno i
   due non vanno d'accordo (un libro spostato in un'altra biblioteca) vince il
   libro.

**Un limite noto, scritto qui perche' non si scopra da solo.** `a` e' il
primo pezzo riservato agli autori, quindi una biblioteca la cui cartella si
chiamasse *esattamente* `a` non sarebbe raggiungibile da questi indirizzi (i
suoi libri verrebbero letti come nomi di autore). Non si e' aggiunto un pezzo
in piu' per difendersene — `/k/b/libreria/…` — perche' avrebbe allungato ogni
link di tutti per un caso che non si e' mai visto. Se capita, si vede subito:
il link non apre niente.

Questo modulo **non interroga nessun database**: compone e legge stringhe, e
niente altro. Chi risolve davvero sta in `api/link.py`.
"""

import re
import unicodedata
from typing import Optional
from urllib.parse import quote, unquote

PREFISSO = "/k"
#: Il pezzo riservato agli autori (vedi il limite noto in testa al modulo).
PEZZO_AUTORI = "a"
#: Il pezzo che introduce una nota dentro un libro.
PEZZO_NOTE = "n"
#: Quanti caratteri dell'uuid di Calibre si usano quando bastano.
CARATTERI_MINIMI = 8

#: **Tutti** i motivi per cui un indirizzo non si risolve. E' un elenco
#: chiuso, e sta qui perche' lo leggono in tre: `api/link.py` che li
#: risponde, il browser che per ognuno ha una frase da mostrare
#: (`src/pages/ApriIndirizzo.tsx`), e due prove che controllano che i tre
#: elenchi combacino.
#:
#: **Perche' serve un elenco e non bastano le stringhe sparse.** Un motivo
#: aggiunto qui e non tradotto la' non da' nessun errore: la pagina mostra il
#: NOME della chiave di traduzione — `link.broken.pippo` — a chi ha appena
#: cliccato un link che non funziona. Un difetto che si vede solo nel momento
#: peggiore.
MOTIVI = (
    "nota_sparita",
    "libro_sparito",
    "libro_ambiguo",
    "biblioteca_sparita",
    "biblioteca_ambigua",
    "indirizzo_senza_libro",
)

_NON_PAROLE = re.compile(r"[^a-z0-9]+")
_PEZZO_CORTO = re.compile(r"[0-9a-f]{4,}")


def slug(testo: Optional[str]) -> str:
    """
    Il testo ridotto a quello che si puo' scrivere in un indirizzo.

    Gli accenti si **srotolano** invece di sparire (`à` diventa `a`, non
    niente): `Cronaca familiare` e `Cronaca famigliare` devono restare
    distinguibili, e un titolo italiano senza le sue vocali accentate
    diventerebbe illeggibile. Tutto il resto — spazi, punteggiatura, virgolette
    tipografiche — diventa un trattino, e i trattini non si accumulano.
    """
    if not testo:
        return ""
    senza_accenti = "".join(
        c for c in unicodedata.normalize("NFKD", testo)
        if not unicodedata.combining(c)
    )
    return _NON_PAROLE.sub("-", senza_accenti.lower()).strip("-")


def caratteri_che_bastano(uuid_del_libro: str, altri_uuid, minimo: int = CARATTERI_MINIMI) -> int:
    """
    Quanti caratteri dell'uuid servono perche' nessun altro libro cominci
    uguale.

    Otto bastano quasi sempre — con milleduecento libri la probabilita' che due
    uuid condividano i primi otto caratteri e' intorno a due su centomila — ma
    *quasi sempre* non e' una garanzia, e un link ambiguo e' un link che apre
    il libro sbagliato. Quindi chi genera guarda, invece di fidarsi.
    """
    if not uuid_del_libro:
        return minimo
    altri = [u for u in (altri_uuid or []) if u and u != uuid_del_libro]
    for quanti in range(minimo, len(uuid_del_libro) + 1):
        inizio = uuid_del_libro[:quanti]
        if not any(u.startswith(inizio) for u in altri):
            return quanti
    return len(uuid_del_libro)


def pezzo_del_libro(titolo: Optional[str], uuid_del_libro: str, caratteri: int = CARATTERI_MINIMI) -> str:
    """`"i-miserabili-39e1f730"`. Senza titolo resta il solo pezzo corto."""
    corto = (uuid_del_libro or "")[:caratteri]
    s = slug(titolo)
    return f"{s}-{corto}" if s else corto


def pezzo_della_biblioteca(cartella: str) -> str:
    """
    Il nome della cartella **cosi' com'e'**, non ridotto a slug.

    **Perche' non lo slug**, che sarebbe piu' bello da leggere: il 05/11/2026
    sul server di Paolo c'erano due cartelle che differivano solo per la
    maiuscola, `libreria` e `Libreria`, e lo slug le appiattiva sulla stessa
    parola — i due indirizzi venivano identici, e quello della seconda apriva
    la prima. Quel caso li' era un residuo e se n'e' andato (una biblioteca
    cancellata a luglio che aveva lasciato la cartella), ma il nome di una
    cartella su Linux **distingue le maiuscole**, quindi la coppia si puo'
    rifare in qualunque momento. La misura resta il motivo della scelta anche
    se il caso che l'ha mostrata non c'e' piu'.

    Il nome di una cartella e' gia' quasi sempre scrivibile in un indirizzo
    (`libreria`, `anarcobiblioteca`, `ldb`), quindi il prezzo di questa scelta
    si paga solo su un nome con spazi o accenti, dove compare un `%20`. Un
    link leggibile che apre la biblioteca sbagliata non e' un buon affare.
    """
    return quote(cartella or "", safe="")


def percorso_della_biblioteca(cartella: str) -> str:
    return f"{PREFISSO}/{pezzo_della_biblioteca(cartella)}"


def percorso_del_libro(cartella: str, titolo: Optional[str], uuid_del_libro: str,
                       caratteri: int = CARATTERI_MINIMI) -> str:
    return f"{percorso_della_biblioteca(cartella)}/{pezzo_del_libro(titolo, uuid_del_libro, caratteri)}"


def percorso_della_nota(cartella: str, titolo: Optional[str], uuid_del_libro: str,
                        id_durevole: str, caratteri: int = CARATTERI_MINIMI) -> str:
    libro = percorso_del_libro(cartella, titolo, uuid_del_libro, caratteri)
    return f"{libro}/{PEZZO_NOTE}/{id_durevole}"


def percorso_dell_autore(nome: Optional[str]) -> str:
    return f"{PREFISSO}/{PEZZO_AUTORI}/{slug(nome)}"


# ── L'indirizzo da mettere davanti al percorso ──────────────────────────
#
# **Perche' non e' scritto da nessuna parte nel codice.** Un percorso
# (`/k/libreria/...`) e' uguale su ogni impianto; l'indirizzo davanti no:
# dipende dalla macchina su cui il server gira, e il server non puo'
# inventarselo. La richiesta, 05/11/2026: *«L'indirizzo pubblico deve essere
# preso dal server; se e' un indirizzo di rete locale va bene che sia cosi',
# basta che si adatti alla macchina su cui gira»*.
#
# Si ricava da tre cose, in ordine di autorita':
#
# 1. **`PUBLIC_BASE_URL`**, se chi ha installato l'ha scritto. E' l'unico modo
#    di avere un indirizzo giusto quando ce n'e' uno vero (un dominio, un
#    nome interno) che il server da dentro non puo' conoscere.
# 2. **Le intestazioni di inoltro** (`X-Forwarded-Host`/`-Proto`), se c'e' un
#    proxy davanti. In quel caso **la porta non si tocca**: chi passa da un
#    proxy arriva sulla stessa origine per tutto, e aggiungerci la porta del
#    frontend romperebbe l'indirizzo invece di completarlo.
# 3. **L'indirizzo con cui la richiesta e' arrivata**, cambiando la porta con
#    quella del frontend. E' il caso normale di casa: il plugin o il browser
#    parlano col backend su 8089 e l'interfaccia sta su 5566, e il link deve
#    portare all'interfaccia.
#
# **Nota su chi decide.** Nel caso 3 il nome della macchina arriva
# dall'intestazione `Host`, che la scrive il client. Va bene qui, e va detto
# perche' non sembri una dimenticanza: questo indirizzo serve a comporre un
# link da incollare, non a decidere se qualcuno puo' entrare — nessun
# controllo di permessi lo guarda. Un client che mente ottiene un link che
# non si apre, e l'unico danneggiato e' lui.

#: Le porte che in un indirizzo non si scrivono.
PORTE_SOTTINTESE = {"http": "80", "https": "443"}


def _nome_senza_porta(host: str) -> str:
    """Il nome della macchina, buttando la porta. Tiene conto di IPv6, dove
    il nome e' fra parentesi quadre e contiene i due punti suo
    (`[::1]:8089`): dividere sul primo `:` lo spezzerebbe a meta'."""
    host = (host or "").strip()
    if host.startswith("["):
        chiusa = host.find("]")
        return host[: chiusa + 1] if chiusa != -1 else host
    return host.split(":", 1)[0]


def indirizzo_base(host: Optional[str], schema: str, porta_del_frontend: Optional[str],
                   host_inoltrato: Optional[str] = None,
                   schema_inoltrato: Optional[str] = None,
                   scritto_a_mano: Optional[str] = None) -> Optional[str]:
    """
    L'indirizzo da mettere davanti a un percorso, senza la barra finale.
    `None` quando non si ricava: meglio dare il solo percorso che un indirizzo
    inventato.
    """
    if scritto_a_mano and scritto_a_mano.strip():
        return scritto_a_mano.strip().rstrip("/")
    if host_inoltrato and host_inoltrato.strip():
        # Puo' essere un elenco separato da virgole (piu' proxy in fila): il
        # primo e' quello piu' vicino a chi guarda, cioe' l'unico che lui sa
        # digitare.
        primo = host_inoltrato.split(",")[0].strip()
        proto = (schema_inoltrato or schema or "http").split(",")[0].strip()
        return f"{proto}://{primo}".rstrip("/")
    if not host or not host.strip():
        return None
    schema = (schema or "http").strip()
    nome = _nome_senza_porta(host)
    if not nome:
        return None
    porta = (porta_del_frontend or "").strip()
    if not porta or porta == PORTE_SOTTINTESE.get(schema):
        return f"{schema}://{nome}"
    return f"{schema}://{nome}:{porta}"


def _pezzo_in_due(segmento: str) -> dict:
    """Divide `"i-miserabili-39e1f730"` in decorazione e identita'.

    Si guarda **l'ultimo** trattino, perche' il titolo ne contiene quanti
    vuole. E se l'ultimo pezzo non ha la forma di un uuid accorciato, allora
    quel segmento non porta nessuna identita': si dice, invece di indovinare.
    """
    if "-" in segmento:
        testo, forse = segmento.rsplit("-", 1)
    else:
        testo, forse = "", segmento
    if _PEZZO_CORTO.fullmatch(forse):
        return {"slug": testo, "corto": forse}
    return {"slug": segmento, "corto": None}


def leggi(percorso: Optional[str]) -> Optional[dict]:
    """
    Che cosa indica un indirizzo. `None` se non e' uno dei nostri.

    Torna `tipo` piu' i pezzi: `biblioteca`, `libro` (`slug` e `corto`),
    `nota`, `autore`. **Non controlla che esistano**: questo modulo legge
    stringhe, chi guarda nel database e' `api/link.py`.
    """
    if not percorso:
        return None
    pulito = percorso.split("#", 1)[0].split("?", 1)[0].strip()
    if not pulito:
        return None
    if not pulito.startswith("/"):
        pulito = "/" + pulito
    if pulito != PREFISSO and not pulito.startswith(PREFISSO + "/"):
        return None
    pezzi = [p for p in pulito[len(PREFISSO):].split("/") if p]
    if not pezzi:
        return None
    if pezzi[0] == PEZZO_AUTORI:
        # `/k/a` da solo non e' l'elenco degli autori: e' un indirizzo
        # incompleto, e vale dirlo invece di aprire una pagina a caso.
        return {"tipo": "autore", "autore": pezzi[1]} if len(pezzi) == 2 else None
    # La biblioteca si scioglie dalla forma percentuale: nell'indirizzo ci
    # finisce il nome vero della cartella, che puo' avere spazi o accenti.
    if len(pezzi) == 1:
        return {"tipo": "biblioteca", "biblioteca": unquote(pezzi[0])}
    if len(pezzi) == 2:
        return {"tipo": "libro", "biblioteca": unquote(pezzi[0]), "libro": _pezzo_in_due(pezzi[1])}
    if len(pezzi) == 4 and pezzi[2] == PEZZO_NOTE:
        return {"tipo": "nota", "biblioteca": unquote(pezzi[0]),
                "libro": _pezzo_in_due(pezzi[1]), "nota": pezzi[3]}
    return None


def genitore(percorso: Optional[str]) -> Optional[str]:
    """L'indirizzo di cui questo e' un pezzo: nota → libro → biblioteca.

    E' la ragione per cui la forma e' gerarchica, e quindi va provata: se
    tagliare un link non da' il suo genitore, la gerarchia e' solo un
    indirizzo piu' lungo.
    """
    letto = leggi(percorso)
    if not letto:
        return None
    pezzo_bib = pezzo_della_biblioteca(letto["biblioteca"])
    if letto["tipo"] == "nota":
        return f"{PREFISSO}/{pezzo_bib}/{percorso.rstrip('/').split('/')[-3]}"
    if letto["tipo"] == "libro":
        return f"{PREFISSO}/{pezzo_bib}"
    return None
