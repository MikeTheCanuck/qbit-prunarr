"""Demo mode: run the real app against a made-up library and fake services.

    python demo.py            # then open http://localhost:8585/orphans

Builds a throwaway library under a temp folder (sparse files, so a "29 GB"
movie takes no disk space) and starts small stand-ins for qBittorrent,
Sonarr, Radarr and Plex that answer the same API calls the real clients
make. The app itself is unchanged: it scans the sandbox and talks to the
stand-ins over HTTP exactly as it would on a NAS. Deletes are real, but
only inside the sandbox, which is rebuilt every time this starts.

The films are public-domain titles and the TV shows are invented, so the
screenshots in the README show nothing anyone could object to.
"""
import os
import shutil
import tempfile
import threading
import time

import uvicorn
from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse, PlainTextResponse

GB = 1_000_000_000
MB = 1_000_000
DAY = 86400
PREFIX = "/data"  # what every fake service calls the shared folder
FAKE_PORT = int(os.environ.get("DEMO_SERVICES_PORT", "8586"))
APP_PORT = int(os.environ.get("PORT", "8585"))


# --- The library ------------------------------------------------------------
# Each entry: relative path, size, and who knows about it. "link" names a
# second path that is a hardlink to the same file (a download the *arr
# imported). Sidecars are tiny files named after their video.

LIBRARY = [
    # Fine: linked, tracked by Radarr and Plex. Not shown anywhere.
    dict(path="media/movies/Night of the Living Dead (1968)/Night of the Living Dead (1968) Bluray-1080p.mkv",
         size=9.8 * GB, radarr=True, plex=True,
         link="torrents/movies/Night.of.the.Living.Dead.1968.1080p.BluRay.x264/Night.of.the.Living.Dead.1968.1080p.BluRay.x264.mkv"),
    # Probably junk: an old copy Radarr replaced.
    dict(path="media/movies/Night of the Living Dead (1968)/Night of the Living Dead (1968) WEBRip-720p.mkv",
         size=2.1 * GB, sidecars=[".en.srt", ".nfo"]),
    dict(path="media/movies/Nosferatu (1922)/Nosferatu (1922) Bluray-1080p.mkv",
         size=7.4 * GB, radarr=True, plex=True,
         link="torrents/movies/Nosferatu.1922.RESTORED.1080p.BluRay/Nosferatu.1922.RESTORED.1080p.BluRay.mkv"),
    # Probably junk: a sample clip.
    dict(path="media/movies/Nosferatu (1922)/Nosferatu (1922)-sample.mkv", size=48 * MB),
    # Extras tab: Plex has this attached as an extra.
    dict(path="media/movies/Nosferatu (1922)/Featurettes/The Restoration of Nosferatu.mkv",
         size=1.3 * GB, plex_extra=True),
    # Sonarr/Radarr wants it: Radarr has the movie but no file.
    dict(path="media/movies/His Girl Friday (1940)/His.Girl.Friday.1940.1080p.WEB-DL.mkv", size=6.2 * GB),
    dict(path="media/movies/Charade (1963)/Charade (1963) Bluray-1080p.mkv", size=11.6 * GB,
         radarr=True, plex=True,
         link="torrents/movies/Charade.1963.1080p.BluRay.x264/Charade.1963.1080p.BluRay.x264.mkv"),
    # Plex can't see it: an extras folder nested inside another one.
    dict(path="media/movies/Charade (1963)/Extras/Deleted Scenes/Deleted Scene - Alternate Opening.mkv",
         size=310 * MB),
    # Your call: nothing knows about this folder.
    dict(path="media/movies/Plan 9 from Outer Space (1957)/Plan.9.from.Outer.Space.1957.DVDRip.XviD.avi",
         size=1.4 * GB, sidecars=[".srt"]),
    # A usenet import: moved, not hardlinked, so it only exists library-side.
    dict(path="media/movies/The General (1926)/The General (1926) Bluray-1080p.mkv", size=8.9 * GB,
         radarr=True, plex=True),
    # Your call: loose at the top of the library.
    dict(path="media/movies/charade-1963-trailer.mp4", size=94 * MB),

    # TV. The shows are made up.
    dict(path="media/tv/Starship Tidewater/Season 01/Starship Tidewater - S01E01 - Pilot.mkv", size=2.4 * GB,
         sonarr=True, plex=True,
         link="torrents/tv/Starship.Tidewater.S01.1080p.WEB-DL/Starship.Tidewater.S01E01.1080p.WEB-DL.mkv"),
    dict(path="media/tv/Starship Tidewater/Season 01/Starship Tidewater - S01E02 - Undertow.mkv", size=2.3 * GB,
         sonarr=True, plex=True,
         link="torrents/tv/Starship.Tidewater.S01.1080p.WEB-DL/Starship.Tidewater.S01E02.1080p.WEB-DL.mkv"),
    # Sonarr/Radarr wants it: matches a missing special by title (its own code is wrong).
    dict(path="media/tv/Starship Tidewater/Specials/Starship Tidewater - S00E03 - The Lost Broadcast.mkv",
         size=1.1 * GB, sidecars=[".en.srt"]),
    # Identify it: looks like a special, matches nothing Sonarr is missing.
    dict(path="media/tv/Starship Tidewater/Specials/Starship Tidewater - Holiday Special.mkv", size=900 * MB),
    dict(path="media/tv/The Lighthouse Keepers/Season 01/The Lighthouse Keepers - S01E01 - First Light.mkv",
         size=1.8 * GB, sonarr=True, plex=True),
    # Your call: a second copy of an episode nobody tracks.
    dict(path="media/tv/The Lighthouse Keepers/Season 01/The Lighthouse Keepers - S01E01 - First Light (copy).mkv",
         size=1.8 * GB),
    # Plex can't see it: bonus material in a season folder.
    dict(path="media/tv/The Lighthouse Keepers/Season 01/Bonus/Blooper Reel.mkv", size=420 * MB),
    # Extras tab.
    dict(path="media/tv/The Lighthouse Keepers/Featurettes/Behind the Lamp.mkv", size=650 * MB, plex_extra=True),

    # Seeding, never imported (qBittorrent owns these).
    dict(path="torrents/linux-isos/debian-11.6.0-amd64-DVD-1.iso", size=3.7 * GB),
    dict(path="torrents/linux-isos/ubuntu-22.04.3-desktop-amd64.iso", size=4.9 * GB),
    dict(path="torrents/linux-isos/archlinux-2024.03.01-x86_64.iso", size=1.0 * GB),

    # Unlinked downloads: nothing claims these.
    dict(path="torrents/movies/Metropolis.1927.2160p.UHD.Restored.HDR.mkv", size=29.3 * GB),
    dict(path="torrents/tv/The.Lighthouse.Keepers.S02.720p.HDTV/The.Lighthouse.Keepers.S02E01.720p.HDTV.mkv",
         size=1.2 * GB),
    dict(path="torrents/tv/The.Lighthouse.Keepers.S02.720p.HDTV/The.Lighthouse.Keepers.S02E02.720p.HDTV.mkv",
         size=1.2 * GB),
    dict(path="torrents/tv/The.Lighthouse.Keepers.S02.720p.HDTV/The.Lighthouse.Keepers.S02E03.720p.HDTV.mkv",
         size=1.1 * GB),
    dict(path="usenet/complete/Detour.1945.720p.BluRay/Detour.1945.720p.BluRay.mkv", size=4.4 * GB),
    # Protected: Radarr's queue still wants this one.
    dict(path="torrents/movies/The.Kid.1921.1080p.BluRay/The.Kid.1921.1080p.BluRay.mkv", size=5.0 * GB,
         radarr_queue=True),
]

RADARR_MOVIES = [
    ("Night of the Living Dead (1968)", "Night of the Living Dead", 1968),
    ("Nosferatu (1922)", "Nosferatu", 1922),
    ("His Girl Friday (1940)", "His Girl Friday", 1940),
    ("Charade (1963)", "Charade", 1963),
    ("The General (1926)", "The General", 1926),
]

SONARR_SERIES = [
    (1, "Starship Tidewater", [(1, "Cast Reunion", True), (2, "The Lost Broadcast", True)]),
    (2, "The Lighthouse Keepers", []),
]

# (name, size, days since last activity, category, content path under the data root or None)
TORRENTS = [
    ("debian-11.6.0-amd64-DVD-1.iso", 3.7 * GB, 412, "linux-isos", None),
    ("Night.of.the.Living.Dead.1968.1080p.BluRay.x264", 9.8 * GB, 241, "radarr",
     "torrents/movies/Night.of.the.Living.Dead.1968.1080p.BluRay.x264"),
    ("ubuntu-22.04.3-desktop-amd64.iso", 4.9 * GB, 198, "linux-isos", None),
    ("Nosferatu.1922.RESTORED.1080p.BluRay", 7.4 * GB, 133, "radarr",
     "torrents/movies/Nosferatu.1922.RESTORED.1080p.BluRay"),
    ("archlinux-2024.03.01-x86_64.iso", 1.0 * GB, 97, "linux-isos", None),
    ("Starship.Tidewater.S01.1080p.WEB-DL", 4.7 * GB, 64, "sonarr",
     "torrents/tv/Starship.Tidewater.S01.1080p.WEB-DL"),
    ("Charade.1963.1080p.BluRay.x264", 11.6 * GB, 41, "radarr", "torrents/movies/Charade.1963.1080p.BluRay.x264"),
    ("ubuntu-24.04.1-live-server-amd64.iso", 2.7 * GB, 12, "linux-isos", None),
]
COLD_TAG = "only-for-ratio"


def _touch(full: str, size: float) -> None:
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as f:
        f.truncate(int(size))  # sparse: reports the size, uses no space


def build_library(root: str) -> None:
    for item in LIBRARY:
        full = os.path.join(root, item["path"])
        _touch(full, item["size"])
        if item.get("link"):
            link = os.path.join(root, item["link"])
            os.makedirs(os.path.dirname(link), exist_ok=True)
            os.link(full, link)
        stem = os.path.splitext(full)[0]
        for ext in item.get("sidecars", []):
            _touch(stem + ext, 40_000)
    for sub in ("media/movies-no-backup", "media/tv-no-backup"):
        os.makedirs(os.path.join(root, sub), exist_ok=True)


# --- The fake services ------------------------------------------------------

def make_services(root: str) -> FastAPI:
    svc = FastAPI()
    now = time.time()
    torrents = [
        {
            "hash": f"{i:040x}",
            "name": name,
            "size": int(size),
            "last_activity": int(now - days * DAY),
            "category": cat,
            "tags": COLD_TAG,
            "content_path": f"{PREFIX}/{content}" if content else f"{PREFIX}/torrents/linux-isos/{name}",
            "save_path": f"{PREFIX}/torrents/",
        }
        for i, (name, size, days, cat, content) in enumerate(TORRENTS, start=1)
    ]

    def data(path: str) -> str:
        return f"{PREFIX}/{path}"

    def present(path: str) -> bool:
        return os.path.exists(os.path.join(root, path))

    def tracked(flag: str) -> list[str]:
        return [i["path"] for i in LIBRARY if i.get(flag) and present(i["path"])]

    # qBittorrent
    @svc.post("/qbit/api/v2/auth/login")
    def qbit_login():
        return PlainTextResponse("Ok.")

    @svc.get("/qbit/api/v2/torrents/info")
    def qbit_info(tag: str | None = None):
        return [t for t in torrents if tag is None or tag in t["tags"].split(",")]

    @svc.post("/qbit/api/v2/torrents/delete")
    def qbit_delete(hashes: str = Form(...), deleteFiles: str = Form("false")):
        gone = set(hashes.split("|"))
        for t in [t for t in torrents if t["hash"] in gone]:
            torrents.remove(t)
            if deleteFiles == "true":
                target = os.path.join(root, t["content_path"][len(PREFIX) + 1:])
                if os.path.isdir(target):
                    shutil.rmtree(target)
                elif os.path.exists(target):
                    os.remove(target)
        return PlainTextResponse("")

    # Sonarr
    def series_folder(title: str) -> str:
        return f"media/tv/{title}"

    @svc.get("/sonarr/api/v3/series")
    def sonarr_series():
        return [{"id": sid, "title": t, "path": data(series_folder(t))} for sid, t, _ in SONARR_SERIES]

    @svc.get("/sonarr/api/v3/episodefile")
    def sonarr_files(seriesId: int):
        title = next(t for sid, t, _ in SONARR_SERIES if sid == seriesId)
        return [{"path": data(p)} for p in tracked("sonarr") if p.startswith(series_folder(title) + "/")]

    @svc.get("/sonarr/api/v3/episode")
    def sonarr_episodes(seriesId: int):
        missing = next(m for sid, _, m in SONARR_SERIES if sid == seriesId)
        return [{"seasonNumber": 0, "episodeNumber": n, "title": t, "monitored": mon, "hasFile": False}
                for n, t, mon in missing]

    @svc.get("/sonarr/api/v3/queue")
    def sonarr_queue():
        return {"records": [], "totalRecords": 0}

    # Radarr
    @svc.get("/radarr/api/v3/movie")
    def radarr_movies():
        out = []
        for folder, title, year in RADARR_MOVIES:
            rel = f"media/movies/{folder}"
            file = next((p for p in tracked("radarr") if p.startswith(rel + "/")), None)
            out.append({"title": title, "year": year, "path": data(rel),
                        "movieFile": {"path": data(file)} if file else None})
        return out

    @svc.get("/radarr/api/v3/queue")
    def radarr_queue():
        records = [{"outputPath": data(p)} for p in tracked("radarr_queue")]
        return {"records": records, "totalRecords": len(records)}

    # Plex: one movie section, one TV section. Rating keys are just the
    # index of the title folder.
    folders = sorted({"/".join(i["path"].split("/")[:3]) for i in LIBRARY if i["path"].startswith("media/")
                      and i["path"].count("/") > 2})

    def key_for(path: str) -> str:
        return str(folders.index("/".join(path.split("/")[:3])) + 1)

    @svc.get("/plex/library/sections")
    def plex_sections():
        return {"MediaContainer": {"Directory": [{"key": "1", "type": "movie"}, {"key": "2", "type": "show"}]}}

    @svc.get("/plex/library/sections/{key}/all")
    def plex_all(key: str, type: int):
        base = "media/movies/" if key == "1" else "media/tv/"
        items = []
        for p in tracked("plex"):
            if p.startswith(base):
                k = key_for(p)
                items.append({"ratingKey": k, "grandparentRatingKey": k if key == "2" else None,
                              "Media": [{"Part": [{"file": data(p)}]}]})
        return {"MediaContainer": {"Metadata": items}}

    @svc.get("/plex/library/metadata/{key}/extras")
    def plex_extras(key: str):
        items = [{"Media": [{"Part": [{"file": data(p)}]}]} for p in tracked("plex_extra") if key_for(p) == key]
        return {"MediaContainer": {"Metadata": items}}

    @svc.exception_handler(StopIteration)
    def _missing(_: Request, __: StopIteration):
        return JSONResponse([], status_code=404)

    return svc


def configure_env(root: str) -> None:
    base = f"http://127.0.0.1:{FAKE_PORT}"
    os.environ.update({
        "DATA_ROOT": root,
        "QBIT_URL": f"{base}/qbit", "QBIT_USERNAME": "demo", "QBIT_PASSWORD": "demo", "QBIT_TAG": COLD_TAG,
        "SONARR_URL": f"{base}/sonarr", "SONARR_API_KEY": "demo",
        "RADARR_URL": f"{base}/radarr", "RADARR_API_KEY": "demo",
        "PLEX_URL": f"{base}/plex", "PLEX_TOKEN": "demo",
        "QBIT_PATH_PREFIX": PREFIX, "SONARR_PATH_PREFIX": PREFIX,
        "RADARR_PATH_PREFIX": PREFIX, "PLEX_PATH_PREFIX": PREFIX,
    })
    os.environ.pop("AUDIT_LOG", None)


def main() -> None:
    root = os.path.join(tempfile.gettempdir(), "qbit-prunarr-demo")
    shutil.rmtree(root, ignore_errors=True)
    build_library(root)
    configure_env(root)

    services = uvicorn.Server(uvicorn.Config(make_services(root), host="127.0.0.1", port=FAKE_PORT,
                                             log_level="warning", access_log=False))
    threading.Thread(target=services.run, daemon=True).start()
    while not services.started:
        time.sleep(0.05)

    print(f"\nqbit-prunarr demo: open http://localhost:{APP_PORT}/orphans and press Scan.")
    print(f"Sandbox library: {root} (rebuilt on every start; deletes only touch this folder)\n")
    from main import app
    uvicorn.run(app, host=os.environ.get("HOST", "0.0.0.0"), port=APP_PORT)


if __name__ == "__main__":
    main()
