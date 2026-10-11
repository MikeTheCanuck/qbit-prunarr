# qbit-prunarr

A small web app for reclaiming disk space on a homelab media server. It does two jobs the \*arr stack doesn't:

1. **Cold torrents.** Lists qBittorrent torrents with a given tag (`only-for-ratio` by default) that haven't seen activity in N days, bucketed by age, and deletes them with their files.
2. **Orphan trawler.** Finds files that nothing references anymore: downloads no torrent or \*arr queue claims, and media files that Sonarr/Radarr and Plex don't know about. You review them and delete what's actually dead.

It never deletes anything on its own. Every delete is something you ticked, confirmed, and that passed a fresh re-check first.

Built for a Synology NAS running qBittorrent, Sonarr, Radarr and Plex in Docker. FastAPI, Jinja2 and HTMX. No JS framework, no build step.

## Why this exists

qBittorrent's WebUI has no "last activity" column and no bulk prune, so ratio-only torrents pile up quietly. Separately, years of manual imports, re-grabs and half-finished downloads leave stuff behind: a 29 GB 4K download Radarr gave up on in March, a 2018 WEBRip sitting next to the BluRay that replaced it, a 40 GB disc rip nothing points to. None of the apps involved will tell you about it, because each one only knows about what it's tracking.

## The orphan trawler

### How it decides what's an orphan

Sonarr and Radarr hardlink downloads into the media library, and the two copies have different names (release name vs. library name). Matching by filename doesn't work, so the scan groups files by **inode**:

- A file under `torrents/` or `usenet/` that shares an inode with something under `media/` is linked, which means it's fine.
- **Unlinked Downloads**: download-side files with no media link, that no qBittorrent torrent and no Sonarr/Radarr queue item claims. These are usually safe to reclaim.
- **Needs Review**: media-side files that aren't confirmed by *both* the relevant \*arr (Sonarr for TV, Radarr for movies) *and* Plex. These are genuinely ambiguous: a safe leftover duplicate, or real content that never got imported. Look before deleting.

Synology housekeeping folders (`@eaDir`, `#recycle`) are skipped. Subtitles, `.nfo` files and artwork are kept out of Needs Review, since no \*arr ever tracks them.

### Fail closed

If a service is unreachable, or its paths don't overlap with anything on disk (the fingerprint of a wrong `*_PATH_PREFIX`), nothing that depends on it gets flagged. Each scan shows a per-service status (`ok` / `unreachable` / `unusable`) under "Service status", so you can tell a clean result from a blind one.

### Working through Needs Review

- Grouped by movie or show folder, collapsible, biggest first. There's also a flat list.
- A **Superseded** badge when Radarr tracks a different file in the same movie folder. Radarr never removes files it didn't import itself, so old copies outlive their replacements forever.
- A warning badge when Radarr's tracked file for the movie is a *sample clip*. In that case the untracked file is probably the real movie. Fix it in Radarr; don't delete it.
- Deleting a video also deletes its sidecars in the same folder: `Film.srt`, `Film.en.srt`, `Film.nfo`, `Film-thumb.jpg`. If another video shares the name, nothing is claimed.

### Deleting

Single rows, whole groups (a fully orphaned folder), or a bulk selection on either tab. Before anything is removed, the app re-runs the scan and skips anything that's no longer an orphan. Empty parent folders are pruned up to, never past, the library root. A scan takes around 15 seconds on a large library, so deletes take about that long too. The button goes orange while that runs.

### The delete log

Every file removed is logged as `DELETED <path> (<bytes>)` in the container log and, if `AUDIT_LOG` is set, appended to that file. Container logs are thrown away on every rebuild, so put the audit file on a mounted volume (see below) if you want to be able to answer "what did that delete actually remove?" next week. The banner after a bulk delete also lists exactly what went.

## Setup

### Configuration

Copy `.env.example` to `.env` and fill it in:

| Variable | What it's for |
|---|---|
| `QBIT_URL`, `QBIT_USERNAME`, `QBIT_PASSWORD` | qBittorrent WebUI |
| `QBIT_TAG` | Tag the cold-torrent page looks at. Default `only-for-ratio` |
| `SONARR_URL`, `SONARR_API_KEY` | Sonarr |
| `RADARR_URL`, `RADARR_API_KEY` | Radarr |
| `PLEX_URL`, `PLEX_TOKEN` | Plex, for the "is it in the library" half of Needs Review |
| `DATA_ROOT` | Where the shared data folder is mounted inside this container. Default `/data` |
| `QBIT_PATH_PREFIX`, `SONARR_PATH_PREFIX`, `RADARR_PATH_PREFIX`, `PLEX_PATH_PREFIX` | Each app's own path to that same shared folder (e.g. `/data`), stripped so all four can be compared |
| `AUDIT_LOG` | Optional. File to append every delete to, e.g. `/logs/deletes.log` |

The path prefixes are the part people get wrong. Every container sees the same files under its own mount point, so qBittorrent might report `/downloads/completed/x.mkv` while this app sees `/data/torrents/completed/x.mkv`. If the scan says a service is `unusable`, its prefix is the first thing to check.

The scan expects this layout under `DATA_ROOT` (the [TRaSH Guides](https://trash-guides.info/File-and-Folder-Structure/) shape):

```
torrents/   usenet/
media/movies   media/movies-no-backup   media/tv   media/tv-no-backup
```

Those folder names live in `app/main.py` (`MEDIA_SUBDIRS`, `DOWNLOAD_SUBDIRS`) if yours differ.

### Running it

On a Synology NAS (or anything with Docker), using the repo's `compose.yaml` as a starting point:

```yaml
services:
  qbit-prunarr:
    build:
      context: /volume1/docker/qbit-prunarr/app
    container_name: qbit-prunarr
    ports:
      - 8585:8585
    env_file:
      - /volume1/docker/qbit-prunarr/.env
    volumes:
      - /volume1/data:/data                       # the shared torrents + media tree
      - /volume1/docker/qbit-prunarr/logs:/logs   # for AUDIT_LOG
    restart: unless-stopped
```

The orphan trawler needs the data mount; the cold-torrent page works without it.

After changing the code, rebuild the image rather than just restarting. On Synology, Container Manager's "Clean" recreates the container from the *old* image, which looks like a deploy and isn't:

```
sudo docker compose build --no-cache && sudo docker compose up -d --force-recreate
```

Then open `http://<nas>:8585/` for cold torrents and `http://<nas>:8585/orphans` for the trawler.

### Homepage widget

`GET /api/widget` returns `{"cold_torrents": N, "wasted_gb": X}` for every torrent with the configured tag, for a [Homepage](https://gethomepage.dev) `customapi` widget:

```yaml
widget:
  type: customapi
  url: http://<nas>:8585/api/widget
  mappings:
    - field: cold_torrents
      label: Cold Torrents
    - field: wasted_gb
      label: GB Wasted
      format: float
```

## Development

```
cd app
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q
```

The tests mock qBittorrent, Sonarr, Radarr and Plex and build real files and hardlinks in a temp directory, so the scan and delete paths run against an actual filesystem. They don't run the page's JavaScript; selection, grouping and the sticky delete bar get checked by hand in a browser.

Design notes and implementation plans live in `docs/`.

## Limitations

- Only one qBittorrent tag on the cold-torrent page.
- Scans are on demand. Nothing runs on a schedule, and results live in memory until the next scan or restart.
- TV extras and specials that Sonarr hasn't matched still land in Needs Review. Teaching it Plex's extras conventions and Sonarr's Season 00 is the next piece of work.
- Built for one person's NAS. It'll work on yours if your layout is close to the one above, but it hasn't been tested anywhere else.
