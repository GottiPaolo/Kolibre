import secrets
from datetime import datetime

from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Float, LargeBinary, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from .database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    fullname = Column(String, nullable=True)
    photo_url = Column(String, nullable=True)
    is_admin = Column(Boolean, default=False)
    # ── Permessi legati all'ACCOUNT ──────────────────────────────────────
    #
    # Distinti da quelli legati alla coppia utente-biblioteca
    # (LibraryPermission qui sotto): rispondono a domande di tipo diverso.
    # "Posso modificare questa biblioteca?" dipende da quale biblioteca;
    # "posso crearne una?" no.
    #
    # Il fondatore ha un flag suo e non e' "l'utente con id 1": scelta del
    # 28/09/2026. Un id non e' un ruolo — basta una migrazione che
    # rinumera, o un primo utente cancellato, perche' il proprietario
    # dell'impianto diventi qualcun altro senza che nessuno l'abbia deciso.
    is_founder = Column(Boolean, default=False, nullable=False)
    can_create_libraries = Column(Boolean, default=False, nullable=False)
    can_create_users = Column(Boolean, default=False, nullable=False)
    can_manage_permissions = Column(Boolean, default=False, nullable=False)
    can_register_devices = Column(Boolean, default=True, nullable=False)
    # Gli autori sono UNA tabella per tutte le biblioteche (decisione del
    # 28/09: l'autore e' un fatto del mondo, non della tua biblioteca),
    # quindi modificarli e' un permesso dell'account e non della
    # condivisione — non avrebbe senso poter correggere la biografia di
    # Dostoevskij "solo dentro la biblioteca di Anna".
    can_edit_authors = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    devices = relationship("Device", back_populates="user", cascade="all, delete-orphan")
    highlights = relationship("Highlight", back_populates="user", cascade="all, delete-orphan")
    reading_sessions = relationship("ReadingSession", back_populates="user", cascade="all, delete-orphan")

class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, index=True)
    device_token = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    model = Column(String, nullable=False)
    hardware_id = Column(String, nullable=True)  # physical device id reported by KOReader, distinct from our own PK
    is_default = Column(Boolean, default=False)
    last_sync_at = Column(DateTime, nullable=True)
    last_backup_at = Column(DateTime, nullable=True)
    # Spazio del volume che ospita i libri, in byte, misurato dal plugin
    # (util.diskUsage su books_dir) a ogni handshake dalla v0.6.15. Prima
    # esisteva solo storage_used e nessuno l'ha mai riempito: la scheda del
    # dispositivo ha detto "non riportato" per tutta la vita del campo.
    storage_used = Column(Integer, nullable=True)
    storage_total = Column(Integer, nullable=True)
    storage_available = Column(Integer, nullable=True)
    # Le userpatch che il dispositivo ha nella sua cartella `patches/`, come
    # il plugin le riporta a ogni handshake: un JSON `[{"file":…,"sha256":…}]`.
    #
    # **Perche' l'impronta e non la versione dichiarata.** Una patch
    # modificata senza cambiarle nome ne' numero — cioe' il caso normale
    # mentre la si sviluppa — dev'essere riconosciuta come «da aggiornare»,
    # e solo l'impronta lo dice.
    #
    # **Perche' una colonna di testo e non una tabella.** Non e' uno stato che
    # il server possiede: e' una fotografia di cosa c'era sul dispositivo
    # l'ultima volta che si e' fatto vivo, e vale solo insieme a
    # `last_sync_at`. Una tabella suggerirebbe che sia un registro con una
    # storia, e non lo e'.
    #
    # NULL vuol dire **«il dispositivo non lo ha detto»** (plugin piu'
    # vecchio), che e' diverso da «nessuna patch installata»: la scheda
    # distingue i due casi, come fa gia' per lo spazio su disco.
    patch_installate = Column(String, nullable=True)
    # I dizionari che si e' chiesto dal portale di mandare a QUESTO lettore
    # (JSON, elenco di codici di lingua: `["it","en"]`). E' una coda, non uno
    # stato: il dispositivo la svuota man mano che li installa.
    #
    # Perche' una coda e non un comando immediato: il server non puo'
    # raggiungere un e-reader — e' il lettore che si fa vivo, quando ha la
    # rete e quando e' accesso. Qualunque "manda adesso" sarebbe una bugia.
    # NULL o vuoto vogliono dire la stessa cosa qui ("niente da mandare"),
    # al contrario di patch_installate: quella e' un'informazione che il
    # dispositivo riporta, e li' "non lo ha detto" conta.
    dizionari_richiesti = Column(String, nullable=True)
    # On-device layout the KOReader plugin uses when downloading books — a
    # purely device-local filesystem concern, unrelated to the server-side
    # Calibre library layout (which always stays one-folder-per-book).
    # "author": <books_dir>/<Author>/<Title> (id).<ext> — one folder per
    #   author holding all their books directly (no per-book subfolder).
    # "flat": <books_dir>/<Title> (id).<ext>, no subfolders at all.
    folder_layout = Column(String, nullable=False, default="author")
    write_folder_cover = Column(Boolean, nullable=False, default=True)
    # Sync protocol v2 bookkeeping: version string reported by the plugin at
    # each /sync handshake, and the last time ANY device-token request hit the
    # server (updated in auth.get_current_device, the single choke point).
    plugin_version = Column(String, nullable=True)
    last_seen_at = Column(DateTime, nullable=True)
    # Server-driven deletion policy for this device:
    # "auto"  — the plugin deletes without asking;
    # "ask"   — the plugin prompts the user (default, per §7 decisions);
    # "never" — the server never even sends removes[] to this device.
    delete_policy = Column(String, nullable=False, default="ask")
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    user = relationship("User", back_populates="devices")
    sync_queue = relationship("SyncQueue", back_populates="device", cascade="all, delete-orphan")

class SyncQueue(Base):
    __tablename__ = "sync_queue"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    library = Column(String, nullable=False, default="default")
    calibre_book_id = Column(Integer, nullable=False)
    action = Column(String, nullable=False)  # 'queued_download', 'queued_delete'
    format = Column(String, nullable=True)   # EPUB, PDF, MOBI, MD
    status = Column(String, default="pending")  # 'pending', 'done'
    timestamp = Column(DateTime, default=datetime.utcnow)

    device = relationship("Device", back_populates="sync_queue")


class DeviceBook(Base):
    """
    Per-device DESIRED state for one (book, format) — sync protocol v2's core
    table (the BookOrbit-Kobo "snapshot" concept, our own implementation).
    Each row says what the server wants on the device and what the device last
    reported. Lifecycle by `status`:
      pending_send      — queued from the web UI, plugin must download it;
      synced            — server and device agree the file is on the device;
      pending_delete    — queued for removal; once the device CONFIRMS the
                          delete the row is DELETED (trace stays in
                          DeviceSyncHistory), it never lingers as a tombstone;
      delete_declined   — the user on the device refused the removal (GUI can
                          re-queue or drop it);
      removed_by_device — the device reported the file gone on its own; the
                          row stays until the GUI archives it;
      send_failed       — last delivery attempt failed (see last_error).
    """
    __tablename__ = "device_books"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    library = Column(String, nullable=False, default="default")
    calibre_book_id = Column(Integer, nullable=False)
    format = Column(String, nullable=False)
    # Stamped once, when the row is first created, and never touched again —
    # unlike synced_at (bumped on every re-sync confirmation), this is the
    # actual "added to this device" date the web UI wants to show.
    created_at = Column(DateTime, default=datetime.utcnow)
    synced_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, nullable=False, default="synced", index=True)
    # KOReader partial-MD5 of the file the server handed out, stamped when the
    # row is offered in sends[] — lets a later handshake prove the device holds
    # exactly the delivered file even after Calibre rewrites the library copy.
    delivery_hash = Column(String, nullable=True)
    device_path = Column(String, nullable=True)   # on-device filesystem path, as reported
    device_pages = Column(Integer, nullable=True)  # page count computed on-device (GUI display only)
    device_pages_updated_at = Column(DateTime, nullable=True)
    requested_by = Column(String, nullable=True)  # 'server' (queued from web UI) | 'device' (on-device catalog download / adoption)
    last_error = Column(String, nullable=True)    # last delivery/deletion error reported by the plugin
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    removed_at = Column(DateTime, nullable=True)  # when the device reported the file missing

    __table_args__ = (UniqueConstraint("device_id", "library", "calibre_book_id", "format"),)


class DeviceSyncHistory(Base):
    """
    One row per v2 sync session: opened by
    POST /sync, updated by /sync/ack batches, closed by /sync/finish. Sessions
    left 'open' for more than an hour are lazily marked 'abandoned' by the
    next handshake; at most 100 rows are kept per device (pruned at finish).
    """
    __tablename__ = "device_sync_history"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id = Column(String, unique=True, nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    outcome = Column(String, default="open")  # open | ok | partial | error | abandoned
    plugin_version = Column(String, nullable=True)
    trigger = Column(String, nullable=True)  # free-form string from the plugin: manual | auto_open | auto_resume | ...
    books_reported = Column(Integer, default=0)
    downloads_requested = Column(Integer, default=0)
    downloads_ok = Column(Integer, default=0)
    downloads_failed = Column(Integer, default=0)
    deletes_requested = Column(Integer, default=0)
    deletes_done = Column(Integer, default=0)
    deletes_declined = Column(Integer, default=0)
    removed_by_device = Column(Integer, default=0)
    pages_reported = Column(Integer, default=0)
    detail_json = Column(Text, nullable=True)


class BookHash(Base):
    """KOReader-compatible partial-MD5 per (library, book, format) — the join
    key a device's sync handshake uses to say "I have this file" without ever
    exchanging calibre_book_id (the device doesn't know or care about our ids)."""
    __tablename__ = "book_hashes"

    id = Column(Integer, primary_key=True, index=True)
    library = Column(String, nullable=False, default="default")
    calibre_book_id = Column(Integer, nullable=False)
    format = Column(String, nullable=False)
    file_hash = Column(String, nullable=False, index=True)
    computed_at = Column(DateTime, default=datetime.utcnow)
    # True (default) when computed straight from the server's OWN file
    # (upsert_book_hash) — a hash-based match against this row is genuinely
    # byte-verified. False when the value was instead RECORDED from a
    # device's own report (record_device_hash — the manual/fuzzy "Accoppia"
    # actions), never independently checked against the server's copy. Read
    # back to surface a "non verificato per checksum" badge wherever a
    # DeviceBook row's match ultimately traces back to one of these — even
    # after it flows through the normal hash-adoption path on a later sync,
    # since that path can't otherwise tell a forced hash from a real one.
    verified = Column(Boolean, nullable=False, default=True)

    # Content-level identity (services/text_fingerprint.py) alongside the
    # byte-level file_hash above: a SHA256 of a normalized text window,
    # invariant to filename/folder/OPF-metadata/zip-compression differences
    # that break file_hash whenever a device file is an independently
    # produced copy of the same book rather than a byte-identical one.
    # Nullable — None for unsupported formats (pdf/mobi/azw3) or books with
    # too little extractable text, never a low-quality fingerprint.
    content_fingerprint = Column(String, nullable=True, index=True)

    __table_args__ = (UniqueConstraint("library", "calibre_book_id", "format"),)


class BookHashHistory(Base):
    """
    Previous BookHash.file_hash values for a (library, calibre_book_id,
    format), archived whenever book_hash_service._get_or_create_book_hash
    overwrites the live row with a newly-recomputed hash — e.g. after
    embedding page-count/cover/OPF metadata into the file (opf_metadata.py),
    which changes the exact bytes a partial-MD5 samples even though the book
    is unchanged. Without this, a device that already downloaded and hashed
    an OLDER copy can never resolve its reported statistics.sqlite3 md5
    again once the server rewrites the file — confirmed against real data
    while investigating a stats gap on one such rewritten book (hundreds of
    orphaned sessions, all predating the book's last server-side rewrite).
    stats_service._resolve_book_identities checks this table as a fallback
    when the live BookHash.file_hash no longer matches.
    """
    __tablename__ = "book_hash_history"

    id = Column(Integer, primary_key=True, index=True)
    library = Column(String, nullable=False)
    calibre_book_id = Column(Integer, nullable=False)
    format = Column(String, nullable=False)
    file_hash = Column(String, nullable=False, index=True)
    recorded_at = Column(DateTime, default=datetime.utcnow)


class DeviceFlaggedBook(Base):
    """
    "Da rivedere" list for the plugin's device-initialization scan (§ cerca
    libri non accoppiati). A local file that fuzzy-matches a server book by
    title/author but already has reading progress or annotations is never
    touched automatically (overwriting it could destroy that data) — it's
    parked here instead, so it stays visible/actionable from the web UI
    rather than silently forgotten on the device.
    """
    __tablename__ = "device_flagged_books"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True)
    local_path = Column(String, nullable=False)
    local_title = Column(String, nullable=True)
    # Indovinato dal plugin KOReader da nome file/cartella (Kolibre:
    # _guessAuthorFromPath), non da metadati embedded — nullo per righe
    # segnalate da un plugin KOReader precedente a questo campo. Distinto da
    # candidate_author, che è l'autore del libro CANDIDATO suggerito dal
    # server, non del file locale non ancora accoppiato.
    local_author = Column(String, nullable=True)
    candidate_library = Column(String, nullable=True)
    candidate_calibre_book_id = Column(Integer, nullable=True)
    candidate_title = Column(String, nullable=True)
    candidate_author = Column(String, nullable=True)
    flagged_at = Column(DateTime, default=datetime.utcnow)
    # 'flagged_started' (probable candidate found, but the local file already
    # has reading progress or annotations) or 'no_candidate' (device-init
    # scan found nothing plausible at all) — see main.lua's
    # _classifyResolvedFuzzyMatches / _showNoCandidateMenu.
    match_status = Column(String, nullable=False, default="flagged_started")
    # Explains WHY a flagged_started row wasn't touched automatically — read
    # once at scan time from the local KOReader sidecar.
    local_percent_read = Column(Float, nullable=True)
    local_highlights_count = Column(Integer, nullable=True)
    # The device-reported KOReader partial-MD5 for this local file — absent
    # on rows created before this column existed. Needed for the 'pair'
    # action (see queue_flagged_book_action): pairing records THIS hash
    # against the chosen book, even if it never matches the server's own
    # copy of the file byte-for-byte (e.g. a Kindle that re-packages EPUBs
    # on transfer) — that's what makes a manual pairing stick permanently.
    file_hash = Column(String, nullable=True)
    # Web-UI-queued action, applied by the plugin on its NEXT sync (the
    # device isn't always online) — same "desired state, applied later"
    # pattern as DeviceBook. Row is deleted once the plugin acks it applied.
    # 'pair' is the exception: it touches no device state, so it's applied
    # synchronously in queue_flagged_book_action itself, never queued here.
    pending_action = Column(String, nullable=True)  # 'delete' | 'overwrite'
    pending_action_library = Column(String, nullable=True)
    pending_action_calibre_book_id = Column(Integer, nullable=True)
    pending_action_format = Column(String, nullable=True)

    device = relationship("Device")


class ReadingPosition(Base):
    """Latest known reading position for a book, kosync-style: whichever
    device pushes last (by wall-clock updated_at) wins the "current" spot;
    conflict prompting on pull is left to the client, this just stores the
    latest push and who made it.

    PER UTENTE dal 24/09/2026. "Vince l'ultimo che scrive" e' la regola
    giusta fra i DISPOSITIVI di una stessa persona — il Kindle e il lettore
    web che si passano il segnalibro sono esattamente questo — ed e' la
    regola sbagliata fra persone diverse: con una biblioteca condivisa, due
    lettori dello stesso libro si spostavano il segnalibro a vicenda ogni due
    secondi, senza che niente lo segnalasse. La chiave era
    (biblioteca, libro), adesso e' (utente, biblioteca, libro).

    Dov'e' arrivata una persona e' un dato personale per definizione: questo
    non dipende da nessuna delle decisioni ancora aperte su chi possiede una
    biblioteca e con chi la condivide."""
    __tablename__ = "reading_positions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    library = Column(String, nullable=False, default="default")
    calibre_book_id = Column(Integer, nullable=False)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="SET NULL"), nullable=True)
    device_name = Column(String, nullable=True)
    percentage = Column(Float, nullable=False)
    progress = Column(String, nullable=False)  # page number (paged docs) or xpointer (reflow docs)
    # How much of the book was actually VISITED (distinct pages seen /
    # total pages), from statistics.sqlite3 page_stat_data — distinct from
    # `percentage` above (furthest point reached, kept live by the KOSync
    # push endpoint): a reader can jump straight to page 300 (percentage
    # jumps too) without ever having actually read pages 1-299 (coverage
    # stays low). Populated by stats_service.process_statistics_db,
    # monotonically (never decreases). Never overwrites `percentage`/
    # `progress` — those stay exclusively KOSync's, this is purely additive.
    coverage_percent = Column(Float, nullable=True)
    # Quello che il DISPOSITIVO dichiara sul libro, non quello che il server
    # deduce.
    #
    # Finora "finito" era una nostra supposizione: la pagina Interventi
    # propone di segnare un libro come letto quando la copertura supera il
    # 90% (vedi api/interventions.py), che e' una stima, e sbaglia in due
    # direzioni — un libro saltato a meta' e poi finito, un saggio di cui si
    # leggono tre capitoli su dieci. KOReader intanto la risposta la ha, e
    # ce l'ha dalla persona: quando chiude un libro chiede «segnarlo come
    # finito?», e la risposta finisce nel suo sidecar (`summary.status`).
    # Nessuno gliela chiedeva.
    #
    # I valori sono i SUOI, non tradotti: 'reading', 'complete',
    # 'abandoned'. Tradurli vorrebbe dire inventare un vocabolario parallelo
    # e dover decidere cosa fare di un valore nuovo che KOReader aggiungesse
    # domani.
    #
    # `stato_dichiarato_il` e' la data che KOReader scrive accanto allo stato
    # (`summary.modified`, che e' solo un giorno, senza ora): e' il giorno in
    # cui la persona ha detto «finito», non il giorno in cui noi lo abbiamo
    # saputo — quello e' `updated_at`.
    #
    # La data di INIZIO non sta qui di proposito: KOReader non ne tiene una
    # (mette `status = 'reading'` appena il libro viene aperto, anche solo
    # per sfogliarlo), e noi abbiamo qualcosa di meglio — le sessioni di
    # lettura vere, con le loro durate (`ReadingSession`). Da quelle la data
    # di inizio si RICAVA, con una regola che si puo' cambiare senza toccare
    # il dispositivo: la prima sessione, o la prima che superi una certa
    # durata, cioe' la prima vera e non quella in cui il libro e' stato
    # aperto e richiuso.
    stato_lettura = Column(String, nullable=True)
    stato_dichiarato_il = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("user_id", "library", "calibre_book_id"),)

#: 31 caratteri: le cifre da 2 a 9 e le minuscole senza `i`, `l`, `o`.
#: Niente caratteri ambigui, perche' questo nome finisce dentro un link che
#: una persona legge, ripete ad alta voce e a volte ricopia a mano.
ALFABETO_DUREVOLE = "23456789abcdefghjkmnpqrstuvwxyz"


def sorteggia_id_durevole() -> str:
    """
    Dieci caratteri a caso: il nome durevole di una nota.

    **Sta qui, accanto alla colonna, e non nel servizio** perche' e' il
    `default=` della colonna stessa: cosi' il nome lo mette il database e
    nessun punto di creazione futuro puo' dimenticarsene. Le note nascono in
    cinque posti diversi (il lettore web, la sincronizzazione da un
    dispositivo, l'arrivo di un'orfana, la copia di un libro in un'altra
    biblioteca, la creazione a mano) e il sesto che qualcuno aggiungera' non
    deve sapere niente di tutto questo.

    **Non controlla che sia libero**, e la scelta e' consapevole: il
    `default=` di una colonna non ha una sessione con cui interrogare il
    database. Dieci caratteri sono 8,2 * 10^14 combinazioni — con un milione
    di note la probabilita' che due coincidano, in tutta la vita
    dell'impianto, e' intorno a sei su diecimila — e l'indice e' **unico**,
    quindi il caso impossibile fallisce a voce alta invece di sovrascrivere
    silenziosamente l'identita' di un'altra nota. Chi assegna molti nomi in
    fila (la migrazione di un database che esisteva prima della colonna) usa
    invece `identita_durevole.nuovo()`, che il controllo lo fa.
    """
    return "".join(secrets.choice(ALFABETO_DUREVOLE) for _ in range(10))


class Highlight(Base):
    """
    Unified annotation store: a highlight/note can come from the web reader
    (cfi_start/cfi_end), KOReader (koreader_pos0/koreader_pos1/page), or be
    entered manually — whichever positions are relevant get filled in, the
    others stay null. `library` is required because `calibre_book_id` is only
    unique *within* one Calibre library, not globally.
    """
    __tablename__ = "highlights"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="SET NULL"), nullable=True)
    library = Column(String, nullable=False, default="default")
    calibre_book_id = Column(Integer, nullable=False)
    # Il nome che non cambia mai, e che va **fuori** da qui: nel marcatore di
    # un file di Obsidian, in un link dentro un appunto. `id` resta la chiave
    # veloce dentro al database, ma non e' un'identita': e' il numero di riga,
    # si muove quando una riga viene rifatta e SQLite lo **riusa** dopo una
    # cancellazione vera. Vedi `services/identita_durevole.py` per i tre modi
    # misurati in cui si muove. Nullable perche' un database che esisteva
    # prima della colonna la riempie alla prima accensione
    # (`assegna_mancanti`), non perche' una nota possa restare senza nome.
    id_durevole = Column(String, nullable=True, unique=True, index=True,
                         default=sorteggia_id_durevole)
    text = Column(String, nullable=False)
    comment = Column(String, nullable=True)
    chapter = Column(String, nullable=True)
    page = Column(Integer, nullable=True)
    cfi_start = Column(String, nullable=True)
    cfi_end = Column(String, nullable=True)
    koreader_pos0 = Column(String, nullable=True)
    koreader_pos1 = Column(String, nullable=True)
    # Calibre Desktop's own built-in viewer annotation id (its `annot_id`/
    # uuid) — the dedup/update key for imports from Calibre's native
    # `annotations` table, same role koreader_pos0 plays for device sync.
    annot_id = Column(String, nullable=True)
    # Where this highlight came from — 'device' (KOReader sync), 'web'
    # (Kolibre's own reader), or 'calibre' (Calibre Desktop's built-in
    # viewer, imported via the Calibre plugin). Added after device_id/
    # cfi_start already existed and were the only clue; this makes the
    # source explicit instead of inferred.
    source = Column(String, nullable=False, default="web")
    # Result of lazily converting a device highlight's koreader_pos0/1
    # (crengine xpointer — an addressing scheme epub.js can't read) into a
    # real cfi_start/cfi_end — see services/highlight_position.py. None =
    # never attempted (web/calibre highlights already have a real CFI and
    # never need this); 'exact'/'repaired' = cfi_start/cfi_end are usable;
    # 'failed' = conversion was tried and could not resolve a position,
    # deliberately never retried automatically (a missing/corrupt EPUB
    # would otherwise redo the same failing work on every page load).
    position_status = Column(String, nullable=True)
    color = Column(String, default="yellow")  # yellow, green, blue, pink, orange
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)  # soft delete (trash / restore)

    user = relationship("User", back_populates="highlights")


class OrphanHighlight(Base):
    """
    A device-pushed annotation whose file_hash didn't resolve via BookHash at
    push time — see push_device_annotations. Deliberately a SEPARATE table
    from Highlight rather than making Highlight.calibre_book_id nullable:
    this project has no real migration system (see main.py's
    _ensure_schema_migrations — additive ALTER TABLE ADD COLUMN only), and
    SQLite can't drop a NOT NULL constraint already baked into an existing
    production table without rebuilding it. A new table sidesteps that
    entirely (create_all() makes it automatically) and keeps every existing
    Highlight query (annotations.py, highlight_position.py, the per-book
    counts in devices.py) exactly as it is today — none of them need to
    learn about a "maybe this book doesn't exist" case.

    Identified by (device_id, local_path) instead of (library,
    calibre_book_id) — there IS no book yet. Once the user pairs local_path
    to a real book (queue_flagged_book_action's 'pair' action, or
    push_device_annotations noticing the hash resolved on its own), matching
    rows are copied into a real Highlight (position_status left None so it
    re-enters the normal lazy CFI-resolution batch) and deleted from here.
    """
    __tablename__ = "orphan_highlights"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    local_path = Column(String, nullable=False)
    file_hash = Column(String, nullable=True)
    # Lo stesso nome durevole di `Highlight`, e nasce **qui**: quando questa
    # riga diventera' una nota vera (accoppiando il libro) il nome si copia,
    # ed e' il motivo per cui un marcatore scritto in un file di Obsidian
    # quando il libro non era ancora accoppiato continua a valere dopo.
    id_durevole = Column(String, nullable=True, unique=True, index=True,
                         default=sorteggia_id_durevole)
    text = Column(String, nullable=False)
    comment = Column(String, nullable=True)
    chapter = Column(String, nullable=True)
    page = Column(Integer, nullable=True)
    koreader_pos0 = Column(String, nullable=True)
    koreader_pos1 = Column(String, nullable=True)
    color = Column(String, default="yellow")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)

    __table_args__ = (UniqueConstraint("device_id", "local_path", "koreader_pos0"),)


class OrphanReadingSession(Base):
    """
    Same rationale as OrphanHighlight, applied to reading sessions: a
    KOReader page_stat_data session whose book.md5 has NO matching BookHash
    row at ingest time (book never hashed server-side — never ingested,
    never rescanned, or genuinely not in any library). Previously these
    were counted and logged (see stats_service.process_statistics_db's
    sessions_skipped_unresolved) but never persisted anywhere — the choice
    was to keep them rather than throw them away, mirroring how orphan
    highlights already work. Deliberately NOT merged into ReadingSession (which
    requires a real library+calibre_book_id) for the same reason
    OrphanHighlight is a separate table from Highlight: no real migration
    system here, additive-only (see main.py's _ensure_schema_migrations),
    so a brand new table is far simpler than trying to make
    ReadingSession.calibre_book_id nullable on an existing production table.

    One row per grouped session (same 15-minute-gap grouping as
    ReadingSession, see process_statistics_db), not a single pre-aggregated
    total — this keeps the shape symmetric with ReadingSession so a future
    "pair this orphan device-book to a real book" action can just copy
    matching rows into real ReadingSession rows and delete them here,
    exactly like OrphanHighlight's own eventual pairing story (not built
    yet, same as this table's pairing story isn't built yet either).

    title/authors/series are the device's own self-reported metadata
    (KOReader's book table) — the only identification available for a book
    the server has never seen, and exactly what a future manual-pairing UI
    would show a human to recognize it by.
    """
    __tablename__ = "orphan_reading_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    md5 = Column(String, nullable=False)
    title = Column(String, nullable=True)
    authors = Column(String, nullable=True)
    series = Column(String, nullable=True)
    start_time = Column(DateTime, nullable=False)
    duration = Column(Integer, nullable=False)
    pages_read = Column(Integer, default=0)
    # Vedi ReadingSession.fraction_read: viaggia insieme, cosi' una
    # sessione orfana che viene accoppiata non perde la misura buona.
    fraction_read = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("device_id", "md5", "start_time"),)

class DeviceRestoreRequest(Base):
    """
    "Resetta a stato di dispositivo" (task #266): eredita lo stato locale
    (statistics.sqlite3, dizionario del vocabolario, impostazioni reader,
    ecc.) da un ALTRO dispositivo già registrato, leggendo dal suo backup
    già presente sul server — mai dal dispositivo sorgente fisico stesso.
    Pensato per il caso "ho rotto/smarrito un dispositivo, il nuovo deve
    tornare allo stato del backup", non per la convivenza di due device.

    Tre conferme distinte, mai applicazione silenziosa (a differenza di
    DeviceFlaggedBook.pending_action, il precedente più vicino nello
    schema "stato desiderato applicato al prossimo sync"): il device
    target la crea, un admin la conferma sul frontend, poi il device
    target la esegue solo dopo un'ulteriore conferma locale dell'utente.
    Una sola richiesta non completata per target alla volta — crearne una
    nuova sostituisce quella precedente (vedi create_device_restore_request
    in api/devices.py).
    """
    __tablename__ = "device_restore_requests"

    id = Column(Integer, primary_key=True, index=True)
    target_device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    source_device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    status = Column(String, nullable=False, default="pending_admin")  # pending_admin | confirmed_admin | done
    requested_at = Column(DateTime, default=datetime.utcnow)
    confirmed_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    files_applied = Column(Text, nullable=True)  # JSON: lista dei file effettivamente trovati/copiati


class StatsHashPairing(Base):
    """
    Manual, user-confirmed pairing from a KOReader-reported statistics.sqlite3
    md5 straight to a (library, calibre_book_id) — the definitive fix for
    reading history that was orphaned BEFORE BookHashHistory existed (see
    that model's own docstring): for those books the server-side file was
    already rewritten with no history captured, so the device's old md5 has
    nothing left to automatically fall back to. This table is the same idea
    as BookHashHistory but filled by an explicit human decision instead of
    an automatic archive (mirrors devices.py's pair_device_book/
    queue_flagged_book_action "pair" action for OrphanHighlight — same
    problem, same one-time-confirmation shape, applied to reading sessions
    instead of highlights).

    Deliberately its OWN table rather than another BookHash row: BookHash's
    (library, calibre_book_id, format) rows are read by the device sync/
    pairing subsystem as "the current, verified hash of the server's own
    file" — writing a stale device-reported hash in there to make stats
    resolve would risk confusing that unrelated system. This table is read
    ONLY by stats_service._resolve_book_identities, nothing else.

    Global by md5 (no device_id): once a human confirms "this md5 is really
    this book", it should resolve for every device reporting that same
    hash, not just the one it was first noticed on — same scope BookHash
    itself already uses (also no device_id).
    """
    __tablename__ = "stats_hash_pairings"

    id = Column(Integer, primary_key=True, index=True)
    md5 = Column(String, nullable=False, unique=True, index=True)
    library = Column(String, nullable=False)
    calibre_book_id = Column(Integer, nullable=False)
    paired_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class StatsHashDiscard(Base):
    """
    The complement of StatsHashPairing: a human decision that a given
    KOReader-reported statistics.sqlite3 md5 is NOT a book worth tracking
    for reading statistics at all (e.g. a sample/preview file, something
    read outside any Calibre library on purpose) — as opposed to "this IS a
    real book, here's which one" (StatsHashPairing). Existing
    OrphanReadingSession rows for this md5 are deleted the moment this row
    is created (see stats_service.discard_orphan_sessions) — this table's
    only remaining job afterwards is to stop process_statistics_db from
    ever recreating them on a future device backup sync (checked the same
    way _resolve_book_identities checks StatsHashPairing, just to decide
    "skip silently" instead of "resolve to this book").

    Global by md5 (no device_id/user_id scoping on the lookup), same
    reasoning as StatsHashPairing: once a human decides a hash isn't worth
    tracking, that should hold for every device reporting it.
    """
    __tablename__ = "stats_hash_discards"

    id = Column(Integer, primary_key=True, index=True)
    md5 = Column(String, nullable=False, unique=True, index=True)
    discarded_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ReadingSession(Base):
    """One grouped reading session (KoServer-style 15-minute-gap grouping of
    KOReader's raw page_stat_data rows — see stats_service.process_statistics_db).
    `library` is required for the same reason every other book-identifying
    table in this app requires it: calibre_book_id is only unique WITHIN one
    library, not globally."""
    __tablename__ = "reading_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    library = Column(String, nullable=False, default="default")
    calibre_book_id = Column(Integer, nullable=False)
    device_id = Column(Integer, nullable=True)
    start_time = Column(DateTime, nullable=False)
    duration = Column(Integer, nullable=False)  # duration in seconds
    pages_read = Column(Integer, default=0)
    # Quanto LIBRO e' stato letto in questa sessione, da 0 a 1.
    #
    # Le pagine di KOReader non sono un'unita' di misura: dipendono dal corpo
    # del carattere, dai margini e dallo schermo. Su dati reali un'opera in
    # piu' volumi ha dodici impaginazioni diverse in cronologia, da 2.687 a
    # 7.342 pagine: una "pagina" vale fino a 2,7 volte un'altra dello stesso
    # libro, e sommarle fra libri diversi non significa niente.
    #
    # KOReader pero' registra, riga per riga, anche il totale di pagine di
    # QUEL momento (page_stat_data.total_pages): 1/total_pages e' quindi la
    # frazione di libro di quella pagina, ed e' indipendente dal carattere.
    # Questa colonna somma quelle frazioni. Moltiplicata per il conteggio
    # caratteri del libro (BookTextStats) da' i caratteri letti.
    #
    # NULL per le sessioni importate prima di questa colonna e per quelle del
    # lettore web, che non contano pagine affatto.
    fraction_read = Column(Float, nullable=True)
    # 'koreader' | 'web' — same role as Highlight.source: distinguishes a
    # batch-imported KOReader session (device_id always set, from a
    # statistics.sqlite3 backup) from a live tick recorded straight off the
    # browser reader's own reading-position pushes (device_id always NULL,
    # same as ReadingPosition's own "Web Reader" convention) — needed because
    # device_id alone can't disambiguate a hypothetical future NULL-device
    # KOReader edge case from an intentional web session.
    source = Column(String, nullable=False, default="koreader")

    user = relationship("User", back_populates="reading_sessions")


class VocabularyEntry(Base):
    """
    One row per KOReader Vocabulary Builder word, imported wholesale from a
    device's vocabulary_builder.sqlite3 backup (see main.lua's
    BACKUP_FILES_SETTINGS — already backed up before this table existed,
    just never parsed) by
    services.vocabulary_service.process_vocabulary_db, same pattern as
    process_statistics_db for statistics.sqlite3.

    KOReader's own `vocabulary` table has `word` (not an id) as its PRIMARY
    KEY — one row per unique word PER DEVICE, globally across every book
    read on it, not per (word, book). Looking the same word up again just
    updates review_time/due_time/review_count/streak_count in place; it
    never creates a second row, even in a different book. `(device_id,
    word)` mirrors that exact identity here.

    definition/definition_source/definition_fetched_at (added later) are
    deliberately NOT populated from the device import — KOReader itself
    never persists a definition (confirmed against a real device file), it
    looks the word up live, on-device, in whatever dictionaries happen to be
    installed there. These three columns are filled ONLY by an explicit
    server-side lookup (services/dictionary_service.py, "Cerca definizione"
    in the frontend), one word at a time — never automatically on import,
    to avoid firing a burst of external HTTP calls (and hitting Wiktionary's
    rate limits) every time a device uploads a backup with hundreds of
    words. NULL means "never looked up", not "no definition exists".

    book_title is the device's own self-reported string (KOReader's
    `title.name`, joined via `title_id` at parse time) — NOT resolved to a
    real (library, calibre_book_id) the way ReadingSession/Highlight are,
    because this table has nothing hash-based to resolve from (no md5
    anywhere in vocabulary_builder.sqlite3) — always shown as plain text on
    the device page, never a book link.
    """
    __tablename__ = "vocabulary_entries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    word = Column(String, nullable=False)
    book_title = Column(String, nullable=True)
    context_before = Column(Text, nullable=True)
    context_after = Column(Text, nullable=True)
    # The actual inflected form KOReader found highlighted in the text (e.g.
    # "mefistofelica"), when different from the dictionary-lookup `word`
    # (e.g. "mefistofelico") — KOReader itself only sets this when they
    # differ, NULL otherwise (falls back to `word` for display).
    highlight = Column(String, nullable=True)
    create_time = Column(DateTime, nullable=False)
    review_time = Column(DateTime, nullable=True)
    due_time = Column(DateTime, nullable=True)
    review_count = Column(Integer, nullable=False, default=0)
    streak_count = Column(Integer, nullable=False, default=0)

    # Server-side dictionary lookup (services/dictionary_service.py), fetched
    # on demand — see this model's own docstring for why it's never
    # auto-populated on import. definition_source is the Wiktionary edition
    # that answered (e.g. "it.wiktionary.org"), shown next to the definition
    # so a wrong-language guess is obvious rather than silently misleading.
    definition = Column(Text, nullable=True)
    definition_source = Column(String, nullable=True)
    definition_fetched_at = Column(DateTime, nullable=True)

    __table_args__ = (UniqueConstraint("device_id", "word"),)


class WebVocabularyEntry(Base):
    """
    Vocabulary Builder entries added from Kolibre's OWN web reader (word
    lookup while reading an EPUB in the browser), not imported from a
    device's vocabulary_builder.sqlite3.

    Deliberately a SEPARATE table from VocabularyEntry rather than making
    that table's device_id nullable: this project has no real migration
    system (see main.py's _ensure_schema_migrations — additive ALTER TABLE
    ADD COLUMN only), and SQLite can't relax an existing NOT NULL column on
    a live production table without a full rebuild. Same reasoning, same
    fix, as OrphanHighlight being a separate table from Highlight instead of
    making Highlight.calibre_book_id nullable (see that model's own
    docstring) — a new table sidesteps the problem entirely.

    Unlike VocabularyEntry.book_title (a device's own self-reported string,
    unresolvable to a real book — see that model's docstring), a web-reader
    lookup happens INSIDE an already-open Kolibre book, so `library` +
    `calibre_book_id` are a real reference here, not a display string —
    the centralized Vocabulary Builder page (GET /api/kolibre/vocabulary)
    can link straight back to the book.

    review_time/due_time/review_count/streak_count mirror VocabularyEntry
    field-for-field (even though nothing writes them yet) so the unified
    API response has one shape regardless of origin, ready for a future
    review/flashcard feature without another schema change later.

    Unique per (user_id, word): a web-reader lookup is user-initiated, not
    per-device — looking the same word up again from any book just updates
    this one row in place, same "one row per unique word" identity
    VocabularyEntry itself already uses (there per-device, here per-user).
    """
    __tablename__ = "web_vocabulary_entries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    library = Column(String, nullable=False)
    calibre_book_id = Column(Integer, nullable=False)
    word = Column(String, nullable=False)
    context_before = Column(Text, nullable=True)
    context_after = Column(Text, nullable=True)
    highlight = Column(String, nullable=True)
    create_time = Column(DateTime, nullable=False, default=datetime.utcnow)
    review_time = Column(DateTime, nullable=True)
    due_time = Column(DateTime, nullable=True)
    review_count = Column(Integer, nullable=False, default=0)
    streak_count = Column(Integer, nullable=False, default=0)

    definition = Column(Text, nullable=True)
    definition_source = Column(String, nullable=True)
    definition_fetched_at = Column(DateTime, nullable=True)

    __table_args__ = (UniqueConstraint("user_id", "word"),)


class StatsCache(Base):
    """
    Precomputed reading-stats aggregates for one library — refreshed
    periodically in the background (main.py::_refresh_stats_loop, every
    STATS_REFRESH_INTERVAL_SECONDS) instead of recomputed on every page
    load. GET /api/kolibre/stats/* just reads this row; the actual
    aggregation logic lives in stats_service.compute_summary/compute_raw/
    compute_timeline, called by the background loop.

    summary/raw/timeline are stored as JSON text in one row per library
    rather than three separate cache tables — nothing here is ever queried
    by SQL, it's read back out whole and json.loads()'d, so there's no
    benefit to a more granular schema.

    PER UTENTE dal 24/09/2026, come ReadingPosition e BookReadingCoverage
    prima di lei. Le sessioni di lettura hanno sempre avuto un utente, ma
    questa cache no: le aggregava tutte insieme, quindi su una biblioteca
    condivisa il cruscotto avrebbe mostrato a ciascuno le ore, la striscia e
    i libri completati di tutti. Una riga per (utente, biblioteca).
    """
    __tablename__ = "stats_cache"
    __table_args__ = (UniqueConstraint("user_id", "library"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    library = Column(String, nullable=False)
    summary_json = Column(Text, nullable=False)
    raw_json = Column(Text, nullable=False)
    timeline_json = Column(Text, nullable=False)
    computed_at = Column(DateTime, default=datetime.utcnow)


class AuthorPagesCache(Base):
    """
    Precomputed sum of estimated page count per author, across every book by
    that author in every library on the server — backs the "Pagine" column
    on the Autori table (frontend-react's AuthorsPage.tsx).

    GET /api/kolibre/authors' own list_authors already opens every library's
    metadata.db and joins books_authors_link in ONE pass per request, just
    to get book_count — doing the same PLUS a join against each library's
    `pages` custom-column value table (see calibre/connection.py's
    PAGE_COUNT_COLUMN_LABEL/_ensure_page_count_column) on every single page
    load would be pure waste for a number that only actually changes when a
    book is added or removed. So, same idea as StatsCache above: a cache row
    read back by the endpoint instead of recomputed inline. Two differences
    from StatsCache on purpose:
      - one single row, not one per library — author totals are already a
        cross-library view (an author can have books in more than one
        library, summed together), same as list_authors' own `counts` dict.
      - invalidated (not recomputed) at every book-add/book-remove call site
        (see services/author_stats_service.py's docstring for the full
        list): those call sites only flip `dirty`, a one-row write with no
        library scanning — the actual recompute happens lazily, at most
        once, on the next GET /api/kolibre/authors that finds dirty=True.
        A real recompute on every single mutation would be its own version
        of the exact waste this cache exists to avoid: upload_library_book
        (the Calibre Desktop plugin's per-book sync endpoint) can fire
        hundreds of times in a row during one full-library sync, and an
        eager full cross-library recompute after each call would make that
        sync dramatically slower for a number nobody's necessarily even
        about to look at.

    pages_json is the whole {author_name: total_pages} map as JSON text,
    same "write once, json.loads() back out whole, never queried by SQL"
    reasoning as StatsCache's own blobs.
    """
    __tablename__ = "author_pages_cache"

    id = Column(Integer, primary_key=True, index=True)
    pages_json = Column(Text, nullable=False)
    dirty = Column(Boolean, nullable=False, default=True)
    computed_at = Column(DateTime, default=datetime.utcnow)


class Library(Base):
    """Registry of Calibre-compatible library folders known to this server."""
    __tablename__ = "libraries"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    folder_name = Column(String, unique=True, nullable=False)  # directory name under LIBRARIES_DIR
    path = Column(String, nullable=False)  # absolute path to the library folder (may be external, zero-copy)
    # User-controlled display/priority order (Impostazioni → Librerie ▲▼).
    # The library with the lowest sort_order is THE default: whichever
    # endpoint needs a library and none was specified (ingest, bare API calls
    # without ?library=) falls back to it — no separate "is this the special
    # one" flag, no folder name is privileged over any other.
    sort_order = Column(Integer, default=0, nullable=False)
    # Chi la possiede. Nullable perche' una biblioteca puo' sopravvivere al
    # suo proprietario (l'utente cancellato non porta con se' i libri), e
    # perche' all'atto della migrazione una biblioteca senza proprietario
    # deve poter esistere per un istante invece di bloccare l'avvio.
    # Cancellarla resta del solo proprietario: decisione del 28/09.
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class LibraryPermission(Base):
    """
    Cosa puo' fare UNA persona su UNA biblioteca.

    L'esistenza della riga e' gia' il permesso di leggere: non c'e' un
    `can_read`, perche' una riga che dice "non puo' fare niente" e l'assenza
    della riga sono la stessa cosa, e tenerle distinte vorrebbe dire
    spiegare la differenza a chi guarda la tabella dei permessi.

    Il proprietario non ha bisogno di una riga: possedere le comprende
    tutte. Il fondatore nemmeno — sta fuori da ogni limitazione, ed e' l'unico.
    """
    __tablename__ = "library_permissions"
    __table_args__ = (UniqueConstraint("user_id", "library_id"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    library_id = Column(Integer, ForeignKey("libraries.id", ondelete="CASCADE"), nullable=False, index=True)
    can_edit = Column(Boolean, default=False, nullable=False)
    # Condividere a sua volta: dare a un terzo l'accesso che si ha.
    can_share = Column(Boolean, default=False, nullable=False)
    # Gestire i permessi ALTRUI su questa biblioteca — piu' di condividere:
    # comprende togliere.
    can_manage = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class DeletedLibraryFolder(Base):
    """
    Tombstone for a folder_name the user explicitly deleted via DELETE
    /api/kolibre/libraries/{name}. Without this, sync_library_registry (which
    resurrects a registry row for any folder it finds with a metadata.db)
    would bring a deleted library right back the moment anything — a stray
    write-queue job, an ingest defaulting to the "default" library, a plain
    CalibreLibrary(...) call — recreates an empty metadata.db at that same
    path, since SQLite/bootstrap code has no idea the folder was ever deleted.
    """
    __tablename__ = "deleted_library_folders"

    id = Column(Integer, primary_key=True, index=True)
    folder_name = Column(String, unique=True, nullable=False)
    deleted_at = Column(DateTime, default=datetime.utcnow)


class IngestedBook(Base):
    """A file detected in the ingest/watched folder, staged for review before import."""
    __tablename__ = "ingested_books"

    id = Column(Integer, primary_key=True, index=True)
    file_path = Column(String, nullable=False)
    filename = Column(String, nullable=False)
    file_format = Column(String, nullable=False)
    file_size_bytes = Column(Integer, nullable=True)
    file_hash = Column(String, nullable=True, index=True)

    title = Column(String, nullable=False, default="Unknown Title")
    author = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    tags = Column(String, nullable=True)  # CSV
    cover_path = Column(String, nullable=True)
    # Auto-estratti da metadata_parser.py quando presenti nell'EPUB (calibre:series/
    # calibre:series_index, dc:language, dc:identifier scheme=ISBN); editabili
    # nell'editor metadati esteso e applicati al libro Calibre solo all'importazione
    # (vedi import_book_from_ingest) — mai persistiti prima, a differenza di
    # description/tags sopra che restano anche se l'utente scarta senza importare.
    series = Column(String, nullable=True)
    series_index = Column(Float, nullable=True)
    language = Column(String, nullable=True)
    isbn = Column(String, nullable=True)

    status = Column(String, default="pending", index=True)  # pending, confirmed, rejected
    # Mai scritta da nessuno: era pensata per marcare un file come doppione di
    # un libro preciso. Il controllo doppioni della pagina Ingest (28/09/2026,
    # `ingest.py::ingest_duplicati`) NON la usa di proposito — calcola i
    # candidati al momento e non li registra, perche' un avviso registrato
    # diventa una decisione presa: il giorno in cui il libro somigliante viene
    # accorpato o cancellato, questa colonna direbbe ancora "doppione di 412".
    duplicate_book_id = Column(Integer, nullable=True)
    error_message = Column(String, nullable=True)

    detected_at = Column(DateTime, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)


class AuthorMetadata(Base):
    """Wikipedia-derived author bio/photo cache, shared across tutte le biblioteche."""
    __tablename__ = "author_metadata"

    id = Column(Integer, primary_key=True, index=True)
    author_name = Column(String, unique=True, index=True, nullable=False)
    bio_it = Column(Text, nullable=True)
    bio_en = Column(Text, nullable=True)
    wikipedia_url_it = Column(String, nullable=True)
    wikipedia_url_en = Column(String, nullable=True)
    image_cached = Column(String, nullable=True)  # filename under config.AUTHORS_DIR
    last_scraped_at = Column(DateTime, nullable=True)

    # Esito dell'ultimo tentativo. `last_scraped_at` da solo diceva soltanto
    # "ci abbiamo provato", e mescolava cose che vanno trattate in modo
    # opposto: una voce che su Wikipedia non esiste (inutile riprovare), una
    # che esiste ma senza foto (inutile riprovare per la foto, ma vale la
    # pena ogni tanto: le foto vengono aggiunte), e un rifiuto temporaneo per
    # troppe richieste (va riprovato, ed e' il caso piu' frequente).
    #   'ok'       bio e immagine
    #   'no_image' pagina trovata, nessuna immagine da nessuna fonte
    #   'no_page'  nessuna voce su Wikipedia con quel nome
    #   'blocked'  rifiutati per limite di richieste (429)
    #   'error'    rete o risposta illeggibile
    scrape_status = Column(String, nullable=True)
    # Frase leggibile sull'ultimo esito, per la pagina Autori e per i log:
    # "HTTP 429", "nessuna immagine su it/en/Wikidata", "timeout".
    scrape_detail = Column(String, nullable=True)
    # Fallimenti consecutivi, per allungare progressivamente l'attesa.
    scrape_attempts = Column(Integer, nullable=False, default=0)
    # Prima di questo istante non ha senso ritentare. NULL = nessuna attesa
    # imposta (mai provato, o riuscito).
    next_retry_at = Column(DateTime, nullable=True)

    # ── Dati anagrafici da Wikidata ──────────────────────────────────────
    # Raggiunto attraverso la pagina Wikipedia che gia' salviamo: da un
    # articolo all'elemento Wikidata il passaggio e' meccanico e senza
    # ambiguita', ed e' il motivo per cui questi campi si riempiono al 97-99%
    # mentre cercare gli stessi dati per nome sarebbe un disastro di omonimi.
    # Misurato sulla biblioteca vera: 511 autori su 529 con URL agganciati.
    wikidata_qid = Column(String, nullable=True)
    # Etichetta italiana della proprieta' P21 ("sesso o genere"): "maschio",
    # "femmina", "uomo transgender"... Si salva l'etichetta e non un codice
    # perche' l'insieme dei valori non e' chiuso e non tocca a noi deciderlo.
    gender = Column(String, nullable=True)
    # P27, cittadinanza. Piu' valori separati da "; " (chi ha cambiato paese,
    # e chi e' nato in uno stato che non esiste piu': Wikidata registra
    # "Regno d'Italia" e "Impero russo", il che e' corretto ma va normalizzato
    # prima di farci una statistica).
    nationality = Column(String, nullable=True)
    birth_date = Column(String, nullable=True)   # ISO, "1821-11-11"; puo' essere solo l'anno
    death_date = Column(String, nullable=True)   # NULL anche per i viventi: vedi wikidata_fetched_at
    # P106, occupazione. Non l'avevi chiesta ma c'e' sul 99% ed e' il campo
    # piu' interessante per capire CHE COSA leggi (filosofi, romanzieri...).
    occupations = Column(String, nullable=True)
    # Distingue "mai interrogato Wikidata" da "interrogato, non aveva nulla":
    # senza, un autore senza data di morte sarebbe indistinguibile da un
    # autore mai cercato, e si ritenterebbe all'infinito.
    wikidata_fetched_at = Column(DateTime, nullable=True)


class PendingCalibreWrite(Base):
    """Fallback queue for metadata.db writes that failed after exhausting in-process retries."""
    __tablename__ = "pending_calibre_writes"

    id = Column(Integer, primary_key=True, index=True)
    library_path = Column(String, nullable=False)
    op_type = Column(String, nullable=False)
    payload_json = Column(Text, nullable=False)
    attempts = Column(Integer, default=0)
    last_error = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)


class SavedChart(Base):
    """
    A user-built chart from the Statistics chart builder (CRUD under
    /api/kolibre/stats/charts) — stores only the builder's *configuration*
    (chart type + data source + group-by + aggregation), never the computed
    data itself: reopening a saved chart re-aggregates fresh from GET
    /stats/raw or /stats/timeline every time, same as every other stats
    widget on this page (no separate cache/invalidation story needed).
    Typed columns rather than a JSON config blob — this v1's shape is small
    and fixed, so a JSON blob would only cost greppability/indexability for
    no real flexibility gained yet. Additive new table, no
    _ensure_schema_migrations entry needed (see OrphanReadingSession's own
    docstring: create_all() alone is enough for a brand new table, that
    function only matters for ALTER TABLE on an EXISTING one).

    v2 (chart builder deepening — independent X/Y, optional secondary
    grouping/series with a bar mode, client-side filters): three columns
    added on an EXISTING table, so THOSE do need an _ensure_schema_migrations
    entry (see that function's own docstring) — group_by_secondary/
    chart_mode/filters_json below. filters_json breaks from the "typed
    columns" reasoning above on purpose: filters are a small, genuinely
    open-ended bag (date range + N multi-selects, more may be added later)
    rather than a fixed enum, same tradeoff StatsCache.summary_json already
    made for this codebase. Existing rows predate all three and come back
    NULL — the frontend/backend both treat NULL the same as "no secondary
    grouping / grouped mode / no filters", i.e. exactly today's behaviour.

    v3 (the ask was the same power as grafidinamici — assi liberi,
    aggregazioni multiple, filtri a livelli, ordinamento): `metric`'s
    string values grew richer (e.g. "duration:avg", "distinct_authors")
    and `filters_json` now holds a nested AND/OR rule tree instead of a
    flat object — neither needs a migration here, since both were already
    untyped/opaque (see above). sort_by/sort_order are the one genuinely
    NEW top-level field, hence the two ALTER TABLEs below. Existing rows
    come back NULL for both, which the frontend treats as "no explicit
    sort" — i.e. the exact legacy ordering policy (chronological asc for
    time axes, value desc for categorical), so old saved charts render
    identically.
    """
    __tablename__ = "saved_charts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    library = Column(String, nullable=False, default="default")
    name = Column(String, nullable=False)
    chart_type = Column(String, nullable=False)  # 'bar' | 'line' | 'pie'
    data_source = Column(String, nullable=False)  # 'raw' | 'timeline'
    group_by = Column(String, nullable=False)  # asse X — 'day' | 'week' | 'month' | 'author' | 'format' | 'device' | 'source' | 'book_title'
    metric = Column(String, nullable=False, default="duration_sum")  # asse Y — legacy 'duration_sum'|'session_count'|'pages_sum' o v3 'duration:avg'|'distinct_authors'|...
    group_by_secondary = Column(String, nullable=True)  # dimensione "raggruppa per" (serie), stesso set di group_by — NULL = nessuna (comportamento v1)
    chart_mode = Column(String, nullable=False, default="grouped")  # 'grouped' | 'stacked' — usato solo da bar quando group_by_secondary è impostato
    filters_json = Column(Text, nullable=True)  # blob JSON: v1/v2 oggetto piatto o v3 albero di regole AND/OR — NULL = nessun filtro
    sort_by = Column(String, nullable=True)  # 'label' | 'value' — NULL = policy legacy (vedi docstring v3)
    sort_order = Column(String, nullable=True)  # 'asc' | 'desc' — NULL = policy legacy
    created_at = Column(DateTime, default=datetime.utcnow)


class AppSetting(Base):
    """Global key/value app settings (JSON-encoded value), e.g. page-count mode."""
    __tablename__ = "app_settings"

    key = Column(String, primary_key=True)
    value_json = Column(Text, nullable=False)


class PreferenzeUtente(Base):
    """
    Le preferenze di UNA PERSONA, in un oggetto JSON — il gemello per persona
    di AppSetting, che fa la stessa cosa per l'impianto.

    Ci entra solo quello che e' della persona e non dello schermo: il criterio
    sta in `services/preferenze_utente.py` e, per intero, in
    `docs/inventario-regole-nel-browser.md`. Oggi dentro c'e' la lingua
    dell'interfaccia, e quasi nient'altro merita di entrarci — la dimensione
    del testo nel lettore, la larghezza di una colonna, il formato della data
    dipendono dallo schermo e dal sistema su cui il client gira, e spostarle
    qui vorrebbe dire imporre a un telefono le scelte fatte su un portatile.

    Una riga per persona, non una per preferenza: il client le vuole tutte
    insieme all'avvio, e una preferenza nuova non deve chiedere una
    migrazione dello schema.
    """
    __tablename__ = "preferenze_utente"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    valore_json = Column(Text, nullable=False, default="{}")


class BookTextStats(Base):
    """
    Quanti caratteri e quante parole ha un libro.

    Vive qui e non come colonna personalizzata di Calibre di proposito: e' un
    dato di servizio di Kolibre, non un metadato del libro, e la biblioteca
    dell'utente non deve riempirsi di colonne che non ha chiesto.

    Serve a una cosa sola ma importante: trasformare la frazione di libro
    letta (ReadingSession.fraction_read) in caratteri letti, che e' l'unica
    misura di lettura confrontabile fra libri, dispositivi e impostazioni di
    carattere diverse.

    Si riempie dove si contano gia' le pagine — all'importazione e con
    "Ricalcola le pagine stimate" — perche' il testo, per contare le pagine,
    viene estratto comunque: prima lo si buttava via.
    """
    __tablename__ = "book_text_stats"
    __table_args__ = (UniqueConstraint("library", "calibre_book_id"),)

    id = Column(Integer, primary_key=True, index=True)
    library = Column(String, nullable=False, default="default")
    calibre_book_id = Column(Integer, nullable=False)
    chars = Column(Integer, nullable=False)
    words = Column(Integer, nullable=False)
    computed_at = Column(DateTime, default=datetime.utcnow)


class BookReadingCoverage(Base):
    """
    Quanta PARTE di un libro e' stata vista almeno una volta.

    Distinta da ReadingSession.fraction_read, che e' un'altra domanda:
    quella somma quanto si e' letto (e rileggendo supera il 100%, giustamente
    — quei caratteri li hai letti due volte), questa dice fin dove si e'
    arrivati. Su dati reali un libro ha volume 157% e copertura 89%: letto
    una volta e ripassato molto. Mostrare il 157% chiamandolo "percentuale
    del libro" era sbagliato, e in uso si vedeva subito.

    Il conto non puo' essere fatto sulle pagine: cambiando il corpo del
    carattere le stesse parole prendono numeri di pagina diversi, e le pagine
    distinte di un'impaginazione non si possono unire a quelle di un'altra.
    Si usa invece la POSIZIONE normalizzata: ogni pagina occupa l'intervallo
    [(p-1)/totale, p/totale) del libro, e si segnano i millesimi che copre.
    Quella misura e' la stessa sotto qualunque impaginazione, quindi le
    letture fatte con impostazioni diverse si sommano correttamente.

    `bins` e' quella mappa: 1000 bit, 125 byte per libro. Si conserva (invece
    del solo totale) perche' l'unione va fatta con le letture future, e da un
    numero solo non si puo' riottenere.
    """
    __tablename__ = "book_reading_coverage"
    __table_args__ = (UniqueConstraint("user_id", "library", "calibre_book_id"),)

    BINS = 1000

    id = Column(Integer, primary_key=True, index=True)
    # Per utente per la stessa ragione di ReadingPosition: quanta parte di un
    # libro hai visto tu non ha niente a che vedere con quanta ne ha vista
    # un'altra persona sullo stesso libro condiviso. Unire le due mappe
    # darebbe a entrambi una copertura che nessuno dei due ha.
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    library = Column(String, nullable=False, default="default")
    calibre_book_id = Column(Integer, nullable=False)
    bins = Column(LargeBinary, nullable=False)
    coverage = Column(Float, nullable=False, default=0.0)
    updated_at = Column(DateTime, default=datetime.utcnow)


class DuplicatiDistinti(Base):
    """
    "Questi due NON sono lo stesso libro."

    Senza ricordarlo, la ricerca dei doppioni ripropone ogni volta le stesse
    coppie gia' esaminate, e chi ha una biblioteca vera smette di usarla
    dopo il secondo giro: il valore di una coda di lavoro sta tutto nel
    fatto che si accorcia.

    Serve davvero, non e' difensivo: i falsi positivi legittimi esistono e
    sono comuni. Due volumi di un'opera in piu' tomi hanno spesso lo stesso
    titolo e lo stesso autore; un'antologia e il racconto che le da' il
    nome pure; e un libro in due traduzioni diverse e' un caso in cui la
    risposta giusta dipende da chi possiede la biblioteca, non dai dati.

    La coppia e' registrata ORDINATA (vedi chiave_coppia): "A e B sono
    distinti" e "B e A sono distinti" sono la stessa affermazione, e
    scriverle come due righe vorrebbe dire non ritrovarne una delle due.
    """

    __tablename__ = "duplicati_distinti"
    __table_args__ = (UniqueConstraint("chiave"),)

    id = Column(Integer, primary_key=True, index=True)
    # "biblioteca:id|biblioteca:id", i due estremi in ordine.
    chiave = Column(String, nullable=False, index=True)
    library_a = Column(String, nullable=False)
    book_a = Column(Integer, nullable=False)
    library_b = Column(String, nullable=False)
    book_b = Column(Integer, nullable=False)
    deciso_il = Column(DateTime, default=datetime.utcnow)


class SuggerimentoRifiutato(Base):
    """
    "Questo libro non me lo suggerire piu'."

    Gemella di `DuplicatiDistinti`, e per la stessa ragione: il valore di una
    coda di lavoro sta nel fatto che si accorcia. L'elenco dei libri che
    sembrano letti non e' una lista salvata — si ricalcola a ogni apertura
    della pagina da quanto del libro risulta attraversato — quindi senza un
    posto dove scrivere "questo no", un suggerimento sbagliato torna per
    sempre (segnalato da Paolo il 03/11/2026: «metti che mi suggerisce un
    libro che io non voglio marcare, poi rimane li' a vita?»).

    I falsi positivi sono comuni e legittimi, non sono un difetto da
    correggere: un saggio di cui si leggono tre capitoli su dieci puo'
    superare la soglia di copertura senza essere stato letto, e un libro
    sfogliato tutto in cinque minuti pure.

    **Per utente**, a differenza dei doppioni. Un doppione e' un fatto della
    biblioteca, uguale per tutti; «l'ho letto» e' di chi legge, e la stessa
    pagina lo dice gia' mostrando solo la copertura di chi guarda.

    **Si puo' riprendere**: la riga si cancella, e il suggerimento torna.
    Una decisione presa per sbaglio non deve essere definitiva — e' la stessa
    accortezza dei doppioni, dove «non sono lo stesso libro» si disfa.
    """

    __tablename__ = "suggerimenti_rifiutati"
    __table_args__ = (UniqueConstraint("user_id", "library", "calibre_book_id", "tipo"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    library = Column(String, nullable=False)
    calibre_book_id = Column(Integer, nullable=False)
    # Quale suggerimento si e' rifiutato. Oggi uno solo ("da_segnare_letto"),
    # ma la colonna c'e' da subito: la pagina Interventi ha sette voci e
    # ognuna prima o poi vorra' lo stesso bottone, e aggiungerla dopo
    # vorrebbe dire una migrazione invece di una stringa nuova.
    tipo = Column(String, nullable=False, default="da_segnare_letto")
    deciso_il = Column(DateTime, default=datetime.utcnow)


def chiave_coppia(lib_a: str, id_a: int, lib_b: str, id_b: int) -> str:
    """La chiave di una coppia, indipendente dall'ordine in cui arriva."""
    estremi = sorted([f"{lib_a}:{id_a}", f"{lib_b}:{id_b}"])
    return "|".join(estremi)


class EntitaDistinte(Base):
    """
    "Queste due grafie sono due cose diverse."

    Gemella di [DuplicatiDistinti], e nasce dalla stessa constatazione: una
    coda di lavoro vale quanto la sua capacita' di accorciarsi. La pagina
    Entita' propone le grafie che si somigliano, ma l'algoritmo non sa
    distinguere un refuso da un omonimo — "Giuseppe Berta" e "Giuseppe Berto"
    sono uno storico e un romanziere — e senza un posto dove ricordare quel
    "no" la stessa coppia torna a ogni apertura della pagina, per sempre.
    Riscontrato in uso il 30/09/2026, dopo una pulizia in cui otto coppie su
    oltre trecento erano proprio di questo tipo.

    **La decisione e' condivisa, non personale.** I metadati della biblioteca
    sono gli stessi per tutti, e un'unione fatta da uno la vedono tutti: un
    rifiuto che valesse solo per chi l'ha espresso lascerebbe il suggerimento
    in piedi per gli altri, che lo unirebbero. Si registra chi ha deciso —
    serve a ricostruire il perche', non a limitare la validita'.

    **Non per biblioteca.** "Berta e Berto sono due persone" e' un'affermazione
    sul mondo, non su una cartella, e i gruppi si formano guardando tutte le
    biblioteche insieme proprio perche' il disordine dei nomi non si fermava
    al loro confine.

    La coppia e' registrata ORDINATA, come per i doppioni: "A e B sono
    distinti" e "B e A sono distinti" sono la stessa affermazione. Qui la
    coppia ordinata E' la chiave — non serve inventarne una di sintesi, e si
    evita il problema di scegliere un separatore che nessun nome contenga.
    """

    __tablename__ = "entita_distinte"
    __table_args__ = (UniqueConstraint("tipo", "valore_a", "valore_b"),)

    id = Column(Integer, primary_key=True, index=True)
    # 'autori' | 'serie' | 'tag' | 'editori'
    tipo = Column(String, nullable=False, index=True)
    valore_a = Column(String, nullable=False)
    valore_b = Column(String, nullable=False)
    deciso_da = Column(String, nullable=True)
    deciso_il = Column(DateTime, default=datetime.utcnow)


def coppia_ordinata(a: str, b: str) -> tuple:
    """I due estremi in ordine, cosi' che la coppia non dipenda da come arriva."""
    return tuple(sorted([a, b]))


class DoppioniScansione(Base):
    """
    L'ultima ricerca di doppioni, tenuta da parte.

    Serve perche' quella ricerca e' CARA: per decidere se due file sono lo
    stesso legge i file dal disco e ne calcola lo SHA-256. Rifarla a ogni
    apertura della pagina Interventi vuol dire aspettare, e rifarla dopo
    ogni azione vuol dire che l'azione sembra non aver fatto niente —
    il difetto riscontrato era "si carica ogni volta che la apro... e inoltre
    non pare aggiornarsi reattivamente".

    Una riga per AMBITO (una biblioteca, o "*" per tutte): sono domande
    diverse e non si possono servire con la stessa risposta. La cache si
    aggiorna in due modi, e il secondo e' quello che rende la pagina viva:
    per intero quando si chiede una nuova ricerca, e per SOTTRAZIONE quando
    si accorpa o si dichiara una coppia distinta — li' il gruppo esce
    dall'elenco subito, senza rileggere un solo byte.
    """

    __tablename__ = "doppioni_scansione"
    __table_args__ = (UniqueConstraint("ambito"),)

    id = Column(Integer, primary_key=True, index=True)
    ambito = Column(String, nullable=False, index=True)
    risultato_json = Column(Text, nullable=False)
    calcolato_il = Column(DateTime, default=datetime.utcnow)


class FileSulDispositivo(Base):
    """
    L'inventario: ogni file di libro che un lettore ha nella sua cartella.

    **Perche' esiste** (05/11/2026). Fino a oggi il server sapeva solo quello
    che *lui* aveva consegnato (`DeviceBook`) e quello che il dispositivo non
    aveva saputo accoppiare (`DeviceFlaggedBook`). Dei file che ci sono
    davvero la' sopra non sapeva niente — e per questo non poteva accorgersi
    della cosa piu' banale: lo **stesso libro presente in due copie**. Il
    difetto che le creava e' stato chiuso nel plugin 0.12.0; questa tabella
    serve a vedere e pulire quelle che ci sono.

    **Non e' uno strumento di emergenza.** Il plugin la camminata della
    cartella la fa gia' in quattro posti diversi (`_scanLocalBooks`:
    inizializza libreria, spinta di tutte le annotazioni, carico della
    sincronizzazione, calcolo dell'avanzamento) e ogni volta butta il
    risultato. Qui quel risultato resta, e diventa il dato da cui partono
    cose che oggi non si possono fare: dire «questo file lo gestisco, ma
    sotto un altro nome», far guardare al controllo del legame anche i file
    del dispositivo e non solo le righe del server, e adottare un lettore
    che ha gia' una vita.

    **E' un'istantanea, non uno storico**: un nuovo inventario sostituisce
    quello di prima per quel dispositivo. Un file che non viene piu'
    riportato non c'e' piu', e tenerne la riga direbbe una cosa falsa.

    **I campi del sidecar sono la ragione per cui questa tabella vale.**
    KOReader tiene la lettura — quanto hai letto, se l'hai finito, le note —
    in una cartella accanto al file. Senza quei numeri «quale delle due copie
    cancello» non ha risposta; con quelli ce l'ha, e misurata: su un libro
    vero le due copie erano 3367 minuti contro 24.
    """

    __tablename__ = "file_sul_dispositivo"
    __table_args__ = (UniqueConstraint("device_id", "local_path"),)

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True)
    local_path = Column(String, nullable=False)
    #: Il partial-MD5 di KOReader. **Nullo si puo'**: su un file illeggibile
    #: il calcolo non riesce, e dirlo e' meglio che non riportare il file.
    file_hash = Column(String, nullable=True, index=True)
    format = Column(String, nullable=False)
    size_bytes = Column(Integer, nullable=True)

    # ── Quello che dice il sidecar, nullo se il file non e' mai stato aperto
    #: Frazione fra 0 e 1.
    percent_finished = Column(Float, nullable=True)
    #: `reading`, `complete`, `abandoned` — la risposta che la persona ha
    #: dato alla domanda «segno questo libro come finito?».
    stato_lettura = Column(String, nullable=True)
    #: La data che KOReader scrive accanto allo stato, `YYYY-MM-DD`.
    stato_modificato = Column(String, nullable=True)
    #: **Quante**, non quali: l'inventario e' una misura, le annotazioni
    #: viaggiano per conto loro.
    annotazioni = Column(Integer, nullable=True)
    pagine = Column(Integer, nullable=True)
    #: L'XPointer di KOReader dell'ultima posizione.
    ultima_posizione = Column(String, nullable=True)

    visto_il = Column(DateTime, default=datetime.utcnow)


class TokenApplicazione(Base):
    """
    Un token con cui un'**applicazione** parla col server a nome di una
    persona: il plugin Obsidian, uno script, un domani un client nativo.

    **Perche' esiste** (05/11/2026). Il plugin Obsidian si collegava con nome
    utente e password, riceveva un token di sessione che vale sette giorni, e
    poi — per non chiedere di riaccedere ogni settimana — **conservava la
    password** nel proprio `data.json`. Quel file sta dentro il vault: cioe'
    dentro la cartella che la gente sincronizza fra computer, a volte in un
    repository git.

    Non era una svista, era il rimedio a un difetto vero («ogni tanto mi
    salta la connessione e devo riaccedere»). Ma metteva la password
    dell'intero account in un posto che viaggia. Questo token lo sostituisce:
    si ottiene una volta con la password, non scade, **si revoca**, e non da'
    accesso a niente di piu' di quello che l'account puo' fare.

    E' lo stesso disegno che i dispositivi KOReader hanno da sempre
    (`Device.device_token`), portato alle applicazioni — con una differenza.

    **Qui si conserva l'impronta, non il token.** I dispositivi il loro lo
    tengono in chiaro; un token d'applicazione nasce per vivere sul computer
    di qualcun altro, e se un giorno il database del server finisse in mano a
    qualcuno le righe dei dispositivi gliene regalerebbero i token, queste no.
    L'incoerenza fra i due resta, ed e' scritta nel backlog: si sistema
    cambiando i dispositivi, non rinunciando qui.

    **Revocare non cancella la riga.** Si scrive `revocato_il` e la riga
    resta: «questo token e' stato spento il giorno tale» e' un'informazione,
    e una riga cancellata non la racconta. L'elenco mostra solo i vivi.
    """

    __tablename__ = "token_applicazione"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                     nullable=False, index=True)
    #: Come l'ha chiamato chi l'ha creato: «Obsidian sul portatile». Serve a
    #: sapere quale spegnere quando se ne hanno tre.
    nome = Column(String, nullable=False)
    #: **L'impronta SHA-256 del token, non il token.** Si cerca per impronta:
    #: chi presenta il token lo fa passare per la stessa funzione e si
    #: confronta il risultato.
    token_hash = Column(String, nullable=False, unique=True, index=True)
    creato_il = Column(DateTime, default=datetime.utcnow)
    #: Aggiornato a ogni uso, ed e' la sola cosa che dice se un token serve
    #: ancora o e' stato dimenticato su un computer che non c'e' piu'.
    ultimo_uso_il = Column(DateTime, nullable=True)
    revocato_il = Column(DateTime, nullable=True)


class RimandoDiNota(Base):
    """
    «Quel nome, da adesso, significa quest'altro.»

    **Perche' serve.** Un `id_durevole` non cambia mai, ma due note possono
    diventare **una**: succede quando un libro viene riaccoppiato altrove e al
    libro nuovo quella stessa posizione c'e' gia' (vedi
    `_migrate_device_highlights_to_new_book`). Una delle due righe se ne va, e
    con lei se ne andrebbe il suo nome — cioe' si romperebbe un link che Paolo
    aveva incollato in un appunto due anni prima, o un marcatore in un file di
    Obsidian.

    L'identita' durevole da sola protegge il futuro; questa tabella protegge
    **il passato**. Si scrive solo nei due casi rari (fusione, e una
    promozione che finisce in una nota che c'era gia'), quindi resta piccola:
    non e' un registro di tutto, e' l'elenco delle volte in cui due nomi sono
    diventati lo stesso.

    `vecchio` e' unico perche' un nome non puo' significare due cose. Si segue
    a catena (`identita_durevole.risolvi`) con un tetto, perche' un anello
    chiuso non deve diventare un giro infinito dentro una richiesta web.
    """

    __tablename__ = "rimandi_di_nota"

    id = Column(Integer, primary_key=True, index=True)
    vecchio = Column(String, nullable=False, unique=True, index=True)
    nuovo = Column(String, nullable=False, index=True)
    creato_il = Column(DateTime, default=datetime.utcnow)


class ClienteDiAppunti(Base):
    """
    Chi tiene le note fuori da Kolibre: per ora il vault Obsidian di Paolo.

    **Nessuna registrazione**, per sua decisione del 05/11/2026: si installa
    il plugin e funziona. Allora chi e'? **Il token d'applicazione con cui
    parla.** Quel token ha gia' un nome — quello che Paolo scrive quando lo
    crea, «Obsidian sul portatile» — quindi la pagina puo' dire di chi sta
    parlando senza avergli chiesto niente in piu'. Chi accede con nome e
    password (server vecchio) non ha un token: ricade su una riga sola per
    account, `token_id` nullo.

    **E' una fotografia, non uno specchio**, e per questo porta `visto_il`: il
    server non sa cosa c'e' nel vault adesso, sa cosa c'era quando il plugin
    gliel'ha raccontato. La pagina mostra la data accanto ai conti. Un
    registro spacciato per specchio e' precisamente il difetto del manifesto
    che ha messo 21 libri in doppia copia sul Kindle.
    """

    __tablename__ = "clienti_di_appunti"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                     nullable=False, index=True)
    #: Il token con cui si e' presentato, che e' anche il suo nome. Nullo per
    #: chi accede con nome e password.
    token_id = Column(Integer, ForeignKey("token_applicazione.id", ondelete="CASCADE"),
                      nullable=True, index=True)
    #: Quando ha raccontato l'ultima volta. **Senza questa data i conti
    #: mentono**, perche' nessuno sa di quando sono.
    visto_il = Column(DateTime, default=datetime.utcnow)
    #: Quanti file e quanti blocchi conteneva quel racconto. Ridondanti —
    #: si contano da `blocchi_di_appunti` — ma la pagina li mostra in testa e
    #: contarli a ogni apertura e' lavoro per niente.
    file_visti = Column(Integer, default=0)
    note_viste = Column(Integer, default=0)

    __table_args__ = (UniqueConstraint("user_id", "token_id"),)


class BloccoDiAppunti(Base):
    """
    Un blocco dentro un file del vault, come il plugin l'ha raccontato.

    Tre campi sono il cuore del confronto a tre vie: `id_durevole` dice **di
    quale nota** parla quel blocco (e sopravvive al rifacimento della riga nel
    database), `impronta_base` e' quello che Kolibre aveva scritto l'ultima
    volta, `impronta_attuale` e' com'e' adesso nel file. Dal terzo valore —
    com'e' adesso sul server — escono i quattro casi, e solo uno ha bisogno di
    Paolo.

    `testo_attuale` si riempie **solo quando le due impronte non
    corrispondono**, cioe' solo per i pochi blocchi che lui ha ritoccato:
    serve alla pagina per mostrare i due testi affiancati, e mandare il testo
    di milleduecento blocchi a ogni sincronizzazione per poi non guardarlo
    sarebbe sprecato.

    **Una riga per (cliente, nota)**: un blocco spostato a mano da Paolo in
    un'altra parte del file resta lo stesso blocco, perche' lo si riconosce
    dal nome e non dalla posizione.
    """

    __tablename__ = "blocchi_di_appunti"

    id = Column(Integer, primary_key=True, index=True)
    cliente_id = Column(Integer, ForeignKey("clienti_di_appunti.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    #: Il file nel vault, come lo chiama il plugin. Serve alla pagina per
    #: dire dove sta una nota, e a riconoscere che due blocchi stanno insieme.
    percorso = Column(String, nullable=False)
    id_durevole = Column(String, nullable=False, index=True)
    impronta_base = Column(String, nullable=True)
    impronta_attuale = Column(String, nullable=True)
    testo_attuale = Column(String, nullable=True)
    visto_il = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("cliente_id", "id_durevole"),)


class NotaConsegnata(Base):
    """
    Una nota che questo client ha **ricevuto almeno una volta**.

    **Il difetto da cui nasce** (06/11/2026). `BloccoDiAppunti` e' una
    fotografia: dice cosa c'e' nel vault adesso, e il racconto nuovo
    sostituisce il vecchio. Giusto, ed e' il motivo per cui un file
    cancellato torna «non creato» invece di restare «in pari» per sempre. Ma
    una fotografia **non sa dire cosa c'era prima**: «questo libro non ha
    nessun blocco nel vault» e' identico, carattere per carattere, a «questo
    libro non ha mai avuto un file». Due situazioni opposte, lo stesso dato —
    ed e' per questo che il plugin ricreava ogni file che Paolo cancellava e
    rimetteva ogni nota che togliesse a mano. Non per insistenza: non aveva
    modo di distinguere.

    Questa tabella e' la seconda memoria, di natura diversa: non «cosa c'e'
    adesso» ma **«cosa ti ho gia' consegnato»**. Da qui escono due stati che
    prima erano uno: `mai_consegnata` (da scrivere) e `togliata_da_te` (da
    lasciare in pace).

    **La consegna e' provata dalla fotografia stessa**: una nota che e'
    comparsa in un racconto e' stata consegnata. Questo registro e' l'unione
    di tutte le fotografie nel tempo, quindi non serve nessun protocollo in
    piu' col plugin — e nasce da se', riempito dal primo racconto che arriva.
    Conseguenza da sapere: i file cancellati **prima** che il registro
    esistesse vengono ricreati una volta sola, e dalla seconda restano
    cancellati.

    Le righe non si cancellano mai. Se una nota viene eliminata per sempre in
    Kolibre la sua riga resta orfana, e non fa danno: i conti partono sempre
    dalle note che il server ha, quindi una riga che non corrisponde a niente
    non compare da nessuna parte.
    """

    __tablename__ = "note_consegnate"

    id = Column(Integer, primary_key=True, index=True)
    cliente_id = Column(Integer, ForeignKey("clienti_di_appunti.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    #: Il nome durevole della nota. Non il numero di riga: quello si muove.
    id_durevole = Column(String, nullable=False, index=True)
    consegnata_il = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("cliente_id", "id_durevole"),)


class DecisioneDiAppunti(Base):
    """
    Una decisione di Paolo su un libro: «non mandarlo», o «rimandalo da zero».

    **Sta nel server e non nel plugin** perche' e' una regola sui dati, non una
    preferenza di quel computer: se domani ci fosse un secondo client, un
    libro bloccato deve restare bloccato per tutti. E perche' il server non
    puo' scrivere nel vault, quindi una decisione qui non e' un'azione: e'
    un'**istruzione** che il plugin esegue al prossimo giro.

    Un libro bloccato **non si cancella dal vault**: il file che c'e' resta
    dov'e', intoccato. Bloccare vuol dire «smetti di aggiornarlo», non
    «buttalo» — e quello che Paolo ci ha scritto dentro non si tocca mai.

    `calibre_book_id` e' nullo per un file non ancora accoppiato, che non ha
    un libro: quelli non si possono bloccare, ed e' una semplificazione
    consapevole (sono tre, e passeggeri per natura).
    """

    __tablename__ = "decisioni_di_appunti"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                     nullable=False, index=True)
    library = Column(String, nullable=False)
    calibre_book_id = Column(Integer, nullable=True)
    bloccato = Column(Boolean, nullable=False, default=False)
    #: Il titolo al momento della decisione. Non e' l'identita' — quella e'
    #: (biblioteca, id) — ma serve a far combaciare la decisione col
    #: raggruppamento del plugin, che per i file usa il titolo.
    titolo = Column(String, nullable=True)
    deciso_il = Column(DateTime, default=datetime.utcnow)
    #: «Rifai il file di questo libro da zero», con la data in cui l'ho
    #: chiesto. Nullo quando non c'e' niente da rifare.
    #:
    #: **E' un'istruzione, e si spegne quando il plugin dice di averla
    #: eseguita** (nell'inventario, campo `rifatti`). Non quando il server la
    #: manda: il server non sa se il plugin e' arrivato in fondo, e se si
    #: spegnesse all'invio un plugin interrotto a meta' lascerebbe il file
    #: come l'ha trovato con l'istruzione gia' consumata. Se invece il
    #: plugin crolla, l'istruzione resta e si riprova al giro dopo.
    #:
    #: Rifare il file **cancella quello che hai scritto tu dentro quei
    #: blocchi**: e' il senso del comando, e la pagina lo dice prima di
    #: chiederlo.
    rifai_dal = Column(DateTime, nullable=True)

    __table_args__ = (UniqueConstraint("user_id", "library", "calibre_book_id"),)


class DecisioneDiNota(Base):
    """
    Come si risolve il conflitto su **una** nota.

    **Da zero.** Un conflitto vero e' quando lo stesso brano e' cambiato in
    tutte due le parti rispetto all'ultima volta che Kolibre l'ha scritto: tu
    hai corretto un refuso nel vault e nel frattempo e' cambiato anche sul
    server (una risincronizzazione dal lettore, una modifica dal browser).
    Nessuno dei due puo' decidere da se' chi ha ragione.

    Paolo ha deciso (05/11/2026) che **si risolve dalla pagina di Kolibre e
    il plugin esegue**. Quindi qui non si scrive un testo: si scrive **quale
    delle due versioni vince**, e il plugin al prossimo giro fa la cosa che
    ne segue.

    - `kolibre`: il plugin riscrive la parte sopra il marcatore con il testo
      del server. Quello che hai scritto **sotto** il marcatore resta, come
      sempre.
    - `mio`: il plugin non tocca il testo e aggiorna solo la base del
      marcatore a quello che c'e' nel file — cosi' da quel momento il brano
      del vault e' la nuova base e il conflitto non si ripresenta ogni volta.

    La decisione e' per nota (`id_durevole`) e non per libro: due note dello
    stesso libro possono andare in direzioni diverse.

    Si cancella quando il plugin dice di averla eseguita, per la stessa
    ragione scritta su `DecisioneDiAppunti.rifai_dal`.
    """

    __tablename__ = "decisioni_di_nota"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                     nullable=False, index=True)
    #: Il nome durevole della nota. Non il numero di riga: quello si muove.
    id_durevole = Column(String, nullable=False, index=True)
    #: "kolibre" oppure "mio". Vedi SCELTE_DI_CONFLITTO.
    scelta = Column(String, nullable=False)
    deciso_il = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("user_id", "id_durevole"),)


#: Le sole due risposte possibili a un conflitto. Un insieme chiuso: una
#: scelta scritta a mano che non e' una di queste viene rifiutata, invece di
#: finire nel database e non voler dire niente per nessuno.
SCELTE_DI_CONFLITTO = ("kolibre", "mio")
