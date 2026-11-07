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
    assert "sorted by what to do about them" in response.text


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


def test_scan_status_is_one_message_beside_the_button():
    """'Not scanned yet' and 'Scanning…' share one element next to Scan Now,
    so the page never shows a stale 'Not scanned yet' under the tabs while
    a scan runs."""
    html = TestClient(app).get("/orphans").text
    status = html[html.index('id="scan-status"'):html.index('id="scan-results"')]
    assert "Not scanned yet" in status
    assert "Scanning" in status
    assert html.count("Not scanned yet") == 1
    assert 'hx-indicator="#scan-status"' in html
    assert 'hx-select-oob="#scan-status"' in html


def test_review_columns_have_fixed_widths():
    """Size and the last column keep explicit widths, so they don't drift
    when a table has only a few short rows."""
    html = TestClient(app).get("/orphans").text
    assert "th.col-size" in html and "th.col-delete" in html and "th.col-more" in html
    download = _table_region(html, "download-table")
    assert '<th class="col-delete">Delete</th>' in download
    review = _table_region(html, "review-table")
    assert '<th class="sortable col-size" data-sort="size">Size</th>' in review
    assert '<th class="col-more"></th>' in review


def test_scan_status_hides_not_scanned_after_a_scan():
    with patch("main.QBitClient", return_value=_mock_client(get_all_content_paths=set())), \
         patch("main.SonarrClient", return_value=_mock_client(get_all_episode_paths=set(), get_all_queue_paths=set())), \
         patch("main.RadarrClient", return_value=_mock_client(get_all_movie_paths=set(), get_all_queue_paths=set())), \
         patch("main.PlexClient", return_value=_mock_client(
             get_all_movie_paths=set(), get_all_episode_paths=set()
         )):
        html = TestClient(app).post("/orphans/scan").text
    assert 'id="scan-status" class="scanned"' in html


def test_extras_tab_exists_without_counts_before_a_scan():
    response = TestClient(app).get("/orphans")
    assert 'data-tab="extras"' in response.text
    assert 'data-panel="extras"' in response.text
    assert 'class="tab-count"' not in response.text



def test_plex_confirmed_extra_moves_to_extras_tab(tmp_path):
    response = _scan_with(tmp_path, _plex_with_extras({f"{FILM}/Featurettes/Making Of.mkv"}))
    review = _table_region(response.text, "review-table")
    extras = _table_region(response.text, "extras-table")
    assert "Making Of.mkv" not in review
    assert "Making Of.mkv" in extras
    assert "Trailer.mkv" in review


def test_review_rows_carry_their_verdict(tmp_path):
    response = _scan_with(tmp_path, _plex_with_extras())
    review = _table_region(response.text, "review-table")
    assert 'data-verdict="junk"' in review          # film-sample.mkv
    assert 'data-verdict="plex"' in review          # Extras/Trailer.mkv
    assert "Move to Film (2020)/Trailers/Trailer.mkv" in review


def test_sonarr_series_folder_with_prefix_and_trailing_slash_still_maps(tmp_path, monkeypatch):
    import os
    monkeypatch.setenv("SONARR_PATH_PREFIX", "/data")
    root = str(tmp_path)
    _make_file(os.path.join(root, "media", "tv", "Show", "Season 01", "ep1.mkv"))
    _make_file(os.path.join(root, "media", "tv", "Show", "Show.S01E00.The.Pilot.Story.mkv"))
    sonarr = _mock_client(
        get_all_episode_paths={"/data/media/tv/Show/Season 01/ep1.mkv"}, get_all_queue_paths=set(),
        get_series=[{"id": 3, "title": "Show", "path": "/data/media/tv/Show/"}],
        get_missing_specials=[{"code": "S00E01", "title": "The Pilot Story", "monitored": True}],
    )
    plex = _mock_client(get_all_movie_paths=set(), get_all_episode_paths={"media/tv/Show/Season 01/ep1.mkv"},
                        get_movie_files={}, get_episode_files={"media/tv/Show/Season 01/ep1.mkv": ["1", "2"]},
                        get_extra_paths=set())
    with patch("main.QBitClient", return_value=_mock_client(get_all_content_paths=set())), \
         patch("main.SonarrClient", return_value=sonarr), \
         patch("main.RadarrClient", return_value=_mock_client(get_all_movie_paths=set(), get_all_queue_paths=set(), get_movies=[])), \
         patch("main.PlexClient", return_value=plex):
        response = TestClient(app).post("/orphans/scan")
    # Jinja autoescapes the title's quotes in the rendered row.
    assert 'Import as S00E01 &#34;The Pilot Story&#34;' in _table_region(response.text, "review-table")


def test_review_form_has_its_own_bulk_delete_button(tmp_path):
    """Needs Review gets a submit inside its own form, so its checkboxes do
    something - and still can't post anything from the download table."""
    response = _scan_with(tmp_path, _plex_with_extras())

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


def test_page_has_sticky_delete_bar():
    html = TestClient(app).get("/orphans").text
    assert 'id="sticky-delete"' in html and 'id="sticky-delete-btn"' in html


def test_bulk_delete_records_exactly_what_it_removed(tmp_path, monkeypatch):
    """The banner lists the deleted paths, and every delete is appended to
    AUDIT_LOG, so 'what did that delete actually remove?' always has an
    answer, even after the container is recreated."""
    import os
    audit = tmp_path / "audit.log"
    monkeypatch.setenv("AUDIT_LOG", str(audit))
    path_a = os.path.join(str(tmp_path), "media", "movies", "Film", "old copy.avi")
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

    assert "media/movies/Film/old copy.avi" in page.text
    assert "DELETED media/movies/Film/old copy.avi (2000 bytes)" in audit.read_text()


def test_deleting_a_review_video_takes_its_sidecars_but_nothing_else(tmp_path, monkeypatch):
    import os
    audit = tmp_path / "audit.log"
    monkeypatch.setenv("AUDIT_LOG", str(audit))
    d = os.path.join(str(tmp_path), "media", "movies", "Film")
    _make_file(os.path.join(d, "Old.mp4"), content=b"x" * 3000)
    _make_file(os.path.join(d, "Old.srt"), content=b"x" * 30)
    _make_file(os.path.join(d, "Other.srt"), content=b"x" * 30)

    with patch("main.QBitClient", return_value=_mock_client(get_all_content_paths=set())), \
         patch("main.SonarrClient", return_value=_mock_client(get_all_episode_paths=set(), get_all_queue_paths=set())), \
         patch("main.RadarrClient", return_value=_mock_client(get_all_movie_paths=set(), get_all_queue_paths=set())), \
         patch("main.PlexClient", return_value=_mock_client(
             get_all_movie_paths=set(), get_all_episode_paths=set()
         )):
        client = TestClient(app, follow_redirects=False)
        scan = client.post("/orphans/scan")
        assert "+1 sidecar" in scan.text
        inodes = [i for i, c in main._scan_cache.items() if c.paths[0].endswith("Old.mp4")]
        response = client.post("/orphans/delete", data={"inodes": [str(i) for i in inodes]})
        page = client.get(response.headers["location"])

    assert not os.path.exists(os.path.join(d, "Old.mp4"))
    assert not os.path.exists(os.path.join(d, "Old.srt"))
    assert os.path.exists(os.path.join(d, "Other.srt"))
    assert "plus 1 subtitle/metadata file" in page.text
    assert "media/movies/Film/Old.srt" in page.text
    assert "DELETED media/movies/Film/Old.srt (30 bytes)" in audit.read_text()


FILM = "media/movies/Film (2020)"


def _plex_with_extras(extra_paths=(), raises=False):
    plex = _mock_client(
        get_all_movie_paths={f"{FILM}/Film.mkv"}, get_all_episode_paths=set(),
        get_movie_files={f"{FILM}/Film.mkv": ["7"]}, get_episode_files={},
        get_extra_paths=set(extra_paths),
    )
    if raises:
        plex.get_extra_paths.side_effect = RuntimeError("plex 500 on one key")
    return plex


def _scan_with(tmp_path, plex, sonarr=None, radarr=None):
    import os
    root = str(tmp_path)
    _make_file(os.path.join(root, *FILM.split("/"), "Film.mkv"))
    _make_file(os.path.join(root, *FILM.split("/"), "Featurettes", "Making Of.mkv"))
    _make_file(os.path.join(root, *FILM.split("/"), "Extras", "Trailer.mkv"))
    _make_file(os.path.join(root, *FILM.split("/"), "film-sample.mkv"))
    with patch("main.QBitClient", return_value=_mock_client(get_all_content_paths=set())), \
         patch("main.SonarrClient", return_value=sonarr or _mock_client(get_all_episode_paths=set(), get_all_queue_paths=set())), \
         patch("main.RadarrClient", return_value=radarr or _mock_client(
             get_all_movie_paths={f"{FILM}/Film.mkv"}, get_all_queue_paths=set(), get_movies=[])), \
         patch("main.PlexClient", return_value=plex):
        return TestClient(app).post("/orphans/scan")


def test_confirmed_extra_is_never_in_the_scan_cache(tmp_path):
    import os
    _scan_with(tmp_path, _plex_with_extras({f"{FILM}/Featurettes/Making Of.mkv"}))
    inode = os.stat(os.path.join(str(tmp_path), *FILM.split("/"), "Featurettes", "Making Of.mkv")).st_ino
    assert inode not in main._scan_cache
    assert any("Making Of.mkv" in c.paths[0] for c in main._extras_cache)


def test_bulk_delete_of_an_extra_skips_it(tmp_path):
    import os
    path = os.path.join(str(tmp_path), *FILM.split("/"), "Featurettes", "Making Of.mkv")
    plex = _plex_with_extras({f"{FILM}/Featurettes/Making Of.mkv"})
    _scan_with(tmp_path, plex)
    with patch("main.QBitClient", return_value=_mock_client(get_all_content_paths=set())), \
         patch("main.SonarrClient", return_value=_mock_client(get_all_episode_paths=set(), get_all_queue_paths=set())), \
         patch("main.RadarrClient", return_value=_mock_client(
             get_all_movie_paths={f"{FILM}/Film.mkv"}, get_all_queue_paths=set(), get_movies=[])), \
         patch("main.PlexClient", return_value=plex):
        TestClient(app).post("/orphans/delete", data={"inodes": [str(os.stat(path).st_ino)]}, follow_redirects=False)
    assert os.path.exists(path)


def test_failed_extras_lookup_keeps_everything_in_review(tmp_path):
    response = _scan_with(tmp_path, _plex_with_extras(raises=True))
    review = _table_region(response.text, "review-table")
    assert "Making Of.mkv" in review
    assert "Plex extras: not checked" in _swapped_region(response.text)
    # Said where it's seen, not only inside the collapsed Service status box.
    assert 'id="extras-unchecked"' in _swapped_region(response.text)
    assert "No Plex extras among" not in response.text
    assert "Plex extras couldn't be checked this scan, so any extras" in response.text


def _row_for(review: str, name: str) -> str:
    at = review.index(name)
    return review[review.rindex("<tr", 0, at): review.index("</tr>", at)]


def test_unreachable_plex_keeps_extras_in_review_and_says_not_checked(tmp_path):
    """Plex's movie fetch fails: movie files can't be reviewed at all (fail
    closed), and the extras lookup is skipped, so a TV Featurettes file that
    Plex may well show as an extra stays in Needs Review as a keep."""
    import os
    root = str(tmp_path)
    ep = "media/tv/Show/Season 01/Show.S01E01.mkv"
    _make_file(os.path.join(root, *ep.split("/")))
    _make_file(os.path.join(root, "media", "tv", "Show", "Featurettes", "Making Of.mkv"))
    plex = _mock_client(get_all_episode_paths={ep}, get_movie_files={}, get_episode_files={ep: ["1"]},
                        get_extra_paths={"media/tv/Show/Featurettes/Making Of.mkv"})
    plex.get_all_movie_paths.side_effect = RuntimeError("plex down")
    with patch("main.QBitClient", return_value=_mock_client(get_all_content_paths=set())), \
         patch("main.SonarrClient", return_value=_mock_client(
             get_all_episode_paths={ep}, get_all_queue_paths=set(), get_series=[])), \
         patch("main.RadarrClient", return_value=_mock_client(
             get_all_movie_paths=set(), get_all_queue_paths=set(), get_movies=[])), \
         patch("main.PlexClient", return_value=plex):
        response = TestClient(app).post("/orphans/scan")
    plex.get_extra_paths.assert_not_called()
    swapped = _swapped_region(response.text)
    review = _table_region(response.text, "review-table")
    row = _row_for(review, "Featurettes/Making Of.mkv")
    assert "verdict-plex" in row and "Leave it where it is." in row
    assert 'name="inodes"' not in row
    assert "Plex: unreachable" in swapped
    assert "Plex extras:" not in swapped
    assert 'id="extras-unchecked"' in swapped
    assert "Plex extras couldn't be checked this scan, so any extras" in swapped
    assert "No Plex extras among" not in swapped
    assert not main._extras_cache


def test_checked_extras_with_none_found_say_so(tmp_path):
    response = _scan_with(tmp_path, _plex_with_extras())
    swapped = _swapped_region(response.text)
    assert "No Plex extras among the files this scan found." in swapped
    assert 'id="extras-unchecked"' not in swapped


def test_extras_not_checked_before_a_scan_shows_no_notice():
    response = TestClient(app).get("/orphans")
    assert 'id="extras-unchecked"' not in response.text
    assert "couldn't be checked" not in response.text


def test_extra_confirmed_under_a_second_hardlink_path_still_moves(tmp_path):
    """The extras lookup keys on every path's title folder, not just the
    first: here the first path's folder has no Plex title at all."""
    import os
    root = str(tmp_path)
    film = "media/movies-no-backup/Film (2020)"
    first = os.path.join(root, "media", "movies", "Other (2019)", "copy.mkv")
    second = os.path.join(root, *film.split("/"), "Featurettes", "Making Of.mkv")
    _make_file(os.path.join(root, *film.split("/"), "Film.mkv"))
    _make_file(first)
    os.makedirs(os.path.dirname(second), exist_ok=True)
    os.link(first, second)
    plex = _mock_client(
        get_all_movie_paths={f"{film}/Film.mkv"}, get_all_episode_paths=set(),
        get_movie_files={f"{film}/Film.mkv": ["7"]}, get_episode_files={},
        get_extra_paths={f"{film}/Featurettes/Making Of.mkv"},
    )
    with patch("main.QBitClient", return_value=_mock_client(get_all_content_paths=set())), \
         patch("main.SonarrClient", return_value=_mock_client(get_all_episode_paths=set(), get_all_queue_paths=set())), \
         patch("main.RadarrClient", return_value=_mock_client(
             get_all_movie_paths={f"{film}/Film.mkv"}, get_all_queue_paths=set(), get_movies=[])), \
         patch("main.PlexClient", return_value=plex):
        TestClient(app).post("/orphans/scan")
    inode = os.stat(first).st_ino
    assert main._extras_cache and main._extras_cache[0].paths[0] == "media/movies/Other (2019)/copy.mkv"
    assert inode not in main._scan_cache


def test_bulk_delete_skips_an_inode_this_page_never_showed(tmp_path):
    """A hand-crafted bulk POST can't delete a file the scan didn't show,
    even when the re-verify scan would flag it."""
    import os
    _scan_with(tmp_path, _plex_with_extras())
    late = os.path.join(str(tmp_path), *FILM.split("/"), "Late Arrival.mkv")
    _make_file(late)
    inode = os.stat(late).st_ino
    assert inode not in main._scan_cache
    with patch("main.QBitClient", return_value=_mock_client(get_all_content_paths=set())), \
         patch("main.SonarrClient", return_value=_mock_client(get_all_episode_paths=set(), get_all_queue_paths=set())), \
         patch("main.RadarrClient", return_value=_mock_client(
             get_all_movie_paths={f"{FILM}/Film.mkv"}, get_all_queue_paths=set(), get_movies=[])), \
         patch("main.PlexClient", return_value=_plex_with_extras()):
        response = TestClient(app).post("/orphans/delete", data={"inodes": [str(inode)]}, follow_redirects=False)
    assert os.path.exists(late)
    assert inode in main._scan_cache  # the re-scan did flag it
    assert "1 skipped" in response.headers["location"].replace("%20", " ")


def test_review_buckets_count_every_kind_including_empty():
    rows = [{"verdict": "junk", "size_bytes": 2_000_000_000}, {"verdict": None, "size_bytes": 5}]
    b = {x["kind"]: x for x in main._review_buckets(rows)}
    assert [x["kind"] for x in main.REVIEW_BUCKETS] == ["junk", "wanted", "plex", "identify", "call"]
    assert b["junk"]["count"] == 1 and b["junk"]["size_gb"] == "2.0"
    assert b["call"]["count"] == 1          # no verdict counts as Your call
    assert b["wanted"]["count"] == 0 and b["wanted"]["keep"] is True
    assert b["junk"]["keep"] is False


def test_needs_review_shows_group_cards_after_a_scan(tmp_path):
    response = _scan_with(tmp_path, _plex_with_extras())
    swapped = _swapped_region(response.text)
    cards = swapped[swapped.index('id="review-buckets"'):swapped.index('id="review-form"')]
    assert 'data-kind="junk"' in cards and "Probably junk" in cards and ">Delete<" in cards
    assert "Sonarr/Radarr wants it" in cards and "Keep: " not in cards
    assert "Nothing to delete here. Each file lists its next step." in swapped
    assert "Tick the ones to delete." in swapped


def test_needs_review_with_nothing_says_so(tmp_path):
    with _services():
        html = TestClient(app).post("/orphans/scan").text
    assert "Nothing needs review." in html
    assert 'id="review-buckets"' not in html


def test_needs_review_drops_flat_mode_and_expand_collapse():
    html = TestClient(app).get("/orphans").text
    assert 'data-mode="flat"' not in html and 'data-folders="expand"' not in html
    assert "folder-all" not in html and "orphans-review-mode" not in html
    assert "showBucket" in html and "orphans-review-bucket" in html


@pytest.mark.parametrize("path,expected", [
    ("media/tv/Lucky Hank/Lucky.Hank.S01E07.1080p.WEB.h264-ETHEL.mkv",
     ("Lucky Hank S01E07 1080p WEB h264-ETHEL", "tv / Lucky Hank")),
    ("media/movies/Iron Man 3 2013/Sample,Screens/Iron Man 3 (Sample).mkv",
     ("Iron Man 3 (Sample)", "movies / Iron Man 3 2013 / Sample,Screens")),
    ("media/tv/American_Dad_S07E08.mkv", ("American Dad S07E08", "tv")),
    ("media/x.mkv", ("x", "")),
])
def test_review_title_splits_name_and_folder(path, expected):
    assert main._review_title(path) == expected


def _review_row(review: str, name: str) -> str:
    """The one review <tr> whose content names the file. _row_for can land
    on the previous row, because each row's tbody repeats its path."""
    rows = [r.split("</tr>")[0] for r in review.split('<tr id="orphan-row-')[1:]]
    return next(r for r in rows if name in r)


def test_keep_rows_have_no_checkbox_and_delete_hides_in_a_menu(tmp_path):
    response = _scan_with(tmp_path, _plex_with_extras())
    review = _table_region(response.text, "review-table")
    row = _review_row(review, "Extras/Trailer.mkv")
    assert 'name="inodes"' not in row
    assert 'class="keep-mark"' in row
    assert 'class="delete-anyway"' in row and "Delete anyway" in row
    assert "<button hx-delete" not in row   # the old red per-row Delete button is gone


def test_deletable_rows_keep_a_checkbox_and_no_delete_button(tmp_path):
    response = _scan_with(tmp_path, _plex_with_extras())
    row = _review_row(_table_region(response.text, "review-table"), "film-sample.mkv")
    assert 'name="inodes"' in row and "delete-anyway" not in row
    assert ">film-sample<" in row or "film-sample</" in row   # readable name, extension dropped
    assert 'class="copy-path"' in row


def test_review_table_has_no_delete_column():
    html = TestClient(app).get("/orphans").text
    review = html[html.index('id="review-table"'):html.index("</thead>", html.index('id="review-table"'))]
    assert "col-delete" not in review and ">Delete<" not in review
    assert ">File<" in review


def test_copy_path_works_over_plain_http():
    html = TestClient(app).get("/orphans").text
    assert "execCommand('copy')" in html


def test_review_deletes_confirm_in_a_styled_dialog():
    html = TestClient(app).get("/orphans").text
    dialog = html[html.index('<dialog id="delete-dialog"'):html.index("</dialog>")]
    assert "Deleted files can't be recovered. Each one is re-checked first, and anything that has since shown up in Sonarr, Radarr or Plex is skipped." in dialog
    assert ">Cancel<" in dialog and "autofocus" in dialog
    assert "showModal()" in html
    assert "The suggestion is to keep this file: " in html


def test_sticky_bar_has_clear_and_is_the_review_tabs_only_delete(tmp_path):
    response = _scan_with(tmp_path, _plex_with_extras())
    html = response.text
    bar = html[html.index('id="sticky-delete"'):html.index("</div>", html.index('id="sticky-delete"'))]
    assert 'id="sticky-clear"' in bar and ">Clear<" in bar
    form = html[html.index('id="review-form"'):html.index("</form>", html.index('id="review-form"'))]
    assert 'id="review-delete-btn"' in form and 'type="submit"' in form
    assert '<button type="submit" id="review-delete-btn" hidden' in form


def test_delete_anyway_goes_through_the_dialog_not_hx_confirm(tmp_path):
    response = _scan_with(tmp_path, _plex_with_extras())
    row = _review_row(_table_region(response.text, "review-table"), "Extras/Trailer.mkv")
    assert 'class="delete-anyway"' in row and "hx-confirm" not in row and "hx-delete" not in row


def test_clicks_inside_a_row_menu_keep_it_open():
    """The close-on-outside-click handler ran first and hid the menu, so
    Copy path's "Copied" was written to a button nobody could see."""
    html = TestClient(app).get("/orphans").text
    assert "if (e.target.closest('.menu')) { return; }" in html


def test_delete_anyway_ignores_a_row_already_deleting():
    """A second confirm while the ~15s re-check runs would send a second
    DELETE whose "skipped" row overwrites the first one's "Deleted" row."""
    html = TestClient(app).get("/orphans").text
    assert "if (tr.classList.contains('deleting')) { return; }" in html


def test_review_confirm_no_longer_uses_native_confirm():
    html = TestClient(app).get("/orphans").text
    assert "None of them are in your library" not in html     # the old confirm() text
    assert "confirm('Delete every selected file and folder?')" in html   # download tab unchanged


def test_review_rows_carry_their_sidecar_names(tmp_path):
    """The confirm lists each sidecar by name under its video, so the
    row has to hand the dialog the names, not just a count."""
    import os
    _make_file(os.path.join(str(tmp_path), *FILM.split("/"), "film-sample.srt"))
    response = _scan_with(tmp_path, _plex_with_extras())
    row = _review_row(_swapped_region(response.text), "film-sample")
    assert 'data-sidecar-names=\'["film-sample.srt"]\'' in row


def test_delete_dialog_lists_each_sidecar_under_its_video():
    html = TestClient(app).get("/orphans").text
    assert "JSON.parse(tr.dataset.sidecarNames" in html
    assert "sub.className = 'sc';" in html
    assert "Indented: subtitle and metadata files named after the video above them. They're deleted with it." in html


def test_an_in_flight_delete_says_so_in_the_row():
    """A dimmed row alone read as stalled; the row now says what's happening."""
    html = TestClient(app).get("/orphans").text
    assert "function markDeleting(tr)" in html
    assert "Deleting. First making sure nothing has claimed it since your scan (about 15 seconds)." in html


def test_busy_label_does_not_promise_a_fresh_scan():
    """"Re-checking" made people expect fresh scan results on screen."""
    html = TestClient(app).get("/orphans").text
    assert "Re-checking" not in html
    assert "Deleting… (about 15 seconds)" in html
