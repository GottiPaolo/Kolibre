#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Kolibre — Calibre Desktop plugin.
# Copyright (C) 2026 Paolo Gotti. GNU AGPL-3.0-or-later; see the LICENSE and
# NOTICE files in the Kolibre repository.
"""
Kolibre Sync — Calibre Desktop plugin.

This top-level module is intentionally metadata-only and MUST NOT import Qt
(directly or transitively): Calibre's zip plugin loader instantiates
InterfaceActionBase subclasses to read their name/version/description before
the GUI (and therefore Qt) is necessarily ready — see
calibre/customize/zipplugin.py's _locate_code() and
calibre/gui2/init.py's plugin-loading sequence. The real, Qt-dependent
InterfaceAction implementation lives in action.py and is loaded lazily via
`actual_plugin` below, exactly like every built-in Calibre action (see
calibre/customize/builtins.py, e.g. `ActionAdd.actual_plugin =
'calibre.gui2.actions.add:AddAction'`).
"""

from calibre.customize import InterfaceActionBase

from .lingua import t


class KolibreSyncPlugin(InterfaceActionBase):
    name = 'Kolibre Sync'
    description = t('calibre.plugin.description')
    supported_platforms = ['windows', 'osx', 'linux']
    author = 'Kolibre'
    # 2.0.0 e non 1.4.0: sono sparite delle funzioni, non ne sono arrivate.
    # L'accoppiamento fra libreria locale e libreria del server, con tutto il
    # confronto bidirezionale che ne dipendeva, non esiste piu'.
    #
    # 2.1.0: «Invia a Kolibre ed elimina da qui». Il numero va alzato ANCHE
    # per questo: il server legge la versione da questo file per rispondere
    # «c'e' qualcosa di nuovo?», quindi senza un numero diverso chi ha gia' il
    # plugin installato non saprebbe mai che c'e'.
    version = (2, 1, 0)
    minimum_calibre_version = (5, 0, 0)

    # module:ClassName resolved lazily by load_actual_plugin(gui) — see
    # InterfaceActionBase.load_actual_plugin in calibre/customize/__init__.py.
    actual_plugin = 'calibre_plugins.kolibre_sync.action:KolibreSyncAction'

    def is_customizable(self):
        # Configuration (server address, nome/cognome) lives in the plugin's
        # own dialog (gear icon), not in Calibre's generic "Customize plugin"
        # text box — a JSONConfig-backed settings dialog is a much better fit
        # for multiple structured fields than the single free-text string
        # Calibre's built-in customization mechanism offers.
        return False
