"""Tests for PlexClient."""
import pytest
from pytest_httpx import HTTPXMock

from plex import PlexClient

BASE_URL = "http://plex:32400"


@pytest.fixture
def client():
    return PlexClient(base_url=BASE_URL, token="tok789")


def _sections_response(directories):
    return {"MediaContainer": {"Directory": directories}}


def _items_response(items):
    return {"MediaContainer": {"Metadata": items}}


def test_get_all_movie_paths(client: PlexClient, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}/library/sections",
        json=_sections_response([
            {"key": "1", "type": "movie", "title": "Movies"},
            {"key": "2", "type": "show", "title": "TV"},
        ]),
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}/library/sections/1/all?type=1",
        json=_items_response([
            {"title": "Movie A", "Media": [{"Part": [{"file": "/movies/a.mkv"}]}]},
        ]),
    )

    paths = client.get_all_movie_paths()

    assert paths == {"/movies/a.mkv"}


def test_get_all_episode_paths(client: PlexClient, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}/library/sections",
        json=_sections_response([
            {"key": "1", "type": "movie", "title": "Movies"},
            {"key": "2", "type": "show", "title": "TV"},
        ]),
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}/library/sections/2/all?type=4",
        json=_items_response([
            {"title": "Ep1", "Media": [{"Part": [{"file": "/tv/Show/ep1.mkv"}]}]},
            {"title": "Ep2", "Media": [{"Part": [{"file": "/tv/Show/ep2.mkv"}]}]},
        ]),
    )

    paths = client.get_all_episode_paths()

    assert paths == {"/tv/Show/ep1.mkv", "/tv/Show/ep2.mkv"}


def test_no_libraries_returns_empty(client: PlexClient, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET", url=f"{BASE_URL}/library/sections", json=_sections_response([])
    )

    assert client.get_all_movie_paths() == set()


def test_sends_plex_token_header(client: PlexClient, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET", url=f"{BASE_URL}/library/sections", json=_sections_response([])
    )
    client.get_all_movie_paths()

    request = httpx_mock.get_requests()[0]
    assert request.headers["x-plex-token"] == "tok789"
