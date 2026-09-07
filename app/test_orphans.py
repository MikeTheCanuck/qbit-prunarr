"""Tests for orphan classification logic."""
import os

from inode_scan import ScanResult
from orphans import OrphanCandidate, classify_download_orphans, classify_media_orphans


def _make_file(path: str, content: bytes = b"x" * 100) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)


# --- classify_download_orphans -----------------------------------------

def test_download_only_file_not_in_qbit_is_orphan(tmp_path):
    root = str(tmp_path)
    _make_file(os.path.join(root, "torrents", "seed.mkv"))
    result = ScanResult(download_only={111: ["torrents/seed.mkv"]})

    candidates = classify_download_orphans(result, root, qbit_paths=set())

    assert len(candidates) == 1
    assert candidates[0].category == "unlinked download"
    assert candidates[0].inode == 111


def test_download_only_file_tracked_by_qbit_is_kept(tmp_path):
    root = str(tmp_path)
    _make_file(os.path.join(root, "torrents", "active.mkv"))
    result = ScanResult(download_only={222: ["torrents/active.mkv"]})

    candidates = classify_download_orphans(result, root, qbit_paths={"torrents/active.mkv"})

    assert candidates == []


def test_qbit_unreachable_fails_closed(tmp_path):
    root = str(tmp_path)
    _make_file(os.path.join(root, "torrents", "seed.mkv"))
    result = ScanResult(download_only={333: ["torrents/seed.mkv"]})

    candidates = classify_download_orphans(result, root, qbit_paths=None)

    assert candidates == []


# --- classify_media_orphans ----------------------------------------------

def test_movie_confirmed_by_radarr_and_plex_is_kept(tmp_path):
    root = str(tmp_path)
    _make_file(os.path.join(root, "media", "movies", "movie.mkv"))
    result = ScanResult(media_only={444: ["media/movies/movie.mkv"]})

    candidates = classify_media_orphans(
        result, root, tv_subdirs={"media/tv", "media/tv-no-backup"},
        sonarr_paths=set(), radarr_paths={"media/movies/movie.mkv"},
        plex_episode_paths=set(), plex_movie_paths={"media/movies/movie.mkv"},
    )

    assert candidates == []


def test_movie_missing_from_plex_is_orphan(tmp_path):
    root = str(tmp_path)
    _make_file(os.path.join(root, "media", "movies", "movie.mkv"))
    result = ScanResult(media_only={555: ["media/movies/movie.mkv"]})

    candidates = classify_media_orphans(
        result, root, tv_subdirs={"media/tv", "media/tv-no-backup"},
        sonarr_paths=set(), radarr_paths={"media/movies/movie.mkv"},
        plex_episode_paths=set(), plex_movie_paths=set(),
    )

    assert len(candidates) == 1
    assert candidates[0].category == "orphaned media"


def test_tv_episode_uses_sonarr_and_plex_episode_sets(tmp_path):
    root = str(tmp_path)
    _make_file(os.path.join(root, "media", "tv", "Show", "ep1.mkv"))
    result = ScanResult(media_only={666: ["media/tv/Show/ep1.mkv"]})

    candidates = classify_media_orphans(
        result, root, tv_subdirs={"media/tv", "media/tv-no-backup"},
        sonarr_paths={"media/tv/Show/ep1.mkv"}, radarr_paths=set(),
        plex_episode_paths={"media/tv/Show/ep1.mkv"}, plex_movie_paths=set(),
    )

    assert candidates == []


def test_arr_unreachable_fails_closed(tmp_path):
    root = str(tmp_path)
    _make_file(os.path.join(root, "media", "movies", "movie.mkv"))
    result = ScanResult(media_only={777: ["media/movies/movie.mkv"]})

    candidates = classify_media_orphans(
        result, root, tv_subdirs={"media/tv", "media/tv-no-backup"},
        sonarr_paths=set(), radarr_paths=None,
        plex_episode_paths=set(), plex_movie_paths=set(),
    )

    assert candidates == []


def test_plex_unreachable_fails_closed(tmp_path):
    root = str(tmp_path)
    _make_file(os.path.join(root, "media", "movies", "movie.mkv"))
    result = ScanResult(media_only={888: ["media/movies/movie.mkv"]})

    candidates = classify_media_orphans(
        result, root, tv_subdirs={"media/tv", "media/tv-no-backup"},
        sonarr_paths=set(), radarr_paths={"media/movies/movie.mkv"},
        plex_episode_paths=None, plex_movie_paths=None,
    )

    assert candidates == []


def test_size_bytes_reflects_real_file_size(tmp_path):
    root = str(tmp_path)
    _make_file(os.path.join(root, "torrents", "seed.mkv"), content=b"x" * 12345)
    result = ScanResult(download_only={999: ["torrents/seed.mkv"]})

    candidates = classify_download_orphans(result, root, qbit_paths=set())

    assert candidates[0].size_bytes == 12345
