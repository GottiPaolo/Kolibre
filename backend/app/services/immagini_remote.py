"""Scaricare un'immagine da un indirizzo dato dall'utente, senza aprire una
finestra sulla rete di casa.

Vive qui e non dentro un modulo di API perche' serve a due posti che non si
conoscono: la foto di un autore (`api/authors.py`) e la copertina di un libro
presa dai metadati online (`api/books.py`). Finche' e' stato un solo
chiamante e' rimasto li'; quando il secondo e' arrivato ha fatto la sua
richiesta HTTP per conto proprio, senza nessuno dei controlli, ed e' per
questo che adesso sta in un posto solo.
"""

import io
import ipaddress
import os
import socket
from urllib.parse import urljoin, urlparse

import httpx
from PIL import Image
from fastapi import HTTPException


# ── Scaricare un'immagine da un indirizzo dato da chi chiama ─────────────
#
# E' il SERVER a fare la richiesta, quindi un indirizzo qualunque e' una SSRF
# da manuale: puntandolo a http://localhost:8081 o a una macchina della rete di
# casa, la risposta finirebbe salvata come "foto" e si potrebbe rileggere.
# Prima il rimedio era una lista di host ammessi — solo upload.wikimedia.org —
# che chiudeva il buco ma anche la funzione: dal 01/10/2026 si vuole poter
# incollare l'indirizzo di una qualunque immagine.
#
# Il rimedio giusto non e' su QUALE host, e' su DOVE PORTA: si risolve il nome
# e si rifiuta se l'indirizzo e' privato, di loopback, link-local o comunque
# riservato. Cosi' "qualunque sito pubblico" resta possibile e "la mia rete"
# no, che e' esattamente la distinzione che serve.
#
# I reindirizzamenti NON si seguono da soli: un 302 verso 127.0.0.1 passerebbe
# il controllo fatto sul primo indirizzo e lo aggirerebbe. Si seguono a mano,
# ricontrollando ogni salto.
#
# Resta un rischio teorico di DNS rebinding — il nome potrebbe risolvere a un
# indirizzo pubblico durante il controllo e a uno privato un istante dopo.
# Chiuderlo per davvero vorrebbe dire connettersi all'IP verificato forzando
# l'header Host, cioe' riscrivere il trasporto: sproporzionato per un endpoint
# che richiede gia' di essere autenticati.

MAX_SALTI = 3
ESTENSIONI_IMMAGINE = (".jpg", ".jpeg", ".png", ".webp", ".gif")
TIPI_IMMAGINE = {
    "image/jpeg": ".jpg", "image/png": ".png",
    "image/webp": ".webp", "image/gif": ".gif",
}


def indirizzo_raggiungibile(url: str) -> str:
    """Controlla che l'URL sia https e che NON punti dentro la rete locale."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise HTTPException(status_code=400, detail="Serve un indirizzo https://")
    try:
        indirizzi = socket.getaddrinfo(parsed.hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise HTTPException(status_code=400, detail=f"Nome non risolvibile: {parsed.hostname}")
    for info in indirizzi:
        ip = ipaddress.ip_address(info[4][0])
        # `is_global` e' falso per privati, loopback, link-local, riservati e
        # multicast insieme: una riga invece di sei controlli da ricordarsi.
        if not ip.is_global:
            raise HTTPException(
                status_code=400,
                detail=f"L'indirizzo punta dentro la rete locale ({ip}): non e' permesso.",
            )
    return parsed.path


def scarica_immagine(url: str) -> tuple:
    """Scarica l'immagine seguendo a mano i reindirizzamenti. (contenuto, estensione)"""
    percorso = indirizzo_raggiungibile(url)
    for _ in range(MAX_SALTI + 1):
        try:
            resp = httpx.get(
                url,
                timeout=httpx.Timeout(connect=3.0, read=15.0, write=5.0, pool=5.0),
                headers={"User-Agent": "Kolibre/1.0 (self-hosted library server)"},
                follow_redirects=False,
            )
        except httpx.HTTPError:
            raise HTTPException(status_code=502, detail="Download dell'immagine fallito")
        if resp.status_code in (301, 302, 303, 307, 308):
            prossimo = resp.headers.get("location")
            if not prossimo:
                raise HTTPException(status_code=502, detail="Reindirizzamento senza destinazione")
            url = urljoin(url, prossimo)
            percorso = indirizzo_raggiungibile(url)
            continue
        break
    else:
        raise HTTPException(status_code=502, detail="Troppi reindirizzamenti")

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Download dell'immagine fallito (HTTP {resp.status_code})")
    if len(resp.content) > 5_000_000:
        raise HTTPException(status_code=400, detail="L'immagine supera il limite di 5MB")

    # L'estensione dall'indirizzo quando c'e', dal tipo dichiarato altrimenti:
    # moltissimi indirizzi di immagini non finiscono in .jpg, e rifiutarli
    # vorrebbe dire rifiutare meta' del web per una questione di forma.
    ext = os.path.splitext(percorso)[1].lower()
    tipo = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ext not in ESTENSIONI_IMMAGINE:
        ext = TIPI_IMMAGINE.get(tipo, "")
    if ext not in ESTENSIONI_IMMAGINE:
        raise HTTPException(
            status_code=400,
            detail="Non sembra un'immagine jpg, png, webp o gif"
            + (f" (il server dichiara «{tipo}»)" if tipo else ""),
        )
    # Il tipo dichiarato puo' mentire: si prova ad aprirla davvero. Salvare un
    # HTML chiamandolo .jpg darebbe una foto rotta e nessuna spiegazione.
    try:
        Image.open(io.BytesIO(resp.content)).verify()
    except Exception:
        raise HTTPException(status_code=400, detail="Il file scaricato non e' un'immagine leggibile")
    return resp.content, ext
