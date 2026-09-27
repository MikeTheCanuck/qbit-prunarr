"""Tests for RadarrClient."""
import pytest
from pytest_httpx import HTTPXMock

from radarr import RadarrClient

BASE_URL = "http://radarr:7878"


@pytest.fixture
def client():
    return RadarrClient(base_url=BASE_URL, api_key="key456")


def test_get_all_movie_paths(client: RadarrClient, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}/api/v3/movie",
        json=[
            {"id": 1, "title": "Movie A", "hasFile": True, "movieFile": {"path": "/movies/Movie A/a.mkv"}},
            {"id": 2, "title": "Movie B", "hasFile": False},
        ],
    )

    paths = client.get_all_movie_paths()

    assert paths == {"/movies/Movie A/a.mkv"}


def test_get_all_movie_paths_empty_library(client: RadarrClient, httpx_mock: HTTPXMock):
    httpx_mock.add_response(method="GET", url=f"{BASE_URL}/api/v3/movie", json=[])

    assert client.get_all_movie_paths() == set()


def test_sends_api_key_header(client: RadarrClient, httpx_mock: HTTPXMock):
    httpx_mock.add_response(method="GET", url=f"{BASE_URL}/api/v3/movie", json=[])
    client.get_all_movie_paths()

    request = httpx_mock.get_requests()[0]
    assert request.headers["x-api-key"] == "key456"


def test_get_all_queue_paths_single_page(client: RadarrClient, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}/api/v3/queue?page=1&pageSize=250",
        json={
            "page": 1,
            "pageSize": 250,
            "totalRecords": 2,
            "records": [
                {"id": 1, "outputPath": "/movies/Movie A/a.mkv"},
                {"id": 2, "outputPath": "/movies/Movie B/b.mkv"},
            ],
        },
    )

    assert client.get_all_queue_paths() == {"/movies/Movie A/a.mkv", "/movies/Movie B/b.mkv"}


def test_get_all_queue_paths_skips_records_with_no_output_path(client: RadarrClient, httpx_mock: HTTPXMock):
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


def test_get_all_queue_paths_empty_queue(client: RadarrClient, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}/api/v3/queue?page=1&pageSize=250",
        json={"page": 1, "pageSize": 250, "totalRecords": 0, "records": []},
    )

    assert client.get_all_queue_paths() == set()


def test_get_all_queue_paths_follows_pagination(client: RadarrClient, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}/api/v3/queue?page=1&pageSize=250",
        json={
            "page": 1,
            "pageSize": 250,
            "totalRecords": 251,
            "records": [{"id": i, "outputPath": f"/movies/m{i}.mkv"} for i in range(250)],
        },
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}/api/v3/queue?page=2&pageSize=250",
        json={
            "page": 2,
            "pageSize": 250,
            "totalRecords": 251,
            "records": [{"id": 250, "outputPath": "/movies/m250.mkv"}],
        },
    )

    paths = client.get_all_queue_paths()

    assert len(paths) == 251
    assert "/movies/m0.mkv" in paths
    assert "/movies/m250.mkv" in paths
