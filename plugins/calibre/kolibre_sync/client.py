#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
HTTP client for the Kolibre server, stdlib-only (urllib.request), mirroring
the KOReader plugin's kolibre_api.lua in spirit (a thin JSON-in/JSON-out
wrapper plus raw streaming for downloads/uploads) but written against
Python's standard library rather than KOReader's bundled socket.http/ltn12,
since a Calibre Desktop plugin runs inside Calibre's embedded CPython, not
KOReader's Lua runtime. There is no concrete evidence in calibre-master's own
source that the `requests` package is bundled inside Calibre's embedded
Python (no plugin in the tree imports it), so this deliberately avoids it.

Every call here is synchronous and blocking — callers that must not freeze
the GUI (i.e. anything downloading/uploading a whole library) run this from
a QThread (see workers.py), never directly from a slot on the GUI thread.
"""

import json
import mimetypes
import os
import urllib.parse
import uuid
import urllib.error
import urllib.request

from .lingua import t

# Applies to calls whose whole purpose IS to answer "is the server there at
# all" (login, listing libraries) — these must fail fast with a clear message
# rather than tie up the caller for the full 30s default. Deliberately
# shorter than every other per-endpoint timeout in this file, all of which
# are for calls that legitimately take a while (a real download/upload), not
# for a first contact check.
REACHABILITY_TIMEOUT = 6.0


class KolibreApiError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class KolibreClient:
    def __init__(self, server_url: str, auth_token: str = '', timeout: float = 30.0):
        self.server_url = server_url.rstrip('/')
        self.auth_token = auth_token or ''
        self.timeout = timeout
        # A Kolibre server is always the user's own machine or LAN device —
        # never something reachable only through an HTTP proxy. Bypass any
        # system-configured proxy explicitly rather than relying on
        # urllib.request's default opener, which on macOS auto-detects
        # System Settings / environment proxies (via the stdlib's
        # _scproxy integration) and would otherwise route a LAN/localhost
        # request through an unrelated proxy (corporate VPN, Little
        # Snitch/Charles-style local proxy, etc.) if the user happens to
        # have one configured for other apps — a failure mode that would
        # affect Calibre's embedded Python but not necessarily curl/browser
        # traffic, since those often carry their own "bypass for local
        # addresses" exceptions that urllib does not apply the same way.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    # -- low level -----------------------------------------------------

    def _url(self, path: str) -> str:
        return self.server_url + path

    def _auth_headers(self) -> dict:
        return {'Authorization': f'Bearer {self.auth_token}'} if self.auth_token else {}

    def login(self, username: str, password: str) -> str:
        """
        POSTs to Kolibre's own /token (the same OAuth2-password-flow endpoint
        the web UI itself uses — see backend/app/auth.py) and returns the JWT
        access token on success. Raises KolibreApiError (status=401) on bad
        credentials, so callers can show a real "wrong username/password"
        message instead of a generic connection failure.
        """
        body = urllib.parse.urlencode({'username': username, 'password': password}).encode('utf-8')
        req = urllib.request.Request(
            self._url('/token'), data=body, method='POST',
            headers={'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'},
        )
        # _open_and_read, not a bare _open()+resp.read(): a stall during the
        # read phase (not just connecting) must also come back as
        # KolibreApiError — the same reasoning _open_and_read's own docstring
        # gives for every other endpoint in this file, which this one had
        # been missing.
        raw = self._open_and_read(req, timeout=REACHABILITY_TIMEOUT)
        data = json.loads(raw.decode('utf-8')) if raw else {}
        token = data.get('access_token')
        if not token:
            raise KolibreApiError(t('calibre.client.no_token'))
        self.auth_token = token
        return token

    def _open(self, request: urllib.request.Request, timeout=None):
        effective_timeout = timeout or self.timeout
        try:
            return self._opener.open(request, timeout=effective_timeout)
        except urllib.error.HTTPError as exc:
            detail = None
            try:
                body = exc.read()
                parsed = json.loads(body.decode('utf-8', 'replace'))
                detail = parsed.get('detail') if isinstance(parsed, dict) else None
            except Exception:
                pass
            raise KolibreApiError(detail or f'HTTP {exc.code} {exc.reason}', status=exc.code) from exc
        except urllib.error.URLError as exc:
            raise KolibreApiError(t('calibre.client.contact_failed', reason=exc.reason)) from exc
        except OSError as exc:
            # A socket-level timeout (socket.timeout, a plain OSError
            # subclass) reaching THIS FAR means it happened establishing the
            # connection itself — the far more common case, a slow server
            # response body, happens inside resp.read() calls AFTER this
            # method returns, which is why _open_and_read below exists: a
            # timeout during .read() used to escape as a raw, unwrapped
            # OSError that callers only ever caught as `KolibreApiError`,
            # which — for a multi-hundred-book upload/download loop in
            # workers.py — silently killed the ENTIRE remaining batch over
            # ONE slow book instead of just marking that one as failed.
            raise KolibreApiError(
                t('calibre.client.unreachable_timeout', timeout=effective_timeout, error=exc)
            ) from exc

    def _open_and_read(self, request: urllib.request.Request, timeout=None) -> bytes:
        """Like _open, but also performs the response read() inside the same
        try/except — see the OSError branch above for why this matters."""
        try:
            with self._open(request, timeout=timeout) as resp:
                return resp.read()
        except KolibreApiError:
            raise
        except OSError as exc:
            raise KolibreApiError(t('calibre.client.read_timeout', error=exc)) from exc

    def request_json(self, method: str, path: str, json_body=None, timeout=None):
        data = None
        headers = {'Accept': 'application/json', **self._auth_headers()}
        if json_body is not None:
            data = json.dumps(json_body).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        req = urllib.request.Request(self._url(path), data=data, headers=headers, method=method)
        raw = self._open_and_read(req, timeout=timeout)
        if not raw:
            return {}
        try:
            return json.loads(raw.decode('utf-8'))
        except ValueError:
            return {}

    # -- high level: reads ----------------------------------------------

    def list_libraries(self) -> list:
        # Same reachability logic as login(): this is typically the very
        # first request made after opening the dialog, so it must fail fast
        # rather than tie up the caller for the full default timeout.
        return self.request_json('GET', '/api/kolibre/library-transfer', timeout=REACHABILITY_TIMEOUT)

    def frontend_url(self) -> str:
        """
        server_url is the BACKEND's address (what every other method here
        talks to) — a human clicking "Naviga su Kolibre" needs the actual
        web UI's address instead, which lives on a different, independently
        configured port (see backend/app/api/tools.py::get_public_frontend_port
        and docker-compose.yml's FRONTEND_PORT/PUBLIC_FRONTEND_PORT pair).
        Falls back to server_url itself if the port lookup fails (an older
        server without this endpoint, or a genuine network hiccup) — wrong
        only in the same way this button always was before this existed,
        not a new failure mode.
        """
        try:
            port = self.request_json('GET', '/api/tools/frontend-port', timeout=REACHABILITY_TIMEOUT).get('port')
        except KolibreApiError:
            port = None
        if not port:
            return self.server_url
        parsed = urllib.parse.urlsplit(self.server_url)
        return f'{parsed.scheme}://{parsed.hostname}:{port}'

    def delete_remote_book(self, folder: str, book_id: int) -> dict:
        """
        DELETE /api/kolibre/books/{id}?library=... — the same endpoint the
        web UI itself uses to delete a book, reused as-is for the paired-
        library sync's 'delete_server' direction (a book removed locally
        that the user confirms removing from Kolibre too).
        """
        query = urllib.parse.urlencode({'library': folder})
        return self.request_json('DELETE', f'/api/kolibre/books/{book_id}?{query}')

    def update_book(self, book_id: int, library: str, fields: dict) -> dict:
        """
        PUT /api/kolibre/books/{id}?library=... — a partial update (only the
        keys present in `fields` are touched server-side, see
        backend/app/api/books.py::update_book). Used both for the mapped
        page-estimate column override (workers.py's UploadWorker, applied
        after the whole batch uploads) and by the paired-library diff/apply
        flow, so it belongs here rather than being duplicated in each caller.
        """
        query = urllib.parse.urlencode({'library': library})
        return self.request_json('PUT', f'/api/kolibre/books/{book_id}?{query}', fields)

    def get_manifest(self, folder: str) -> dict:
        return self.request_json('GET', f'/api/kolibre/library-transfer/{folder}/manifest', timeout=60)

    def download_to_file(self, path: str, dest_path: str, chunk_cb=None) -> int:
        """Streams a GET response straight to disk (books/covers/fulltext.db
        can be tens of MB — never buffered fully in memory). Returns the
        number of bytes written; raises KolibreApiError on any non-2xx."""
        req = urllib.request.Request(self._url(path), method='GET', headers=self._auth_headers())
        total = 0
        try:
            with self._open(req, timeout=120) as resp:
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                with open(dest_path, 'wb') as out:
                    while True:
                        chunk = resp.read(262144)
                        if not chunk:
                            break
                        out.write(chunk)
                        total += len(chunk)
                        if chunk_cb:
                            chunk_cb(total)
        except KolibreApiError:
            raise
        except OSError as exc:
            # Same reasoning as _open_and_read: a stall between chunks (slow
            # connection, large file) raises here, well outside _open's own
            # try/except, and must not escape as a raw/unwrapped exception —
            # see workers.py's per-book loops, which only catch KolibreApiError.
            raise KolibreApiError(t('calibre.client.download_timeout', error=exc)) from exc
        return total

    def try_download_to_file(self, path: str, dest_path: str) -> bool:
        """Same as download_to_file but treats a 404 as "not available"
        rather than an error — used for the optional fulltext.db sidecar,
        which most libraries won't have."""
        try:
            self.download_to_file(path, dest_path)
            return True
        except KolibreApiError as exc:
            if exc.status == 404:
                return False
            raise

    # -- aggiornamento del plugin stesso --

    def plugin_version(self) -> str:
        """
        La versione del plugin Calibre che il server ha in casa.

        Endpoint pubblico (come quelli dell'aggiornamento di KOReader):
        dice solo un numero di versione, e serve a poter rispondere "c'e'
        qualcosa di nuovo?" anche prima di aver fatto l'accesso.
        """
        data = self.request_json('GET', '/api/tools/plugins/calibre/version')
        return (data or {}).get('version') or t('calibre.client.unknown_version')

    def download_plugin_zip(self, dest_path: str) -> int:
        """
        Scarica lo zip del plugin — lo stesso che si scaricherebbe a mano
        dalla pagina Integrazioni, quindi non c'e' una seconda strada da
        tenere allineata. Richiede l'accesso, come ogni download.
        """
        return self.download_to_file('/api/tools/plugins/calibre', dest_path)

    # -- high level: library/column creation (reuses existing endpoints) --

    def create_library(self, name: str) -> None:
        self.request_json('POST', '/api/kolibre/libraries', {'name': name})

    def create_custom_column(self, folder: str, label: str, name: str, datatype: str, display: dict) -> None:
        self.request_json(
            'POST', f'/api/kolibre/custom-columns?library={folder}',
            {'label': label, 'name': name, 'datatype': datatype, 'display': display or {}},
        )

    def list_custom_columns(self, folder: str) -> list:
        return self.request_json('GET', f'/api/kolibre/custom-columns?library={folder}')

    def reindex_fulltext(self, folder: str) -> None:
        self.request_json('POST', f'/api/kolibre/fulltext/reindex?library={folder}')

    # -- high level: upload -----------------------------------------------

    @staticmethod
    def _build_book_multipart(metadata: dict, format_paths: dict, cover_path: str = None):
        """
        Shared by upload_book (POST, create) and update_remote_book (PUT,
        in-place edit) — same wire shape either way, only the HTTP method
        and URL differ. Whole files are read into memory to build the body —
        fine for typical ebook sizes (a handful to a few hundred MB); a
        fully streamed multipart encoder would need a custom http.client
        body writer, left as a known limitation (see plugin README notes /
        the task report) since Kolibre's own device-backup upload endpoint
        makes the same simplifying trade-off server-side.
        """
        boundary = uuid.uuid4().hex
        parts = []

        def add_field(name, value):
            parts.append(
                (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n')
                .encode('utf-8')
            )

        add_field('metadata', json.dumps(metadata))

        for fmt, path in (format_paths or {}).items():
            filename = os.path.basename(path)
            ctype = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
            with open(path, 'rb') as f:
                data = f.read()
            header = (
                f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{filename}"\r\n'
                f'Content-Type: {ctype}\r\n\r\n'
            ).encode('utf-8')
            parts.append(header + data + b'\r\n')

        if cover_path and os.path.exists(cover_path):
            with open(cover_path, 'rb') as f:
                data = f.read()
            header = (
                f'--{boundary}\r\nContent-Disposition: form-data; name="cover"; filename="cover.jpg"\r\n'
                'Content-Type: image/jpeg\r\n\r\n'
            ).encode('utf-8')
            parts.append(header + data + b'\r\n')

        parts.append(f'--{boundary}--\r\n'.encode('utf-8'))
        return b''.join(parts), boundary

    def upload_book(self, folder: str, metadata: dict, format_paths: dict, cover_path: str = None) -> dict:
        """
        metadata: {"title", "author", "series_index"?, "custom_values": {"#label": value, ...}}
        format_paths: {"EPUB": "/local/path/book.epub", ...}
        """
        body, boundary = self._build_book_multipart(metadata, format_paths, cover_path)
        req = urllib.request.Request(
            self._url(f'/api/kolibre/library-transfer/{folder}/books'),
            data=body, method='POST',
            headers={
                'Content-Type': f'multipart/form-data; boundary={boundary}',
                'Content-Length': str(len(body)),
                'Accept': 'application/json',
                **self._auth_headers(),
            },
        )
        raw = self._open_and_read(req, timeout=180)
        return json.loads(raw.decode('utf-8')) if raw else {}

    def upload_fulltext_db(self, folder: str, path: str) -> dict:
        with open(path, 'rb') as f:
            data = f.read()
        req = urllib.request.Request(
            self._url(f'/api/kolibre/library-transfer/{folder}/fulltext-db'),
            data=data, method='POST',
            headers={
                'Content-Type': 'application/octet-stream',
                'Content-Length': str(len(data)),
                **self._auth_headers(),
            },
        )
        raw = self._open_and_read(req, timeout=120)
        return json.loads(raw.decode('utf-8')) if raw else {}
