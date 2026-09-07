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
