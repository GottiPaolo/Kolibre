#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Persistent plugin configuration, stored by Calibre itself under its own
config directory (~/.config/calibre/plugins/kolibre_sync.json on Linux, the
platform-equivalent elsewhere) via calibre.utils.config.JSONConfig — the
standard mechanism third-party Calibre plugins use for settings, so this
survives Calibre restarts/updates without the plugin managing its own file.

Kolibre's /api/kolibre/library-transfer/* endpoints require the same JWT
login as the web UI (see backend/app/auth.py's get_current_user_flexible),
so this plugin needs a real username/password login, not just a free-text
"nome e cognome" label — an earlier version of this file asked for a first
and last name instead, which made no sense once those endpoints actually
started requiring authentication: a name isn't a credential. The login
itself happens in dialogs.py's SettingsDialog (via KolibreClient.login),
which then stores the resulting JWT here — never the raw password.

Pre-baked config at download time: GET /api/tools/plugins/calibre accepts
optional ?server_url=&username=&token= query params (see
backend/app/api/tools.py's download_calibre_plugin) and, when any is given,
writes a small "kolibre_preconfig.json" resource into the zip at its root
(sibling to this file, not nested — this plugin's zip layout has no
"kolibre_sync/" prefix). That file is NOT a drop-in replacement for the real
settings storage below: JSONConfig persists to a file in Calibre's OWN user
config directory (outside the plugin's zip/folder entirely), so there is no
path we could bake the resource into that JSONConfig would pick up by
itself. Instead, _apply_bundled_preconfig() below reads the bundled resource
via `get_resources` — a function Calibre's zip plugin loader injects into
every plugin module's namespace at import time (see
calibre/customize/zipplugin.py's CalibrePluginLoader.exec_module, which sets
`module.__dict__['get_resources'] = partial(get_resources, zfp)` before
exec'ing the module's code) — and copies its values into the real `prefs`
JSONConfig, but only the first time this module is imported in a given
Calibre session AND only if the user hasn't already configured (or
reconfigured) the plugin by hand, so a stale bundled file from an old
download can never clobber live settings. A pre-baked download hands over an
already-issued token (the SAME pattern the KOReader plugin's gconfig.lua
uses — a real credential, not a password), never a plaintext password.
"""

import json

from calibre.utils.config import JSONConfig

from .lingua import t

prefs = JSONConfig('plugins/kolibre_sync')

prefs.defaults['server_url'] = ''
# Independently overridable: server_url is the BACKEND's address, but the
# "Naviga su Kolibre" button needs the actual web UI's address, which lives
# on its own separately-configured port (see client.py::frontend_url) and
# isn't always auto-detectable from the backend alone (e.g. Docker port
# remapping where the two are reachable on different mapped ports than the
# containers' own). Empty means "keep auto-detecting at runtime", the
# original behavior — never a value silently assumed here.
prefs.defaults['frontend_url'] = ''
prefs.defaults['username'] = ''
prefs.defaults['auth_token'] = ''
# Fingerprint of the last bundled kolibre_preconfig.json this plugin actually
# applied — see _apply_bundled_preconfig below for why this exists instead of
# a plain "already configured?" check.
prefs.defaults['_applied_preconfig_raw'] = ''


def is_configured() -> bool:
    return bool(prefs.get('server_url')) and bool(prefs.get('auth_token'))


def _apply_bundled_preconfig() -> None:
    """
    Originally this skipped entirely once is_configured() was true — meant to
    stop a stale bundled file from clobbering settings the user had since
    changed by hand. In practice it did the opposite of what a re-download is
    for: Calibre's JSONConfig persists in Calibre's OWN config dir, completely
    outside the plugin's zip, so it survives every reinstall — a user who
    downloads a FRESH, correctly pre-configured zip after having used any
    earlier version (even one configured wrong, or a plain unconfigured
    install used with a local test server) would have that new config
    silently discarded, with no visible sign why: the plugin just kept using
    whatever server_url happened to be sitting in Calibre's config already.
    Comparing raw bytes against the last-applied bundle's own fingerprint
    fixes both cases: a genuinely NEW download (different bytes) still wins
    over a manual edit made in between, since re-downloading with fresh
    credentials baked in is an explicit, deliberate reconfiguration — but
    Calibre simply re-importing this SAME already-applied zip on every
    restart (identical bytes) won't re-clobber a manual edit made since.
    """
    try:
        # `get_resources` only exists in this module's namespace when it was
        # actually loaded from a Calibre plugin zip (see module docstring);
        # NameError below covers any other import context (e.g. a future
        # non-zip install, or this file being imported directly for testing).
        raw = get_resources(  # noqa: F821 — injected by Calibre's zip loader
            'kolibre_preconfig.json', print_tracebacks_for_missing_resources=False,
        )
    except NameError:
        return
    if not raw:
        return  # normal case for a plain (non pre-configured) download
    raw_str = raw.decode('utf-8', 'replace')
    if raw_str == prefs.get('_applied_preconfig_raw'):
        return  # this exact bundle was already applied once — don't reapply
    try:
        data = json.loads(raw_str)
    except ValueError:
        return
    if not isinstance(data, dict):
        return
    server_url = data.get('server_url')
    if server_url:
        prefs['server_url'] = normalize_server_url(str(server_url))
    frontend_url = data.get('frontend_url')
    if frontend_url:
        prefs['frontend_url'] = normalize_server_url(str(frontend_url))
    username = data.get('username')
    if username:
        prefs['username'] = str(username).strip()
    token = data.get('token')
    if token:
        prefs['auth_token'] = str(token).strip()
    prefs['_applied_preconfig_raw'] = raw_str


def display_name() -> str:
    return prefs.get('username') or t('calibre.prefs.default_display_name')


def normalize_server_url(raw: str) -> str:
    """"http://192.168.1.10:8081/" -> "http://192.168.1.10:8081" — mirrors
    KolibreApi.normalizeServerUrl in the KOReader plugin's kolibre_api.lua."""
    url = (raw or '').strip()
    if not url:
        return ''
    if not url.startswith(('http://', 'https://')):
        url = 'http://' + url
    return url.rstrip('/')


# Runs once, the first time this module is imported in a given Calibre
# session (Python caches modules — a second `import prefs` elsewhere is a
# no-op here). Must be the last statement in the file: it calls
# normalize_server_url above, which has to already be bound in this
# module's namespace by the time it runs.
_apply_bundled_preconfig()
