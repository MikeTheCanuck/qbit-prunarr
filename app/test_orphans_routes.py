"""Tests for /orphans scan routes in main.py."""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import main
from main import app


@pytest.fixture(autouse=True)
def set_env(monkeypatch, tmp_path):
    monkeypatch.setenv("QBIT_URL", "http://qbit:8080")
    monkeypatch.setenv("QBIT_USERNAME", "admin")
    monkeypatch.setenv("QBIT_PASSWORD", "secret")
    monkeypatch.setenv("SONARR_URL", "http://sonarr:8989")
    monkeypatch.setenv("SONARR_API_KEY", "sonarr-key")
    monkeypatch.setenv("RADARR_URL", "http://radarr:7878")
    monkeypatch.setenv("RADARR_API_KEY", "radarr-key")
    monkeypatch.setenv("PLEX_URL", "http://plex:32400")
    monkeypatch.setenv("PLEX_TOKEN", "plex-token")
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))


def _mock_client(**method_returns):
    instance = MagicMock()
    instance.__enter__ = MagicMock(return_value=instance)
    instance.__exit__ = MagicMock(return_value=False)
    for name, value in method_returns.items():
        getattr(instance, name).return_value = value
    return instance


def _make_file(path, content=b"x" * 1000):
    import os
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)


def _table_region(html: str, table_id: str) -> str:
    """Slice out just one of the two independent orphan tables (download
    vs. review) — the two never share a selection surface, so tests need
    to assert against the right one specifically, not the whole page."""
    start = html.index(f'id="{table_id}"')
    end = html.index("</table>", start)
    return html[start:end]


def _swapped_region(html: str) -> str:
    """Return only what HTMX actually swaps into the page.

    The Scan Now button uses hx-select, so anything rendered OUTSIDE the
    selected element never reaches the browser. Asserting against the whole
    response would pass for banners the user can never see.
    """
    start = html.index('id="scan-results"')
    return html[start:]


def test_orphans_page_renders_empty_state():
    client = TestClient(app)
    response = client.get("/orphans")
    assert response.status_code == 200
    assert "Scan" in response.text


def test_scan_finds_download_orphan(tmp_path):
    import os
    _make_file(os.path.join(str(tmp_path), "torrents", "seed.mkv"))

    with patch("main.QBitClient", return_value=_mock_client(get_all_content_paths=set())), \
         patch("main.SonarrClient", return_value=_mock_client(get_all_episode_paths=set(), get_all_queue_paths=set())), \
         patch("main.RadarrClient", return_value=_mock_client(get_all_movie_paths=set(), get_all_queue_paths=set())), \
         patch("main.PlexClient", return_value=_mock_client(
             get_all_movie_paths=set(), get_all_episode_paths=set()
         )):
        client = TestClient(app)
        response = client.post("/orphans/scan")

    assert response.status_code == 200
    assert "seed.mkv" in _table_region(response.text, "download-table")


def test_scan_result_rows_carry_sort_data_attributes(tmp_path):
    """The client-side size-sort (biggest orphan first, since one orphaned
    torrent can fragment into hundreds of near-zero metadata-file rows)
    reads these attributes directly off each row."""
    import os
    _make_file(os.path.join(str(tmp_path), "torrents", "seed.mkv"), content=b"x" * 5000)

    with patch("main.QBitClient", return_value=_mock_client(get_all_content_paths=set())), \
         patch("main.SonarrClient", return_value=_mock_client(get_all_episode_paths=set(), get_all_queue_paths=set())), \
         patch("main.RadarrClient", return_value=_mock_client(get_all_movie_paths=set(), get_all_queue_paths=set())), \
         patch("main.PlexClient", return_value=_mock_client(
             get_all_movie_paths=set(), get_all_episode_paths=set()
         )):
        client = TestClient(app)
        response = client.post("/orphans/scan")

    region = _table_region(response.text, "download-table")
    assert 'data-size-bytes="5000"' in region
    assert 'data-path="torrents/seed.mkv"' in region


def test_download_and_review_candidates_render_in_separate_tables(tmp_path):
    """Unlinked-download (mostly safe) and orphaned-media (genuinely
    ambiguous - could be a safe duplicate or unimported content) never
    share a table, a select-all checkbox, or a delete form - selecting
    everything in one is structurally incapable of touching the other."""
    import os
    root = str(tmp_path)
    _make_file(os.path.join(root, "torrents", "seed.mkv"))
    _make_file(os.path.join(root, "media", "movies", "orphan-movie.mkv"))

    with patch("main.QBitClient", return_value=_mock_client(get_all_content_paths=set())), \
         patch("main.SonarrClient", return_value=_mock_client(get_all_episode_paths=set(), get_all_queue_paths=set())), \
         patch("main.RadarrClient", return_value=_mock_client(get_all_movie_paths=set(), get_all_queue_paths=set())), \
         patch("main.PlexClient", return_value=_mock_client(
             get_all_movie_paths=set(), get_all_episode_paths=set()
         )):
        client = TestClient(app)
        response = client.post("/orphans/scan")

    download_region = _table_region(response.text, "download-table")
    review_region = _table_region(response.text, "review-table")

    assert "seed.mkv" in download_region
    assert "orphan-movie.mkv" not in download_region

    assert "orphan-movie.mkv" in review_region
    assert "seed.mkv" not in review_region

    assert 'id="download-form"' in response.text
    assert 'id="review-form"' in response.text
    assert 'id="select-all-download"' in response.text
    assert 'id="select-all-review"' in response.text

    assert "Needs Review" in response.text
    assert "safe duplicate" in response.text and "never got imported" in response.text


def test_scan_returns_200_with_inline_error_on_unexpected_failure(tmp_path):
    with patch("main.scan", side_effect=RuntimeError("disk fell off")):
        client = TestClient(app)
        response = client.post("/orphans/scan")

    assert response.status_code == 200
    assert "error-banner" in response.text
    assert "Scan failed" in response.text


def test_scan_protects_file_still_in_sonarr_queue_from_download_orphan_flag(tmp_path):
    """A file stuck 'unable to import automatically' can lose its
    qBittorrent entry (per the *arr app's own cleanup settings) before
    Sonarr gives up on it - the queue signal alone has to be able to save
    it from being flagged as a safe bulk-delete 'unlinked download'."""
    import os
    _make_file(os.path.join(str(tmp_path), "torrents", "stuck-import.mkv"))

    with patch("main.QBitClient", return_value=_mock_client(get_all_content_paths=set())), \
         patch("main.SonarrClient", return_value=_mock_client(
             get_all_episode_paths=set(), get_all_queue_paths={"torrents/stuck-import.mkv"}
         )), \
         patch("main.RadarrClient", return_value=_mock_client(get_all_movie_paths=set(), get_all_queue_paths=set())), \
         patch("main.PlexClient", return_value=_mock_client(
             get_all_movie_paths=set(), get_all_episode_paths=set()
         )):
        client = TestClient(app)
        response = client.post("/orphans/scan")

    assert response.status_code == 200
    assert "stuck-import.mkv" not in _swapped_region(response.text)


def test_scan_with_sonarr_queue_fetch_failure_fails_closed_for_download_side(tmp_path):
    """A queue-fetch failure has to disable download-orphan detection the
    same way an unreachable Sonarr does for media-orphan detection - not
    silently fall back to only checking qBittorrent."""
    import os
    _make_file(os.path.join(str(tmp_path), "torrents", "seed.mkv"))

    broken_sonarr = MagicMock()
    broken_sonarr.__enter__ = MagicMock(return_value=broken_sonarr)
    broken_sonarr.__exit__ = MagicMock(return_value=False)
    broken_sonarr.get_all_episode_paths.return_value = set()
    broken_sonarr.get_all_queue_paths.side_effect = ConnectionError("refused")

    with patch("main.QBitClient", return_value=_mock_client(get_all_content_paths=set())), \
         patch("main.SonarrClient", return_value=broken_sonarr), \
         patch("main.RadarrClient", return_value=_mock_client(get_all_movie_paths=set(), get_all_queue_paths=set())), \
         patch("main.PlexClient", return_value=_mock_client(
             get_all_movie_paths=set(), get_all_episode_paths=set()
         )):
        client = TestClient(app)
        response = client.post("/orphans/scan")

    region = _swapped_region(response.text)
    assert "seed.mkv" not in region
    assert "Sonarr" in region
    assert "unreachable" in region.lower()


def test_scan_with_unreachable_apis_flags_nothing(tmp_path):
    import os
    _make_file(os.path.join(str(tmp_path), "media", "movies", "movie.mkv"))
    _make_file(os.path.join(str(tmp_path), "torrents", "seed.mkv"))

    with patch("main.QBitClient", side_effect=ConnectionError("refused")), \
         patch("main.SonarrClient", side_effect=ConnectionError("refused")), \
         patch("main.RadarrClient", side_effect=ConnectionError("refused")), \
         patch("main.PlexClient", side_effect=ConnectionError("refused")):
        client = TestClient(app)
        response = client.post("/orphans/scan")

    assert response.status_code == 200
    assert "movie.mkv" not in response.text
    assert "seed.mkv" not in response.text


# --- path-prefix sanity guard (Fix 2) ---------------------------------

def test_service_with_zero_scan_overlap_is_treated_as_unusable(tmp_path):
    """A wrong *_PATH_PREFIX normalizes every path to something the scan
    never saw. That must fail CLOSED, not flag the whole download side."""
    import os
    _make_file(os.path.join(str(tmp_path), "torrents", "seed.mkv"))

    with patch("main.QBitClient", return_value=_mock_client(
             get_all_content_paths={"/wrong/mount/completed/seed.mkv"})), \
         patch("main.SonarrClient", return_value=_mock_client(get_all_episode_paths=set(), get_all_queue_paths=set())), \
         patch("main.RadarrClient", return_value=_mock_client(get_all_movie_paths=set(), get_all_queue_paths=set())), \
         patch("main.PlexClient", return_value=_mock_client(
             get_all_movie_paths=set(), get_all_episode_paths=set()
         )):
        client = TestClient(app)
        response = client.post("/orphans/scan")

    region = _swapped_region(response.text)
    assert "seed.mkv" not in region
    assert "qBittorrent" in region
    assert "unusable" in region.lower()
    assert "PREFIX" in region.upper()


def test_genuinely_empty_service_is_not_treated_as_unusable(tmp_path):
    """Zero movies in Radarr is a legitimate state, not a misconfiguration."""
    import os
    _make_file(os.path.join(str(tmp_path), "media", "movies", "movie.mkv"))

    with patch("main.QBitClient", return_value=_mock_client(get_all_content_paths=set())), \
         patch("main.SonarrClient", return_value=_mock_client(get_all_episode_paths=set(), get_all_queue_paths=set())), \
         patch("main.RadarrClient", return_value=_mock_client(get_all_movie_paths=set(), get_all_queue_paths=set())), \
         patch("main.PlexClient", return_value=_mock_client(
             get_all_movie_paths=set(), get_all_episode_paths=set()
         )):
        client = TestClient(app)
        response = client.post("/orphans/scan")

    region = _swapped_region(response.text)
    assert "movie.mkv" in _table_region(response.text, "review-table")
    assert "unusable" not in region.lower()


def test_multifile_torrent_does_not_make_qbit_look_unusable(tmp_path):
    """The overlap guard has to use the same directory-containment rule as
    classification, or every multi-file-torrent setup reads as misconfigured."""
    import os
    pack = os.path.join(str(tmp_path), "torrents", "completed", "Show.S01-GRP")
    _make_file(os.path.join(pack, "S01E01.mkv"))
    _make_file(os.path.join(pack, "S01E02.mkv"))

    with patch("main.QBitClient", return_value=_mock_client(
             get_all_content_paths={"/data/torrents/completed/Show.S01-GRP"})), \
         patch("main.SonarrClient", return_value=_mock_client(get_all_episode_paths=set(), get_all_queue_paths=set())), \
         patch("main.RadarrClient", return_value=_mock_client(get_all_movie_paths=set(), get_all_queue_paths=set())), \
         patch("main.PlexClient", return_value=_mock_client(
             get_all_movie_paths=set(), get_all_episode_paths=set()
         )):
        monkey_prefix = patch.dict(os.environ, {"QBIT_PATH_PREFIX": "/data"})
        with monkey_prefix:
            client = TestClient(app)
            response = client.post("/orphans/scan")

    region = _swapped_region(response.text)
    assert "S01E01.mkv" not in region
    assert "S01E02.mkv" not in region
    assert "unusable" not in region.lower()


def test_qbit_status_ignores_usenet_only_orphans(tmp_path):
    """A usenet-only orphan (no dedicated usenet client exists to judge it)
    must not make a correctly-configured qBittorrent look 'unusable' just
    because its paths don't cover a subdir qBittorrent was never
    responsible for in the first place."""
    import os
    root = str(tmp_path)
    media_path = os.path.join(root, "media", "movies", "Movie.mkv")
    torrent_path = os.path.join(root, "torrents", "Movie.release.mkv")
    os.makedirs(os.path.dirname(media_path), exist_ok=True)
    os.makedirs(os.path.dirname(torrent_path), exist_ok=True)
    with open(media_path, "wb") as f:
        f.write(b"x" * 1000)
    os.link(media_path, torrent_path)
    _make_file(os.path.join(root, "usenet", "stale.mkv"))

    with patch("main.QBitClient", return_value=_mock_client(
             get_all_content_paths={"torrents/Movie.release.mkv"})), \
         patch("main.SonarrClient", return_value=_mock_client(get_all_episode_paths=set(), get_all_queue_paths=set())), \
         patch("main.RadarrClient", return_value=_mock_client(get_all_movie_paths=set(), get_all_queue_paths=set())), \
         patch("main.PlexClient", return_value=_mock_client(
             get_all_movie_paths=set(), get_all_episode_paths=set()
         )):
        client = TestClient(app)
        response = client.post("/orphans/scan")

    region = _swapped_region(response.text)
    assert "qBittorrent: ok" in region
    assert "stale.mkv" in region


# --- per-service status line reaches the browser (Fix 3) ---------------

def test_scan_reports_unreachable_service_inside_swapped_region(tmp_path):
    import os
    _make_file(os.path.join(str(tmp_path), "media", "movies", "movie.mkv"))

    with patch("main.QBitClient", return_value=_mock_client(get_all_content_paths=set())), \
         patch("main.SonarrClient", side_effect=ConnectionError("refused")), \
         patch("main.RadarrClient", return_value=_mock_client(get_all_movie_paths=set(), get_all_queue_paths=set())), \
         patch("main.PlexClient", return_value=_mock_client(
             get_all_movie_paths=set(), get_all_episode_paths=set()
         )):
        client = TestClient(app)
        response = client.post("/orphans/scan")

    region = _swapped_region(response.text)
    assert "Sonarr" in region
    assert "unreachable" in region.lower()


def test_scan_reports_every_service_as_ok_when_all_respond(tmp_path):
    with patch("main.QBitClient", return_value=_mock_client(get_all_content_paths=set())), \
         patch("main.SonarrClient", return_value=_mock_client(get_all_episode_paths=set(), get_all_queue_paths=set())), \
         patch("main.RadarrClient", return_value=_mock_client(get_all_movie_paths=set(), get_all_queue_paths=set())), \
         patch("main.PlexClient", return_value=_mock_client(
             get_all_movie_paths=set(), get_all_episode_paths=set()
         )):
        client = TestClient(app)
        response = client.post("/orphans/scan")

    region = _swapped_region(response.text)
    for name in ("qBittorrent", "Sonarr", "Radarr", "Plex"):
        assert name in region
    assert "unreachable" not in region.lower()


def test_scan_error_banner_is_inside_the_swapped_region(tmp_path):
    with patch("main.scan", side_effect=RuntimeError("disk fell off")):
        client = TestClient(app)
        response = client.post("/orphans/scan")

    region = _swapped_region(response.text)
    assert "error-banner" in region
    assert "Scan failed" in region


def test_delete_single_orphan_after_reverify(tmp_path):
    import os
    path = os.path.join(str(tmp_path), "torrents", "seed.mkv")
    _make_file(path)

    with patch("main.QBitClient", return_value=_mock_client(get_all_content_paths=set())), \
         patch("main.SonarrClient", return_value=_mock_client(get_all_episode_paths=set(), get_all_queue_paths=set())), \
         patch("main.RadarrClient", return_value=_mock_client(get_all_movie_paths=set(), get_all_queue_paths=set())), \
         patch("main.PlexClient", return_value=_mock_client(
             get_all_movie_paths=set(), get_all_episode_paths=set()
         )):
        client = TestClient(app)
        client.post("/orphans/scan")  # populate _scan_cache
        inode = next(iter(main._scan_cache))
        response = client.delete(f"/orphans/{inode}")

    assert response.status_code == 200
    assert not os.path.exists(path)


def test_delete_single_orphan_removes_all_hardlink_paths(tmp_path):
    """Two names for the same inode within torrents/ (a duplicate copy, no
    media link) both have to go — leaving one behind means the file's data
    is never actually freed even though the whole size was reported."""
    import os
    root = str(tmp_path)
    original = os.path.join(root, "torrents", "seed.mkv")
    duplicate = os.path.join(root, "torrents", "seed-copy.mkv")
    _make_file(original)
    os.link(original, duplicate)

    with patch("main.QBitClient", return_value=_mock_client(get_all_content_paths=set())), \
         patch("main.SonarrClient", return_value=_mock_client(get_all_episode_paths=set(), get_all_queue_paths=set())), \
         patch("main.RadarrClient", return_value=_mock_client(get_all_movie_paths=set(), get_all_queue_paths=set())), \
         patch("main.PlexClient", return_value=_mock_client(
             get_all_movie_paths=set(), get_all_episode_paths=set()
         )):
        client = TestClient(app)
        client.post("/orphans/scan")
        inode = next(iter(main._scan_cache))
        response = client.delete(f"/orphans/{inode}")

    assert response.status_code == 200
    assert not os.path.exists(original)
    assert not os.path.exists(duplicate)


def test_delete_skips_if_no_longer_orphan(tmp_path):
    import os
    path = os.path.join(str(tmp_path), "torrents", "seed.mkv")
    _make_file(path)

    with patch("main.QBitClient", return_value=_mock_client(get_all_content_paths=set())), \
         patch("main.SonarrClient", return_value=_mock_client(get_all_episode_paths=set(), get_all_queue_paths=set())), \
         patch("main.RadarrClient", return_value=_mock_client(get_all_movie_paths=set(), get_all_queue_paths=set())), \
         patch("main.PlexClient", return_value=_mock_client(
             get_all_movie_paths=set(), get_all_episode_paths=set()
         )):
        client = TestClient(app)
        client.post("/orphans/scan")
        inode = next(iter(main._scan_cache))

        # Between scan and delete, qBit now reports this path as active.
        with patch("main.QBitClient", return_value=_mock_client(
            get_all_content_paths={"torrents/seed.mkv"}
        )):
            response = client.delete(f"/orphans/{inode}")

    assert response.status_code == 200
    assert os.path.exists(path)
    assert "no longer" in response.text.lower()


def test_bulk_delete_orphans(tmp_path):
    import os
    path_a = os.path.join(str(tmp_path), "torrents", "a.mkv")
    path_b = os.path.join(str(tmp_path), "torrents", "b.mkv")
    _make_file(path_a)
    _make_file(path_b)

    with patch("main.QBitClient", return_value=_mock_client(get_all_content_paths=set())), \
         patch("main.SonarrClient", return_value=_mock_client(get_all_episode_paths=set(), get_all_queue_paths=set())), \
         patch("main.RadarrClient", return_value=_mock_client(get_all_movie_paths=set(), get_all_queue_paths=set())), \
         patch("main.PlexClient", return_value=_mock_client(
             get_all_movie_paths=set(), get_all_episode_paths=set()
         )):
        client = TestClient(app, follow_redirects=False)
        client.post("/orphans/scan")
        inodes = list(main._scan_cache.keys())
        response = client.post("/orphans/delete", data={"inodes": [str(i) for i in inodes]})

    assert response.status_code == 302
    assert not os.path.exists(path_a)
    assert not os.path.exists(path_b)


def test_bulk_delete_reports_failures_via_flash_instead_of_silently_dropping_them(tmp_path):
    """Unlike single-delete (which shows an inline error row), the old bulk
    path caught OSError/ValueError per item and just continued — a user
    could submit a batch, have every delete fail, and see a plain redirect
    with no indication anything went wrong."""
    import os
    path_a = os.path.join(str(tmp_path), "torrents", "a.mkv")
    _make_file(path_a)

    with patch("main.QBitClient", return_value=_mock_client(get_all_content_paths=set())), \
         patch("main.SonarrClient", return_value=_mock_client(get_all_episode_paths=set(), get_all_queue_paths=set())), \
         patch("main.RadarrClient", return_value=_mock_client(get_all_movie_paths=set(), get_all_queue_paths=set())), \
         patch("main.PlexClient", return_value=_mock_client(
             get_all_movie_paths=set(), get_all_episode_paths=set()
         )):
        client = TestClient(app, follow_redirects=False)
        client.post("/orphans/scan")
        inodes = list(main._scan_cache.keys())

        with patch("main.delete_orphan", side_effect=OSError("boom")):
            response = client.post("/orphans/delete", data={"inodes": [str(i) for i in inodes]})

    assert response.status_code == 302
    assert "flash=" in response.headers["location"]
    assert os.path.exists(path_a)


# --- orphan grouping -------------------------------------------------

from contextlib import contextmanager


@contextmanager
def _services(qbit_paths=()):
    with patch("main.QBitClient", return_value=_mock_client(get_all_content_paths=set(qbit_paths))), \
         patch("main.SonarrClient", return_value=_mock_client(get_all_episode_paths=set(), get_all_queue_paths=set())), \
         patch("main.RadarrClient", return_value=_mock_client(get_all_movie_paths=set(), get_all_queue_paths=set())), \
         patch("main.PlexClient", return_value=_mock_client(
             get_all_movie_paths=set(), get_all_episode_paths=set()
         )):
        yield


BLUEBIRD = "torrents/completed/radarr/BLUEBIRD"
OTHER_MOVIE = "torrents/completed/radarr/Other.Movie"


def _make_bluebird(root):
    """The spec's motivating shape: a fully orphaned multi-level disc rip
    (with an empty, never-populated subdir) next to a torrent qBit still
    tracks."""
    import os
    base = os.path.join(root, *BLUEBIRD.split("/"))
    _make_file(os.path.join(base, "BDMV", "STREAM", "00000.m2ts"), content=b"x" * 5000)
    _make_file(os.path.join(base, "BDMV", "BACKUP", "CLIPINF", "00153.clpi"), content=b"x" * 10)
    _make_file(os.path.join(base, "BDMV", "index.bdmv"), content=b"x" * 20)
    os.makedirs(os.path.join(base, "BDMV", "AUXDATA"))
    _make_file(os.path.join(root, *OTHER_MOVIE.split("/"), "movie.mkv"), content=b"x" * 300)


def test_fully_orphaned_directory_renders_as_one_collapsed_group(tmp_path):
    _make_bluebird(str(tmp_path))

    with _services(qbit_paths={OTHER_MOVIE}):
        response = TestClient(app).post("/orphans/scan")

    region = _table_region(response.text, "download-table")
    assert f'data-path="{BLUEBIRD}"' in region
    assert 'data-size-bytes="5030"' in region
    assert '<span class="group-count">3 files</span>' in region
    # Verify the count is inside the button
    assert 'class="group-toggle"' in region and '<span class="group-count">3 files</span>' in region
    assert 'class="orphan-unit orphan-group"' in region  # collapsed: no "expanded"
    assert region.count('class="group-child"') == 3
    assert main._group_cache[BLUEBIRD].size_bytes == 5030


def test_group_children_show_paths_relative_to_group_root(tmp_path):
    _make_bluebird(str(tmp_path))

    with _services(qbit_paths={OTHER_MOVIE}):
        response = TestClient(app).post("/orphans/scan")

    region = _table_region(response.text, "download-table")
    assert "BDMV/BACKUP/CLIPINF/00153.clpi" in region
    assert f"{BLUEBIRD}/BDMV/BACKUP/CLIPINF/00153.clpi" not in region


def test_group_does_not_swallow_a_still_tracked_sibling(tmp_path):
    _make_bluebird(str(tmp_path))

    with _services(qbit_paths={OTHER_MOVIE}):
        response = TestClient(app).post("/orphans/scan")

    assert "Other.Movie" not in _table_region(response.text, "download-table")


def test_standalone_orphans_still_render_as_ordinary_units(tmp_path):
    import os
    _make_file(os.path.join(str(tmp_path), "torrents", "seed.mkv"), content=b"x" * 5000)

    with _services():
        response = TestClient(app).post("/orphans/scan")

    region = _table_region(response.text, "download-table")
    assert '<tbody class="orphan-unit" data-path="torrents/seed.mkv" data-size-bytes="5000">' in region
    assert "orphan-group" not in region
    assert main._group_cache == {}


def test_needs_review_rows_are_never_grouped(tmp_path):
    import os
    root = str(tmp_path)
    _make_file(os.path.join(root, "media", "movies", "Film (2020)", "a.mkv"))
    _make_file(os.path.join(root, "media", "movies", "Film (2020)", "b.mkv"))

    with _services():
        response = TestClient(app).post("/orphans/scan")

    region = _table_region(response.text, "review-table")
    assert "a.mkv" in region and "b.mkv" in region
    assert "orphan-group" not in region


def test_group_delete_removes_every_file_and_the_emptied_tree(tmp_path):
    import os
    root = str(tmp_path)
    _make_bluebird(root)

    with _services(qbit_paths={OTHER_MOVIE}):
        client = TestClient(app)
        client.post("/orphans/scan")
        response = client.post("/orphans/groups/delete", data={"root": BLUEBIRD})

    assert response.status_code == 200
    assert 'class="deleted-row"' in response.text and "Deleted" in response.text
    assert not os.path.exists(os.path.join(root, *BLUEBIRD.split("/")))  # incl. empty AUXDATA/
    assert os.path.exists(os.path.join(root, *OTHER_MOVIE.split("/"), "movie.mkv"))


def test_group_delete_is_best_effort_and_survivors_come_back_standalone(tmp_path):
    import os
    root = str(tmp_path)
    _make_bluebird(root)
    clpi = os.path.join(root, *BLUEBIRD.split("/"), "BDMV", "BACKUP", "CLIPINF", "00153.clpi")
    real_delete = main.delete_orphan

    def flaky_delete(data_root, relative_path, boundary):
        if relative_path.endswith("00153.clpi"):
            raise OSError("permission denied")
        return real_delete(data_root, relative_path, boundary)

    with _services(qbit_paths={OTHER_MOVIE}):
        client = TestClient(app)
        client.post("/orphans/scan")
        with patch("main.delete_orphan", side_effect=flaky_delete):
            response = client.post("/orphans/groups/delete", data={"root": BLUEBIRD})
        rescan = client.post("/orphans/scan")

    assert "1 of 3 deletes failed" in response.text
    assert f'id="{main._group_dom_id(BLUEBIRD)}"' in response.text
    assert os.path.exists(clpi)
    assert not os.path.exists(os.path.join(root, *BLUEBIRD.split("/"), "BDMV", "STREAM"))

    region = _table_region(rescan.text, "download-table")
    assert f"{BLUEBIRD}/BDMV/BACKUP/CLIPINF/00153.clpi" in region  # full path, standalone
    assert "orphan-group" not in region


def test_group_delete_skips_members_that_are_no_longer_orphans(tmp_path):
    import os
    root = str(tmp_path)
    _make_bluebird(root)

    with _services(qbit_paths={OTHER_MOVIE}):
        client = TestClient(app)
        client.post("/orphans/scan")
    # Between scan and click, the torrent was re-added in qBittorrent.
    with _services(qbit_paths={OTHER_MOVIE, BLUEBIRD}):
        response = client.post("/orphans/groups/delete", data={"root": BLUEBIRD})

    assert response.status_code == 200
    assert "no longer" in response.text.lower()
    assert os.path.exists(os.path.join(root, *BLUEBIRD.split("/"), "BDMV", "STREAM", "00000.m2ts"))
    # A live torrent's empty subdirs are left alone too.
    assert os.path.isdir(os.path.join(root, *BLUEBIRD.split("/"), "BDMV", "AUXDATA"))


def test_group_delete_with_unknown_root_deletes_nothing(tmp_path):
    """An unknown root (stale page, or a hand-crafted path) must not return
    an empty 200 - HTMX would swap that in as if the delete had succeeded,
    silently removing the row from the page while the files stay put."""
    import os
    root = str(tmp_path)
    _make_bluebird(root)

    with _services(qbit_paths={OTHER_MOVIE}):
        client = TestClient(app)
        client.post("/orphans/scan")
        stale = client.post("/orphans/groups/delete", data={"root": "torrents/completed/radarr"})
        forged = client.post("/orphans/groups/delete", data={"root": "../../etc"})

    assert stale.status_code == 200
    assert "changed since this scan" in stale.text
    assert forged.status_code == 200
    assert "changed since this scan" in forged.text
    assert os.path.exists(os.path.join(root, *BLUEBIRD.split("/"), "BDMV", "STREAM", "00000.m2ts"))


def test_bulk_delete_with_unknown_group_root_flashes_and_deletes_nothing_in_that_group(tmp_path):
    """Every single delete re-scans and rebuilds `_group_cache`; a group
    root posted by a stale page (or already deleted by another request)
    is no longer a key in that cache. Silently skipping it would let the
    bulk redirect look like a clean success with no indication that group
    was never touched."""
    import os
    root = str(tmp_path)
    _make_bluebird(root)

    with _services(qbit_paths={OTHER_MOVIE}):
        client = TestClient(app, follow_redirects=False)
        client.post("/orphans/scan")
        response = client.post(
            "/orphans/delete",
            data={"group_roots": ["torrents/completed/radarr/does-not-exist"]},
        )

    from urllib.parse import unquote

    assert response.status_code == 302
    assert "flash=" in response.headers["location"]
    assert "changed since this scan" in unquote(response.headers["location"])
    assert os.path.exists(os.path.join(root, *BLUEBIRD.split("/"), "BDMV", "STREAM", "00000.m2ts"))


def test_group_delete_reports_reverify_failure_without_deleting(tmp_path):
    import os
    root = str(tmp_path)
    _make_bluebird(root)

    with _services(qbit_paths={OTHER_MOVIE}):
        client = TestClient(app)
        client.post("/orphans/scan")
        with patch("main.run_scan", side_effect=RuntimeError("disk fell off")):
            response = client.post("/orphans/groups/delete", data={"root": BLUEBIRD})

    assert "Re-verify failed" in response.text
    assert os.path.exists(os.path.join(root, *BLUEBIRD.split("/"), "BDMV", "index.bdmv"))


def test_download_form_has_a_bulk_delete_button(tmp_path):
    with _services():
        response = TestClient(app).post("/orphans/scan")

    start = response.text.index('id="download-form"')
    form = response.text[start:response.text.index("</form>", start)]
    assert 'id="bulk-delete-btn"' in form
    assert 'type="submit"' in form


def test_bulk_delete_accepts_a_group_root(tmp_path):
    import os
    root = str(tmp_path)
    _make_bluebird(root)

    with _services(qbit_paths={OTHER_MOVIE}):
        client = TestClient(app, follow_redirects=False)
        client.post("/orphans/scan")
        response = client.post("/orphans/delete", data={"group_roots": [BLUEBIRD]})

    assert response.status_code == 302
    assert "flash=" not in response.headers["location"]
    assert not os.path.exists(os.path.join(root, *BLUEBIRD.split("/")))


def test_bulk_delete_with_group_and_its_child_both_checked_deletes_once(tmp_path):
    """The child's inode is also a group member - deleting it twice would
    fail the second time and flash a spurious 'deletes failed'."""
    import os
    root = str(tmp_path)
    _make_bluebird(root)

    with _services(qbit_paths={OTHER_MOVIE}):
        client = TestClient(app, follow_redirects=False)
        client.post("/orphans/scan")
        child_inode = main._group_cache[BLUEBIRD].members[0].inode
        response = client.post(
            "/orphans/delete",
            data={"group_roots": [BLUEBIRD], "inodes": [str(child_inode)]},
        )

    assert response.status_code == 302
    assert "flash=" not in response.headers["location"]
    assert not os.path.exists(os.path.join(root, *BLUEBIRD.split("/")))


def test_bulk_delete_with_nothing_selected_is_a_no_op_redirect(tmp_path):
    with _services():
        client = TestClient(app, follow_redirects=False)
        client.post("/orphans/scan")
        response = client.post("/orphans/delete", data={})

    assert response.status_code == 302


def test_bulk_delete_dedupes_duplicate_group_roots(tmp_path):
    """The same group root posted twice (e.g. a double-submitted form)
    must not run `_delete_group` on it twice - the second pass would find
    every member already gone and flash a spurious 'deletes failed'."""
    import os
    root = str(tmp_path)
    _make_bluebird(root)

    with _services(qbit_paths={OTHER_MOVIE}):
        client = TestClient(app, follow_redirects=False)
        client.post("/orphans/scan")
        response = client.post(
            "/orphans/delete",
            data={"group_roots": [BLUEBIRD, BLUEBIRD]},
        )

    assert response.status_code == 302
    assert "flash=" not in response.headers["location"]
    assert not os.path.exists(os.path.join(root, *BLUEBIRD.split("/")))


def test_group_delete_skips_member_with_hardlink_escaping_the_group_root(tmp_path):
    """A member's file gains a second name outside the group root between
    scan and delete-click (a duplicate copy dropped elsewhere under a
    download root). Deleting "this folder" can't touch it: unlinking only
    the in-root name would still leave the file's data referenced by the
    escaped name, silently keeping a copy alive under a different path
    than the one the user was shown, so that member has to be skipped -
    not deleted at all - and the skip also cancels the empty-tree prune."""
    import os
    root = str(tmp_path)
    _make_bluebird(root)

    with _services(qbit_paths={OTHER_MOVIE}):
        client = TestClient(app)
        client.post("/orphans/scan")

        clpi_in_root = os.path.join(
            root, *BLUEBIRD.split("/"), "BDMV", "BACKUP", "CLIPINF", "00153.clpi"
        )
        escaped = os.path.join(root, "torrents", "completed", "radarr", "escaped.clpi")
        os.link(clpi_in_root, escaped)

        response = client.post("/orphans/groups/delete", data={"root": BLUEBIRD})

    assert response.status_code == 200
    assert "skipped" in response.text.lower()
    assert os.path.exists(clpi_in_root)
    assert os.path.exists(escaped)
    # The other two members deleted normally, but the skip cancels pruning
    # of the group root's (now not-fully-emptied) directory tree.
    assert not os.path.exists(
        os.path.join(root, *BLUEBIRD.split("/"), "BDMV", "STREAM", "00000.m2ts")
    )
    assert os.path.isdir(os.path.join(root, *BLUEBIRD.split("/")))


# --- logging on delete failure (Fix F3) -------------------------------

import logging


def test_bulk_delete_per_inode_failure_is_logged(tmp_path, caplog):
    import os
    path_a = os.path.join(str(tmp_path), "torrents", "a.mkv")
    _make_file(path_a)

    with _services():
        client = TestClient(app, follow_redirects=False)
        client.post("/orphans/scan")
        inodes = list(main._scan_cache.keys())
        with patch("main.delete_orphan", side_effect=OSError("boom")):
            with caplog.at_level(logging.WARNING, logger="qbit-prunarr"):
                client.post("/orphans/delete", data={"inodes": [str(i) for i in inodes]})

    assert "boom" in caplog.text
    assert str(inodes[0]) in caplog.text


def test_group_delete_member_failure_is_logged(tmp_path, caplog):
    import os
    root = str(tmp_path)
    _make_bluebird(root)
    real_delete = main.delete_orphan

    def flaky_delete(data_root, relative_path, boundary):
        if relative_path.endswith("00153.clpi"):
            raise OSError("permission denied")
        return real_delete(data_root, relative_path, boundary)

    with _services(qbit_paths={OTHER_MOVIE}):
        client = TestClient(app)
        client.post("/orphans/scan")
        with patch("main.delete_orphan", side_effect=flaky_delete):
            with caplog.at_level(logging.WARNING, logger="qbit-prunarr"):
                client.post("/orphans/groups/delete", data={"root": BLUEBIRD})

    assert "permission denied" in caplog.text


def test_standalone_mac_junk_files_are_hidden_from_download_table(tmp_path):
    """.DS_Store and ._* AppleDouble sidecars are Finder noise, not
    meaningful orphans - torrents/incoming is a direct child of the
    torrents/ boundary, so nothing here groups and each junk file would
    otherwise render as its own pointless standalone row."""
    import os
    root = str(tmp_path)
    _make_file(os.path.join(root, "torrents", "incoming", "real.mkv"), content=b"x" * 5000)
    _make_file(os.path.join(root, "torrents", "incoming", ".DS_Store"), content=b"x" * 10)
    _make_file(os.path.join(root, "torrents", "incoming", "._foo.mkv"), content=b"x" * 10)

    with _services():
        response = TestClient(app).post("/orphans/scan")

    region = _table_region(response.text, "download-table")
    assert "real.mkv" in region
    assert ".DS_Store" not in region
    assert "._foo.mkv" not in region


def test_group_child_rows_still_include_mac_junk_files(tmp_path):
    """A .DS_Store inside a fully-orphaned group folder is still real
    group content: it's counted in the file count and shown when the
    group is expanded, because a group delete has to remove it too or
    the folder would survive as a shell containing only .DS_Store."""
    import os
    root = str(tmp_path)
    _make_bluebird(root)
    _make_file(os.path.join(root, *BLUEBIRD.split("/"), "BDMV", ".DS_Store"), content=b"x" * 10)

    with _services(qbit_paths={OTHER_MOVIE}):
        response = TestClient(app).post("/orphans/scan")

    region = _table_region(response.text, "download-table")
    assert ".DS_Store" in region
    assert '<span class="group-count">4 files</span>' in region


def test_is_mac_junk_helper():
    assert main._is_mac_junk(["torrents/incoming/.DS_Store"])
    assert main._is_mac_junk(["torrents/incoming/._foo.mkv"])
    assert not main._is_mac_junk(["torrents/incoming/x.DS_Store"])
    assert not main._is_mac_junk(["torrents/incoming/._foo.mkv", "torrents/incoming/real.mkv"])


def test_sections_render_as_tabs_with_counts(tmp_path):
    """Unlinked Downloads and Needs Review are tabs on one page, not stacked
    sections, and each tab shows how many items (and GB) are behind it."""
    import os
    root = str(tmp_path)
    _make_file(os.path.join(root, "torrents", "seed.mkv"))
    _make_file(os.path.join(root, "media", "movies", "orphan-movie.mkv"))

    with patch("main.QBitClient", return_value=_mock_client(get_all_content_paths=set())), \
         patch("main.SonarrClient", return_value=_mock_client(get_all_episode_paths=set(), get_all_queue_paths=set())), \
         patch("main.RadarrClient", return_value=_mock_client(get_all_movie_paths=set(), get_all_queue_paths=set())), \
         patch("main.PlexClient", return_value=_mock_client(
             get_all_movie_paths=set(), get_all_episode_paths=set()
         )):
        client = TestClient(app)
        response = client.post("/orphans/scan")

    html = response.text
    assert 'data-tab="download"' in html and 'data-tab="review"' in html
    assert 'data-panel="download"' in html and 'data-panel="review"' in html
    # Each table lives inside its own tab panel.
    assert html.index('data-panel="download"') < html.index('id="download-table"') < html.index('data-panel="review"')
    assert html.index('data-panel="review"') < html.index('id="review-table"')
    assert html.count('class="tab-count">1 ·') == 2


def test_tabs_show_no_counts_before_a_scan():
    """Before any scan, a '0 · 0.0 GB' badge would read as a finished
    analysis that found nothing, so the tabs show names only."""
    response = TestClient(app).get("/orphans")
    assert 'data-tab="download"' in response.text
    assert 'class="tab-count"' not in response.text
    assert "Not scanned yet" in response.text


def test_needs_review_offers_folder_grouping():
    response = TestClient(app).get("/orphans")
    assert 'data-mode="folder"' in response.text and 'data-mode="flat"' in response.text


def test_review_form_has_its_own_bulk_delete_button(tmp_path):
    """Needs Review gets a submit inside its own form, so its checkboxes do
    something - and still can't post anything from the download table."""
    with _services():
        response = TestClient(app).post("/orphans/scan")

    start = response.text.index('id="review-form"')
    form = response.text[start:response.text.index("</form>", start)]
    assert 'id="review-delete-btn"' in form
    assert 'type="submit"' in form
    assert 'id="bulk-delete-btn"' not in form


def test_bulk_delete_success_says_what_it_did(tmp_path):
    """A clean bulk delete redirects to an unscanned page, so it has to
    report the count and space freed or it looks like nothing happened."""
    import os
    path_a = os.path.join(str(tmp_path), "media", "movies", "a.mkv")
    _make_file(path_a, content=b"x" * 2000)

    with patch("main.QBitClient", return_value=_mock_client(get_all_content_paths=set())), \
         patch("main.SonarrClient", return_value=_mock_client(get_all_episode_paths=set(), get_all_queue_paths=set())), \
         patch("main.RadarrClient", return_value=_mock_client(get_all_movie_paths=set(), get_all_queue_paths=set())), \
         patch("main.PlexClient", return_value=_mock_client(
             get_all_movie_paths=set(), get_all_episode_paths=set()
         )):
        client = TestClient(app, follow_redirects=False)
        client.post("/orphans/scan")
        inodes = list(main._scan_cache.keys())
        response = client.post("/orphans/delete", data={"inodes": [str(i) for i in inodes]})
        page = client.get(response.headers["location"])

    assert not os.path.exists(path_a)
    assert "done=" in response.headers["location"]
    assert "Deleted 1 file" in page.text
    assert 'class="done-banner"' in page.text


def test_page_has_sticky_delete_bar_and_folder_controls():
    html = TestClient(app).get("/orphans").text
    assert 'id="sticky-delete"' in html and 'id="sticky-delete-btn"' in html
    assert 'data-folders="expand"' in html and 'data-folders="collapse"' in html
