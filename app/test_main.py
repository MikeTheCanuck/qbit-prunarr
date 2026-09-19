"""Tests for FastAPI routes in main.py."""
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import main
from main import app

NOW = time.time()

# A torrent that's been inactive for 5 days (won't show at min_days=30)
TORRENT_FRESH = {
    "name": "fresh-file.mkv",
    "hash": "hash001",
    "last_activity": int(NOW - 5 * 86400),
    "added_on": int(NOW - 10 * 86400),
    "size": 5_000_000_000,
    "uploaded": 10_000_000_000,
    "tags": "only-for-ratio",
    "category": "",
}

# A torrent that's been inactive for 100 days (shows at min_days=30 and min_days=90)
TORRENT_OLD = {
    "name": "old-series.mkv",
    "hash": "hash002",
    "last_activity": int(NOW - 100 * 86400),
    "added_on": int(NOW - 200 * 86400),
    "size": 10_000_000_000,
    "uploaded": 20_000_000_000,
    "tags": "only-for-ratio",
    "category": "",
}

ALL_TORRENTS = [TORRENT_FRESH, TORRENT_OLD]

# A torrent that's been inactive for 150 days (older than TORRENT_OLD)
TORRENT_OLDER_STILL = {
    "name": "ancient-movie.mkv",
    "hash": "hash003",
    "last_activity": int(NOW - 150 * 86400),
    "added_on": int(NOW - 300 * 86400),
    "size": 8_000_000_000,
    "uploaded": 16_000_000_000,
    "tags": "only-for-ratio",
    "category": "",
}


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("QBIT_URL", "http://qbit:8080")
    monkeypatch.setenv("QBIT_USERNAME", "admin")
    monkeypatch.setenv("QBIT_PASSWORD", "secret")


def _make_mock_client(torrents: list[dict], login_raises=None, delete_raises=None):
    """Build a mock QBitClient instance configured for a test scenario."""
    mock_instance = MagicMock()
    mock_instance.__enter__ = MagicMock(return_value=mock_instance)
    mock_instance.__exit__ = MagicMock(return_value=False)

    if login_raises is not None:
        mock_instance.login.side_effect = login_raises
    if delete_raises is not None:
        mock_instance.delete.side_effect = delete_raises

    mock_instance.get_torrents.return_value = torrents
    return mock_instance


# ---------------------------------------------------------------------------
# Test 1: GET / — happy path: returns 200, HTML contains torrent names
# ---------------------------------------------------------------------------

def test_index_happy_path():
    mock_instance = _make_mock_client(ALL_TORRENTS)
    with patch("main.QBitClient", return_value=mock_instance):
        client = TestClient(app)
        response = client.get("/")
    assert response.status_code == 200
    assert "old-series.mkv" in response.text
    # fresh-file has 5 days inactive, filtered out at default min_days=30
    assert "fresh-file.mkv" not in response.text


# ---------------------------------------------------------------------------
# Test 2: GET /?min_days=90 — slider filter: fewer torrents shown
# ---------------------------------------------------------------------------

def test_index_min_days_filter():
    mock_instance = _make_mock_client(ALL_TORRENTS)
    with patch("main.QBitClient", return_value=mock_instance):
        client = TestClient(app)
        response = client.get("/?min_days=90")
    assert response.status_code == 200
    # old-series is 100 days inactive — passes min_days=90
    assert "old-series.mkv" in response.text
    # fresh-file is 5 days inactive — filtered out
    assert "fresh-file.mkv" not in response.text


# ---------------------------------------------------------------------------
# Test: GET / — default order: within a bucket, most-stale-first (ascending
# last_activity) — this is the ordering bug Mike spotted in v1.
# ---------------------------------------------------------------------------

def test_index_default_order_within_bucket():
    # TORRENT_OLD (100d) and TORRENT_OLDER_STILL (150d) both land in the
    # 90-180d bucket. TORRENT_OLDER_STILL has the smaller last_activity
    # (older timestamp = longer inactive) and must render first.
    mock_instance = _make_mock_client([TORRENT_OLD, TORRENT_OLDER_STILL])
    with patch("main.QBitClient", return_value=mock_instance):
        client = TestClient(app)
        response = client.get("/?min_days=30")
    assert response.status_code == 200
    assert response.text.index("ancient-movie.mkv") < response.text.index("old-series.mkv")


# ---------------------------------------------------------------------------
# Test 3: GET / — qBit unreachable: returns 200 with error banner (no 500)
# ---------------------------------------------------------------------------

def test_index_qbit_unreachable():
    mock_instance = _make_mock_client([], login_raises=ConnectionError("refused"))
    with patch("main.QBitClient", return_value=mock_instance):
        client = TestClient(app)
        response = client.get("/")
    assert response.status_code == 200
    assert "qBit unreachable" in response.text


# ---------------------------------------------------------------------------
# Test 4: DELETE /torrents/{hash} — happy path: returns 200
# ---------------------------------------------------------------------------

def test_delete_single_torrent_happy():
    mock_instance = _make_mock_client([])
    with patch("main.QBitClient", return_value=mock_instance):
        client = TestClient(app)
        response = client.delete("/torrents/hash002")
    assert response.status_code == 200
    mock_instance.delete.assert_called_once_with(["hash002"], delete_files=True)


# ---------------------------------------------------------------------------
# Test 5: DELETE /torrents/{hash} — delete fails: returns 200 with error HTML
# (HTMX only swaps on 2xx; a 500 would be silently discarded, leaving the row
#  with no feedback. We return 200 + an error <tr> so the row shows the error.)
# ---------------------------------------------------------------------------

def test_delete_single_torrent_failure():
    mock_instance = _make_mock_client([], delete_raises=RuntimeError("boom"))
    with patch("main.QBitClient", return_value=mock_instance):
        client = TestClient(app)
        response = client.delete("/torrents/hash002")
    assert response.status_code == 200
    assert "Delete failed" in response.text
    assert "hash002" in response.text


# ---------------------------------------------------------------------------
# Test 6: POST /torrents/delete — happy path: redirects to /
# ---------------------------------------------------------------------------

def test_bulk_delete_redirects():
    mock_instance = _make_mock_client([])
    with patch("main.QBitClient", return_value=mock_instance):
        client = TestClient(app, follow_redirects=False)
        response = client.post(
            "/torrents/delete",
            data={"hashes": ["hash001", "hash002"]},
        )
    assert response.status_code == 302
    assert response.headers["location"] == "/"



# ---------------------------------------------------------------------------
# Test 7: GET /api/widget — returns JSON with correct fields
# ---------------------------------------------------------------------------

def test_widget_returns_json():
    mock_instance = _make_mock_client(ALL_TORRENTS)
    with patch("main.QBitClient", return_value=mock_instance):
        client = TestClient(app)
        response = client.get("/api/widget")
    assert response.status_code == 200
    data = response.json()
    assert "cold_torrents" in data
    assert "wasted_gb" in data
    # ALL_TORRENTS has 2 torrents regardless of threshold
    assert data["cold_torrents"] == 2
    # total size = 5GB + 10GB = 15GB
    assert data["wasted_gb"] == 15.0


# ---------------------------------------------------------------------------
# Test: QBIT_TAG env var overrides the default "only-for-ratio" tag filter
# ---------------------------------------------------------------------------

def test_index_uses_qbit_tag_env_var(monkeypatch):
    monkeypatch.setenv("QBIT_TAG", "custom-tag")
    mock_instance = _make_mock_client(ALL_TORRENTS)
    with patch("main.QBitClient", return_value=mock_instance):
        client = TestClient(app)
        client.get("/")
    mock_instance.get_torrents.assert_called_once_with("custom-tag")


def test_index_default_tag_when_env_unset():
    mock_instance = _make_mock_client(ALL_TORRENTS)
    with patch("main.QBitClient", return_value=mock_instance):
        client = TestClient(app)
        client.get("/")
    mock_instance.get_torrents.assert_called_once_with("only-for-ratio")


def test_index_renders_tags_column():
    mock_instance = _make_mock_client(ALL_TORRENTS)
    with patch("main.QBitClient", return_value=mock_instance):
        client = TestClient(app)
        response = client.get("/")
    assert "<th>Tags</th>" in response.text
    assert "only-for-ratio" in response.text


# ---------------------------------------------------------------------------
# Test: page title and heading say "qBit Prunarr" (renamed from "qBit Pruner")
# ---------------------------------------------------------------------------

def test_index_title_is_prunarr():
    mock_instance = _make_mock_client(ALL_TORRENTS)
    with patch("main.QBitClient", return_value=mock_instance):
        client = TestClient(app)
        response = client.get("/")
    assert "<title>qBit Prunarr</title>" in response.text
    assert "<h1>qBit Prunarr</h1>" in response.text


# ---------------------------------------------------------------------------
# Test: Size column header is "Size (GB)" and cell shows a bare number
# (no trailing "GB" suffix, per v2 cleanup)
# ---------------------------------------------------------------------------

def test_index_size_column_format():
    mock_instance = _make_mock_client(ALL_TORRENTS)
    with patch("main.QBitClient", return_value=mock_instance):
        client = TestClient(app)
        response = client.get("/")
    assert '<th class="sortable num" data-sort="size">Size (GB)</th>' in response.text
    # TORRENT_OLD is 10_000_000_000 bytes -> 10.0 GB, rendered bare (no "GB" suffix)
    assert ">10.0<" in response.text
    assert "10.0 GB" not in response.text


# ---------------------------------------------------------------------------
# Test: sortable column headers and row data-attributes are present
# (client-side sort JS itself is verified manually in a browser - no JS
# test harness in this stack)
# ---------------------------------------------------------------------------

def test_index_sort_attributes_present():
    mock_instance = _make_mock_client(ALL_TORRENTS)
    with patch("main.QBitClient", return_value=mock_instance):
        client = TestClient(app)
        response = client.get("/")
    assert 'data-sort="name"' in response.text
    assert 'data-sort="size"' in response.text
    assert 'data-sort="inactive"' in response.text
    assert 'data-name="old-series.mkv"' in response.text
    assert 'data-size="10.0"' in response.text
    assert 'data-inactive="100"' in response.text


# ---------------------------------------------------------------------------
# Test: dark skin CSS variables are present (smoke check - full visual
# verification happens manually in a browser, see plan's final step)
# ---------------------------------------------------------------------------

def test_index_dark_skin_applied():
    mock_instance = _make_mock_client(ALL_TORRENTS)
    with patch("main.QBitClient", return_value=mock_instance):
        client = TestClient(app)
        response = client.get("/")
    assert "--bg: #1f2126" in response.text
    assert "--accent: #3ba7d9" in response.text
