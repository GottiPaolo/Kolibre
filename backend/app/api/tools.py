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
        log_message("warning", "tools", f"Pulizia zip plugin temporaneo fallita per '{path}': {e}")


@public_router.get("/server-port")
def get_public_backend_port():
    """
    The port the frontend should suggest when it asks the user for a
    LAN-reachable server address before downloading a plugin (KOReader,
    Calibre, Obsidian all talk to the backend directly, never through the
    frontend's own nginx proxy). Not guessable from inside the container —
    see config.PUBLIC_BACKEND_PORT.
    """
    return {"port": config.PUBLIC_BACKEND_PORT}


@public_router.get("/frontend-port")
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


def _plugin_file_bytes(src_dir: str, rel_path: str) -> bytes:
    """
    Raw bytes of one plugin source file, read in binary mode (no text-mode
    universal-newline translation) so this is byte-for-byte identical to what
    the /file/{file_path} endpoints serve — that identity is what makes
    the sha256 in the manifest below actually verify what the device receives,
    rather than a checksum of some other reading of the same file.
    """
    abs_path = os.path.join(src_dir, rel_path)
    with open(abs_path, "rb") as f:
        return f.read()


def _plugin_update_files() -> list:
    return _plugin_files(_KOREADER_PLUGIN_SRC_DIR)


def _read_plugin_file_bytes(rel_path: str) -> bytes:
    return _plugin_file_bytes(_KOREADER_PLUGIN_SRC_DIR, rel_path)


def _plugin_file_checksums() -> dict:
    """
    sha256 + size per updatable file, so the device can detect a truncated or
    corrupted download (a dropped connection can still leave the transport
    layer reporting HTTP 200 with a short body) before it ever stages the
    file for install, instead of trusting "HTTP 200 + file exists" alone.
    """
    return _plugin_checksums(_KOREADER_PLUGIN_SRC_DIR)


def _plugin_checksums(src_dir: str) -> dict:
    checksums = {}
    for rel_path in _plugin_files(src_dir):
        data = _plugin_file_bytes(src_dir, rel_path)
        checksums[rel_path] = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        }
    return checksums


@router.get("/plugins/calibre")
def download_calibre_plugin(server_url: str = None, frontend_url: str = None, username: str = None, token: str = None):
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
        raise HTTPException(status_code=404, detail="Plugin Calibre non trovato sul server")

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
                z.write(abs_path, arcname)
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


@router.get("/plugins/obsidian")
def download_obsidian_plugin(server_url: str = None, username: str = None, token: str = None):
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
        raise HTTPException(status_code=404, detail="Plugin Obsidian non trovato sul server")

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
                z.write(abs_path, arcname)
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


@router.get("/plugins/koreader")
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
        raise HTTPException(status_code=404, detail="Plugin KOReader non trovato sul server")

    gconfig_lua = None
    if device_id is not None:
        device = db.query(models.Device).filter(
            models.Device.id == device_id, models.Device.user_id == current_user.id
        ).first()
        if not device:
            raise HTTPException(status_code=404, detail="Dispositivo non trovato")
        if not server_url:
            raise HTTPException(status_code=400, detail="server_url è obbligatorio per un download pre-configurato")
        gconfig_lua = (
            "-- Generato automaticamente al momento del download — non modificare a mano,\n"
            "-- verrà sovrascritto se il plugin viene riscaricato per questo dispositivo.\n"
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
                z.write(abs_path, arcname)
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


@public_router.get("/plugins/obsidian/version")
def get_obsidian_plugin_version():
    return {"version": _read_obsidian_version()}


@public_router.get("/plugins/obsidian/manifest")
def get_obsidian_plugin_manifest():
    """
    Elenco file + impronte per l'aggiornamento del plugin Obsidian.
    `data.json` e' escluso per costruzione (vedi _FILE_NON_AGGIORNABILI): e'
    il file dove Obsidian tiene le impostazioni di QUESTO vault, token
    compreso, e un aggiornamento non deve mai toccarlo.
    """
    return {
        "version": _read_obsidian_version(),
        "files": _plugin_files(_OBSIDIAN_PLUGIN_SRC_DIR),
        "checksums": _plugin_checksums(_OBSIDIAN_PLUGIN_SRC_DIR),
    }


@public_router.get("/plugins/obsidian/file/{file_path:path}")
def get_obsidian_plugin_file(file_path: str):
    """
    Il contenuto grezzo di un file del plugin. A prova di uscita dalla
    cartella, e limitato ai file elencati nel manifest — cosi' `data.json`
    non e' raggiungibile nemmeno chiedendolo per nome.
    """
    if file_path not in _plugin_files(_OBSIDIAN_PLUGIN_SRC_DIR):
        raise HTTPException(status_code=404, detail="File non trovato")
    abs_path = os.path.abspath(os.path.join(_OBSIDIAN_PLUGIN_SRC_DIR, file_path))
    if os.path.commonpath([abs_path, _OBSIDIAN_PLUGIN_SRC_DIR]) != _OBSIDIAN_PLUGIN_SRC_DIR:
        raise HTTPException(status_code=404, detail="File non trovato")
    if not os.path.exists(abs_path):
        raise HTTPException(status_code=404, detail="File non trovato")
    with open(abs_path, "rb") as f:
        return Response(content=f.read(), media_type="text/plain; charset=utf-8")


@public_router.get("/plugins/calibre/version")
def get_calibre_plugin_version():
    return {"version": _read_calibre_version()}


@public_router.get("/plugins/koreader/version")
def get_koreader_plugin_version():
    """
    Lets the plugin itself ask "is there a newer version?" without needing
    the cable — it's a plain unauthenticated GET (same trust level as the
    manifest/file endpoints below) since it exposes nothing sensitive.
    """
    return {"version": _read_plugin_version()}


@public_router.get("/plugins/koreader/manifest")
def get_koreader_plugin_manifest():
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
    """
    return {
        "version": _read_plugin_version(),
        "files": _plugin_update_files(),
        "checksums": _plugin_file_checksums(),
    }


@public_router.get("/plugins/koreader/file/{file_path:path}")
def get_koreader_plugin_file(file_path: str):
    """
    Raw contents of a single plugin source file, for the device to fetch and
    overwrite locally one file at a time (no zip/unzip needed on-device).
    Path-traversal-safe: resolves against the real source dir and rejects
    anything that escapes it, and only serves files actually listed in the
    manifest (so gconfig.lua can never be fetched this way either).
    """
    if file_path not in _plugin_update_files():
        raise HTTPException(status_code=404, detail="File non trovato")
    abs_path = os.path.abspath(os.path.join(_KOREADER_PLUGIN_SRC_DIR, file_path))
    if os.path.commonpath([abs_path, _KOREADER_PLUGIN_SRC_DIR]) != _KOREADER_PLUGIN_SRC_DIR:
        raise HTTPException(status_code=404, detail="File non trovato")
    if not os.path.exists(abs_path):
        raise HTTPException(status_code=404, detail="File non trovato")
    # Raw bytes, no text-mode decode/re-encode round trip: this must be
    # byte-for-byte what _read_plugin_file_bytes hashed for the manifest, or
    # the device's checksum check would reject every download as "corrupt".
    with open(abs_path, "rb") as f:
        data = f.read()
    return Response(content=data, media_type="text/plain; charset=utf-8")


@router.get("/logs")
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
