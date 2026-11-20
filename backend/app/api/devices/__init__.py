"""
Il pacchetto dei dispositivi: un mestiere per modulo, le stesse rotte di prima.

Fino al 20/11/2026 tutto questo era un file solo, api/devices.py: ~4.300
righe, 61 rotte, tre router e almeno sei mestieri uno sopra l'altro. Il
trasloco (punto A1 della revisione del 19/11, approvato: «senza cambiare il
contenuto, solo ordinare e documentare») lo spacca per mestiere SENZA
cambiare nessuna rotta: stessi percorsi, stessi metodi, stessi modelli di
risposta, corpi delle funzioni identici all'originale.

La mappa del pacchetto:
* _shared.py       — i tre router e gli attrezzi usati da piu' mestieri;
* management.py    — la gestione del parco dispositivi (webapp, JWT);
* sync.py          — il protocollo di sincronizzazione (plugin, token di
                     dispositivo); il disegno d'insieme sta in
                     docs/storico/come-un-dispositivo-parla-con-il-server.md;
* catalog.py       — il catalogo sfogliato dal dispositivo;
* annotations.py   — le annotazioni spinte dal dispositivo;
* flagged_books.py — i file da riconoscere: segnalazioni e accoppiamento;
* readings.py      — posizione di lettura e letture in caratteri;
* backups_stats.py — backup del dispositivo e statistiche di KOReader;
* dictionaries.py  — i dizionari StarDict verso il dispositivo;
* diagnostics.py   — diagnostica, ripristino da backup, inventario.

I tre router nascono in _shared.py; ogni modulo importato qui sotto ci
appende le sue rotte, e main.py continua a vedere `devices.router`,
`devices.sync_router` e `devices.device_token_router` come quando erano in
un file solo. L'ordine di registrazione delle rotte dentro ciascun router
e' cambiato (segue l'ordine dei moduli qui sotto, non piu' l'ordine del
vecchio file): e' innocuo perche' nessuna coppia di rotte si ombreggia —
lo dimostra, per sempre, backend/prove/le_rotte_dei_dispositivi_non_si_ombreggiano.py.

Questo __init__ riesporta anche TUTTI i nomi di primo livello del vecchio
modulo, helper con l'underscore compresi: per le prove e per chiunque
faccia `from app.api import devices; devices.qualcosa`, il trasloco e'
invisibile. `__all__` qui sotto e' la dichiarazione esplicita di quel
contratto (e tiene buono pyflakes sui re-import).
"""

from ._shared import (
    router, sync_router, device_token_router, _SAFE_BACKUP_FILENAME,
    _SENDABLE_STATUSES, _SYNC_HISTORY_KEEP, _get_open_restore_request,
    _serialize_restore_request, _dizionari_in_coda, _get_owned_device,
    _parse_koreader_datetime, _upsert_orphan_highlight,
    _utente_del_dispositivo, _migrate_orphan_highlights,
    _migrate_device_highlights_to_new_book,
)
from .management import (
    register_device, _book_progress_percent, _build_book_titles,
    _build_hash_verified_map, _patch_riportate, list_devices,
    get_own_device, update_device, delete_device, set_default_device,
    queue_book_for_device, forget_device_vocabulary,
    get_device_sync_history, _get_owned_device_book,
    acknowledge_book_removal, cancel_pending_book_action,
    pair_device_book,
)
from .sync import (
    _STICKY_STATUSES, _SYNC_SESSION_BLOCK_WINDOW,
    _SYNC_SESSION_ABANDON_AFTER, _library_token, _get_history_session,
    _adopt_managed_books, _mark_missing_books, _stime_delle_pagine,
    _build_sends, _stime_per_il_manifesto, _consegne_per_il_manifesto,
    _build_removes, _build_file_actions, list_libraries_for_device,
    list_sibling_devices, device_capabilities, koreader_sync_handshake,
    _legacy_sync_handshake, koreader_sync_ack, koreader_sync_finish,
    ack_file_actions, push_device_pages, report_book_removed,
    report_book_delivered, koreader_sync_confirm,
)
from .catalog import (
    _fold_accents, _FUZZY_MATCH_THRESHOLD, _PUNCTUATION_RE,
    _WHITESPACE_RE, _TITLE_SORT_ARTICLES, _TITLE_SORT_SUFFIX_RE,
    _reorder_title_sort_article, _normalize_for_fuzzy, _fuzzy_ratio,
    _bucket_counts, catalog_sections, _stima_dal_libro,
    _serialize_catalog_book, _device_book_ids_on_device,
    catalog_discover, browse_catalog,
)
from .annotations import (
    push_device_annotations, reconcile_device_annotations,
    auto_pair_orphan_annotations, _risolvi_per_percorso_dispositivo,
)
from .flagged_books import (
    scan_unmatched_books, report_flagged_book, identify_device_file,
    list_flagged_books, _get_owned_flagged_book, delete_flagged_book,
    queue_flagged_book_action, bulk_queue_flagged_book_action,
)
from .readings import (
    push_reading_progress, pull_reading_progress, device_letture_state,
    upload_letture_incremental,
)
from .backups_stats import (
    _file_md5, device_backup_state, upload_device_backup,
    device_stats_state, upload_stats_incremental, list_device_backups,
    download_device_backups, _elimina_zip_temporaneo,
)
from .dictionaries import (
    _scrivi_dizionari_in_coda, accoda_dizionario_per_dispositivo,
    annulla_dizionario_per_dispositivo,
    conferma_dizionario_dal_dispositivo, dictionary_manifest_for_device,
    dictionary_file_for_device,
)
from .diagnostics import (
    confirm_device_restore_request, cancel_device_restore_request,
    create_device_restore_request, download_restore_request_file,
    complete_device_restore_request, _MAX_DIAGNOSTIC_BYTES,
    _diagnostics_dir, upload_diagnostic_log, list_device_diagnostics,
    read_device_diagnostic, _intero, _frazione, _riga_di_inventario,
    _identita_di, _conferma_il_nome, _inventario_raggruppato,
    ricevi_inventario, inventario_del_dispositivo,
)

__all__ = [
    "router", "sync_router", "device_token_router",
    "_SAFE_BACKUP_FILENAME", "_SENDABLE_STATUSES", "_SYNC_HISTORY_KEEP",
    "_get_open_restore_request", "_serialize_restore_request",
    "_dizionari_in_coda", "_get_owned_device",
    "_parse_koreader_datetime", "_upsert_orphan_highlight",
    "_utente_del_dispositivo", "_migrate_orphan_highlights",
    "_migrate_device_highlights_to_new_book", "register_device",
    "_book_progress_percent", "_build_book_titles",
    "_build_hash_verified_map", "_patch_riportate", "list_devices",
    "get_own_device", "update_device", "delete_device",
    "set_default_device", "queue_book_for_device",
    "forget_device_vocabulary", "get_device_sync_history",
    "_get_owned_device_book", "acknowledge_book_removal",
    "cancel_pending_book_action", "pair_device_book",
    "_STICKY_STATUSES", "_SYNC_SESSION_BLOCK_WINDOW",
    "_SYNC_SESSION_ABANDON_AFTER", "_library_token",
    "_get_history_session", "_adopt_managed_books",
    "_mark_missing_books", "_stime_delle_pagine", "_build_sends",
    "_stime_per_il_manifesto", "_consegne_per_il_manifesto",
    "_build_removes", "_build_file_actions",
    "list_libraries_for_device", "list_sibling_devices",
    "device_capabilities", "koreader_sync_handshake",
    "_legacy_sync_handshake", "koreader_sync_ack",
    "koreader_sync_finish", "ack_file_actions", "push_device_pages",
    "report_book_removed", "report_book_delivered",
    "koreader_sync_confirm", "_fold_accents", "_FUZZY_MATCH_THRESHOLD",
    "_PUNCTUATION_RE", "_WHITESPACE_RE", "_TITLE_SORT_ARTICLES",
    "_TITLE_SORT_SUFFIX_RE", "_reorder_title_sort_article",
    "_normalize_for_fuzzy", "_fuzzy_ratio", "_bucket_counts",
    "catalog_sections", "_stima_dal_libro", "_serialize_catalog_book",
    "_device_book_ids_on_device", "catalog_discover", "browse_catalog",
    "push_device_annotations", "reconcile_device_annotations",
    "auto_pair_orphan_annotations", "_risolvi_per_percorso_dispositivo",
    "scan_unmatched_books", "report_flagged_book",
    "identify_device_file", "list_flagged_books",
    "_get_owned_flagged_book", "delete_flagged_book",
    "queue_flagged_book_action", "bulk_queue_flagged_book_action",
    "push_reading_progress", "pull_reading_progress",
    "device_letture_state", "upload_letture_incremental", "_file_md5",
    "device_backup_state", "upload_device_backup", "device_stats_state",
    "upload_stats_incremental", "list_device_backups",
    "download_device_backups", "_elimina_zip_temporaneo",
    "_scrivi_dizionari_in_coda", "accoda_dizionario_per_dispositivo",
    "annulla_dizionario_per_dispositivo",
    "conferma_dizionario_dal_dispositivo",
    "dictionary_manifest_for_device", "dictionary_file_for_device",
    "confirm_device_restore_request", "cancel_device_restore_request",
    "create_device_restore_request", "download_restore_request_file",
    "complete_device_restore_request", "_MAX_DIAGNOSTIC_BYTES",
    "_diagnostics_dir", "upload_diagnostic_log",
    "list_device_diagnostics", "read_device_diagnostic", "_intero",
    "_frazione", "_riga_di_inventario", "_identita_di",
    "_conferma_il_nome", "_inventario_raggruppato", "ricevi_inventario",
    "inventario_del_dispositivo",
]
