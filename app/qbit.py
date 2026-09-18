"""qBittorrent API client."""
import httpx


class QBitClient:
    def __init__(self, base_url: str, username: str, password: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._session = httpx.Client()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP session to release connection pools."""
        self._session.close()

    def login(self) -> None:
        """Authenticate with qBittorrent. Raises ValueError on auth failure."""
        response = self._session.post(
            f"{self._base_url}/api/v2/auth/login",
            data={"username": self._username, "password": self._password},
        )
        response.raise_for_status()
        if response.text != "Ok.":
            raise ValueError("qBit auth failed")

    def get_torrents(self, tag: str) -> list[dict]:
        """Return all torrents matching the given tag."""
        response = self._session.get(
            f"{self._base_url}/api/v2/torrents/info",
            params={"tag": tag},
        )
        response.raise_for_status()
        return response.json()

    def delete(self, hashes: list[str], delete_files: bool = True) -> None:
        """Delete torrents by hash list. Optionally remove data files."""
        response = self._session.post(
            f"{self._base_url}/api/v2/torrents/delete",
            data={
                "hashes": "|".join(hashes),
                "deleteFiles": "true" if delete_files else "false",
            },
        )
        response.raise_for_status()

    def get_all_content_paths(self) -> set[str]:
        """Return content_path for every torrent qBittorrent currently knows about."""
        response = self._session.get(f"{self._base_url}/api/v2/torrents/info")
        response.raise_for_status()
        return {t["content_path"] for t in response.json() if t.get("content_path")}
