import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, database, auth, schemas
from ..services import stats_service
from .libraries import default_library_param, resolve_default_library_folder

router = APIRouter(prefix="/api/kolibre/stats", tags=["stats"])


def _get_cache(db: Session, library: str, user_id: int):
    """La cache e' per (utente, biblioteca): le sessioni di lettura hanno
    sempre avuto un utente, questa cache no, e su una biblioteca condivisa
    avrebbe mostrato a ciascuno le ore di tutti."""
    return db.query(models.StatsCache).filter(
        models.StatsCache.user_id == user_id,
        models.StatsCache.library == library,
    ).first()


@router.get("/summary")
def get_stats_summary(
    library: str = Depends(default_library_param),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    Reads the background-refreshed cache (see stats_service.refresh_stats_cache,
    run periodically by main.py::_refresh_stats_loop) instead of recomputing
    on every page load — the whole point of the cache. Falls back to a live
    compute only for a library the background loop hasn't reached yet (e.g.
    the very first refresh cycle hasn't run, or the library was just
    created) so a brand-new library isn't stuck showing nothing until the
    next cycle.
    """
    cache = _get_cache(db, library, current_user.id)
    if cache:
        return json.loads(cache.summary_json)
    return stats_service.compute_summary(db, library, current_user.id)


@router.get("/raw")
def get_stats_raw(
    library: str = Depends(default_library_param),
    from_: str = None,
    to: str = None,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Cached full session list (see get_stats_summary's own docstring for
    the caching rationale); from_/to filter the already-loaded list in
    Python rather than re-querying, cheap enough not to need its own cache
    entry per date range."""
    cache = _get_cache(db, library, current_user.id)
    rows = json.loads(cache.raw_json) if cache else stats_service.compute_raw(db, library, current_user.id)
    if from_:
        rows = [r for r in rows if r["start_time"] >= from_]
    if to:
        rows = [r for r in rows if r["start_time"] <= to]
    return rows


@router.get("/timeline")
def get_stats_timeline(
    library: str = Depends(default_library_param),
    days: int = 365,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Cached timeline (see get_stats_summary's own docstring); the cache
    always holds stats_service._TIMELINE_CACHE_DAYS days, `days` just slices
    that already-loaded window down."""
    cache = _get_cache(db, library, current_user.id)
    rows = json.loads(cache.timeline_json) if cache else stats_service.compute_timeline(db, library, current_user.id, days=days)
    if cache and days < stats_service._TIMELINE_CACHE_DAYS:
        cutoff = (datetime.utcnow() - timedelta(days=days)).date().isoformat()
        rows = [r for r in rows if r["date"] >= cutoff]
    return rows


@router.get("/library-overview")
def get_library_overview(
    library: str = Depends(default_library_param),
):
    """
    Le quattordici statistiche di catalogo, contate sul server.

    Prima le calcolava il browser, che per farlo scaricava il catalogo
    INTERO: su una biblioteca da 5.843 libri quasi sei megabyte di titoli,
    descrizioni e identificatori per ricavarne un paio di chilobyte di
    conteggi — ed era proprio la biblioteca su cui le statistiche di
    catalogo servono di piu'.

    Niente cache: legge il catalogo, che cambia per conto suo, e la
    scansione parte da list_books() che una sua cache ce l'ha gia'.
    """
    return stats_service.panoramica_biblioteca(library)


@router.get("/annotation-intensity")
def get_annotation_intensity(
    library: str = Depends(default_library_param),
    limit: int = 10,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Quali libri hanno fatto fermare di piu', in annotazioni ogni
    centomila caratteri letti — vedi stats_service.intensita_annotazioni."""
    return stats_service.intensita_annotazioni(db, library, current_user, limite=limit)


@router.get("/libri-letti")
def get_libri_letti(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    I libri spuntati come letti, con l'anagrafica di chi li ha scritti.

    **Senza parametro `library`**, e non per dimenticanza: "quanti libri ho
    letto" non e' una proprieta' di una cartella. Vedi
    stats_service.libri_letti per il resto, incluso perche' questo non puo'
    venire dalle sessioni di lettura.
    """
    return stats_service.libri_letti(db, current_user)


@router.post("/recompute")
def recompute_stats(db: Session = Depends(database.get_db)):
    """
    Manual trigger for reprocess_all_device_backups + refresh_stats_cache —
    normally these only run once at server startup and then once every 24h
    (main.py::_refresh_stats_loop's "safety net"), or immediately after a
    fresh device backup upload. That leaves a real gap: rescanning a
    library / recomputing hashes populates BookHash for previously-orphaned
    sessions, but nothing re-walks the ALREADY-STORED statistics.sqlite3
    files against that newly-populated BookHash until the next cycle — a
    server that isn't restarted can leave a user staring at stale/missing
    stats for up to a day with no way to force it. This exposes exactly
    what the background loop does, on demand.
    """
    reprocess_summary = stats_service.reprocess_all_device_backups(db)
    libraries_refreshed = stats_service.refresh_stats_cache(db)
    return {**reprocess_summary, "libraries_refreshed": libraries_refreshed}


@router.get("/orphan-sessions")
def list_orphan_sessions(
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(database.get_db),
):
    """
    Reading sessions imported by process_statistics_db for a book whose md5
    never resolved via BookHash (see OrphanReadingSession's own docstring).
    Deliberately not wired into any dashboard query — grouping by (md5,
    title) into the handful of distinct books a device actually has is a
    frontend concern (see POST /orphan-sessions/pair for the matching
    manual-pairing action).
    """
    rows = (
        db.query(models.OrphanReadingSession)
        .filter(models.OrphanReadingSession.user_id == current_user.id)
        .order_by(models.OrphanReadingSession.start_time.desc())
        .all()
    )
    return {
        "count": len(rows),
        "sessions": [
            {
                "id": r.id,
                "device_id": r.device_id,
                "md5": r.md5,
                "title": r.title,
                "authors": r.authors,
                "series": r.series,
                "start_time": r.start_time.isoformat(),
                "duration": r.duration,
                "pages_read": r.pages_read,
            }
            for r in rows
        ],
    }


@router.post("/orphan-sessions/pair")
def pair_orphan_sessions(
    payload: dict,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(database.get_db),
):
    """
    Manual "Accoppia manualmente" action for orphan reading sessions —
    same shape as devices.py's pair_device_book/queue_flagged_book_action
    "pair" action for OrphanHighlight, applied to stats_service.
    pair_orphan_sessions (see StatsHashPairing's own docstring for why this
    is needed at all: automatic hash-based resolution has nothing left to
    recover for a book orphaned before BookHashHistory existed).

    Body: {md5: str, library: str, calibre_book_id: int}. Refreshes this
    library's stats cache afterward so the dashboard reflects the newly
    migrated sessions immediately, without waiting for the next periodic
    refresh — same reasoning as the /recompute endpoint above.
    """
    md5 = payload.get("md5")
    library = payload.get("library")
    calibre_book_id = payload.get("calibre_book_id")
    if not md5 or not library or not calibre_book_id:
        raise HTTPException(status_code=400, detail="md5, library e calibre_book_id sono obbligatori")

    result = stats_service.pair_orphan_sessions(db, current_user.id, md5, library, int(calibre_book_id))
    stats_service.refresh_stats_cache(db)
    return {"status": "ok", **result}


@router.post("/orphan-sessions/discard")
def discard_orphan_sessions(
    payload: dict,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(database.get_db),
):
    """
    "Scarta" action for orphan reading sessions — the complement of
    /orphan-sessions/pair, for a probable book that simply isn't worth
    tracking for statistics (as opposed to a mismatched guess). Body:
    {md5: str}. Permanent: removes the existing orphan sessions for this
    md5 right away and remembers the decision (StatsHashDiscard) so a
    future device sync reporting the same md5 never recreates them — see
    stats_service.discard_orphan_sessions.
    """
    md5 = payload.get("md5")
    if not md5:
        raise HTTPException(status_code=400, detail="md5 è obbligatorio")

    removed = stats_service.discard_orphan_sessions(db, current_user.id, md5)
    stats_service.refresh_stats_cache(db)
    return {"status": "ok", "sessions_discarded": removed}


def _serialize_chart(c: models.SavedChart) -> dict:
    return {
        "id": c.id,
        "library": c.library,
        "name": c.name,
        "chart_type": c.chart_type,
        "data_source": c.data_source,
        "group_by": c.group_by,
        "metric": c.metric,
        # NULL on a pre-v2 row (see SavedChart's own docstring) reads out as
        # None/"grouped"/{} here — the frontend's own defaults already treat
        # those exactly the same as "not configured", so no extra branching
        # is needed on the client for old vs new saved charts.
        "group_by_secondary": c.group_by_secondary,
        "chart_mode": c.chart_mode or "grouped",
        "filters": json.loads(c.filters_json) if c.filters_json else {},
        "sort_by": c.sort_by,
        "sort_order": c.sort_order,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


def _get_owned_chart(db: Session, id: int, current_user: models.User) -> models.SavedChart:
    chart = db.query(models.SavedChart).filter(
        models.SavedChart.id == id, models.SavedChart.user_id == current_user.id
    ).first()
    if not chart:
        raise HTTPException(status_code=404, detail="Grafico non trovato")
    return chart


@router.get("/charts")
def list_saved_charts(
    library: str = Depends(default_library_param),
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(database.get_db),
):
    """Saved chart-builder configurations for the current user, scoped to
    one library — same per-library scoping as every other stats endpoint
    here, since a saved chart's group-by/metric only means anything against
    that library's own /raw or /timeline rows."""
    rows = (
        db.query(models.SavedChart)
        .filter(models.SavedChart.user_id == current_user.id, models.SavedChart.library == library)
        .order_by(models.SavedChart.created_at.desc())
        .all()
    )
    return [_serialize_chart(c) for c in rows]


@router.post("/charts")
def create_saved_chart(
    payload: schemas.SavedChartCreate,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(database.get_db),
):
    """Persists the chart-builder's configuration only (chart type + data
    source + group-by + metric) — never the computed data itself, see
    SavedChart's own docstring. The frontend re-aggregates from /raw or
    /timeline every time the chart is opened."""
    chart = models.SavedChart(
        user_id=current_user.id,
        # Come per le annotazioni: la biblioteca di ripiego e' la prima che
        # questa persona vede, non una cartella chiamata "default" — quel
        # nome non corrisponde a niente sul disco.
        library=payload.library or resolve_default_library_folder(db, current_user) or "",
        name=payload.name,
        chart_type=payload.chart_type,
        data_source=payload.data_source,
        group_by=payload.group_by,
        metric=payload.metric or "duration_sum",
        group_by_secondary=payload.group_by_secondary or None,
        chart_mode=payload.chart_mode or "grouped",
        filters_json=json.dumps(payload.filters) if payload.filters else None,
        sort_by=payload.sort_by or None,
        sort_order=payload.sort_order or None,
    )
    db.add(chart)
    db.commit()
    return _serialize_chart(chart)


@router.put("/charts/{id}")
def update_saved_chart(
    id: int,
    payload: schemas.SavedChartCreate,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(database.get_db),
):
    """Full replace of a saved chart's config — the builder's "Salva" action
    on an already-saved chart reuses this instead of delete+recreate, so the
    id (and its position in the saved-charts list) stays stable."""
    chart = _get_owned_chart(db, id, current_user)
    chart.library = payload.library or resolve_default_library_folder(db, current_user) or ""
    chart.name = payload.name
    chart.chart_type = payload.chart_type
    chart.data_source = payload.data_source
    chart.group_by = payload.group_by
    chart.metric = payload.metric or "duration_sum"
    chart.group_by_secondary = payload.group_by_secondary or None
    chart.chart_mode = payload.chart_mode or "grouped"
    chart.filters_json = json.dumps(payload.filters) if payload.filters else None
    chart.sort_by = payload.sort_by or None
    chart.sort_order = payload.sort_order or None
    db.commit()
    return _serialize_chart(chart)


@router.delete("/charts/{id}")
def delete_saved_chart(
    id: int,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(database.get_db),
):
    chart = _get_owned_chart(db, id, current_user)
    db.delete(chart)
    db.commit()
    return {"status": "ok"}
