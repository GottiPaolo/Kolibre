"""
Local, offline dictionary lookups — same StarDict format KOReader itself
uses for its own installable dictionaries (.ifo metadata + .idx word index +
.dict/.dict.dz definitions, format spec: stardict-4.sourceforge.net). Tried
BEFORE the online Wiktionary fallback in dictionary_service.py, since a real
monolingual dictionary gives an actual Italian definition instead of an
English gloss of an Italian word.

Confirmed live (backend/scripts/... one-off test, not committed): a plain
`.dict.dz` decompresses fully with the stdlib `gzip` module — dictzip's
random-access chunk table is an EXTRA gzip header field a plain decoder
just ignores, the underlying stream is standard gzip-compatible. True
random-access seeking (avoiding a full decompress) isn't worth the extra
code for dictionaries in the single-digit-MB range: decompressing once and
caching in memory (~25MB for the Italian dictionary below) is simple and
fast enough, and this only runs on an explicit "Cerca definizione" click,
never automatically on a hot path.
"""

import hashlib
import html
import os
import time
import re
import shutil
import struct
import tempfile
import zipfile
from typing import Optional

import httpx

from .. import config

# Only Italian for now — the libraries this runs on are overwhelmingly
# Italian, and this is the one directly relevant to the "spiegami come
# funziona il dizionario" request. Adding another language later is just
# another entry here plus a UI row (see IntegrationsTab.tsx), no other code
# changes needed.
KNOWN_DICTIONARIES = {
    "it": {
        "lang": "it",
        "display_name": "Italiano (reader.dict)",
        "download_url": "https://www.reader-dict.com/file/it/dict-it-it.zip",
        "attribution": "reader.dict / Wiktionary (CC BY-SA + GFDL)",
    },
}

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_FIRST_LIST_ITEM_RE = re.compile(r"<ol>\s*<li>(.*?)</li>", re.DOTALL)

# Loaded dictionaries, keyed by lang — the .idx (parsed) and the fully
# decompressed .dict live here for the life of the process. A handful of MB
# per language; reloading on every lookup would mean re-decompressing the
# whole .dict.dz (a few hundred ms) on every single word click.
_loaded: dict = {}


# Un codice di lingua e' "it", "en", "pt-BR": lettere, cifre, trattino,
# underscore. Nient'altro.
_LANG_VALIDO = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def _lang_dir(lang: str) -> str:
    """La cartella di un dizionario, e il punto in cui `lang` viene validato.

    `lang` arriva da un parametro di percorso URL
    (`/devices/dictionaries/{lang}/file/{filename}`), e prima di questo
    controllo ci arrivava intatto: `file_path_for_device` validava con cura il
    solo `filename`, e nessuno guardava `lang`. Con `lang = ".."` il percorso
    risultante usciva da DICTIONARIES_DIR e saliva di un livello — che in
    produzione e' esattamente DATA_DIR.

    Verificato prima della correzione, con il solo token di un dispositivo:
    `GET /api/kolibre/devices/dictionaries/%2E%2E/file/app.db` rispondeva 200
    con il database intero (hash delle password, token di tutti i dispositivi,
    annotazioni), e `.../file/secret_key` con la chiave che firma i JWT — da
    cui si fabbrica un token per qualunque account.

    Due controlli invece di uno: la forma di `lang`, e poi che il percorso
    risolto stia davvero dentro DICTIONARIES_DIR, perche' il primo da solo
    dipende dal fatto di aver pensato a tutte le forme possibili.
    """
    if not isinstance(lang, str) or not _LANG_VALIDO.match(lang):
        raise ValueError(f"codice lingua non valido: {lang!r}")
    radice = os.path.realpath(config.DICTIONARIES_DIR)
    percorso = os.path.realpath(os.path.join(radice, lang))
    if percorso != radice and not percorso.startswith(radice + os.sep):
        raise ValueError(f"codice lingua non valido: {lang!r}")
    return percorso


def is_installed(lang: str) -> bool:
    try:
        ifo_path = os.path.join(_lang_dir(lang), "dict-data.ifo")
    except ValueError:
        return False
    return os.path.isfile(ifo_path)


def _parse_ifo(path: str) -> dict:
    info = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if "=" not in line:
                continue
            key, _, value = line.strip().partition("=")
            info[key] = value
    return info


def list_installed() -> list:
    result = []
    for lang, meta in KNOWN_DICTIONARIES.items():
        if not is_installed(lang):
            continue
        info = _parse_ifo(os.path.join(_lang_dir(lang), "dict-data.ifo"))
        result.append({
            "lang": lang,
            "display_name": meta["display_name"],
            "bookname": info.get("bookname"),
            "wordcount": int(info["wordcount"]) if info.get("wordcount", "").isdigit() else None,
            "date": info.get("date"),
        })
    return result


def install(lang: str) -> dict:
    """Downloads and installs a known dictionary. Overwrites any existing
    install for the same lang (e.g. to pick up a newer reader-dict.com
    export) — this is an explicit user action (Impostazioni → Integrazioni),
    never automatic, same reasoning as the Wikipedia author-scrape toggle."""
    meta = KNOWN_DICTIONARIES.get(lang)
    if not meta:
        raise ValueError(f"Dizionario sconosciuto: '{lang}'")

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = os.path.join(tmp, "dict.zip")
        with httpx.stream("GET", meta["download_url"], timeout=60, follow_redirects=True) as resp:
            resp.raise_for_status()
            with open(zip_path, "wb") as f:
                for chunk in resp.iter_bytes():
                    f.write(chunk)

        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
            ifo_name = next((n for n in names if n.endswith(".ifo")), None)
            if not ifo_name:
                raise ValueError("Archivio dizionario non valido: manca il file .ifo")
            base = ifo_name[: -len(".ifo")]
            target_dir = _lang_dir(lang)
            if os.path.isdir(target_dir):
                shutil.rmtree(target_dir)
            os.makedirs(target_dir, exist_ok=True)
            for suffix in (".ifo", ".idx", ".idx.gz", ".dict", ".dict.dz", ".syn"):
                member = base + suffix
                if member in names:
                    with z.open(member) as src, open(os.path.join(target_dir, "dict-data" + suffix), "wb") as dst:
                        shutil.copyfileobj(src, dst)

    _loaded.pop(lang, None)  # forza un ricaricamento se era già in memoria
    info = _parse_ifo(os.path.join(_lang_dir(lang), "dict-data.ifo"))
    return {
        "lang": lang,
        "display_name": meta["display_name"],
        "bookname": info.get("bookname"),
        "wordcount": int(info["wordcount"]) if info.get("wordcount", "").isdigit() else None,
    }


def uninstall(lang: str) -> None:
    target_dir = _lang_dir(lang)
    if os.path.isdir(target_dir):
        shutil.rmtree(target_dir)
    _loaded.pop(lang, None)


def device_manifest(lang: str) -> list:
    """
    For "Scarica dizionario sul dispositivo" (main.lua): the exact same
    manifest + per-file-download + os.rename shape the plugin already uses
    for its own self-update (see main.lua's _downloadAndInstallUpdate) —
    reused here instead of inventing an on-device unzip, since KOReader has
    no zip-extraction library available to this plugin. Every actual file
    on disk for this dict is listed (whichever of .idx/.idx.gz and
    .dict/.dict.dz install() picked, plus .ifo and .syn when present) so
    the device ends up with a byte-identical copy of what the server has,
    regardless of which variant was downloaded from reader-dict.com.

    Un `lang` che non e' un codice di lingua da' un elenco vuoto, non
    un'eccezione: per chi chiama, una lingua inventata e una non installata
    sono la stessa risposta (404). Vedi `_lang_dir` per il motivo del
    controllo.
    """
    try:
        target_dir = _lang_dir(lang)
    except ValueError:
        return []
    if not os.path.isdir(target_dir):
        return []
    files = []
    for name in sorted(os.listdir(target_dir)):
        path = os.path.join(target_dir, name)
        if not os.path.isfile(path):
            continue
        with open(path, "rb") as f:
            data = f.read()
        files.append({"name": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    return files


def file_path_for_device(lang: str, filename: str) -> Optional[str]:
    """Resolves one manifest filename to an absolute path, refusing anything
    that isn't the exact basename of a file this same lang's device_manifest
    would list — filename comes straight from a URL path parameter, so no
    directory traversal ("..", "/") is ever allowed through."""
    if not filename or "/" in filename or "\\" in filename or filename in (".", ".."):
        return None
    try:
        path = os.path.join(_lang_dir(lang), filename)
    except ValueError:
        return None
    if os.path.isfile(path):
        return path
    return None


def _read_maybe_gzip(path_no_ext: str) -> bytes:
    """.dict or .dict.dz — StarDict compresses the definitions file with
    dictzip, which is gzip-stream-compatible (confirmed live: stdlib gzip
    decompresses it whole without needing dictzip's own chunk table)."""
    dz_path = path_no_ext + ".dz"
    if os.path.isfile(dz_path):
        import gzip
        with gzip.open(dz_path, "rb") as f:
            return f.read()
    with open(path_no_ext, "rb") as f:
        return f.read()


def purge_idle_dictionaries(max_idle_seconds: float = 1800) -> int:
    """
    Scarica dalla memoria i dizionari che nessuno consulta da mezz'ora.

    Un dizionario decompresso pesa decine di MB e restava caricato per tutta
    la vita del processo: chi ha cliccato una parola alle dieci del mattino
    se lo portava dietro fino a sera. Il prezzo di riscaricarlo e' qualche
    centinaio di millisecondi sulla prima parola dopo la pausa — cioe'
    niente, rispetto a tenere occupata la memoria per ore.

    Mezz'ora e non cinque minuti perche' una sessione di lettura ha pause
    lunghe, e ricaricare in mezzo a una lettura sarebbe il momento peggiore.
    """
    adesso = time.monotonic()
    fermi = [l for l, d in _loaded.items() if adesso - d.get("_ultimo_uso", 0) > max_idle_seconds]
    for l in fermi:
        del _loaded[l]
    return len(fermi)


def _load(lang: str) -> Optional[dict]:
    if lang in _loaded:
        _loaded[lang]["_ultimo_uso"] = time.monotonic()
        return _loaded[lang]
    if not is_installed(lang):
        return None

    lang_dir = _lang_dir(lang)
    ifo = _parse_ifo(os.path.join(lang_dir, "dict-data.ifo"))
    offset_bits = 64 if ifo.get("idxoffsetbits") == "64" else 32
    fmt = ">Q" if offset_bits == 64 else ">I"
    offset_size = 8 if offset_bits == 64 else 4

    idx_path = os.path.join(lang_dir, "dict-data.idx")
    idx_gz_path = idx_path + ".gz"
    if os.path.isfile(idx_gz_path):
        import gzip
        with gzip.open(idx_gz_path, "rb") as f:
            idx_data = f.read()
    else:
        with open(idx_path, "rb") as f:
            idx_data = f.read()

    words: dict = {}
    pos, n = 0, len(idx_data)
    while pos < n:
        end = idx_data.index(b"\x00", pos)
        word = idx_data[pos:end].decode("utf-8", errors="replace")
        pos = end + 1
        offset = struct.unpack(fmt, idx_data[pos:pos + offset_size])[0]
        pos += offset_size
        size = struct.unpack(">I", idx_data[pos:pos + 4])[0]
        pos += 4
        # A word can legitimately repeat in a StarDict idx (multiple
        # entries, e.g. different parts of speech) — first one wins, good
        # enough for a single "definizione" card.
        words.setdefault(word, (offset, size))

    dict_data = _read_maybe_gzip(os.path.join(lang_dir, "dict-data.dict"))

    loaded = {
        "words": words, "dict_data": dict_data, "same_type": ifo.get("sametypesequence"),
        "_ultimo_uso": time.monotonic(),
    }
    _loaded[lang] = loaded
    return loaded


def _extract_definition(raw: str, same_type: Optional[str]) -> str:
    """StarDict content can be plain text ('m'), HTML ('h'), or other marked
    types — see this module's own docstring. This dictionary uses 'h'
    (confirmed via its .ifo). For HTML, take the first <li> of the first
    <ol> (the actual first sense — reader.dict lists synonyms in a SECOND
    <ol> right after, which would be noise here); fall back to stripping all
    tags when the entry doesn't follow that shape."""
    if same_type == "h":
        match = _FIRST_LIST_ITEM_RE.search(raw)
        text = match.group(1) if match else raw
    else:
        text = raw
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def lookup_word(lang: str, word: str) -> Optional[dict]:
    """Best-effort local lookup. Returns None if the dictionary isn't
    installed or the word (in any of a few common casings) isn't in it —
    the caller (dictionary_service.fetch_definition) falls back to the
    online lookup in that case."""
    loaded = _load(lang)
    if not loaded:
        return None

    words = loaded["words"]
    for candidate in (word, word.lower(), word.capitalize()):
        if candidate in words:
            offset, size = words[candidate]
            raw = loaded["dict_data"][offset:offset + size].decode("utf-8", errors="replace")
            definition = _extract_definition(raw, loaded["same_type"])
            if definition:
                meta = KNOWN_DICTIONARIES[lang]
                return {"definition": definition, "source": meta["display_name"]}
            return None
    return None
