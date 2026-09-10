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
         patch("main.SonarrClient", return_value=_mock_client(get_all_episode_paths=set())), \
         patch("main.RadarrClient", return_value=_mock_client(get_all_movie_paths=set())), \
         patch("main.PlexClient", return_value=_mock_client(
             get_all_movie_paths=set(), get_all_episode_paths=set()
         )):
        client = TestClient(app)
        response = client.post("/orphans/scan")

    assert response.status_code == 200
    assert "seed.mkv" in response.text
    assert "unlinked download" in response.text


def test_scan_returns_200_with_inline_error_on_unexpected_failure(tmp_path):
    with patch("main.scan", side_effect=RuntimeError("disk fell off")):
        client = TestClient(app)
        response = client.post("/orphans/scan")

    assert response.status_code == 200
    assert "error-banner" in response.text
    assert "Scan failed" in response.text


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
         patch("main.SonarrClient", return_value=_mock_client(get_all_episode_paths=set())), \
         patch("main.RadarrClient", return_value=_mock_client(get_all_movie_paths=set())), \
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
         patch("main.SonarrClient", return_value=_mock_client(get_all_episode_paths=set())), \
         patch("main.RadarrClient", return_value=_mock_client(get_all_movie_paths=set())), \
         patch("main.PlexClient", return_value=_mock_client(
             get_all_movie_paths=set(), get_all_episode_paths=set()
         )):
        client = TestClient(app)
        response = client.post("/orphans/scan")

    region = _swapped_region(response.text)
    assert "movie.mkv" in region
    assert "orphaned media" in region
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
         patch("main.SonarrClient", return_value=_mock_client(get_all_episode_paths=set())), \
         patch("main.RadarrClient", return_value=_mock_client(get_all_movie_paths=set())), \
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


# --- per-service status line reaches the browser (Fix 3) ---------------

def test_scan_reports_unreachable_service_inside_swapped_region(tmp_path):
    import os
    _make_file(os.path.join(str(tmp_path), "media", "movies", "movie.mkv"))

    with patch("main.QBitClient", return_value=_mock_client(get_all_content_paths=set())), \
         patch("main.SonarrClient", side_effect=ConnectionError("refused")), \
         patch("main.RadarrClient", return_value=_mock_client(get_all_movie_paths=set())), \
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
         patch("main.SonarrClient", return_value=_mock_client(get_all_episode_paths=set())), \
         patch("main.RadarrClient", return_value=_mock_client(get_all_movie_paths=set())), \
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
         patch("main.SonarrClient", return_value=_mock_client(get_all_episode_paths=set())), \
         patch("main.RadarrClient", return_value=_mock_client(get_all_movie_paths=set())), \
         patch("main.PlexClient", return_value=_mock_client(
             get_all_movie_paths=set(), get_all_episode_paths=set()
         )):
        client = TestClient(app)
        client.post("/orphans/scan")  # populate _scan_cache
        inode = next(iter(main._scan_cache))
        response = client.delete(f"/orphans/{inode}")

    assert response.status_code == 200
    assert not os.path.exists(path)


def test_delete_skips_if_no_longer_orphan(tmp_path):
    import os
    path = os.path.join(str(tmp_path), "torrents", "seed.mkv")
    _make_file(path)

    with patch("main.QBitClient", return_value=_mock_client(get_all_content_paths=set())), \
         patch("main.SonarrClient", return_value=_mock_client(get_all_episode_paths=set())), \
         patch("main.RadarrClient", return_value=_mock_client(get_all_movie_paths=set())), \
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
         patch("main.SonarrClient", return_value=_mock_client(get_all_episode_paths=set())), \
         patch("main.RadarrClient", return_value=_mock_client(get_all_movie_paths=set())), \
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
