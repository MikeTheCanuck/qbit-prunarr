"""Tests for SonarrClient."""
import pytest
from pytest_httpx import HTTPXMock

from sonarr import SonarrClient

BASE_URL = "http://sonarr:8989"


@pytest.fixture
def client():
    return SonarrClient(base_url=BASE_URL, api_key="key123")


def test_get_all_episode_paths_across_series(client: SonarrClient, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}/api/v3/series",
        json=[{"id": 1, "title": "Show A"}, {"id": 2, "title": "Show B"}],
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}/api/v3/episodefile?seriesId=1",
        json=[{"id": 10, "path": "/tv/Show A/ep1.mkv"}],
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}/api/v3/episodefile?seriesId=2",
        json=[{"id": 20, "path": "/tv/Show B/ep1.mkv"}, {"id": 21, "path": "/tv/Show B/ep2.mkv"}],
    )

    paths = client.get_all_episode_paths()

    assert paths == {"/tv/Show A/ep1.mkv", "/tv/Show B/ep1.mkv", "/tv/Show B/ep2.mkv"}


def test_get_all_episode_paths_no_series_returns_empty(client: SonarrClient, httpx_mock: HTTPXMock):
    httpx_mock.add_response(method="GET", url=f"{BASE_URL}/api/v3/series", json=[])

    assert client.get_all_episode_paths() == set()


def test_sends_api_key_header(client: SonarrClient, httpx_mock: HTTPXMock):
    httpx_mock.add_response(method="GET", url=f"{BASE_URL}/api/v3/series", json=[])
    client.get_all_episode_paths()

    request = httpx_mock.get_requests()[0]
    assert request.headers["x-api-key"] == "key123"
