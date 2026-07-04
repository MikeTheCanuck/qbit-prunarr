# qBit Pruner — Spec

**Date:** 2026-06-28  
**Status:** Design complete, awaiting implementation

---

## Problem

qBittorrent accumulates `only-for-ratio` torrents (freeleech/ratio-boosting downloads) that go cold indefinitely. The qBit WebUI has no "last activity" column, no age-bucketing, and no bulk-prune workflow. Disk space is wasted silently.

---

## Solution

A lightweight web app that queries the qBit API, surfaces cold `only-for-ratio` torrents bucketed by age, and lets the user delete them (individually or in bulk) with one confirmation click.

---

## Scope

- **In:** Torrents tagged `only-for-ratio` only
- **Out:** All other tags and categories; no cross-tag logic in v1
- **Future:** Tag filtering configurable via UI (left as TODO comment in code)

---

## Architecture

Single Docker container. One Python process. Port **8585** on `synobridge` network.

```
qBittorrent API (port 8090, inside gluetun)
        ↕  HTTP (qBit API v2)
  FastAPI app (port 8585, synobridge)
        ↕  HTML fragments / JSON
  Browser (HTMX) + Homepage widget
```

### File layout

```
projects/qbit-pruner-compose/
  compose.yaml
  .env                    # QBIT_URL, QBIT_USERNAME, QBIT_PASSWORD
  app/
    main.py               # FastAPI routes + Jinja2 rendering
    qbit.py               # QBitClient: login(), get_torrents(tag), delete(hashes)
    templates/
      index.html          # full page: grouped table + slider + bulk delete button
      _row.html           # single <tr> fragment for HTMX one-off delete
```

---

## Stack

- **FastAPI** — routes and API endpoint
- **Jinja2** — server-side HTML templates
- **HTMX** — interactivity (slider, single delete, bulk delete)
- No JS framework. No build step.

---

## Routes

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Fetch all `only-for-ratio` torrents, filter by `min_days` (default 30), bucket by age, render `index.html` |
| `DELETE` | `/torrents/{hash}` | Delete single torrent + files; returns empty 200 → HTMX removes `<tr>` |
| `POST` | `/torrents/delete` | Bulk delete (form submit, `hashes[]`); all-or-nothing; redirect `GET /` with flash on error |
| `GET` | `/api/widget` | Returns `{"cold_torrents": N, "wasted_gb": X}` for Homepage custom API widget |

---

## UI

### Main table

- Grouped by age bucket:
  - 180d+
  - 90–180d
  - 30–90d
  - 0–30d
- Columns: name, size (GB), last active (days ago), category, checkbox
- Slider: inactivity threshold (default 30 days); HTMX re-renders table on change (`hx-get="/?min_days=N" hx-trigger="change" hx-target="#torrent-table"`)
- Per-row delete button: HTMX `DELETE /torrents/{hash}`, waits for 200 before removing row (no optimistic UI)

### Bulk delete

- Checkbox on bucket header selects all in that bucket
- Master select-all checkbox selects everything
- "Delete selected (N) — X GB" button
- Confirmation modal before submit

---

## qBit client (`qbit.py`)

Class `QBitClient`:

```python
login()                          # POST /api/v2/auth/login, store session cookie
get_torrents(tag)                # GET /api/v2/torrents/info?tag={tag}
delete(hashes, delete_files=True) # POST /api/v2/torrents/delete
```

API fields used: `last_activity`, `added_on`, `uploaded`, `name`, `hash`, `tags`, `category`, `size`

Deletion: `deleteFiles=true` always (reclaiming disk space is the point).

---

## Credentials

Environment variables via compose `.env` file (same pattern as `vpnproject`):

```
QBIT_URL=http://TerraFermi:8090
QBIT_USERNAME=...
QBIT_PASSWORD=...
```

---

## Error handling

| Scenario | Behavior |
|----------|----------|
| qBit unreachable | Error banner; page still loads |
| Auth failure | Config error page |
| Single delete fails | HTMX swaps error state into row (row stays, red message) |
| Bulk delete fails | All-or-nothing (qBit returns single Ok./Fails); redirect `GET /` with flash banner |

---

## Homepage widget

The `/api/widget` endpoint counts **all** `only-for-ratio` torrents (no threshold filter) — "total junk on disk" for dashboard glance.

```yaml
widget:
  type: customapi
  url: http://192.168.1.30:8585/api/widget
  mappings:
    - field: cold_torrents
      label: Cold Torrents
    - field: wasted_gb
      label: GB Wasted
      format: float
```

---

## Docker / deploy

- Port: **8585** (confirmed clean — no existing ARR/homelab tool uses it)
- Network: `synobridge`
- PUID=1027, PGID=65536 (stack default)
- Project dir: `~/code/Synology/projects/qbit-pruner-compose/`
- Same compose pattern as other projects in this repo

---

## Out of scope (v1)

- Dry-run mode
- Scheduling / auto-prune
- Multiple tag targets (configurable in UI)
- Pause instead of delete
