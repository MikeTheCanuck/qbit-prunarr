"""qBit Prunarr — FastAPI app."""
import asyncio
import hashlib
import logging
from datetime import datetime
import os
import time
from html import escape
from typing import Optional
from urllib.parse import quote

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from inode_scan import scan
from grouping import OrphanGroup, group_download_orphans
from orphans import (
    OrphanCandidate,
    classify_download_orphans,
    classify_media_orphans,
    delete_orphan,
    is_tv_path,
    mark_superseded,
    path_tracked,
    prune_empty_tree,
)
from pathmap import to_relative
from plex import PlexClient
from qbit import QBitClient
from radarr import RadarrClient
from sonarr import SonarrClient

app = FastAPI()
templates = Jinja2Templates(directory="templates")
logger = logging.getLogger("qbit-prunarr")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(_handler)
    logger.propagate = False

# Paths removed by the most recent bulk delete, shown under its banner.
_last_bulk_deleted: list[str] = []

BUCKETS = [
    ("180d+", 180, None),
    ("90–180d", 90, 180),
    ("30–90d", 30, 90),
    ("0–30d", 0, 30),
]

DATA_ROOT = os.environ.get("DATA_ROOT", "/data")
MEDIA_SUBDIRS = ["media/movies", "media/movies-no-backup", "media/tv", "media/tv-no-backup"]
TV_SUBDIRS = {"media/tv", "media/tv-no-backup"}
DOWNLOAD_SUBDIRS = ["torrents", "usenet"]
QBIT_SUBDIRS = ["torrents"]  # subdirs qBittorrent has authority over — not usenet

_scan_cache: dict[int, OrphanCandidate] = {}
_group_cache: dict[str, OrphanGroup] = {}


def _current_data_root() -> str:
    """Read DATA_ROOT live from the environment (same pattern as run_scan)
    rather than the module-level constant, which goes stale under test
    fixtures that set DATA_ROOT after import."""
    return os.environ.get("DATA_ROOT", DATA_ROOT)


def _get_client() -> QBitClient:
    return QBitClient(
        base_url=os.environ["QBIT_URL"],
        username=os.environ["QBIT_USERNAME"],
        password=os.environ["QBIT_PASSWORD"],
    )


def _get_tag() -> str:
    return os.environ.get("QBIT_TAG", "only-for-ratio")


def _format_gb(size_bytes: int) -> str:
    """1 decimal place at 1GB+ (2 decimals of precision on a multi-GB
    file is noise, not signal, for a "should I delete this" decision);
    2 decimals below 1GB, where the extra precision can actually matter."""
    gb = size_bytes / 1e9
    return f"{gb:.1f}" if gb >= 1 else f"{gb:.2f}"


def _enrich(torrent: dict) -> dict:
    t = dict(torrent)
    t["days_inactive"] = int((time.time() - t["last_activity"]) / 86400)
    t["size_gb"] = _format_gb(t["size"])
    return t


def _bucket_torrents(torrents: list[dict]) -> list[dict]:
    """Group torrents into age buckets (oldest first)."""
    groups: dict[str, list[dict]] = {label: [] for label, _, _ in BUCKETS}
    for t in torrents:
        for label, min_days, max_days in BUCKETS:
            if t["days_inactive"] >= min_days and (
                max_days is None or t["days_inactive"] < max_days
            ):
                groups[label].append(t)
                break
    return [{"label": label, "torrents": groups[label]} for label, _, _ in BUCKETS]


@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request, min_days: int = 30, flash: Optional[str] = None
):
    try:
        with _get_client() as client:
            client.login()
            raw_torrents = client.get_torrents(_get_tag())
    except ValueError:
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "error": "Auth failed — check config",
                "buckets": [],
                "min_days": min_days,
                "total_count": 0,
                "total_gb": 0.0,
                "flash": flash,
            },
        )
    except Exception:
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "error": "qBit unreachable",
                "buckets": [],
                "min_days": min_days,
                "total_count": 0,
                "total_gb": 0.0,
                "flash": flash,
            },
        )

    enriched = [_enrich(t) for t in raw_torrents]
    filtered = [t for t in enriched if t["days_inactive"] >= min_days]
    filtered.sort(key=lambda t: t["last_activity"])
    buckets = _bucket_torrents(filtered)
    total_gb = round(sum(t["size"] for t in filtered) / 1e9, 2)

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "buckets": buckets,
            "min_days": min_days,
            "total_count": len(filtered),
            "total_gb": total_gb,
            "flash": flash,
            "error": None,
        },
    )


@app.delete("/torrents/{hash}")
async def delete_torrent(hash: str):
    try:
        with _get_client() as client:
            client.login()
            client.delete([hash], delete_files=True)
        return Response(status_code=200, content="")
    except Exception as e:
        return Response(
            status_code=200,
            media_type="text/html",
            content=f'<tr id="row-{hash}"><td colspan="7" style="color:red;padding:6px 12px">Delete failed: {e}</td></tr>',
        )


@app.post("/torrents/delete")
async def bulk_delete(hashes: list[str] = Form(...)):
    try:
        with _get_client() as client:
            client.login()
            client.delete(hashes, delete_files=True)
        return RedirectResponse(url="/", status_code=302)
    except Exception:
        return RedirectResponse(url="/?flash=Delete+failed", status_code=302)


@app.get("/api/widget")
async def widget():
    try:
        with _get_client() as client:
            client.login()
            torrents = client.get_torrents(_get_tag())
        wasted_gb = round(sum(t["size"] for t in torrents) / 1e9, 2)
        return JSONResponse({"cold_torrents": len(torrents), "wasted_gb": wasted_gb})
    except Exception:
        return JSONResponse({"cold_torrents": 0, "wasted_gb": 0.0})


def _safe(fn):
    """Call fn(), returning None (instead of raising) on any failure — the
    fail-closed contract: a None result means the caller must treat every
    file that would need this data as 'keep, uncertain'."""
    try:
        return fn()
    except Exception:
        return None


def _fetch_qbit_paths() -> set[str]:
    with _get_client() as client:
        client.login()
        return client.get_all_content_paths()


def _fetch_sonarr_paths() -> tuple[set[str], set[str]]:
    """Episode paths (for media-orphan classification) and queue output
    paths (for download-orphan classification), from one Sonarr session —
    a queue-fetch failure should mark Sonarr as a whole unreachable rather
    than silently disabling only the queue signal."""
    with SonarrClient(os.environ["SONARR_URL"], os.environ["SONARR_API_KEY"]) as client:
        return client.get_all_episode_paths(), client.get_all_queue_paths()


def _fetch_radarr_paths() -> tuple[set[str], set[str]]:
    with RadarrClient(os.environ["RADARR_URL"], os.environ["RADARR_API_KEY"]) as client:
        return client.get_all_movie_paths(), client.get_all_queue_paths()


def _fetch_plex_movie_paths() -> set[str]:
    with PlexClient(os.environ["PLEX_URL"], os.environ["PLEX_TOKEN"]) as client:
        return client.get_all_movie_paths()


def _fetch_plex_episode_paths() -> set[str]:
    with PlexClient(os.environ["PLEX_URL"], os.environ["PLEX_TOKEN"]) as client:
        return client.get_all_episode_paths()


def _flatten(paths_by_inode: dict[int, list[str]]) -> list[str]:
    return [p for paths in paths_by_inode.values() for p in paths]


def _boundary_for(relative_path: str) -> str:
    """Which configured scan subdir a path lives under — the `boundary`
    delete_orphan() needs so pruning stops at the right root (media scan
    roots sit two levels below data_root, download roots sit one)."""
    for sub in MEDIA_SUBDIRS + DOWNLOAD_SUBDIRS:
        if relative_path == sub or relative_path.startswith(sub + "/"):
            return sub
    raise ValueError(f"{relative_path!r} is not under any configured scan subdir")


def _service_status(raw_paths: set[str] | None, scanned_paths: list[str]) -> str:
    """'unreachable' if the fetch itself failed. 'unusable' if it returned
    data sharing zero overlap with what the scan actually found on disk —
    the fingerprint of a wrong *_PATH_PREFIX, which normalizes every path
    to something the scan never saw. A service reporting a legitimately
    empty set isn't unusable — zero movies in Radarr is a real state, not
    a misconfiguration — so the check only fires when raw_paths is
    non-empty AND the scan found files to compare it against."""
    if raw_paths is None:
        return "unreachable"
    if raw_paths and scanned_paths and not any(
        path_tracked(p, raw_paths) for p in scanned_paths
    ):
        return "unusable"
    return "ok"


def run_scan() -> tuple[list[OrphanCandidate], dict[str, str]]:
    """Scan the filesystem and classify orphans against every external API.

    Returns (candidates, service_statuses) — statuses let the caller show
    per-service health (ok/unreachable/unusable) without a second scan.
    """
    data_root = os.environ.get("DATA_ROOT", DATA_ROOT)
    result = scan(data_root, MEDIA_SUBDIRS, DOWNLOAD_SUBDIRS)

    download_scanned = _flatten(result.download_only)
    torrents_scanned = [
        p for p in download_scanned
        if any(p == sub or p.startswith(sub + "/") for sub in QBIT_SUBDIRS)
    ]
    media_scanned = _flatten(result.media_only)
    tv_scanned = [p for p in media_scanned if is_tv_path(p, TV_SUBDIRS)]
    movie_scanned = [p for p in media_scanned if not is_tv_path(p, TV_SUBDIRS)]

    qbit_prefix = os.environ.get("QBIT_PATH_PREFIX", "")
    raw_qbit = _safe(_fetch_qbit_paths)
    qbit_paths = {to_relative(p, qbit_prefix) for p in raw_qbit} if raw_qbit is not None else None
    # Scoped to torrents-only: download_scanned also includes usenet-side
    # orphans, which qBittorrent never reports and can't be blamed for —
    # comparing against the full mix would false-flag a correctly
    # configured qBit as "unusable" whenever a usenet orphan exists.
    qbit_status = _service_status(qbit_paths, torrents_scanned)

    sonarr_prefix = os.environ.get("SONARR_PATH_PREFIX", "")
    raw_sonarr = _safe(_fetch_sonarr_paths)
    if raw_sonarr is None:
        sonarr_paths = None
        sonarr_queue_paths = None
    else:
        raw_sonarr_episodes, raw_sonarr_queue = raw_sonarr
        sonarr_paths = {to_relative(p, sonarr_prefix) for p in raw_sonarr_episodes}
        sonarr_queue_paths = {to_relative(p, sonarr_prefix) for p in raw_sonarr_queue}
    sonarr_status = _service_status(sonarr_paths, tv_scanned)

    radarr_prefix = os.environ.get("RADARR_PATH_PREFIX", "")
    raw_radarr = _safe(_fetch_radarr_paths)
    if raw_radarr is None:
        radarr_paths = None
        radarr_queue_paths = None
    else:
        raw_radarr_movies, raw_radarr_queue = raw_radarr
        radarr_paths = {to_relative(p, radarr_prefix) for p in raw_radarr_movies}
        radarr_queue_paths = {to_relative(p, radarr_prefix) for p in raw_radarr_queue}
    radarr_status = _service_status(radarr_paths, movie_scanned)

    plex_prefix = os.environ.get("PLEX_PATH_PREFIX", "")
    raw_plex_movies = _safe(_fetch_plex_movie_paths)
    plex_movie_paths = (
        {to_relative(p, plex_prefix) for p in raw_plex_movies} if raw_plex_movies is not None else None
    )
    plex_movie_status = _service_status(plex_movie_paths, movie_scanned)
    raw_plex_episodes = _safe(_fetch_plex_episode_paths)
    plex_episode_paths = (
        {to_relative(p, plex_prefix) for p in raw_plex_episodes} if raw_plex_episodes is not None else None
    )
    plex_episode_status = _service_status(plex_episode_paths, tv_scanned)
    plex_sub_statuses = (plex_movie_status, plex_episode_status)
    plex_status = (
        "unreachable" if "unreachable" in plex_sub_statuses
        else "unusable" if "unusable" in plex_sub_statuses
        else "ok"
    )

    # Fail closed: an "unusable" service's paths are untrustworthy — drop
    # them to None so classification treats that side as unknown, same as
    # an unreachable service, instead of confidently flagging real files.
    if qbit_status == "unusable":
        qbit_paths = None
    if sonarr_status == "unusable":
        sonarr_paths = None
        sonarr_queue_paths = None
    if radarr_status == "unusable":
        radarr_paths = None
        radarr_queue_paths = None
    if plex_movie_status == "unusable":
        plex_movie_paths = None
    if plex_episode_status == "unusable":
        plex_episode_paths = None

    arr_queue_paths = (
        None if sonarr_queue_paths is None or radarr_queue_paths is None
        else sonarr_queue_paths | radarr_queue_paths
    )

    candidates = classify_download_orphans(result, data_root, qbit_paths, arr_queue_paths)
    candidates += classify_media_orphans(
        result, data_root, TV_SUBDIRS, sonarr_paths, radarr_paths, plex_episode_paths, plex_movie_paths
    )
    mark_superseded(candidates, radarr_paths, TV_SUBDIRS)

    _scan_cache.clear()
    for c in candidates:
        _scan_cache[c.inode] = c

    # Ground truth for grouping is every file found under the download
    # roots, orphaned or not: download_only covers both orphans and files
    # qBit/*arr still track, and linked files that happen to live under a
    # download root are real contents of those directories too.
    download_files = _flatten(result.download_only) + [
        p for p in result.linked
        if any(p == sub or p.startswith(sub + "/") for sub in DOWNLOAD_SUBDIRS)
    ]
    groups, _ = group_download_orphans(
        [c for c in candidates if c.category == "unlinked download"],
        download_files,
        set(DOWNLOAD_SUBDIRS),
    )
    _group_cache.clear()
    for g in groups:
        _group_cache[g.root] = g

    statuses = {
        "qBittorrent": qbit_status,
        "Sonarr": sonarr_status,
        "Radarr": radarr_status,
        "Plex": plex_status,
    }
    return candidates, statuses


_PREFIX_ENV_VAR = {
    "qBittorrent": "QBIT_PATH_PREFIX",
    "Sonarr": "SONARR_PATH_PREFIX",
    "Radarr": "RADARR_PATH_PREFIX",
    "Plex": "PLEX_PATH_PREFIX",
}


def _status_lines(statuses: dict[str, str]) -> list[str]:
    lines = []
    for name, status in statuses.items():
        if status == "unusable":
            lines.append(f"{name}: unusable — check {_PREFIX_ENV_VAR[name]}")
        else:
            lines.append(f"{name}: {status}")
    return lines


def _enrich_candidate(c: OrphanCandidate) -> dict:
    return {
        "kind": "file",
        "inode": c.inode,
        "display_path": c.paths[0],
        "extra_paths": len(c.paths) - 1,
        "category": c.category,
        "size_gb": _format_gb(c.size_bytes),
        "size_bytes": c.size_bytes,
        "superseded_by": c.superseded_by,
        "tracks_sample": c.tracks_sample,
    }


def _group_dom_id(root: str) -> str:
    """Stable, attribute-safe element id for a group - root paths contain
    spaces, brackets and dots that can't go in an id selector as-is."""
    return "orphan-group-" + hashlib.sha1(root.encode()).hexdigest()[:12]


def _enrich_group(g: OrphanGroup) -> dict:
    return {
        "kind": "group",
        "root": g.root,
        "dom_id": _group_dom_id(g.root),
        "display_path": g.root + "/",
        "file_count": len(g.members),
        "size_bytes": g.size_bytes,
        "size_gb": _format_gb(g.size_bytes),
        "children": [
            {
                **_enrich_candidate(m),
                "display_path": os.path.relpath(m.paths[0], g.root),
                "is_child": True,
            }
            for m in g.members
        ],
    }


def _is_mac_junk(paths: list[str]) -> bool:
    """True when every hardlink path is Finder metadata noise (.DS_Store or an AppleDouble ._* sidecar) - harmless to delete, and Finder just recreates it."""
    return all(
        os.path.basename(p) == ".DS_Store" or os.path.basename(p).startswith("._")
        for p in paths
    )


def _download_units(download_candidates: list[dict]) -> list[dict]:
    """Unlinked Downloads table rows: one unit per cached group, plus
    every candidate that isn't a member of any group. Standalone macOS
    Finder junk is dropped here only - it still counts as an orphan for
    group rollup and a group delete still removes it, so a folder left
    holding just a .DS_Store doesn't survive as a shell."""
    grouped = {m.inode for g in _group_cache.values() for m in g.members}
    units = [_enrich_group(g) for g in _group_cache.values()]
    for c in download_candidates:
        if c["inode"] in grouped:
            continue
        cached = _scan_cache.get(c["inode"])
        if cached is not None and _is_mac_junk(cached.paths):
            continue
        units.append(c)
    return units


_EMPTY_ORPHANS_CONTEXT = {"download_units": [], "review_candidates": [], "status_lines": [], "scanned": False}


def _split_by_category(candidates: list[dict]) -> tuple[list[dict], list[dict]]:
    """Partition enriched candidates into (unlinked downloads, needs review).

    Kept as two separate lists all the way to the template so the page can
    render them as two independent tables — separate select-all checkboxes,
    separate delete forms — making it structurally impossible to bulk-select
    across both at once. "unlinked download" is mostly safe to bulk-delete;
    "orphaned media" genuinely isn't (could be a safe duplicate, or content
    that just hasn't been imported into Sonarr/Radarr yet), so the two
    categories don't share a selection surface at all.
    """
    download = [c for c in candidates if c["category"] == "unlinked download"]
    review = [c for c in candidates if c["category"] == "orphaned media"]
    return download, review


@app.get("/orphans", response_class=HTMLResponse)
async def orphans_page(request: Request, flash: Optional[str] = None, done: Optional[str] = None):
    try:
        return templates.TemplateResponse(
            request, "orphans.html",
            {**_EMPTY_ORPHANS_CONTEXT, "error": None, "flash": flash, "done": done,
             "deleted_paths": list(_last_bulk_deleted) if done else []}
        )
    except Exception:
        return templates.TemplateResponse(
            request,
            "orphans.html",
            {**_EMPTY_ORPHANS_CONTEXT, "error": "Failed to load orphans page", "flash": None},
        )


@app.post("/orphans/scan", response_class=HTMLResponse)
async def orphans_scan(request: Request):
    try:
        # A real scan walks the whole data tree and calls 4 external APIs
        # synchronously — on real data (tens of thousands of files) that's
        # ~15s, long enough to freeze the single-threaded event loop for
        # every other request (including the unrelated /torrents page) if
        # run inline. Offloading to a thread keeps the server responsive.
        raw_candidates, statuses = await asyncio.to_thread(run_scan)
        candidates = [_enrich_candidate(c) for c in raw_candidates]
        download_candidates, review_candidates = _split_by_category(candidates)
        return templates.TemplateResponse(
            request,
            "orphans.html",
            {
                "download_units": _download_units(download_candidates),
                "review_candidates": review_candidates,
                "error": None,
                "status_lines": _status_lines(statuses),
                "scanned": True,
            },
        )
    except Exception:
        return templates.TemplateResponse(
            request,
            "orphans.html",
            {**_EMPTY_ORPHANS_CONTEXT, "error": "Scan failed — check service connectivity"},
        )


async def _reverify(inode: int) -> OrphanCandidate | None:
    """Re-run the scan and return the fresh candidate for inode, or None
    if it's no longer flagged as an orphan.

    This closes the race between a page scan and a delete click: Sonarr
    could grab a replacement file, or a torrent could resume, in between.
    """
    fresh, _ = await asyncio.to_thread(run_scan)
    for c in fresh:
        if c.inode == inode:
            return c
    return None


def _delete_candidate(data_root: str, candidate: OrphanCandidate) -> None:
    """Unlink every hardlink path for this candidate's inode.

    All of candidate.paths point at the same inode — removing only the
    first name leaves the others still referencing it, so the file's
    data is never actually freed even though the UI reports its full
    size as reclaimed.
    """
    for path in candidate.paths:
        delete_orphan(data_root, path, _boundary_for(path))
        _audit(path, candidate.size_bytes)


def _audit(path: str, size_bytes: int) -> None:
    """Record every file this app deletes. Container logs vanish when the
    container is recreated (every rebuild), so if AUDIT_LOG is set the same
    line is also appended to that file, which should live on a mounted
    volume to survive."""
    line = f"DELETED {path} ({size_bytes} bytes)"
    logger.info(line)
    audit_path = os.environ.get("AUDIT_LOG")
    if not audit_path:
        return
    try:
        with open(audit_path, "a") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} {line}\n")
    except OSError as e:
        logger.warning("could not write audit log %s: %s", audit_path, e)


@app.delete("/orphans/{inode}")
async def delete_single_orphan(inode: int):
    if inode not in _scan_cache:
        return Response(status_code=200, content="")

    try:
        fresh = await _reverify(inode)
    except Exception as e:
        return Response(
            status_code=200,
            media_type="text/html",
            content=f'<tr id="orphan-row-{inode}"><td colspan="4" style="color:red">Re-verify failed: {e}</td></tr>',
        )

    if fresh is None:
        return Response(
            status_code=200,
            media_type="text/html",
            content=f'<tr id="orphan-row-{inode}"><td colspan="4">No longer an orphan — skipped</td></tr>',
        )

    try:
        _delete_candidate(_current_data_root(), fresh)
        # A brief confirmation row instead of an empty swap, so the delete
        # visibly lands; the page fades it out after a few seconds.
        return Response(
            status_code=200,
            media_type="text/html",
            content=f'<tr id="orphan-row-{inode}" class="deleted-row"><td colspan="4">'
                    f'Deleted {escape(fresh.paths[0])} ({_format_gb(fresh.size_bytes)} GB freed)</td></tr>',
        )
    except (OSError, ValueError) as e:
        return Response(
            status_code=200,
            media_type="text/html",
            content=f'<tr id="orphan-row-{inode}"><td colspan="4" style="color:red">Delete failed: {e}</td></tr>',
        )


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root + "/")


def _delete_group(
    data_root: str, group: OrphanGroup, fresh: list[OrphanCandidate]
) -> tuple[int, int, int]:
    """Best-effort delete of a group's members, re-verified against a
    fresh scan. Returns (deleted, failed, skipped).

    Only inodes that were members at scan time are touched - a file that
    newly appeared in the folder since then was never shown to the user
    as part of this group. A member missing from the fresh scan (tracked
    again) or that grew a hardlink outside the group root is skipped
    rather than deleted, and any skip also cancels empty-tree pruning.
    """
    fresh_by_inode = {c.inode: c for c in fresh if c.category == "unlinked download"}
    deleted = failed = skipped = 0
    for member in group.members:
        candidate = fresh_by_inode.get(member.inode)
        if candidate is None or not all(_under(p, group.root) for p in candidate.paths):
            skipped += 1
            continue
        try:
            _delete_candidate(data_root, candidate)
            deleted += 1
        except (OSError, ValueError) as e:
            failed += 1
            logger.warning("failed to delete orphan group member %s: %s", candidate.paths, e)
    # A skipped member means the folder is live again (torrent re-added)
    # - don't touch even its empty subdirectories.
    if not skipped:
        try:
            prune_empty_tree(data_root, group.root, _boundary_for(group.root))
        except (OSError, ValueError) as e:
            logger.warning("failed to prune empty tree at %s: %s", group.root, e)
    return deleted, failed, skipped


def _group_message(dom_id: str, message: str, error: bool = False, done: bool = False) -> Response:
    style = ' style="color:red"' if error else ""
    # "deleted-row" tells the page to fade the confirmation out after a moment.
    cls = ' class="deleted-row"' if done else ""
    return Response(
        status_code=200,
        media_type="text/html",
        content=f'<tbody id="{dom_id}"{cls}><tr><td colspan="4"{style}>{escape(message)}</td></tr></tbody>',
    )


@app.post("/orphans/groups/delete")
async def delete_orphan_group(root: str = Form(...)):
    # The posted root is only a cache key - never a filesystem path. An
    # unknown root (stale page, or anything hand-crafted) deletes nothing -
    # but it also must not look like a successful delete: an empty 200
    # would have HTMX swap the row out as if it were gone, when nothing
    # was actually touched. Every single delete elsewhere rebuilds
    # _group_cache via run_scan, so this is reachable just by deleting one
    # member of a 2-file group and then clicking the group's own button.
    dom_id = _group_dom_id(root)
    group = _group_cache.get(root)
    if group is None:
        return _group_message(
            dom_id, "Group changed since this scan — rescan and try again", error=True
        )

    try:
        fresh, _ = await asyncio.to_thread(run_scan)
    except Exception as e:
        return _group_message(dom_id, f"Re-verify failed: {e}", error=True)

    deleted, failed, skipped = _delete_group(_current_data_root(), group, fresh)
    total = len(group.members)
    if failed:
        return _group_message(dom_id, f"{failed} of {total} deletes failed — check logs", error=True)
    if skipped:
        return _group_message(dom_id, f"Deleted {deleted}; {skipped} no longer orphans — skipped")
    return _group_message(
        dom_id, f"Deleted {group.root}/ ({deleted} files, {_format_gb(group.size_bytes)} GB freed)", done=True
    )


@app.post("/orphans/delete")
async def bulk_delete_orphans(
    inodes: list[int] = Form(default=[]),
    group_roots: list[str] = Form(default=[]),
):
    # Resolve groups BEFORE the re-verify scan - run_scan rebuilds
    # _group_cache, and membership has to be what the user was shown.
    # dict.fromkeys dedupes a root posted twice (header + a double-submit,
    # or the same checkbox posted more than once) so it can't run
    # _delete_group on the same group twice and flash a spurious failure
    # from re-deleting files the first pass already removed.
    unique_roots = list(dict.fromkeys(group_roots))
    groups = [_group_cache[r] for r in unique_roots if r in _group_cache]
    stale_roots = [r for r in unique_roots if r not in _group_cache]
    try:
        fresh_candidates, _ = await asyncio.to_thread(run_scan)
        fresh_by_inode = {c.inode: c for c in fresh_candidates}
    except Exception:
        return RedirectResponse(
            url=f"/orphans?flash={quote('Re-verify scan failed — no files deleted')}",
            status_code=302,
        )

    data_root = _current_data_root()
    _last_bulk_deleted.clear()
    failed = 0
    attempted = 0
    deleted = 0
    skipped = 0
    freed_bytes = 0
    handled: set[int] = set()
    for group in groups:
        group_deleted, group_failed, group_skipped = _delete_group(data_root, group, fresh_candidates)
        failed += group_failed
        deleted += group_deleted
        skipped += group_skipped
        attempted += len(group.members)
        if not group_failed and not group_skipped:
            freed_bytes += group.size_bytes
        if group_deleted:
            _last_bulk_deleted.append(f"{group.root}/ ({group_deleted} files)")
        handled.update(m.inode for m in group.members)

    for inode in dict.fromkeys(inodes):
        if inode in handled:
            continue
        attempted += 1
        candidate = fresh_by_inode.get(inode)
        if candidate is None:
            skipped += 1
            continue
        try:
            _delete_candidate(data_root, candidate)
            deleted += 1
            freed_bytes += candidate.size_bytes
            _last_bulk_deleted.extend(candidate.paths)
        except (OSError, ValueError) as e:
            failed += 1
            logger.warning("failed to delete orphan inode %s: %s", inode, e)

    messages = []
    if failed:
        messages.append(f"{failed} of {attempted} deletes failed — check logs")
    if stale_roots:
        noun = "group" if len(stale_roots) == 1 else "groups"
        messages.append(
            f"{len(stale_roots)} selected {noun} changed since this scan — rescan and try again"
        )
    if messages:
        return RedirectResponse(
            url=f"/orphans?flash={quote('; '.join(messages))}", status_code=302
        )

    # Success still needs saying: the redirect lands on an unscanned page,
    # which otherwise looks the same whether anything was deleted or not.
    done = f"Deleted {deleted} {'file' if deleted == 1 else 'files'} ({_format_gb(freed_bytes)} GB freed)."
    if skipped:
        done += f" {skipped} skipped: no longer orphans."
    done += " Scan again to see what's left."
    return RedirectResponse(url=f"/orphans?done={quote(done)}", status_code=302)
