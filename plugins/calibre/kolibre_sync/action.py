#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
The real, Qt-dependent plugin implementation — loaded lazily by
KolibreSyncPlugin.load_actual_plugin (see __init__.py) once Calibre's GUI is
ready. Registers a single toolbar/menu action that opens the Kolibre Sync
window (main_dialog.KolibreMainDialog).
"""

if False:
    # Keeps a static checker from complaining about `get_icons`, a builtin
    # Calibre's zip plugin loader injects into this module's namespace at
    # import time (see calibre/customize/zipplugin.py's
    # CalibrePluginLoader.exec_module) — exactly the pattern used by
    # Calibre's own plugin tutorial (manual/plugin_examples/interface_demo/
    # ui.py). Never executed; `get_icons` really is a global by the time
    # genesis() below runs.
    get_icons = None

import re
import unicodedata
from difflib import SequenceMatcher

from calibre.ebooks.metadata import string_to_authors
from calibre.gui2 import error_dialog, question_dialog
from calibre.gui2.actions import InterfaceAction
from qt.core import QDialog

from .book_snapshot import snapshot_book_for_upload
from .client import KolibreApiError, KolibreClient
from .dialogs import ProgressDialog, SendToLibraryDialog
from .lingua import t
from .main_dialog import (
    KolibreMainDialog, _all_supported_local_columns, _ensure_server_custom_columns,
)
from .prefs import is_configured, prefs
from .workers import UploadWorker



# ── Affinita' fra due libri, come la calcola il server ───────────────────
#
# Porting riga per riga di backend/app/services/duplicates.py: stessa
# normalizzazione, stessa chiave d'autore, stessa soglia, stessa regola dei
# numeri. Tenerli d'accordo conta piu' della raffinatezza: un libro che il
# plugin lascia passare e che il server poi segnala come doppione e' lo
# stesso lavoro fatto due volte, e un plugin che segnala cose che il server
# non considera doppioni e' un plugin di cui non ci si fida piu'.
#
# Resta un confronto di METADATI, non di contenuto: l'hash vorrebbe scaricare
# ogni candidato, che vanificherebbe un'azione nata per essere rapida. Serve
# a dire "questo credo di averlo gia'", non a deciderlo.

_SOGLIA_AFFINITA = 0.85


def _normalizza(testo):
    """Titolo o autore ridotti alla forma confrontabile: via accenti,
    punteggiatura, articolo iniziale e spazi doppi."""
    t = unicodedata.normalize('NFD', testo or '')
    t = ''.join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r'[^\w\s]', ' ', t)
    t = re.sub(r'^(il|lo|la|i|gli|le|un|uno|una|the|a|an|l)\s+', '', t.strip())
    return re.sub(r'\s+', ' ', t).strip()


def _cognome(nome):
    """Il cognome dentro un nome d'autore. La virgola, per Calibre, non
    separa due autori (quello lo fa '&'): dentro un nome segna la forma
    d'ordinamento, e cio' che la precede e' il cognome — senza questo
    "Dostoevskij, Fedor" e "Fedor Dostoevskij" darebbero chiavi diverse."""
    grezzo = nome or ''
    if ',' in grezzo:
        grezzo = grezzo.split(',', 1)[0]
    parti = _normalizza(grezzo).split()
    return parti[-1] if parti else ''


def _chiave_autore(autore):
    """I cognomi degli autori, ordinati — "Fedor Dostoevskij" e "F.
    Dostoevskij" devono dare la stessa chiave."""
    nomi = list(autore) if isinstance(autore, (list, tuple)) else string_to_authors(autore or '')
    return '|'.join(sorted(filter(None, (_cognome(a) for a in nomi))))


# Collana, edizione, provenienza: "(Italian Edition)" e compagnia non dicono
# quale libro sia, ma in un confronto di somiglianza pesano come testo vero.
# Via prima del confronto — quelle CON cifre restano, perche' "(Vol. 2)"
# distingue due tomi e serve alla regola dei numeri.
_PARENTESI_SENZA_CIFRE = re.compile(r'\((?!\s*\d)[^()\d]*\)')


def _affinita_titoli(a, b):
    """Somiglianza fra due titoli, con la regola dei numeri: se entrambi
    contengono cifre e gli insiemi non coincidono non sono lo stesso libro,
    per quanto si somiglino ("Magazzino 00" e "Magazzino 07" stanno al 95%)."""
    na = _normalizza(_PARENTESI_SENZA_CIFRE.sub(' ', a or ''))
    nb = _normalizza(_PARENTESI_SENZA_CIFRE.sub(' ', b or ''))
    if not na or not nb:
        return 0.0
    ca, cb = re.findall(r'\d+', na), re.findall(r'\d+', nb)
    if ca and cb and sorted(int(x) for x in ca) != sorted(int(x) for x in cb):
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def _somiglia_a_qualcosa(libro, esistenti):
    """Il libro assomiglia a qualcosa che sulla libreria di destinazione c'e'
    gia'? Stesso autore (per cognomi) e titolo sopra soglia, come il server."""
    titolo = libro.get('title') or ''
    mia_chiave = _chiave_autore(libro.get('author') or libro.get('authors') or '')
    for altro in esistenti:
        # Senza una chiave d'autore da una delle due parti ci si accontenta
        # del titolo: e' il caso dell'autore sconosciuto, dove separare per
        # autore non separerebbe niente.
        sua_chiave = _chiave_autore(altro.get('author') or '')
        if mia_chiave and sua_chiave and mia_chiave != sua_chiave:
            continue
        if _affinita_titoli(titolo, altro.get('title') or '') >= _SOGLIA_AFFINITA:
            return True
    return False


class KolibreSyncAction(InterfaceAction):
    name = 'Kolibre Sync'
    # (text, icon, tooltip, keyboard shortcut) — the icon element stays None
    # here; it's set explicitly in genesis() below via get_icons(), exactly
    # like calibre's own plugin tutorial does, since action_spec is
    # evaluated at class-definition time (before get_icons is even
    # available) while genesis() runs later, once per plugin load.
    action_spec = ('Kolibre Sync', None, t('calibre.action.tooltip'), None)
    action_type = 'global'
    dont_add_to = frozenset(['context-menu-device'])

    def genesis(self):
        self.window = None
        self._send_worker = None
        self._send_progress = None
        # images/icon.png is the same Kolibre logo used by the web UI
        # (frontend/public/logo/kolibre_red_nobg.png), resized to a square
        # icon — see backend/app/api/tools.py's download_calibre_plugin,
        # which zips this whole source directory verbatim so the file
        # always ships with the plugin.
        icon = get_icons('images/icon.png', 'Kolibre Sync')  # noqa: F821 — injected by Calibre's zip loader
        if icon is not None:
            self.qaction.setIcon(icon)
        self.qaction.triggered.connect(self.show_dialog)

    def initialization_complete(self):
        # A single Calibre plugin zip can only ever register ONE
        # InterfaceAction (calibre.customize.zipplugin's loader picks
        # exactly one Plugin subclass per zip, sorted, first wins — verified
        # against a real install, not assumed) — so the book-context-menu
        # "Invia a libreria Kolibre…" command can't be a second, separate
        # action/plugin. Instead it's a plain QAction added directly to the
        # already-built context menu, which by this lifecycle point (after
        # every action's genesis()) is guaranteed to exist on library_view.
        try:
            menu = self.gui.library_view.context_menu
        except AttributeError:
            return
        menu.addSeparator()
        # Every other entry in this menu — Calibre's own built-ins and every
        # other installed plugin's (EpubMerge, KoServer Delivery, ...) —
        # carries an icon; this one didn't (reported directly, with a
        # screenshot showing it as the one plain-text row in an otherwise
        # all-iconed menu). Same icon as the toolbar button, not a second
        # asset — get_icons caches by name, so this is a cheap lookup, not
        # a second decode of the PNG.
        icon = get_icons('images/icon.png', 'Kolibre Sync')  # noqa: F821 — injected by Calibre's zip loader
        menu_label = t('calibre.action.menu_send_to_library')
        send_action = menu.addAction(icon, menu_label) if icon is not None else menu.addAction(menu_label)
        send_action.triggered.connect(self.send_selected_books_to_library)

        # Seconda voce, non una casella dentro la prima: e' un'azione che
        # CANCELLA, e deve costare un gesto diverso invece di nascondersi
        # dentro quello che si fa tutti i giorni. Senza icona, di proposito —
        # e' l'unica riga di questo menu che toglie qualcosa.
        move_label = t('calibre.action.menu_send_and_delete')
        move_action = menu.addAction(move_label)
        move_action.triggered.connect(self.send_selected_books_and_delete)

    def show_dialog(self):
        if self.window is None:
            self.window = KolibreMainDialog(self.gui, self.qaction.icon(), self.interface_action_base_plugin.do_user_config)
            self.window.finished.connect(self._on_dialog_closed)
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def _on_dialog_closed(self, _result):
        # Drop the reference so a fresh window (and a fresh library list
        # fetch) is built next time rather than resurrecting stale state.
        self.window = None

    # -- book context-menu: send selected book(s) to one server library ----

    def send_selected_books_to_library(self):
        """Invia i libri scelti a una biblioteca del server, e li lascia qui."""
        self._send_selected_books(elimina_dopo=False)

    def send_selected_books_and_delete(self):
        """Invia e poi toglie da Calibre i libri che sono arrivati.

        Per quando Calibre e' stato il banco di lavoro e non la casa: si apre
        l'EPUB, lo si sistema, lo si manda in biblioteca, e qui non serve piu'.

        Due cose non negoziabili, ed e' il motivo per cui questo non e' una
        casella dentro l'invio normale:

        1. Si cancella SOLO quello che e' davvero arrivato. Il worker riporta
           le coppie (id locale, id sul server) dei libri caricati: la
           cancellazione lavora su quelle, non sulla selezione di partenza.
           Un libro che non e' passato resta dov'e'.
        2. Si cancella DOPO, e mai durante. Se l'invio fallisce a meta', in
           Calibre non e' successo niente.

        La cancellazione passa per l'API di Calibre, quindi finisce dove
        finiscono le cancellazioni di Calibre — cestino compreso, dove c'e'.
        """
        self._send_selected_books(elimina_dopo=True)

    def _send_selected_books(self, elimina_dopo: bool = False):
        if not is_configured():
            error_dialog(
                self.gui, 'Kolibre Sync',
                t('calibre.send_to_library.not_configured'), show=True,
            )
            return

        book_ids = self.gui.library_view.get_selected_ids()
        if not book_ids:
            error_dialog(self.gui, 'Kolibre Sync', t('calibre.send_to_library.no_selection'), show=True)
            return

        db = self.gui.current_db.new_api
        # No pages-column picker here on purpose: this is the quick single-
        # book context-menu action (no options dialog at all, unlike the
        # full-library upload's UploadOptionsDialog) — mapping which local
        # custom column holds a page estimate needs a per-library choice
        # anyway (see UploadOptionsDialog's own comment on this), which
        # doesn't fit a one-click "send this book now" flow.
        #
        # selected_columns, unlike pages_column, is NOT a per-library choice
        # that needs a dialog — every locally-representable custom column is
        # simply sent, same as the incremental "Rileva variazioni" sync
        # already does (_apply_pairing_decisions). Previously this passed
        # selected_columns=None, meaning custom_values was ALWAYS empty for
        # a book sent via this exact context-menu action, regardless of what
        # it actually had (found investigating a real report that a Calibre
        # push didn't seem to preserve every metadata field) — full-library
        # upload and "Rileva variazioni" were never affected, only this path.
        local_columns = _all_supported_local_columns(db)
        books = []
        for book_id in book_ids:
            book = snapshot_book_for_upload(db, book_id, local_columns, pages_column=None)
            if book:
                books.append(book)
        if not books:
            error_dialog(
                self.gui, 'Kolibre Sync',
                t('calibre.send_to_library.no_format'),
                show=True,
            )
            return

        client = KolibreClient(prefs.get('server_url', ''), auth_token=prefs.get('auth_token', ''))
        picker = SendToLibraryDialog(client, len(books), self.qaction.icon(), self.gui)
        if picker.exec() != QDialog.DialogCode.Accepted:
            return
        folder = picker.selected_folder()
        if not folder:
            return

        # La conferma viene DOPO aver scelto la biblioteca, non prima: cosi'
        # la domanda puo' dire dove stanno andando, che e' l'informazione che
        # serve per rispondere.
        if elimina_dopo and not question_dialog(
            self.gui, t('calibre.send_and_delete.confirm_title'),
            t('calibre.send_and_delete.confirm_body', count=len(books), library=folder),
        ):
            return

        # Without this, the server's own column lookup silently drops any
        # "#label" value it doesn't recognize yet — no error, just gone, for
        # every book, forever (see _ensure_server_custom_columns' own
        # docstring). Best-effort and silent, no per-column failure dialog:
        # this action already has no options dialog at all, matching that
        # same "quick, no prompts" spirit rather than the full-library
        # upload's own per-failure info_dialog.
        _ensure_server_custom_columns(client, folder, local_columns)

        # Controllo doppioni, con lo STESSO criterio del server.
        #
        # Prima era un confronto di soli titoli, esatto dopo aver abbassato
        # le maiuscole: "Le Opere" e "Le opere, volume 1" non si
        # somigliavano per niente, e l'autore non lo guardava nessuno. Ora
        # usa la stessa affinita' di services/duplicates.py — titolo
        # normalizzato con SequenceMatcher sopra 0,85, piu' l'autore, piu' la
        # regola dei numeri: se entrambi i titoli contengono cifre e gli
        # insiemi non coincidono, non sono lo stesso libro ("Magazzino 00" e
        # "Magazzino 07" si somigliano al 95%).
        #
        # Resta un confronto di METADATI, non di contenuto: per l'hash
        # bisognerebbe scaricare ogni candidato, che vanificherebbe un'azione
        # nata per essere rapida. Serve a dire "questo credo di avercelo
        # gia'", non a deciderlo.
        try:
            existing = client.get_manifest(folder).get('books', [])
        except KolibreApiError:
            existing = []  # un controllo fallito non deve MAI bloccare l'invio
        duplicates = [
            book['title'] for book in books
            if _somiglia_a_qualcosa(book, existing)
        ]
        if duplicates:
            names = '\n'.join(f'• {title}' for title in duplicates)
            if not question_dialog(
                self.gui, t('calibre.send_to_library.duplicates_title'),
                t('calibre.send_to_library.duplicates_body', count=len(duplicates), names=names),
            ):
                return

        progress = ProgressDialog(t('calibre.send_to_library.progress_title'), self.gui)
        worker = UploadWorker(client, folder, books, fulltext_db_path=None, parent=self.gui)
        worker.progress.connect(progress.update_progress)
        worker.log.connect(progress.append_log)

        def on_ok(result):
            messaggio = t(
                'calibre.send_to_library.result',
                uploaded=result['uploaded'], failed=result['failed'], total=result['total'],
            )
            if elimina_dopo:
                # `links` sono le coppie (id locale, id sul server) dei libri
                # davvero caricati: si cancella quello, non la selezione di
                # partenza. Un libro che non e' passato resta dov'e'.
                ids_arrivati = [locale for locale, _remoto in (result.get('links') or [])]
                tolti, errore = self._elimina_da_calibre(ids_arrivati)
                if errore:
                    messaggio += ' ' + t('calibre.send_and_delete.delete_failed', error=errore)
                else:
                    messaggio += ' ' + t('calibre.send_and_delete.deleted', count=tolti)
            progress.set_finished(messaggio)

        worker.finished_ok.connect(on_ok)
        worker.finished_err.connect(lambda message: progress.set_finished(t('calibre.send_to_library.error', message=message)))
        progress.set_on_cancel(worker.cancel)
        # Kept alive on the action instance — a local variable would be
        # garbage-collected as soon as this method returns, well before the
        # QThread finishes (same reason KolibreMainDialog keeps self._worker/
        # self._list_worker around, and self.window above for the same class
        # of bug).
        self._send_worker = worker
        self._send_progress = progress
        worker.start()
        progress.exec()

    def _elimina_da_calibre(self, book_ids):
        """Toglie dalla biblioteca Calibre i libri indicati. (quanti, errore)

        Passa dalla vista invece che dall'API della cache per una ragione
        precisa: `library_view.model().delete_books` e' la stessa strada che
        prende il tasto Canc di Calibre, quindi rispetta il cestino quando c'e'
        e aggiorna la tabella da sola. Chiamare `db.remove_books` direttamente
        toglierebbe le righe lasciando la vista a mostrare libri che non
        esistono piu'.

        Non solleva: un invio riuscito non deve diventare un errore perche' la
        pulizia dopo e' andata storta. Il chiamante lo riporta nel riepilogo.
        """
        if not book_ids:
            return 0, None
        try:
            self.gui.library_view.model().delete_books_by_id(set(book_ids))
            return len(book_ids), None
        except Exception as exc:  # noqa: BLE001
            return 0, str(exc)
