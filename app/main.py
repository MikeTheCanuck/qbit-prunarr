"""qBit Pruner — FastAPI app."""
import os
import time
from typing import Optional

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from qbit import QBitClient

app = FastAPI()
templates = Jinja2Templates(directory="templates")

BUCKETS = [
    ("180d+", 180, None),
    ("90–180d", 90, 180),
    ("30–90d", 30, 90),
    ("0–30d", 0, 30),
]


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
