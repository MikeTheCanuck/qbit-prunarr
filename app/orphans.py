"""Orphan classification: cross-reference scan results against external APIs.

Every classification function here takes already-normalized path sets
(prefix-stripped via pathmap.to_relative, relative to data_root) and does
no I/O of its own besides os.path.getsize for reporting size. Fail-closed
is enforced here: a None set (meaning "that API was unreachable or not
configured") means nothing in that category is ever flagged as an orphan.
"""
import os
from dataclasses import dataclass


@dataclass
class OrphanCandidate:
    inode: int
    paths: list[str]
    category: str
    size_bytes: int


def _file_size(data_root: str, paths: list[str]) -> int:
    """Size of the single file this candidate's paths all point at.

    Every path in an OrphanCandidate is a hardlink to the SAME inode, so
    the space a delete reclaims is one file's size — summing across paths
    reports a 50GB movie with two links as 100GB, which is exactly the
    number this tool exists to get right during a space crunch.
    """
    for p in paths:
        try:
            return os.path.getsize(os.path.join(data_root, p))
        except OSError:
            continue
    return 0


def path_tracked(path: str, tracked: set[str]) -> bool:
    """True if `path` is equal to, or nested inside, any entry in `tracked`.

    qBittorrent's `content_path` is "root path for multifile torrents,
    absolute file path for singlefile torrents" — so a season pack reports
    one DIRECTORY while the filesystem scan reports each file inside it.
    Exact-match membership would flag every file of every multi-file torrent
    as an orphan while it's still actively seeding, so containment has to be
    checked by walking `path`'s ancestors rather than comparing strings.

    Walking ancestors (rather than testing `startswith` against every
    tracked entry) keeps this O(depth) instead of O(len(tracked)), and it
    can't produce the classic `startswith` false positive where
    "torrents/Pack2/a.mkv" looks like it lives under "torrents/Pack".

    A tracked entry of "" (a service's content_path normalizing to the
    shared root itself, e.g. via a wrong-but-exact `*_PATH_PREFIX` or a
    "no subfolder" single-file torrent) has to match every path — every
    ancestor chain terminates at "" — deliberately, since the alternative
    is a live-seeding file's own root-level entry never matching and
    getting deleted as a false-positive orphan. That means such an entry
    disables orphan detection for the whole subtree rather than just its
    one file; failing toward "detect nothing" instead of "delete
    something live" is the same fail-closed direction this module already
    takes everywhere else.
    """
    current = path
    while True:
        if current in tracked or (current and current + "/" in tracked):
            return True
        if not current:
            return False
        parent = os.path.dirname(current)
        current = parent if parent != current else ""


def classify_download_orphans(result, data_root: str, qbit_paths: set[str] | None) -> list[OrphanCandidate]:
    """Flag download-side files with no active torrent referencing them."""
    if qbit_paths is None:
        return []
    candidates = []
    for inode, paths in result.download_only.items():
        if not any(path_tracked(p, qbit_paths) for p in paths):
            candidates.append(
                OrphanCandidate(
                    inode=inode,
                    paths=paths,
                    category="unlinked download",
                    size_bytes=_file_size(data_root, paths),
                )
            )
    return candidates


def is_tv_path(path: str, tv_subdirs: set[str]) -> bool:
    """True if `path` lives under one of `tv_subdirs` (vs. a movie subdir).

    The single shared TV/movie test — main.py's per-service overlap check
    needs the same routing decision classify_media_orphans makes below, and
    two independent copies previously used different separators (this
    module's `os.sep` vs. main.py's hardcoded "/"), which agree only
    because this deployment is POSIX-only; a shared function makes that
    agreement structural instead of coincidental.
    """
    return any(path == sub or path.startswith(sub + "/") for sub in tv_subdirs)


def classify_media_orphans(
    result,
    data_root: str,
    tv_subdirs: set[str],
    sonarr_paths: set[str] | None,
    radarr_paths: set[str] | None,
    plex_episode_paths: set[str] | None,
    plex_movie_paths: set[str] | None,
) -> list[OrphanCandidate]:
    """Flag media-side files missing from EITHER the relevant *arr or Plex.

    A file counts as still-valid only if it's confirmed by both the
    relevant *arr (Sonarr for TV, Radarr for movies) AND Plex. Either
    source being unreachable means every file that would need it is left
    alone (fail closed), not flagged.
    """
    candidates = []
    for inode, paths in result.media_only.items():
        is_tv = any(is_tv_path(p, tv_subdirs) for p in paths)
        arr_paths = sonarr_paths if is_tv else radarr_paths
        plex_paths = plex_episode_paths if is_tv else plex_movie_paths
        if arr_paths is None or plex_paths is None:
            continue
        confirmed = any(p in arr_paths and p in plex_paths for p in paths)
        if not confirmed:
            candidates.append(
                OrphanCandidate(
                    inode=inode,
                    paths=paths,
                    category="orphaned media",
                    size_bytes=_file_size(data_root, paths),
                )
            )
    return candidates


def delete_orphan(data_root: str, relative_path: str, boundary: str) -> None:
    """Delete an orphan file, pruning now-empty parent dirs up to `boundary`.

    `boundary` is the configured scan subdir (relative to data_root) that
    this file lives under — "torrents", "media/movies", etc. Pruning stops
    AT that directory and never removes or climbs above it.

    The boundary has to be passed in rather than inferred from depth below
    data_root: the media scan roots sit two levels down ("media/movies"),
    so a "stop at a direct child of data_root" rule prunes right through
    "media/movies" itself and leaves Radarr with a missing root folder.

    Raises ValueError if relative_path does not actually live under
    boundary — a mismatched pair means the caller lost track of which root
    this file came from, and guessing there would delete the wrong tree.
    """
    boundary_rel = boundary.strip("/")
    path_rel = relative_path.strip("/")
    if not boundary_rel or not (
        path_rel == boundary_rel or path_rel.startswith(boundary_rel + "/")
    ):
        raise ValueError(
            f"refusing to delete {relative_path!r}: not under boundary {boundary!r}"
        )

    full_path = os.path.join(data_root, relative_path)
    boundary_abs = os.path.abspath(os.path.join(data_root, boundary_rel))

    os.remove(full_path)

    parent = os.path.abspath(os.path.dirname(full_path))
    while parent != boundary_abs and parent.startswith(boundary_abs + os.sep):
        try:
            os.rmdir(parent)
        except OSError:
            break
        parent = os.path.dirname(parent)
