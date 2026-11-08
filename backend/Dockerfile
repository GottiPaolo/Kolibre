# Build context is the REPO ROOT (not backend/ alone) — the app is imported
# as the "backend.app.main" package, exactly like run_backend.sh already
# invokes it locally (venv/bin/python3 -m uvicorn backend.app.main:app).
FROM python:3.11-slim

WORKDIR /app

# Calibre fornisce il binario ebook-convert usato dall'endpoint di
# conversione formati (backend/app/services/converter.py, che lo trova in
# /usr/bin/ebook-convert). +~600MB, scelta deliberata: la conversione dei
# formati vale il peso dell'immagine, ma è una decisione da rivedere se un
# giorno la conversione uscisse dal progetto.
# Via apt anziché installer ufficiale calibre-ebook.com: su python:3.11-slim
# apt risolve da solo tutte le dipendenze runtime (Qt/X headless ecc.),
# mentre l'installer binario richiederebbe wget+xz e un elenco manuale di
# librerie di sistema — più fragile da mantenere. Fatto PRIMA del pip install
# così i rebuild per soli cambi di codice/requirements riusano questo layer.
# fonts-dejavu-core: il font serif con cui si disegnano le copertine dei
# libri che non ne hanno (services/cover_builder.py). Calibre si porta dietro
# dei font per conto suo, ma su quali non c'e' nessuna garanzia, e senza un
# TTF vero PIL ripiega sul suo font bitmap — leggibile a fatica. Un megabyte
# per non dover sperare.
RUN apt-get update \
    && apt-get install -y --no-install-recommends calibre fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/
# tools.py resolves the plugin source dirs as repo_root/plugins/... (three
# levels up from backend/app/api/tools.py) — without this, downloading any
# plugin 404s inside the container even though it works from a local checkout.
COPY plugins/ plugins/

# DATA_DIR/DATABASE_URL point at the mounted volume — set by docker-compose,
# not baked in here, so the same image works with whatever host path the
# user chose in .env.
ENV PYTHONUNBUFFERED=1

EXPOSE 8081

# Uses the interpreter already in the image — no extra package (curl/wget)
# needed just for a healthcheck.
#
# /api/kolibre/version e non /api/kolibre/libraries: da quando
# l'autenticazione e' applicata a livello di router (main.py), libraries
# risponde 401 a chi non ha un token — urlopen alza HTTPError, il
# healthcheck fallisce, il container resta "unhealthy" e con lui non parte
# nemmeno il frontend, che dipende da questo. /version e' pubblico apposta
# ed e' l'unico endpoint pensato per essere interrogato senza credenziali.
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
    CMD ["python3", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8081/api/kolibre/version', timeout=3)"]

# No --reload here (that's run_backend.sh's dev-only behavior) — a production
# container should serve exactly what was built into the image.
CMD ["python3", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8081"]
