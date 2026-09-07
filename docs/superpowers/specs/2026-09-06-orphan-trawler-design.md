# Orphan Trawler — Design Spec

## Problem

TerraFermi's `/volume1` is at 81% (12T used of 14T, 2.8T free) and Mike can't add
storage. Media gets imported from `torrents/completed/` and `usenet/completed/`
into `media/` via hardlink, so a fully-imported file exists at two paths sharing
one inode. When one side of that pair gets deleted independently (a torrent
removed from qBittorrent without deleting the seed copy's twin, a Sonarr/Radarr
library item removed without cleaning the download, a manually seeded torrent
that was never actually imported), the other side is left behind, consuming
space with nothing pointing at it as "in use." There is currently no tool that
finds these.

Confirmed live during design: `torrents/completed/Abraham's.Boys.2025...REMUX...mkv`
(53.8 GB, link count 1) has no counterpart anywhere under `media/` — a real
orphan sitting on disk right now.

## Scope (v1)

**In scope:** `media/movies`, `media/movies-no-backup`, `media/tv`,
`media/tv-no-backup` on the media side; `torrents/` and `usenet/` (all
subfolders) on the download side. These are the folders Sonarr/Radarr actually
manage, so the "is this still valid" check has a real source of truth to query.

**Out of scope (v1):** `media/audiobooks`, `media/books`, `media/comics`,
`media/music`. No Sonarr/Radarr-equivalent tracks these, so the "orphaned
media" classification (which requires an *arr + Plex check) has no way to
resolve for them. Revisit if/when those libraries get their own manager
(Readarr, Lidarr, etc).

**Out of scope (v1):** scheduled/automatic scanning. This is an on-demand,
investigative tool for the current space crunch, not a continuous monitor like
Cleanuparr. Scheduling can be added later without changing the core
classification logic.

**Out of scope (v1):** scan result persistence across app restarts. A scan is
metadata-only (stat calls, no file reads) and fast enough to just re-run.

## Architecture

New page inside the existing **qbit-prunarr** app (FastAPI + HTMX + Jinja2,
already deployed on TerraFermi at `/volume1/docker/qbit-prunarr`), not a
standalone service. Reuses the app's existing dark Servarr-style skin, HTMX
row/table patterns, and NAS deployment/compose setup.

New route: `/orphans`. New module (mirrors the existing torrent-pruning
module's shape): scan logic, classification logic, API clients for
Sonarr/Radarr/Plex (new) alongside the existing `QBitClient` (reused as-is).
New template `orphans.html` plus an HTMX partial for the approval-queue table,
following the same partial-swap pattern as the main page's torrent table.

### New requirement: filesystem access

qbit-prunarr today is pure-API — the container has no volume mounts into NAS
storage. This feature needs one: `/volume1/data:/data` bind-mounted into the
container, because deleting a true orphan (by definition untracked by any
*arr or qBit) has no API path to delete through — it has to be a direct
filesystem operation. Scope the mount to `/volume1/data` only, not the whole
NAS.

### New credentials (`.env` additions)

`SONARR_URL`, `SONARR_API_KEY`, `RADARR_URL`, `RADARR_API_KEY`, `PLEX_URL`,
`PLEX_TOKEN`. Existing `QBIT_URL`/`QBIT_USERNAME`/`QBIT_PASSWORD` reused
unchanged.

## Scan algorithm

Filenames do **not** match between the two sides — confirmed on real data:
`10 Cloverfield Lane (2016) Bluray-1080p.mp4` in media/ is the same inode as
`10.Cloverfield.Lane.2016.1080p.BluRay.x264-[YTS.AG].mp4` in
`torrents/completed/radarr/`. Any path- or filename-matching approach is
unreliable. Matching must be by **inode**, since both trees live on the same
filesystem (`/volume1`, confirmed via `df`).

1. Walk `media/{movies,movies-no-backup,tv,tv-no-backup}` and
   `torrents/`+`usenet/` (all subfolders). For each file, `stat()` for inode
   number and link count — metadata only, no file reads, so this stays fast
   even across a multi-TB, hundreds-of-thousands-of-files tree.
2. Build an `inode -> [paths]` map across both trees in one pass.
3. Classify each inode:
   - **Linked** (paths exist on both the media side and the torrents/usenet
     side): keep, skip entirely.
   - **Download-side only** (all paths under torrents/usenet, none under
     media/): query qBittorrent (`/api/v2/torrents/files` or equivalent) for
     an active torrent referencing this path. No match → orphan candidate,
     category `unlinked download`.
   - **Media-side only** (all paths under media/, none under torrents/usenet):
     query Sonarr/Radarr for a file record at this path, AND query Plex for
     library presence. Either missing → orphan candidate, category
     `orphaned media`. **Both** must confirm the file is valid for it to be
     kept — this was an explicit choice (over Sonarr/Radarr alone) to also
     catch the rarer case of an *arr/Plex desync.

## Safety rules

- **Fail closed.** If Sonarr, Radarr, Plex, or qBittorrent is unreachable
  during a check, treat the file as "keep, uncertain" — never classify as
  orphan on missing information.
- **Re-verify before delete.** Between scan and the user clicking confirm,
  state can change (Sonarr could grab a replacement release, a torrent could
  resume). Re-run the classification check for a row immediately before
  deleting it; if it's no longer an orphan, skip it and report why in the UI
  rather than deleting.
- **No bulk auto-delete.** Deletion only happens through the interactive
  approval queue — the user checks specific rows and confirms a batch. No
  scheduled or automatic deletion path exists in this feature.

## Delete flow

1. Scan produces an approval-queue table: path, size, category
   (`unlinked download` / `orphaned media`), and why it was flagged.
2. User checks rows, confirms a batch delete.
3. For each checked row: re-verify orphan status (safety rule above). If
   still orphaned, `os.remove()` the file through the `/data` bind mount, and
   remove now-empty parent directories up to (but not including) the
   scanned root.
4. Row removed from the table via HTMX swap, matching qbit-prunarr's existing
   delete-row UX. A row that failed re-verification or failed to delete stays
   visible with an inline error instead of silently disappearing.

## Testing

Mirror qbit-prunarr's existing test approach: a fixture temp-directory tree
with deliberately-constructed hardlinks (some linked, some media-only-orphan,
some download-only-orphan) plus mocked Sonarr/Radarr/Plex/qBittorrent HTTP
responses. No test hits the real NAS or real APIs. Cover: correct
classification of all three cases, fail-closed behavior when a mocked API
errors or times out, and the re-verify-before-delete race check.
