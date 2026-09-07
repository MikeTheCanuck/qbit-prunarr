"""Path-prefix normalization for comparing paths across containers.

Different containers can be bind-mounted to the same underlying files at
different mount points (e.g. qBittorrent sees "/downloads/completed/x.mkv"
for a file this app sees as "/data/torrents/completed/x.mkv"). Stripping
each service's own prefix makes paths comparable regardless of mount point.
"""


def to_relative(raw_path: str, prefix: str) -> str:
    """Strip prefix from raw_path, returning a path relative to the shared root."""
    prefix = prefix.rstrip("/")
    if prefix and raw_path == prefix:
        return ""
    if prefix and raw_path.startswith(prefix + "/"):
        return raw_path[len(prefix) + 1 :]
    return raw_path.lstrip("/")
