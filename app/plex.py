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

    def _files_for_section(self, section_key: str, item_type: int) -> dict[str, list[str]]:
        """file path -> rating keys of the items whose extras could sit
        beside it: the movie itself, or an episode's show and season."""
        resp = self._session.get(
            f"{self._base_url}/library/sections/{section_key}/all",
            params={"type": item_type},
        )
        resp.raise_for_status()
        files: dict[str, list[str]] = {}
        for item in resp.json()["MediaContainer"].get("Metadata", []):
            keys = [
                k for k in (item.get("ratingKey") if item_type == 1 else None,
                            item.get("grandparentRatingKey"), item.get("parentRatingKey"))
                if k
            ]
            for media in item.get("Media", []):
                for part in media.get("Part", []):
                    if part.get("file"):
                        files[part["file"]] = keys
        return files

    def _sections_of_type(self, section_type: str) -> list[str]:
        resp = self._session.get(f"{self._base_url}/library/sections")
        resp.raise_for_status()
        directories = resp.json()["MediaContainer"].get("Directory", [])
        return [d["key"] for d in directories if d.get("type") == section_type]

    def get_movie_files(self) -> dict[str, list[str]]:
        """Every file Plex has indexed across all movie libraries, with its movie's rating key."""
        files: dict[str, list[str]] = {}
        for key in self._sections_of_type("movie"):
            files |= self._files_for_section(key, item_type=1)
        return files

    def get_episode_files(self) -> dict[str, list[str]]:
        """Every file Plex has indexed across all TV libraries, with its show's and season's rating keys."""
        files: dict[str, list[str]] = {}
        for key in self._sections_of_type("show"):
            files |= self._files_for_section(key, item_type=4)
        return files

    def get_all_movie_paths(self) -> set[str]:
        """Return every file path Plex has indexed across all movie libraries."""
        return set(self.get_movie_files())

    def get_all_episode_paths(self) -> set[str]:
        """Return every file path Plex has indexed across all TV show libraries."""
        return set(self.get_episode_files())

    def get_extra_paths(self, rating_keys: set[str]) -> set[str]:
        """Files Plex has attached as local extras to these items.

        The library listing only ever returns main movies and episodes, so
        a correctly named Featurettes/ file never shows up there. Plex
        mixes online trailers into the same extras list; those have no
        file and are skipped. One request per key, so callers pass only
        the items that actually have something to confirm.
        """
        paths: set[str] = set()
        for key in sorted(rating_keys):
            resp = self._session.get(f"{self._base_url}/library/metadata/{key}/extras")
            resp.raise_for_status()
            for item in resp.json()["MediaContainer"].get("Metadata", []):
                for media in item.get("Media", []):
                    for part in media.get("Part", []):
                        if part.get("file"):
                            paths.add(part["file"])
        return paths
