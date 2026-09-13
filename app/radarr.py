"""Radarr API client."""
import httpx


class RadarrClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._session = httpx.Client(headers={"X-Api-Key": api_key})

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self) -> None:
        self._session.close()

    def get_all_movie_paths(self) -> set[str]:
        """Return every movie file path Radarr currently tracks."""
        resp = self._session.get(f"{self._base_url}/api/v3/movie")
        resp.raise_for_status()

        paths: set[str] = set()
        for movie in resp.json():
            movie_file = movie.get("movieFile")
            if movie_file and movie_file.get("path"):
                paths.add(movie_file["path"])
        return paths
