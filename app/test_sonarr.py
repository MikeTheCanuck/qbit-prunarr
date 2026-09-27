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


def test_get_all_queue_paths_single_page(client: SonarrClient, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}/api/v3/queue?page=1&pageSize=250",
        json={
            "page": 1,
            "pageSize": 250,
            "totalRecords": 2,
            "records": [
                {"id": 1, "outputPath": "/tv/Show/ep1.mkv"},
                {"id": 2, "outputPath": "/tv/Show/ep2.mkv"},
            ],
        },
    )

    assert client.get_all_queue_paths() == {"/tv/Show/ep1.mkv", "/tv/Show/ep2.mkv"}


def test_get_all_queue_paths_skips_records_with_no_output_path(client: SonarrClient, httpx_mock: HTTPXMock):
    """Still-downloading items have no output path yet - there's no file
    on disk yet for a download-orphan check to need protecting."""
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}/api/v3/queue?page=1&pageSize=250",
        json={
            "page": 1,
            "pageSize": 250,
            "totalRecords": 1,
            "records": [{"id": 1, "outputPath": None}],
        },
    )

    assert client.get_all_queue_paths() == set()


def test_get_all_queue_paths_empty_queue(client: SonarrClient, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}/api/v3/queue?page=1&pageSize=250",
        json={"page": 1, "pageSize": 250, "totalRecords": 0, "records": []},
    )

    assert client.get_all_queue_paths() == set()


def test_get_all_queue_paths_follows_pagination(client: SonarrClient, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}/api/v3/queue?page=1&pageSize=250",
        json={
            "page": 1,
            "pageSize": 250,
            "totalRecords": 251,
            "records": [{"id": i, "outputPath": f"/tv/ep{i}.mkv"} for i in range(250)],
        },
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}/api/v3/queue?page=2&pageSize=250",
        json={
            "page": 2,
            "pageSize": 250,
            "totalRecords": 251,
            "records": [{"id": 250, "outputPath": "/tv/ep250.mkv"}],
        },
    )

    paths = client.get_all_queue_paths()

    assert len(paths) == 251
    assert "/tv/ep0.mkv" in paths
    assert "/tv/ep250.mkv" in paths
