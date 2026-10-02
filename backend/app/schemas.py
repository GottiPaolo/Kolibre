from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from datetime import datetime

class UserCreate(BaseModel):
    username: str
    password: str
    fullname: Optional[str] = None
    is_admin: Optional[bool] = False

class UserResponse(BaseModel):
    id: int
    username: str
    fullname: Optional[str] = None
    photo_url: Optional[str] = None
    is_admin: bool
    # Permessi dell'account (28/09/2026). Il fondatore sta fuori da ogni
    # limitazione: i suoi flag sono veri per coerenza con l'interfaccia, non
    # perche' vengano consultati.
    is_founder: bool = False
    can_create_libraries: bool = False
    can_create_users: bool = False
    can_manage_permissions: bool = False
    can_register_devices: bool = True
    can_edit_authors: bool = False
    created_at: datetime

    class Config:
        from_attributes = True

class UserUpdate(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    fullname: Optional[str] = None

class Token(BaseModel):
    access_token: str
    token_type: str

class DeviceCreate(BaseModel):
    name: str
    model: str
    hardware_id: Optional[str] = None

class DeviceResponse(BaseModel):
    id: int
    name: str
    model: str
    hardware_id: Optional[str] = None
    is_default: bool
    device_token: str
    last_sync_at: Optional[datetime] = None
    last_backup_at: Optional[datetime] = None
    storage_used: Optional[int] = None
    storage_total: Optional[int] = None
    storage_available: Optional[int] = None
    folder_layout: str
    write_folder_cover: bool
    plugin_version: Optional[str] = None
    last_seen_at: Optional[datetime] = None
    delete_policy: str = "ask"

    class Config:
        from_attributes = True

class DeviceUpdate(BaseModel):
    name: Optional[str] = None
    model: Optional[str] = None
    folder_layout: Optional[str] = None
    write_folder_cover: Optional[bool] = None
    delete_policy: Optional[str] = None  # auto | ask | never

class SyncQueueCreate(BaseModel):
    calibre_book_id: int
    action: str
    format: Optional[str] = None

class SyncQueueResponse(BaseModel):
    id: int
    calibre_book_id: int
    action: str
    format: Optional[str] = None
    status: str
    timestamp: datetime

    class Config:
        from_attributes = True

class HighlightCreate(BaseModel):
    calibre_book_id: int
    library: Optional[str] = "default"
    text: str
    comment: Optional[str] = None
    chapter: Optional[str] = None
    page: Optional[int] = None
    cfi_position: Optional[str] = None
    color: Optional[str] = "yellow"

class HighlightResponse(BaseModel):
    id: int
    calibre_book_id: int
    text: str
    comment: Optional[str] = None
    page: Optional[int] = None
    cfi_position: Optional[str] = None
    color: str
    created_at: datetime

    class Config:
        from_attributes = True

class ReadingSessionCreate(BaseModel):
    calibre_book_id: int
    device_id: Optional[int] = None
    start_time: datetime
    duration: int
    pages_read: Optional[int] = 0

class ReadingSessionResponse(BaseModel):
    id: int
    calibre_book_id: int
    device_id: Optional[int] = None
    start_time: datetime
    duration: int
    pages_read: int

    class Config:
        from_attributes = True

class SavedChartCreate(BaseModel):
    library: Optional[str] = "default"
    name: str
    chart_type: str
    data_source: str
    group_by: str  # asse X
    metric: Optional[str] = "duration_sum"  # asse Y
    # v2: raggruppamento secondario (serie) + modalità barre + filtri —
    # tutti opzionali per restare compatibili con un client vecchio che
    # posta ancora solo i campi v1 (vedi SavedChart's own docstring).
    group_by_secondary: Optional[str] = None
    chart_mode: Optional[str] = "grouped"
    filters: Optional[Dict[str, Any]] = None
    # v3: ordinamento esplicito dei bucket del grafico — None = policy
    # legacy (vedi SavedChart's own v3 docstring).
    sort_by: Optional[str] = None
    sort_order: Optional[str] = None
class LibraryCreate(BaseModel):
    name: str


class LibraryImport(BaseModel):
    name: str
    path: str


class LibraryResponse(BaseModel):
    id: int
    name: str
    path: str
    books_count: int = 0
    authors_count: int = 0
    size_bytes: int = 0


class IngestImportRequest(BaseModel):
    id: int
    library: Optional[str] = None
    title: Optional[str] = None
    author: Optional[str] = None
    # Tutti opzionali e con fallback al valore già presente su IngestedBook
    # (auto-estratto in staging, vedi metadata_parser.py) se omessi — lo
    # stesso pattern già usato sopra per title/author, così l'editor metadati
    # esteso (frontend) può limitarsi a rimandare indietro solo ciò che
    # l'utente ha davvero toccato.
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    series: Optional[str] = None
    series_index: Optional[float] = None
    language: Optional[str] = None
    isbn: Optional[str] = None
