"""Plex API client."""
import httpx


class PlexClient:
    def __init__(self, base_url: str, token: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._session = httpx.Client(
            headers={"X-Plex-Token": token, "Accept": "application/json"}
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self) -> None:
        self._session.close()

    def _file_paths_for_section(self, section_key: str, item_type: int) -> set[str]:
        resp = self._session.get(
            f"{self._base_url}/library/sections/{section_key}/all",
            params={"type": item_type},
        )
        resp.raise_for_status()
        paths: set[str] = set()
        for item in resp.json()["MediaContainer"].get("Metadata", []):
            for media in item.get("Media", []):
                for part in media.get("Part", []):
                    if part.get("file"):
                        paths.add(part["file"])
        return paths

    def _sections_of_type(self, section_type: str) -> list[str]:
        resp = self._session.get(f"{self._base_url}/library/sections")
        resp.raise_for_status()
        directories = resp.json()["MediaContainer"].get("Directory", [])
        return [d["key"] for d in directories if d.get("type") == section_type]

    def get_all_movie_paths(self) -> set[str]:
        """Return every file path Plex has indexed across all movie libraries."""
        paths: set[str] = set()
        for key in self._sections_of_type("movie"):
            paths |= self._file_paths_for_section(key, item_type=1)
        return paths

    def get_all_episode_paths(self) -> set[str]:
        """Return every file path Plex has indexed across all TV show libraries."""
        paths: set[str] = set()
        for key in self._sections_of_type("show"):
            paths |= self._file_paths_for_section(key, item_type=4)
        return paths
