from fastapi import APIRouter, Depends, HTTPException

from .. import config
from .libraries import biblioteca_scrivibile, default_library_param
from ..logging_utils import log_message
from ..calibre.library import CalibreLibrary
from ..calibre.connection import PAGE_COUNT_COLUMN_LABEL, CALIBRE_PAGE_COUNT_COLUMN_LABEL
from ..calibre.write_queue import CalibreWriteQueue
from ..deps import get_write_queue

router = APIRouter(prefix="/api/kolibre/custom-columns", tags=["custom-columns"])


@router.get("")
def list_custom_columns(library: str = Depends(default_library_param)):
    lib = CalibreLibrary(config.library_path(library))
    return lib.list_custom_columns()


@router.post("")
async def create_custom_column(
    payload: dict,
    library: str = Depends(biblioteca_scrivibile),
    write_queue: CalibreWriteQueue = Depends(get_write_queue),
):
    label = (payload.get("label") or "").strip()
    name = (payload.get("name") or "").strip()
    datatype = (payload.get("datatype") or "").strip()
    if not label or not name or not datatype:
        raise HTTPException(status_code=400, detail="label, name e datatype sono obbligatori")

    library_path = config.library_path(library)
    try:
        col_id = await write_queue.submit(
            "create_custom_column",
            {"label": label, "name": name, "datatype": datatype, "display": payload.get("display")},
            library_path,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    log_message("info", "custom-columns", f"Created custom column '#{label}' ({datatype}) in library '{library}'")
    return {"status": "ok", "id": col_id}


@router.delete("/{label}")
async def delete_custom_column(
    label: str,
    library: str = Depends(biblioteca_scrivibile),
    write_queue: CalibreWriteQueue = Depends(get_write_queue),
):
    if label in (PAGE_COUNT_COLUMN_LABEL, CALIBRE_PAGE_COUNT_COLUMN_LABEL):
        raise HTTPException(
            status_code=400,
            detail="La colonna 'Pagine (stimate)' è gestita automaticamente e non può essere eliminata.",
        )
    library_path = config.library_path(library)
    await write_queue.submit("delete_custom_column", {"label": label}, library_path)
    log_message("info", "custom-columns", f"Deleted custom column '#{label}' from library '{library}'")
    return {"status": "ok"}
