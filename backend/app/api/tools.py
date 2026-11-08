import hashlib
import json
import os
import re
import tempfile
import zipfile

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from starlette.background import BackgroundTask
from sqlalchemy.orm import Session

from ..schemas_risposte import (
    ElencoPatch, ManifestDelPlugin, PortaDelServer, VersioneDelPlugin,
)
from ..services import novita, patch_koreader, preferenze_utente
from .. import config, models, database, auth
from ..logging_utils import log_message

router = APIRouter(prefix="/api/tools", tags=["tools"])

# Endpoint deliberatamente SENZA autenticazione: sono URL che il
# browser (o il plugin KOReader) carica senza poter allegare un header
# Authorization — <img src>, @font-face, self-update del plugin. Tutto
# il resto di questo modulo passa da `router`, che main.py include con
# la dipendenza di autenticazione. Se aggiungi qui un endpoint, stai
# scegliendo di renderlo pubblico: fallo solo se e' in sola lettura.
public_router = APIRouter(prefix="/api/tools", tags=["tools"])

# repo_root/plugins/koreader/kolibre.koplugin — three levels up from this
# file (backend/app/api/tools.py -> backend/app -> backend -> repo root).
# All three plugins live under repo_root/plugins/ (moved there from three
# separate top-level folders for tidiness).
_KOREADER_PLUGIN_SRC_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "plugins", "koreader", "kolibre.koplugin")
)

# repo_root/plugins/calibre/kolibre_sync — same three-levels-up pattern.
_CALIBRE_PLUGIN_SRC_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "plugins", "calibre", "kolibre_sync")
)

# repo_root/plugins/obsidian/kolibre-highlights — same three-levels-up pattern.
_OBSIDIAN_PLUGIN_SRC_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "plugins", "obsidian", "kolibre-highlights")
)


# ── La lingua di chi scarica ─────────────────────────────────────────────
#
# **Da zero.** Ognuno dei tre plugin porta con se' il proprio catalogo di
# traduzioni, completo in italiano e in inglese. Quale dei due usare e' pero'
# una costante scritta nel codice — `active_lang` in kolibre_lingua.lua,
# `_ACTIVE_LANG` in lingua.py, `ACTIVE_LANG` in main.js — e non viene
# assegnata da nessuna parte: un plugin installato parla inglese qualunque
# cosa l'account abbia scelto, e fino al 07/11/2026 l'interfaccia diceva il
# contrario.
#
# Farla arrivare dal server a ogni avvio vorrebbe dire, per ognuno dei tre,
# un giro di andata e ritorno che oggi non c'e'. **Cucirla nel file mentre lo
# si impacchetta, no**: tutti e tre gli endpoint di scarico sono autenticati,
# quindi il server sa gia' chi sta scaricando, e la lingua e' una preferenza
# dell'account dal 04/11 (`services/preferenze_utente.py`). Qui non si
# traduce niente: si cambia **una riga** del sorgente, e il plugin che arriva
# sul dispositivo e' gia' quello giusto.
#
# Il nome del file basta a riconoscerla, ed e' sempre uno solo per plugin.
_RIGA_DELLA_LINGUA = {
    "kolibre_lingua.lua": (re.compile(rb'^local active_lang = "[a-z][a-z]"$', re.M),
                           b'local active_lang = "%s"'),
    "lingua.py": (re.compile(rb"^_ACTIVE_LANG = '[a-z][a-z]'$", re.M),
                  b"_ACTIVE_LANG = '%s'"),
    "main.js": (re.compile(rb"^const ACTIVE_LANG = '[a-z][a-z]';$", re.M),
                b"const ACTIVE_LANG = '%s';"),
}

# Le lingue che i cataloghi dei plugin hanno davvero. Sono le stesse di
# preferenze_utente.LINGUE_AMMESSE, ma non e' lo stesso elenco: aggiungere
# una lingua all'interfaccia non la aggiunge ai plugin, e scaricare un
# plugin in una lingua che non ha vorrebbe dire consegnarlo pieno di chiavi
# grezze. Quando un giorno divergeranno, divergeranno qui.
LINGUE_DEI_PLUGIN = ("it", "en")


def _lingua_valida(lingua) -> str:
    """
    Una lingua che i plugin hanno davvero, o l'inglese.

    Non solleva: un plugin vecchio non manda niente quando si aggiorna, e
    deve continuare ad aggiornarsi — in inglese, che e' esattamente quello
    che gia' faceva.
    """
    return lingua if lingua in LINGUE_DEI_PLUGIN else "en"


def _lingua_dell_account(db: Session, user_id: int) -> str:
    """La lingua scelta dalla persona che sta scaricando, o l'inglese.

    `lingua: None` («non ha scelto», vedi preferenze_utente) finisce qui
    come inglese, che e' il predefinito dichiarato dei plugin."""
    return _lingua_valida(preferenze_utente.leggi(db, user_id).get("lingua"))


def _con_la_lingua(dati: bytes, nome_file: str, lingua: str) -> bytes:
    """
    Gli stessi byte, con la lingua attiva del plugin messa a `lingua`.

    **Fallisce rumorosamente se la riga non si trova.** Una sostituzione muta
    consegnerebbe un plugin in inglese senza che nessuno se ne accorga, e
    l'unico modo di accorgersene sarebbe accendere un lettore e guardare un
    menu: molto piu' tardi, e lontano da qui. Un 500 allo scarico si vede
    subito. `prove/lingua_dei_plugin.py` controlla che le tre righe esistano
    ancora, cosi' il giorno in cui una viene rinominata la prova diventa
    rossa prima che lo diventi uno scarico.
    """
    regola = _RIGA_DELLA_LINGUA.get(os.path.basename(nome_file))
    if regola is None:
        return dati
    schema, riga = regola
    nuovi, quante = schema.subn(riga % lingua.encode("ascii"), dati, count=1)
    if quante != 1:
        # In inglese come ogni messaggio che esce dal server, anche se
        # questo e' per noi e non per chi usa il programma: la regola e'
        # quella, e prove/il_server_parla_inglese.py la fa rispettare.
        raise RuntimeError(
            f"{nome_file}: active-language line not found. "
            "If it was renamed, update _RIGA_DELLA_LINGUA in api/tools.py."
        )
    return nuovi


def _scrivi_nello_zip(z: zipfile.ZipFile, abs_path: str, arcname: str, lingua: str) -> None:
    """
    Un file dentro lo zip: copiato tale e quale, tranne quello della lingua.

    I file normali passano da `ZipFile.write`, che li copia senza mai
    portarli in memoria; solo per il file della lingua — uno per plugin — si
    passa dai byte, perche' e' l'unico che cambia.
    """
    if os.path.basename(abs_path) in _RIGA_DELLA_LINGUA:
        with open(abs_path, "rb") as f:
            z.writestr(arcname, _con_la_lingua(f.read(), abs_path, lingua))
    else:
        z.write(abs_path, arcname)


def _temp_zip_path(prefix: str) -> str:
    """
    A uniquely-named scratch file under PLUGINS_DIR for one plugin-zip
    download. Replaces the old scheme of a filename derived from the
    request's own config (a sha1 of server_url/token) — that guaranteed two
    concurrent downloads with different configs never collided, but since
    every issued token is different, it also guaranteed the file was NEVER
    reused and NEVER cleaned up: confirmed on the production server, where
    a week of normal "scarica plugin preconfigurato" clicks had left ~20
    stale zips behind. tempfile.mkstemp's uniqueness gives the same
    no-collision guarantee without keying the name to content, so the file
    can be deleted right after this response is sent (see the `background=`
    argument on each FileResponse below) instead of accumulating forever.
    """
    fd, path = tempfile.mkstemp(dir=config.PLUGINS_DIR, prefix=prefix, suffix=".zip")
    os.close(fd)
    return path


def _delete_temp_zip(path: str) -> None:
    try:
        os.remove(path)
    except OSError as e:
        log_message("warning", "tools", f"Cleaning up the temporary plugin zip failed for '{path}': {e}")


@public_router.get(
    "/server-port",
    responses={200: {"model": PortaDelServer}},
)
def get_public_backend_port():
    """
    The port the frontend should suggest when it asks the user for a
    LAN-reachable server address before downloading a plugin (KOReader,
    Calibre, Obsidian all talk to the backend directly, never through the
    frontend's own nginx proxy). Not guessable from inside the container —
    see config.PUBLIC_BACKEND_PORT.
    """
    return {"port": config.PUBLIC_BACKEND_PORT}


@public_router.get(
    "/frontend-port",
    responses={200: {"model": PortaDelServer}},
)
def get_public_frontend_port():
    """
    The reverse lookup: a plugin that only knows the BACKEND's own address
    (server_url in kolibre_sync/prefs.py) has no way to derive the web UI's
    port from it — the Calibre plugin's "Naviga su Kolibre" button needs
    this to build a URL a human should actually open in a browser, distinct
    from the API address it talks to for everything else. Same
    not-guessable-from-inside-the-container reasoning as PUBLIC_BACKEND_PORT.
    """
    return {"port": config.PUBLIC_FRONTEND_PORT}


def _read_plugin_version() -> str:
    """
    Single source of truth for the plugin's version: parsed straight out of
    the real main.lua's `VERSION = "x.y.z"` line, the same file the zip
    download/self-update endpoints below serve — so there's no separate
    version number to remember to keep in sync by hand.
    """
    main_lua_path = os.path.join(_KOREADER_PLUGIN_SRC_DIR, "main.lua")
    if not os.path.exists(main_lua_path):
        return "unknown"
    with open(main_lua_path, "r", encoding="utf-8") as f:
        for line in f:
            match = re.match(r'^local VERSION\s*=\s*"([^"]+)"', line.strip())
            if match:
                return match.group(1)
    return "unknown"


# File che non fanno MAI parte di un aggiornamento, per plugin. Sono le
# impostazioni dell'utente, e contengono il suo token: sovrascriverle
# vorrebbe dire sconnettere il plugin ogni volta che si aggiorna.
# (gconfig.lua di KOReader non e' nell'elenco perche' nel sorgente non
# esiste proprio: viene sintetizzato solo per i download preconfigurati.)
_FILE_NON_AGGIORNABILI = {
    _KOREADER_PLUGIN_SRC_DIR: {".DS_Store"},
    _OBSIDIAN_PLUGIN_SRC_DIR: {".DS_Store", "data.json"},
}


def _plugin_files(src_dir: str) -> list:
    """I file di un plugin che possono essere aggiornati, in ordine."""
    esclusi = _FILE_NON_AGGIORNABILI.get(src_dir, {".DS_Store"})
    files = []
    for root, dirs, filenames in os.walk(src_dir):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fname in filenames:
            if fname in esclusi:
                continue
            rel = os.path.relpath(os.path.join(root, fname), src_dir)
            files.append(rel.replace(os.sep, "/"))
    return sorted(files)


def _plugin_file_bytes(src_dir: str, rel_path: str, lingua: str = "en") -> bytes:
    """
    Raw bytes of one plugin source file, read in binary mode (no text-mode
    universal-newline translation) so this is byte-for-byte identical to what
    the /file/{file_path} endpoints serve — that identity is what makes
    the sha256 in the manifest below actually verify what the device receives,
    rather than a checksum of some other reading of the same file. Vale a
    parita' di `lingua`: il file della lingua attiva e' l'unico che cambia
    con lei, e manifest e scarico la ricevono dalla stessa richiesta del
    dispositivo, quindi non possono discordare.
    """
    abs_path = os.path.join(src_dir, rel_path)
    with open(abs_path, "rb") as f:
        return _con_la_lingua(f.read(), rel_path, lingua)


def _plugin_update_files() -> list:
    return _plugin_files(_KOREADER_PLUGIN_SRC_DIR)


def _read_plugin_file_bytes(rel_path: str, lingua: str = "en") -> bytes:
    return _plugin_file_bytes(_KOREADER_PLUGIN_SRC_DIR, rel_path, lingua)


def _plugin_file_checksums(lingua: str = "en") -> dict:
    """
    sha256 + size per updatable file, so the device can detect a truncated or
    corrupted download (a dropped connection can still leave the transport
    layer reporting HTTP 200 with a short body) before it ever stages the
    file for install, instead of trusting "HTTP 200 + file exists" alone.
    """
    return _plugin_checksums(_KOREADER_PLUGIN_SRC_DIR, lingua)


def _plugin_checksums(src_dir: str, lingua: str = "en") -> dict:
    checksums = {}
    for rel_path in _plugin_files(src_dir):
        data = _plugin_file_bytes(src_dir, rel_path, lingua)
        checksums[rel_path] = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        }
    return checksums


@router.get("/plugins/calibre", response_class=FileResponse, responses={200: {"content": {"application/octet-stream": {}}}})
def download_calibre_plugin(
    server_url: str = None,
    frontend_url: str = None,
    username: str = None,
    token: str = None,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user_flexible),
):
    """
    Zips the real plugins/calibre/kolibre_sync/ source on every request (same
    "always fresh, never a stale cached copy" reasoning as the KOReader zip
    below). Unlike the KOReader zip, files must sit at the ZIP ROOT (no
    "kolibre_sync/" prefix): Calibre's zip plugin loader
    (calibre/customize/zipplugin.py) imports the archive's own top-level
    __init__.py directly as the plugin package, it doesn't expect a nested
    folder — see plugin-import-name-kolibre_sync.txt in the source dir for
    how the loader picks the "calibre_plugins.kolibre_sync" import name.

    `server_url`/`frontend_url`/`username`/`token` are all optional and, when
    any is given, get baked into a `kolibre_preconfig.json` resource written
    into the zip (analogous to the KOReader endpoint's gconfig.lua, but NOT a
    drop-in file: the Calibre plugin's own settings live in Calibre's
    per-plugin JSONConfig, which lives outside the plugin's own folder in
    Calibre's user config dir and can't simply be pre-placed on disk).
    `frontend_url` is baked in as an explicit override only when the caller
    supplies one — omitting it leaves the plugin auto-detecting the web UI's
    port at runtime (client.py::frontend_url), unchanged from before this
    param existed. `token` must be an ALREADY-ISSUED JWT (e.g. one the caller
    obtained from POST /token) — never a raw password, which a query string
    would otherwise leak into server access logs and browser history.
    kolibre_sync/prefs.py reads this bundled resource — via `get_resources`,
    which Calibre's zip loader injects into every plugin module's namespace
    (see zipplugin.py's CalibrePluginLoader.exec_module) — on first import
    and copies its values into the real JSONConfig, but only if the user
    hasn't already configured (or reconfigured) the plugin by hand. Omitting
    every param (today's default, unconfigured zip) writes no such resource
    at all, so a plain download behaves exactly as before.
    """
    if not os.path.isdir(_CALIBRE_PLUGIN_SRC_DIR):
        raise HTTPException(status_code=404, detail="Calibre plugin not found on the server")

    lingua = _lingua_dell_account(db, current_user.id)

    preconfig = {}
    if server_url:
        preconfig["server_url"] = server_url.strip().rstrip("/")
    if frontend_url:
        preconfig["frontend_url"] = frontend_url.strip().rstrip("/")
    if username:
        preconfig["username"] = username.strip()
    if token:
        preconfig["token"] = token.strip()

    plugin_path = _temp_zip_path("kolibre_sync.")

    with zipfile.ZipFile(plugin_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(_CALIBRE_PLUGIN_SRC_DIR):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for fname in files:
                if fname == ".DS_Store" or fname.endswith(".pyc"):
                    continue
                abs_path = os.path.join(root, fname)
                arcname = os.path.relpath(abs_path, _CALIBRE_PLUGIN_SRC_DIR)
                _scrivi_nello_zip(z, abs_path, arcname, lingua)
        if preconfig:
            z.writestr("kolibre_preconfig.json", json.dumps(preconfig))
    # This zip is regenerated fresh on every request from current source —
    # a browser (or intermediate cache) serving back a stale prior response
    # for this same URL would silently hand out an outdated/broken plugin.
    # media_type is forced to octet-stream (instead of the "application/zip"
    # FileResponse would otherwise guess from the filename) because Safari's
    # "Open safe files after downloading" treats recognized archive types as
    # safe and auto-extracts them via Archive Utility, handing the user a
    # folder instead of the .zip Calibre's "Load plugin from file" dialog
    # requires — octet-stream isn't on that safe-type list, so Safari just
    # saves the file as-is like every other browser already does.
    return FileResponse(
        plugin_path,
        filename="kolibre_sync.zip",
        media_type="application/octet-stream",
        headers={"Cache-Control": "no-store"},
        background=BackgroundTask(_delete_temp_zip, plugin_path),
    )


@router.get("/plugins/obsidian", response_class=FileResponse, responses={200: {"content": {"application/octet-stream": {}}}})
def download_obsidian_plugin(
    server_url: str = None,
    username: str = None,
    token: str = None,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user_flexible),
):
    """
    Zips the real plugins/obsidian/kolibre-highlights/ source on every
    request — same "always fresh" reasoning as the Calibre/KOReader zips
    above. Unlike those two, Obsidian itself reads a plugin's settings
    straight out of a `data.json` file sitting in the plugin's own folder
    (Plugin.loadData() — see main.js's loadSettings()), so a pre-configured
    download here is simpler than Calibre's kolibre_preconfig.json indirection:
    when `server_url`/`username`/`token` are given, this just writes that
    real data.json directly into the zip. Obsidian picks it up as this
    plugin's actual settings the first time it loads — no separate
    bootstrap/merge step needed in main.js at all.
    """
    if not os.path.isdir(_OBSIDIAN_PLUGIN_SRC_DIR):
        raise HTTPException(status_code=404, detail="Obsidian plugin not found on the server")

    lingua = _lingua_dell_account(db, current_user.id)

    data_json = None
    if server_url or username or token:
        data_json = {
            "serverUrl": (server_url or "").strip().rstrip("/"),
            "username": (username or "").strip(),
            "authToken": (token or "").strip(),
        }

    plugin_path = _temp_zip_path("kolibre-highlights.")

    with zipfile.ZipFile(plugin_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(_OBSIDIAN_PLUGIN_SRC_DIR):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for fname in files:
                if fname == ".DS_Store" or fname == "data.json":
                    continue
                abs_path = os.path.join(root, fname)
                arcname = os.path.relpath(abs_path, _OBSIDIAN_PLUGIN_SRC_DIR)
                _scrivi_nello_zip(z, abs_path, arcname, lingua)
        if data_json:
            z.writestr("data.json", json.dumps(data_json, indent=2))

    return FileResponse(
        plugin_path,
        filename="kolibre-highlights.zip",
        media_type="application/octet-stream",
        headers={"Cache-Control": "no-store"},
        background=BackgroundTask(_delete_temp_zip, plugin_path),
    )


def _lua_string_literal(value: str) -> str:
    """Escapes a Python string for safe embedding as a Lua double-quoted string literal."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


@router.get("/plugins/koreader", response_class=FileResponse, responses={200: {"content": {"application/octet-stream": {}}}})
def download_koreader_plugin(
    device_id: int = None,
    server_url: str = None,
    db: Session = Depends(database.get_db),
    # A pre-configured download is triggered via window.open()/plain
    # navigation from the browser, which can't attach an Authorization
    # header — get_current_user_flexible also accepts ?token=, same as the
    # OPDS/plugin download endpoints elsewhere in the app.
    current_user: models.User = Depends(auth.get_current_user_flexible),
):
    """
    Zips the real plugins/koreader/kolibre.koplugin/ source folder on every
    request (cheap, a handful of small .lua files) rather than caching a
    stale copy. If `device_id` (and, since we can't guess a LAN-reachable
    address, `server_url`) are given, also bakes in a gconfig.lua so the
    plugin self-configures on first run instead of requiring the URL/token
    to be typed by hand on the device — the zip downloaded from a specific
    device's card is pre-configured for that device; the generic download
    (no device_id) is the same plugin with manual setup, as before.
    """
    if not os.path.isdir(_KOREADER_PLUGIN_SRC_DIR):
        raise HTTPException(status_code=404, detail="KOReader plugin not found on the server")

    lingua = _lingua_dell_account(db, current_user.id)

    gconfig_lua = None
    if device_id is not None:
        device = db.query(models.Device).filter(
            models.Device.id == device_id, models.Device.user_id == current_user.id
        ).first()
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
        if not server_url:
            raise HTTPException(status_code=400, detail="server_url is required for a pre-configured download")
        gconfig_lua = (
            "-- Generated automatically at download time — do not edit by hand,\n"
            "-- it will be overwritten if the plugin is downloaded again for this device.\n"
            "return {\n"
            f"    fingerprint = {_lua_string_literal(device.device_token)},\n"
            f"    server_url = {_lua_string_literal(server_url.rstrip('/'))},\n"
            f"    device_token = {_lua_string_literal(device.device_token)},\n"
            "}\n"
        )

    plugin_path = _temp_zip_path("kolibre.koplugin.")
    with zipfile.ZipFile(plugin_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(_KOREADER_PLUGIN_SRC_DIR):
            for fname in files:
                abs_path = os.path.join(root, fname)
                arcname = os.path.join("kolibre.koplugin", os.path.relpath(abs_path, _KOREADER_PLUGIN_SRC_DIR))
                _scrivi_nello_zip(z, abs_path, arcname, lingua)
        if gconfig_lua:
            z.writestr("kolibre.koplugin/gconfig.lua", gconfig_lua)
    return FileResponse(
        plugin_path,
        filename="kolibre.koplugin.zip",
        media_type="application/octet-stream",
        headers={"Cache-Control": "no-store"},
        background=BackgroundTask(_delete_temp_zip, plugin_path),
    )


def _read_obsidian_version() -> str:
    """Dal manifest.json vero del plugin, l'unico posto dove la versione e'
    scritta — Obsidian legge quello stesso file per decidere cosa mostrare."""
    percorso = os.path.join(_OBSIDIAN_PLUGIN_SRC_DIR, "manifest.json")
    if not os.path.exists(percorso):
        return "unknown"
    try:
        with open(percorso, "r", encoding="utf-8") as f:
            return str(json.load(f).get("version") or "unknown")
    except (OSError, ValueError):
        return "unknown"


def _read_calibre_version() -> str:
    """
    Dalla tupla `version = (x, y, z)` dichiarata nella classe del plugin in
    __init__.py: e' quella che Calibre stessa mostra e confronta, quindi
    aggiungere un numero altrove vorrebbe dire tenerne due allineati a mano.
    """
    percorso = os.path.join(_CALIBRE_PLUGIN_SRC_DIR, "__init__.py")
    if not os.path.exists(percorso):
        return "unknown"
    with open(percorso, "r", encoding="utf-8") as f:
        for riga in f:
            m = re.match(r"^\s*version\s*=\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", riga)
            if m:
                return ".".join(m.groups())
    return "unknown"


# ── Aggiornamento dei plugin dal server ──────────────────────────────────
#
# Stessa forma per tutti e tre, con una differenza che viene da come i tre
# programmi caricano un plugin:
#
# - KOReader e Obsidian leggono file sciolti da una cartella, quindi si
#   aggiornano file per file (elenco + impronte qui sotto, poi un file alla
#   volta) e possono ricaricarsi da soli;
# - Calibre installa uno ZIP, e il modulo caricato resta in memoria fino al
#   riavvio: per lei c'e' solo la versione, e lo zip e' quello che il plugin
#   scarica gia' oggi da /plugins/calibre.
#
# Pubblici come quelli di KOReader: espongono il nostro stesso codice
# sorgente, gia' scaricabile, e mai le impostazioni dell'utente.


@public_router.get(
    "/plugins/obsidian/version",
    responses={200: {"model": VersioneDelPlugin}},
)
def get_obsidian_plugin_version():
    return {"version": _read_obsidian_version()}


@public_router.get(
    "/plugins/obsidian/manifest",
    responses={200: {"model": ManifestDelPlugin}},
)
def get_obsidian_plugin_manifest(lingua: str = "en"):
    """
    Elenco file + impronte per l'aggiornamento del plugin Obsidian.
    `data.json` e' escluso per costruzione (vedi _FILE_NON_AGGIORNABILI): e'
    il file dove Obsidian tiene le impostazioni di QUESTO vault, token
    compreso, e un aggiornamento non deve mai toccarlo.

    **`lingua`**: il plugin dice in che lingua e' la copia che ha installata,
    e riceve i file in quella. Serve perche' l'aggiornamento non disfi lo
    scarico: senza, un plugin scaricato in italiano tornerebbe inglese al
    primo aggiornamento, in silenzio. Chi non la manda — un plugin vecchio —
    riceve l'inglese, cioe' quello che gia' faceva. Impronte e contenuto
    vengono dalla stessa lingua, quindi non possono discordare.
    """
    return {
        "version": _read_obsidian_version(),
        "files": _plugin_files(_OBSIDIAN_PLUGIN_SRC_DIR),
        "checksums": _plugin_checksums(_OBSIDIAN_PLUGIN_SRC_DIR, _lingua_valida(lingua)),
    }


@public_router.get("/plugins/obsidian/file/{file_path:path}", response_class=Response, responses={200: {"content": {"text/plain": {}}}})
def get_obsidian_plugin_file(file_path: str, lingua: str = "en"):
    """
    Il contenuto grezzo di un file del plugin. A prova di uscita dalla
    cartella, e limitato ai file elencati nel manifest — cosi' `data.json`
    non e' raggiungibile nemmeno chiedendolo per nome.
    """
    if file_path not in _plugin_files(_OBSIDIAN_PLUGIN_SRC_DIR):
        raise HTTPException(status_code=404, detail="File not found")
    abs_path = os.path.abspath(os.path.join(_OBSIDIAN_PLUGIN_SRC_DIR, file_path))
    if os.path.commonpath([abs_path, _OBSIDIAN_PLUGIN_SRC_DIR]) != _OBSIDIAN_PLUGIN_SRC_DIR:
        raise HTTPException(status_code=404, detail="File not found")
    if not os.path.exists(abs_path):
        raise HTTPException(status_code=404, detail="File not found")
    # Da _plugin_file_bytes e non da un `open()` diretto: e' li' che la riga
    # della lingua cambia, ed e' li' che il manifest ha preso le impronte.
    data = _plugin_file_bytes(_OBSIDIAN_PLUGIN_SRC_DIR, file_path, _lingua_valida(lingua))
    return Response(content=data, media_type="text/plain; charset=utf-8")


@public_router.get(
    "/plugins/calibre/version",
    responses={200: {"model": VersioneDelPlugin}},
)
def get_calibre_plugin_version():
    return {"version": _read_calibre_version()}


@public_router.get(
    "/plugins/koreader/version",
    responses={200: {"model": VersioneDelPlugin}},
)
def get_koreader_plugin_version(lingua: str = "en"):
    """
    Lets the plugin itself ask "is there a newer version?" without needing
    the cable — it's a plain unauthenticated GET (same trust level as the
    manifest/file endpoints below) since it exposes nothing sensitive.

    `novita` is what changes in that version, so the window that offers the
    update can say it. It comes from plugins/koreader/novita.json and NOT
    from inside the plugin's own files, for the reason written at the top of
    services/novita.py: the text a person reads and the bytes a machine
    compares must be able to change separately. `lingua` works like every
    other plugin endpoint — the plugin asks in the language it was packaged
    in, and an older one that doesn't ask gets English.
    """
    versione = _read_plugin_version()
    return {
        "version": versione,
        "novita": novita.per_il_plugin(versione, _lingua_valida(lingua)),
    }


@public_router.get(
    "/plugins/koreader/manifest",
    responses={200: {"model": ManifestDelPlugin}},
)
def get_koreader_plugin_manifest(lingua: str = "en"):
    """
    File list + version for the self-update flow. gconfig.lua is
    deliberately absent (see _plugin_update_files) so a plain update never
    touches the device's own server_url/device_token.

    `checksums` is additive on top of the original `files` list (kept as a
    flat list of paths, unchanged) rather than replacing it, so a plugin
    build from before checksums existed — mid-transition, updating itself for
    the very first time onto a build that understands this field — can still
    decode this response with its old `ipairs(manifest.files)` loop instead
    of choking on a shape change.

    **`lingua`**: il plugin dice in che lingua e' la copia che ha installata,
    e riceve i file in quella. Serve perche' l'aggiornamento non disfi lo
    scarico: senza, un plugin scaricato in italiano tornerebbe inglese al
    primo aggiornamento, in silenzio. Chi non la manda — un plugin vecchio —
    riceve l'inglese, cioe' quello che gia' faceva. Impronte e contenuto
    vengono dalla stessa lingua, quindi non possono discordare.
    """
    return {
        "version": _read_plugin_version(),
        "files": _plugin_update_files(),
        "checksums": _plugin_file_checksums(_lingua_valida(lingua)),
    }


@public_router.get("/plugins/koreader/file/{file_path:path}", response_class=Response, responses={200: {"content": {"text/plain": {}}}})
def get_koreader_plugin_file(file_path: str, lingua: str = "en"):
    """
    Raw contents of a single plugin source file, for the device to fetch and
    overwrite locally one file at a time (no zip/unzip needed on-device).
    Path-traversal-safe: resolves against the real source dir and rejects
    anything that escapes it, and only serves files actually listed in the
    manifest (so gconfig.lua can never be fetched this way either).
    """
    if file_path not in _plugin_update_files():
        raise HTTPException(status_code=404, detail="File not found")
    abs_path = os.path.abspath(os.path.join(_KOREADER_PLUGIN_SRC_DIR, file_path))
    if os.path.commonpath([abs_path, _KOREADER_PLUGIN_SRC_DIR]) != _KOREADER_PLUGIN_SRC_DIR:
        raise HTTPException(status_code=404, detail="File not found")
    if not os.path.exists(abs_path):
        raise HTTPException(status_code=404, detail="File not found")
    # Raw bytes, no text-mode decode/re-encode round trip: this must be
    # byte-for-byte what _read_plugin_file_bytes hashed for the manifest, or
    # the device's checksum check would reject every download as "corrupt".
    # Che e' anche il motivo per cui da qui in poi si passa da quella stessa
    # funzione invece di riaprire il file: la riga della lingua la cambia
    # lei, e un `open()` diretto consegnerebbe byte diversi da quelli
    # misurati nel manifest.
    data = _read_plugin_file_bytes(file_path, _lingua_valida(lingua))
    return Response(content=data, media_type="text/plain; charset=utf-8")


@public_router.get(
    "/koreader/patches",
    responses={200: {"model": ElencoPatch}},
)
def elenco_patch_koreader():
    """
    Le userpatch che questo server sa consegnare, perche' il plugin possa
    installarle da solo.

    **Perche' esiste.** Una userpatch e' un file che KOReader esegue
    all'avvio, e si installa copiandolo in `koreader/patches/` — finora
    attaccando il lettore al computer con un cavo. Per una misura da far
    girare qualche giorno e poi togliere, il cavo e' il motivo per cui la
    misura non si fa.

    Non autenticato come gli altri endpoint dell'autoaggiornamento del
    plugin (version/manifest/file): e' sola lettura e serve lo stesso
    codice che sta nel repository, che il plugin stesso scarica da qui da
    sempre. Il dispositivo poi chiede conferma prima di installare, perche'
    una patch e' codice che gira a ogni avvio.
    """
    # `novita`: cosa cambia in quella patch, in INGLESE e in inglese solo —
    # una patch e' un file unico per tutti e non un menu' con cui si
    # interagisce (decisione di Paolo, 08/11/2026). Vedi services/novita.py.
    return {
        "patches": [
            dict(p, novita=novita.per_la_patch(p.get("file")))
            for p in patch_koreader.elenco()
        ]
    }


@public_router.get("/koreader/patches/file/{nome_file}", response_class=Response, responses={200: {"content": {"text/plain": {}}}})
def file_patch_koreader(nome_file: str):
    """
    Il contenuto di una patch. Si serve solo quello che l'elenco qui sopra
    ha dichiarato: niente percorsi, niente sottocartelle, nessun modo di
    chiedere un file diverso da quelli (il nome deve corrispondere a
    `_NOME_DI_PATCH`, e deve essere uno dei file presenti).
    """
    if not any(p["file"] == nome_file for p in patch_koreader.elenco()):
        raise HTTPException(status_code=404, detail="Patch not found")
    percorso = os.path.abspath(os.path.join(patch_koreader.CARTELLA, nome_file))
    if os.path.commonpath([percorso, patch_koreader.CARTELLA]) != patch_koreader.CARTELLA:
        raise HTTPException(status_code=404, detail="Patch not found")
    # Byte esatti, senza giri di decodifica: devono essere gli stessi su cui
    # e' stata calcolata l'impronta, altrimenti il dispositivo scarterebbe
    # ogni download come corrotto.
    with open(percorso, "rb") as f:
        dati = f.read()
    return Response(content=dati, media_type="text/plain; charset=utf-8")


@router.get(
    "/logs",
    responses={200: {"model": list[str]}},
)
def get_server_logs(_chi: models.User = Depends(auth.get_current_active_admin)):
    """Le ultime cento righe del log del server.

    Riservato agli amministratori: quel file contiene i nomi di chi accede
    («Token issued for user: …»), i nomi delle biblioteche, i percorsi dei
    file e i nomi dei dispositivi di tutti. Prima bastava essere autenticati,
    quindi un ospite leggeva l'attivita' di chiunque altro.
    """
    if not os.path.exists(config.LOGS_FILE):
        return []
    with open(config.LOGS_FILE, "r") as lf:
        lines = lf.readlines()
    return lines[-100:]
