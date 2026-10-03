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
    # Set when Radarr tracks a different file in this same movie folder:
    # this one is very likely an older copy the newer import left behind.
    superseded_by: str | None = None
    # Radarr's tracked file for this movie is a sample clip, so this
    # untracked file is likely the real movie Radarr missed.
    tracks_sample: bool = False


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


def classify_download_orphans(
    result, data_root: str, qbit_paths: set[str] | None, arr_queue_paths: set[str] | None
) -> list[OrphanCandidate]:
    """Flag download-side files with no active torrent referencing them.

    qBittorrent isn't the only thing that can still want a download-side
    file: Sonarr/Radarr keep their own queue of downloads they consider
    active, including ones stuck "unable to import automatically" (a
    title-mismatch failure) — the file is real and still wanted, but
    nothing has hardlinked it into media/ yet, and depending on the
    *arr app's "remove completed downloads" setting the qBittorrent entry
    for it can already be gone. Checking only qbit_paths would flag that
    file as a safe bulk-delete candidate. arr_queue_paths is the same
    fail-closed shape as qbit_paths: None means that signal is unusable
    (unreachable, or not configured), so nothing in this category is
    flagged rather than risk deleting a file either side still wants.
    """
    if qbit_paths is None or arr_queue_paths is None:
        return []
    candidates = []
    for inode, paths in result.download_only.items():
        if any(path_tracked(p, qbit_paths) for p in paths):
            continue
        if any(path_tracked(p, arr_queue_paths) for p in paths):
            continue
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


_VIDEO_EXTENSIONS = {
    ".mkv", ".mp4", ".avi", ".m4v", ".ts", ".m2ts", ".wmv",
    ".mov", ".mpg", ".mpeg", ".flv", ".webm", ".iso",
}


def _is_media_review_candidate(paths: list[str]) -> bool:
    """False for files that were never going to match Sonarr/Radarr's own
    file list, so flagging them as "needs review" would be a permanent,
    unfixable false positive rather than a real signal.

    Sonarr/Radarr's APIs report only the primary video file per episode
    or movie — never subtitle sidecars (.srt/.sub), NFO metadata, or
    artwork sitting next to it, so a companion file next to a perfectly
    tracked episode would otherwise fail this check forever, no matter
    how correctly it's organized. A "Sample" directory is a scene-release
    convention (a short preview clip bundled with a torrent to check
    quality before committing to the real download) that no *arr app or
    Plex tracks as real content either.
    """
    if any(seg.lower() == "sample" for seg in paths[0].split("/")):
        return False
    return any(os.path.splitext(p)[1].lower() in _VIDEO_EXTENSIONS for p in paths)


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
        if not _is_media_review_candidate(paths):
            continue
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


def prune_empty_tree(data_root: str, root_rel: str, boundary: str) -> None:
    """Remove every empty directory at or under `root_rel`, then prune
    now-empty parents up to (never including) `boundary`.

    Group delete needs this on top of delete_orphan's own per-file
    pruning: that only climbs from each deleted file's parent, so a
    directory that never held a file (disc rips ship empty AUXDATA/,
    BDJO/, META/) is never visited and keeps the group root alive as an
    empty shell. rmdir only ever succeeds on an empty directory, so a
    file that failed to delete keeps its whole ancestor chain in place.
    """
    boundary_rel = boundary.strip("/")
    root_rel = root_rel.strip("/")
    if not boundary_rel or not root_rel.startswith(boundary_rel + "/"):
        raise ValueError(
            f"refusing to prune {root_rel!r}: not strictly under boundary {boundary!r}"
        )

    root_abs = os.path.abspath(os.path.join(data_root, root_rel))
    boundary_abs = os.path.abspath(os.path.join(data_root, boundary_rel))

    for dirpath, _dirnames, _filenames in os.walk(root_abs, topdown=False):
        try:
            os.rmdir(dirpath)
        except OSError:
            pass

    parent = os.path.dirname(root_abs)
    while parent != boundary_abs and parent.startswith(boundary_abs + os.sep):
        try:
            os.rmdir(parent)
        except OSError:
            break
        parent = os.path.dirname(parent)


def _title_folder(path: str) -> str:
    """media/movies/<Title>/... -> media/movies/<Title>. The movie (or show)
    folder is what a file belongs to, however deep it sits inside."""
    parts = path.split("/")
    return "/".join(parts[:3]) if len(parts) > 3 and parts[0] == "media" else os.path.dirname(path)


def _is_sample(path: str) -> bool:
    return "sample" in path.lower()


def mark_superseded(
    candidates: list[OrphanCandidate], radarr_paths: set[str] | None, tv_subdirs: set[str]
) -> None:
    """Flag movie-side review candidates that share a folder with the file
    Radarr actually tracks for that movie.

    Radarr only cleans up files it imported itself, so an older full copy
    (a WEBRip from years ago, a multi-CD rip) survives next to a newer
    import. A candidate that IS Radarr's tracked file (here only because
    Plex doesn't know it) is never marked; neither is anything in a TV
    folder, where an untracked file is more likely an extra than a copy.

    When Radarr's tracked file for the movie is a sample clip, the
    candidate is probably the real movie, so it gets `tracks_sample`
    instead. Never call the real movie "superseded" by its own sample.
    """
    if radarr_paths is None:
        return
    tracked_in_dir: dict[str, str] = {}
    tracked_samples_in_title: set[str] = set()
    for p in radarr_paths:
        tracked_in_dir[os.path.dirname(p)] = os.path.basename(p)
        if _is_sample(p):
            tracked_samples_in_title.add(_title_folder(p))
    for c in candidates:
        if c.category != "orphaned media":
            continue
        if any(is_tv_path(p, tv_subdirs) for p in c.paths):
            continue
        if any(p in radarr_paths for p in c.paths):
            continue
        if any(_title_folder(p) in tracked_samples_in_title for p in c.paths):
            if not any(_is_sample(p) for p in c.paths):
                c.tracks_sample = True
            continue
        for p in c.paths:
            tracked = tracked_in_dir.get(os.path.dirname(p))
            if tracked:
                c.superseded_by = tracked
                break
