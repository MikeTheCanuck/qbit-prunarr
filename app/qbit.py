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
        """Return every path qBittorrent currently owns: each torrent's
        content_path, plus the libtorrent part file it keeps beside it.

        libtorrent writes skipped/partial pieces to
        <save_path>/.<infohash>.parts, a file qBit never reports as content.
        Without these, every active torrent's part file shows up as an
        orphan. The infohash used is libtorrent's get_best(): v2 truncated to
        40 hex chars for hybrid/v2 torrents, else v1. Rather than guess which
        one qBit's `hash` field reflects, include every candidate. Extra
        paths can only protect more files, never flag more for deletion.
        """
        response = self._session.get(f"{self._base_url}/api/v2/torrents/info")
        response.raise_for_status()
        paths = set()
        for t in response.json():
            if t.get("content_path"):
                paths.add(t["content_path"])
            hashes = {h for h in (t.get("hash"), t.get("infohash_v1"), (t.get("infohash_v2") or "")[:40]) if h}
            # While a torrent is incomplete with a temp folder enabled, its
            # files (and part file) live under download_path instead.
            dirs = {d.rstrip("/") for d in (t.get("save_path"), t.get("download_path")) if d}
            paths.update(f"{d}/.{h}.parts" for d in dirs for h in hashes)
        return paths
