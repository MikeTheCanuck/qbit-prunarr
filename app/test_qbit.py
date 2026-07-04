"""Tests for QBitClient using pytest-httpx."""
import pytest
import httpx
from pytest_httpx import HTTPXMock

from qbit import QBitClient

BASE_URL = "http://qbit:8080"


@pytest.fixture
def client():
    return QBitClient(base_url=BASE_URL, username="admin", password="secret")


# ---------------------------------------------------------------------------
# Test 1: login() — success path
# ---------------------------------------------------------------------------

def test_login_success(client: QBitClient, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE_URL}/api/v2/auth/login",
        text="Ok.",
    )
    # Should not raise
    client.login()


# ---------------------------------------------------------------------------
# Test 2: login() — failure path
# ---------------------------------------------------------------------------

def test_login_failure_raises(client: QBitClient, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE_URL}/api/v2/auth/login",
        text="Fails.",
    )
    with pytest.raises(ValueError, match="qBit auth failed"):
        client.login()


# ---------------------------------------------------------------------------
# Test 3: get_torrents() — returns parsed JSON list
# ---------------------------------------------------------------------------

def test_get_torrents_returns_list(client: QBitClient, httpx_mock: HTTPXMock):
    tag = "cold"
    sample = [
        {
            "name": "Ubuntu.iso",
            "hash": "abc123",
            "tags": "cold",
            "category": "linux",
            "size": 1024,
            "uploaded": 2048,
            "last_activity": 1700000000,
            "added_on": 1690000000,
        }
    ]
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}/api/v2/torrents/info?tag={tag}",
        json=sample,
    )
    result = client.get_torrents(tag)
    assert result == sample
    assert result[0]["name"] == "Ubuntu.iso"


# ---------------------------------------------------------------------------
# Test 4: delete() — sends correct body
# ---------------------------------------------------------------------------

def test_delete_sends_correct_body(client: QBitClient, httpx_mock: HTTPXMock):
    hashes = ["abc123", "def456", "ghi789"]
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE_URL}/api/v2/torrents/delete",
        status_code=200,
    )
    client.delete(hashes, delete_files=True)

    # Verify the request body
    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    body = requests[0].content.decode()
    assert "hashes=abc123%7Cdef456%7Cghi789" in body or "hashes=abc123|def456|ghi789" in body
    assert "deleteFiles=true" in body


# ---------------------------------------------------------------------------
# Test 5: context manager and close() work correctly
# ---------------------------------------------------------------------------

def test_context_manager_closes_session(client: QBitClient):
    """Verify that using client as context manager calls close()."""
    with client:
        # Session should be open
        assert not client._session.is_closed
    # After exiting context, session should be closed
    assert client._session.is_closed


def test_close_method_closes_session(client: QBitClient):
    """Verify that close() closes the session."""
    assert not client._session.is_closed
    client.close()
    assert client._session.is_closed
