"""Inode-based hardlink scanning.

Files hardlinked between media/ and torrents/usenet/ share an inode
number even though their filenames don't match (release-name vs.
media-server-name conventions differ). Grouping by inode is the only
reliable way to tell a linked file from an orphan.
"""
import os
from dataclasses import dataclass, field


@dataclass
class ScanResult:
    linked: set[str] = field(default_factory=set)
    media_only: dict[int, list[str]] = field(default_factory=dict)
    download_only: dict[int, list[str]] = field(default_factory=dict)


def _walk_inodes(root: str) -> dict[int, list[str]]:
    """Walk a directory tree, return inode -> list of paths relative to root."""
    result: dict[int, list[str]] = {}
    if not os.path.isdir(root):
        return result
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            full = os.path.join(dirpath, name)
            try:
                st = os.stat(full)
            except OSError:
                continue
            rel = os.path.relpath(full, root)
            result.setdefault(st.st_ino, []).append(rel)
    return result


def scan(data_root: str, media_subdirs: list[str], download_subdirs: list[str]) -> ScanResult:
    """Scan media and download subtrees under data_root, classify each inode."""
    media_inodes: dict[int, list[str]] = {}
    for sub in media_subdirs:
        for inode, paths in _walk_inodes(os.path.join(data_root, sub)).items():
            media_inodes.setdefault(inode, []).extend(
                os.path.join(sub, p) for p in paths
            )

    download_inodes: dict[int, list[str]] = {}
    for sub in download_subdirs:
        for inode, paths in _walk_inodes(os.path.join(data_root, sub)).items():
            download_inodes.setdefault(inode, []).extend(
                os.path.join(sub, p) for p in paths
            )

    result = ScanResult()
    for inode in set(media_inodes) | set(download_inodes):
        in_media = inode in media_inodes
        in_download = inode in download_inodes
        if in_media and in_download:
            result.linked.update(media_inodes[inode])
            result.linked.update(download_inodes[inode])
        elif in_media:
            result.media_only[inode] = media_inodes[inode]
        elif in_download:
            result.download_only[inode] = download_inodes[inode]
    return result
