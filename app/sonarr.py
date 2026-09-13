"""Sonarr API client."""
import httpx


class SonarrClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._session = httpx.Client(headers={"X-Api-Key": api_key})

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self) -> None:
        self._session.close()

    def get_all_episode_paths(self) -> set[str]:
        """Return every episode file path Sonarr currently tracks, across all series."""
        series_resp = self._session.get(f"{self._base_url}/api/v3/series")
        series_resp.raise_for_status()

        paths: set[str] = set()
        for series in series_resp.json():
            files_resp = self._session.get(
                f"{self._base_url}/api/v3/episodefile",
                params={"seriesId": series["id"]},
            )
            files_resp.raise_for_status()
            for f in files_resp.json():
                paths.add(f["path"])
        return paths
