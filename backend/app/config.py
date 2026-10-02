import os

# Absolute, not relative: watchdog's file-system events report absolute paths
# regardless of what path you hand its Observer, so a relative DATA_DIR here
# made the ingest watcher and the poll-based fallback scan disagree on the
# "same" file's path string (one absolute, one relative) and both stage it as
# a separate IngestedBook row — the file got queued for import twice.
DATA_DIR = os.path.abspath(os.environ.get("DATA_DIR", "./data"))
LIBRARIES_DIR = os.path.join(DATA_DIR, "libraries")
PLUGINS_DIR = os.path.join(DATA_DIR, "plugins")
INGEST_DIR = os.path.join(DATA_DIR, "ingest")
# Copertine estratte dai file EPUB in staging (services/metadata_parser.py,
# services/watcher.py::stage_ingest_file) — cache separata da INGEST_DIR
# stesso così il watcher/poll fallback (che scansiona INGEST_DIR) non la
# scambia mai per un nuovo file da mettere in staging.
INGEST_COVERS_DIR = os.path.join(DATA_DIR, "ingest_covers")
AUTHORS_DIR = os.path.join(DATA_DIR, "authors")
BACKUPS_DIR = os.path.join(DATA_DIR, "backups")
USERS_DIR = os.path.join(DATA_DIR, "users")
# Font caricati dall'utente per il builder di temi avanzati (Impostazioni →
# Dizionari StarDict installati (Impostazioni → Integrazioni) — vedi
# services/stardict_service.py. Un dizionario è una sottocartella per lingua
# (es. "it/") con i file .ifo/.idx/.dict(.dz)/.syn dentro.
DICTIONARIES_DIR = os.path.join(DATA_DIR, "dictionaries")
LOGS_FILE = os.path.join(DATA_DIR, "server.log")

# The port a client on the LAN (KOReader, Calibre, Obsidian — none go through
# the frontend's nginx proxy) must use to reach this backend directly. Inside
# a container this is ALWAYS 8081 (see Dockerfile's EXPOSE/CMD) regardless of
# which host port docker-compose maps it to — so the actual value has to be
# handed in explicitly. docker-compose.yml sets this to the same BACKEND_PORT
# it uses for the host-side mapping, so the two can never drift apart.
PUBLIC_BACKEND_PORT = os.environ.get("PUBLIC_BACKEND_PORT", "8081")

# The reverse of PUBLIC_BACKEND_PORT: a client that only knows the backend's
# own address (any plugin — Calibre's "Naviga su Kolibre" is the first to
# need this) has no way to derive the frontend's port, since the two are
# independently mapped host ports with no fixed arithmetic relationship
# (docker-compose.yml's BACKEND_PORT/FRONTEND_PORT can be customized
# separately). Handed in the same way as PUBLIC_BACKEND_PORT.
PUBLIC_FRONTEND_PORT = os.environ.get("PUBLIC_FRONTEND_PORT", "8080")


def ensure_directories() -> None:
    for d in (LIBRARIES_DIR, PLUGINS_DIR, INGEST_DIR, INGEST_COVERS_DIR, AUTHORS_DIR, BACKUPS_DIR, USERS_DIR, DICTIONARIES_DIR):
        os.makedirs(d, exist_ok=True)


def library_path(name: str) -> str:
    return os.path.join(LIBRARIES_DIR, name)
