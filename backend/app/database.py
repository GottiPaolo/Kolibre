import os
from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from .config import DATA_DIR

# Il percorso predefinito sta DENTRO DATA_DIR, non nella cartella di lancio.
# Fino al 20/11/2026 era "sqlite:///./app.db", relativo a dove si lancia il
# processo: in container non si vedeva mai (docker-compose.yml imposta
# DATABASE_URL esplicitamente), ma in locale run_backend.sh parte dalla
# radice del repo, e il database nasceva LI' — e' cosi' che alla radice e'
# rimasto un app.db fantasma del 23/09, scollegato dai dati veri che stanno
# in DATA_DIR (difetto C5 della revisione del 19/11). DATA_DIR e' gia'
# assoluto (config.py lo passa per os.path.abspath), quindi il default non
# dipende piu' dalla cartella di lancio.
_DEFAULT_DB_URL = "sqlite:///" + os.path.join(DATA_DIR, "app.db")

DB_PATH = os.environ.get("DATABASE_URL", _DEFAULT_DB_URL)

# SQLite crea il file ma non la cartella che lo contiene: all'avvio normale
# ci pensa config.ensure_directories() (chiamata nel lifespan prima della
# prima connessione), ma uno script che importa questo modulo e si connette
# senza passare dal lifespan fallirebbe su un DATA_DIR mai nato.
if DB_PATH == _DEFAULT_DB_URL:
    os.makedirs(DATA_DIR, exist_ok=True)

engine = create_engine(
    DB_PATH, connect_args={"check_same_thread": False}
)

# Enable WAL mode and busy timeout for SQLite to ensure safe concurrent write queues
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
