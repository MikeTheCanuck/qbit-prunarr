"""Roll Unlinked Downloads candidates up into per-directory groups.

Classification is per-inode, so one orphaned torrent that happens to be a
raw disc rip fragments into hundreds of rows. qBittorrent has already
forgotten the torrent by the time its files are orphans, so there's no
torrent name left to group by - grouping is inferred purely from directory
structure: a directory rolls up only if every file the scan found under
it is an orphan candidate. A group root is also never a direct child of a
scan boundary (`torrents`, `usenet`) - directories like `torrents/incoming`
or `usenet/complete` are download-client structure, not a torrent's own
folder, even if everything under them happens to be orphaned.
"""
import os
from dataclasses import dataclass

from orphans import OrphanCandidate


@dataclass
class OrphanGroup:
    root: str
    members: list[OrphanCandidate]

    @property
    def size_bytes(self) -> int:
        return sum(m.size_bytes for m in self.members)


def _ancestors(path: str):
    """Every ancestor directory of path, nearest first, excluding ""."""
    current = os.path.dirname(path)
    while current:
        yield current
        current = os.path.dirname(current)


def _group_root(path: str, blocked: set[str], boundaries: set[str]) -> str | None:
    """Topmost directory above `path` that contains nothing but orphans,
    strictly inside a boundary, and never a direct child of a boundary.
    None if the immediate parent is already blocked, or the path isn't
    under any boundary at all.

    A directory directly under a boundary (`torrents/incoming`,
    `usenet/complete`) is download-client structure, not a torrent's own
    folder, so it can never be assigned as a root - the climb stops one
    level short of it, keeping whatever root (possibly None) was found
    below."""
    root = None
    for directory in _ancestors(path):
        if directory in boundaries:
            return root
        if os.path.dirname(directory) in boundaries:
            return root
        if directory in blocked:
            # Still have to confirm the path lives under a boundary before
            # trusting `root`.
            return root if any(a in boundaries for a in _ancestors(directory)) else None
        root = directory
    return None


def group_download_orphans(
    candidates: list[OrphanCandidate],
    download_files: list[str],
    boundaries: set[str],
) -> tuple[list[OrphanGroup], list[OrphanCandidate]]:
    """Split candidates into (groups, standalone).

    `download_files` is every file the scan found under the download
    roots, orphaned or not - the ground truth a directory's contents get
    checked against. Any directory that is an ancestor of a non-orphan
    file is "blocked" and can never be (or sit inside) a group root.
    Marking ancestors of each non-orphan once makes every later check a
    set lookup, so a 300-file tree costs O(files x depth), not more.

    A candidate joins a group only if every one of its hardlink paths
    rolls up to the same root - otherwise deleting "this folder" would
    also delete a name for the file that lives somewhere else. A root
    that ends up with a single member is returned as standalone: a
    one-file group is just the same row with an extra toggle.
    """
    orphan_paths = {p for c in candidates for p in c.paths}
    blocked: set[str] = set()
    for f in download_files:
        if f not in orphan_paths:
            blocked.update(_ancestors(f))

    by_root: dict[str, list[OrphanCandidate]] = {}
    standalone: list[OrphanCandidate] = []
    for c in candidates:
        roots = {_group_root(p, blocked, boundaries) for p in c.paths}
        if len(roots) == 1 and None not in roots:
            by_root.setdefault(roots.pop(), []).append(c)
        else:
            standalone.append(c)

    groups: list[OrphanGroup] = []
    for root, members in by_root.items():
        if len(members) < 2:
            standalone.extend(members)
        else:
            members.sort(key=lambda m: m.size_bytes, reverse=True)
            groups.append(OrphanGroup(root=root, members=members))
    return groups, standalone
