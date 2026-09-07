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


def _total_size(data_root: str, paths: list[str]) -> int:
    total = 0
    for p in paths:
        try:
            total += os.path.getsize(os.path.join(data_root, p))
        except OSError:
            pass
    return total


def classify_download_orphans(result, data_root: str, qbit_paths: set[str] | None) -> list[OrphanCandidate]:
    """Flag download-side files with no active torrent referencing them."""
    if qbit_paths is None:
        return []
    candidates = []
    for inode, paths in result.download_only.items():
        if not any(p in qbit_paths for p in paths):
            candidates.append(
                OrphanCandidate(
                    inode=inode,
                    paths=paths,
                    category="unlinked download",
                    size_bytes=_total_size(data_root, paths),
                )
            )
    return candidates


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
        is_tv = any(
            p.startswith(tv_subdir + os.sep)
            for p in paths
            for tv_subdir in tv_subdirs
        )
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
                    size_bytes=_total_size(data_root, paths),
                )
            )
    return candidates
