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
