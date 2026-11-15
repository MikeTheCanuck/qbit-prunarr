"""A page on another site must not be able to make your browser delete files."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from main import app, same_origin

HOST = "nas.local:8585"


@pytest.mark.parametrize(
    "headers",
    [
        {"host": HOST, "origin": "http://nas.local:8585"},
        {"host": HOST, "origin": "https://nas.local:8585"},
        {"host": HOST, "referer": "http://nas.local:8585/orphans"},
        {"host": "127.0.0.1:8585", "x-forwarded-host": "media.example.com", "origin": "https://media.example.com"},
        {"host": HOST},  # curl and scripts send neither header; CSRF needs a browser
    ],
)
def test_same_origin_requests_are_allowed(headers):
    assert same_origin(headers)


@pytest.mark.parametrize(
    "headers",
    [
        {"host": HOST, "origin": "http://evil.example"},
        {"host": HOST, "origin": "http://nas.local:9999"},
        {"host": HOST, "origin": "null"},
        {"host": HOST, "referer": "http://evil.example/page"},
        {"host": HOST, "origin": "http://evil.example", "referer": "http://nas.local:8585/"},
    ],
)
def test_cross_origin_requests_are_refused(headers):
    assert not same_origin(headers)


@pytest.mark.parametrize(
    "method,path",
    [
        ("delete", "/torrents/abc123"),
        ("post", "/torrents/delete"),
        ("delete", "/orphans/42"),
        ("post", "/orphans/delete"),
        ("post", "/orphans/groups/delete"),
        ("post", "/orphans/scan"),
    ],
)
def test_cross_origin_delete_never_reaches_a_service(method, path):
    with patch("main._get_client") as qbit:
        resp = getattr(TestClient(app), method)(path, headers={"origin": "http://evil.example"})
    assert resp.status_code == 403
    assert "another site" in resp.text
    qbit.assert_not_called()


def test_pages_still_load_from_another_site():
    with patch("main._get_client") as qbit:
        qbit.return_value.__enter__.return_value.get_torrents.return_value = []
        resp = TestClient(app).get("/orphans", headers={"origin": "http://evil.example"})
    assert resp.status_code == 200
