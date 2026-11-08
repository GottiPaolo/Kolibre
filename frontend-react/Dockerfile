# Stesso pattern multi-stage di frontend/Dockerfile (Node solo per la build,
# l'immagine finale è nginx puro). Differenza voluta rispetto a quello:
# nessun reverse proxy verso il backend qui — vedi nginx.conf per il perché
# (CORS già aperto, il browser chiama il backend direttamente). I tipi
# generati da OpenAPI (src/api/schema.d.ts) sono già committati nel
# repository, quindi questa build non ha bisogno di un backend live.
# Bug reale corretto qui: senza questo ARG, il browser in produzione
# chiamava sempre la porta di DEFAULT (8081) — Vite la "cuoce" nel bundle a
# build time, un valore letto a runtime da import.meta.env non esiste.
# Se l'host aveva personalizzato BACKEND_PORT nel .env, ogni richiesta
# (login compreso) andava alla porta sbagliata e falliva silenziosamente,
# mascherata lato UI come "credenziali non valide".
FROM node:20-alpine AS build
WORKDIR /app
ARG VITE_BACKEND_PORT=8081
ENV VITE_BACKEND_PORT=$VITE_BACKEND_PORT
# Version string baked into this build — same mechanism as VITE_BACKEND_PORT
# above, substituted into the bundle at build time. Falls back to "dev" when
# unset (local `npm run dev`, or a build that doesn't pass the ARG).
ARG VITE_KOLIBRE_VERSION=dev
ENV VITE_KOLIBRE_VERSION=$VITE_KOLIBRE_VERSION
COPY package.json package-lock.json .npmrc ./
RUN npm ci
COPY . .
# Cotto nel bundle come VITE_BACKEND_PORT sopra — non esiste ancora un vero
# numero di versione per la GUI web, ma un orario di build permette di
# vedere a colpo d'occhio se un deploy è andato davvero a buon fine.
RUN VITE_BUILD_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)" npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

# "localhost" risolve su ::1 (IPv6) dentro il container, ma nginx.conf
# ascolta solo IPv4 ("listen 80;") — l'healthcheck otteneva sempre
# Connection refused. 127.0.0.1 forza IPv4, che nginx ascolta davvero.
HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=5 \
    CMD ["wget", "--quiet", "--spider", "http://127.0.0.1/"]
