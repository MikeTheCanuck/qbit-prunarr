"""qBit Pruner — FastAPI app."""
import os
import time
from typing import Optional

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from inode_scan import scan
from orphans import OrphanCandidate, classify_download_orphans, classify_media_orphans
from pathmap import to_relative
from plex import PlexClient
from qbit import QBitClient
from radarr import RadarrClient
from sonarr import SonarrClient

app = FastAPI()
templates = Jinja2Templates(directory="templates")

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

_scan_cache: dict[int, OrphanCandidate] = {}


def _get_client() -> QBitClient:
    return QBitClient(
        base_url=os.environ["QBIT_URL"],
        username=os.environ["QBIT_USERNAME"],
        password=os.environ["QBIT_PASSWORD"],
    )


def _enrich(torrent: dict) -> dict:
    t = dict(torrent)
    t["days_inactive"] = int((time.time() - t["last_activity"]) / 86400)
    t["size_gb"] = round(t["size"] / 1e9, 2)
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
            raw_torrents = client.get_torrents("only-for-ratio")
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
            content=f'<tr id="row-{hash}"><td colspan="6" style="color:red;padding:6px 12px">Delete failed: {e}</td></tr>',
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
            torrents = client.get_torrents("only-for-ratio")
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


def _fetch_sonarr_paths() -> set[str]:
    with SonarrClient(os.environ["SONARR_URL"], os.environ["SONARR_API_KEY"]) as client:
        return client.get_all_episode_paths()


def _fetch_radarr_paths() -> set[str]:
    with RadarrClient(os.environ["RADARR_URL"], os.environ["RADARR_API_KEY"]) as client:
        return client.get_all_movie_paths()


def _fetch_plex_movie_paths() -> set[str]:
    with PlexClient(os.environ["PLEX_URL"], os.environ["PLEX_TOKEN"]) as client:
        return client.get_all_movie_paths()


def _fetch_plex_episode_paths() -> set[str]:
    with PlexClient(os.environ["PLEX_URL"], os.environ["PLEX_TOKEN"]) as client:
        return client.get_all_episode_paths()


def run_scan() -> list[OrphanCandidate]:
    """Scan the filesystem and classify orphans against every external API."""
    data_root = os.environ.get("DATA_ROOT", DATA_ROOT)
    result = scan(data_root, MEDIA_SUBDIRS, DOWNLOAD_SUBDIRS)

    qbit_prefix = os.environ.get("QBIT_PATH_PREFIX", "")
    raw_qbit = _safe(_fetch_qbit_paths)
    qbit_paths = {to_relative(p, qbit_prefix) for p in raw_qbit} if raw_qbit is not None else None

    sonarr_prefix = os.environ.get("SONARR_PATH_PREFIX", "")
    raw_sonarr = _safe(_fetch_sonarr_paths)
    sonarr_paths = {to_relative(p, sonarr_prefix) for p in raw_sonarr} if raw_sonarr is not None else None

    radarr_prefix = os.environ.get("RADARR_PATH_PREFIX", "")
    raw_radarr = _safe(_fetch_radarr_paths)
    radarr_paths = {to_relative(p, radarr_prefix) for p in raw_radarr} if raw_radarr is not None else None

    plex_prefix = os.environ.get("PLEX_PATH_PREFIX", "")
    raw_plex_movies = _safe(_fetch_plex_movie_paths)
    plex_movie_paths = (
        {to_relative(p, plex_prefix) for p in raw_plex_movies} if raw_plex_movies is not None else None
    )
    raw_plex_episodes = _safe(_fetch_plex_episode_paths)
    plex_episode_paths = (
        {to_relative(p, plex_prefix) for p in raw_plex_episodes} if raw_plex_episodes is not None else None
    )

    candidates = classify_download_orphans(result, data_root, qbit_paths)
    candidates += classify_media_orphans(
        result, data_root, TV_SUBDIRS, sonarr_paths, radarr_paths, plex_episode_paths, plex_movie_paths
    )

    _scan_cache.clear()
    for c in candidates:
        _scan_cache[c.inode] = c
    return candidates


def _enrich_candidate(c: OrphanCandidate) -> dict:
    return {
        "inode": c.inode,
        "display_path": c.paths[0],
        "extra_paths": len(c.paths) - 1,
        "category": c.category,
        "size_gb": round(c.size_bytes / 1e9, 2),
    }


@app.get("/orphans", response_class=HTMLResponse)
async def orphans_page(request: Request):
    return templates.TemplateResponse(request, "orphans.html", {"candidates": []})


@app.post("/orphans/scan", response_class=HTMLResponse)
async def orphans_scan(request: Request):
    candidates = [_enrich_candidate(c) for c in run_scan()]
    return templates.TemplateResponse(request, "orphans.html", {"candidates": candidates})
