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

    def get_all_queue_paths(self) -> set[str]:
        """Return the output path of every item currently in Radarr's queue.

        Covers downloads Radarr still considers active — including ones
        stuck "unable to import automatically" — so a download-side orphan
        check doesn't delete a file Radarr is still trying to get into the
        library just because qBittorrent no longer has an entry for it.
        Items with no output path yet (still downloading) contribute
        nothing, since there's no file on disk yet to protect.
        """
        paths: set[str] = set()
        page = 1
        page_size = 250
        while True:
            resp = self._session.get(
                f"{self._base_url}/api/v3/queue",
                params={"page": page, "pageSize": page_size},
            )
            resp.raise_for_status()
            data = resp.json()
            for record in data.get("records", []):
                output_path = record.get("outputPath")
                if output_path:
                    paths.add(output_path)
            if page * page_size >= data.get("totalRecords", 0):
                break
            page += 1
        return paths
