"""Tests for orphan classification logic."""
import os

import pytest

from inode_scan import ScanResult
from orphans import (
    OrphanCandidate,
    classify_download_orphans,
    classify_media_orphans,
    delete_orphan,
    is_tv_path,
    path_tracked,
)


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


def test_multifile_torrent_dir_covers_its_files(tmp_path):
    """qBittorrent reports content_path as the ROOT DIR for multi-file
    torrents, so the scan's per-file paths never match it exactly."""
    root = str(tmp_path)
    pack = os.path.join(root, "torrents", "completed", "Show.S01.1080p-GRP")
    _make_file(os.path.join(pack, "S01E01.mkv"))
    _make_file(os.path.join(pack, "S01E02.mkv"))
    result = ScanResult(
        download_only={
            1001: ["torrents/completed/Show.S01.1080p-GRP/S01E01.mkv"],
            1002: ["torrents/completed/Show.S01.1080p-GRP/S01E02.mkv"],
        }
    )

    candidates = classify_download_orphans(
        result, root, qbit_paths={"torrents/completed/Show.S01.1080p-GRP"}
    )

    assert candidates == []


def test_multifile_torrent_dir_with_trailing_slash_covers_its_files(tmp_path):
    root = str(tmp_path)
    _make_file(os.path.join(root, "torrents", "Pack", "a.mkv"))
    result = ScanResult(download_only={1003: ["torrents/Pack/a.mkv"]})

    candidates = classify_download_orphans(result, root, qbit_paths={"torrents/Pack/"})

    assert candidates == []


def test_empty_string_tracked_entry_covers_every_path(tmp_path):
    """A service reporting its content_path as exactly its own
    *_PATH_PREFIX normalizes to "" — every ancestor chain terminates at
    "", so this has to match everything rather than nothing, or a
    live-seeding file with this exact layout gets deleted as a false
    positive orphan (the fail-closed direction, not the dangerous one)."""
    root = str(tmp_path)
    _make_file(os.path.join(root, "torrents", "seed.mkv"))
    result = ScanResult(download_only={1005: ["torrents/seed.mkv"]})

    candidates = classify_download_orphans(result, root, qbit_paths={""})

    assert candidates == []


def test_path_tracked_empty_tracked_set_matches_nothing():
    assert path_tracked("torrents/seed.mkv", set()) is False


def test_sibling_dir_with_shared_name_prefix_is_still_an_orphan(tmp_path):
    """'torrents/Pack2/a.mkv' must NOT be considered covered by 'torrents/Pack'."""
    root = str(tmp_path)
    _make_file(os.path.join(root, "torrents", "Pack2", "a.mkv"))
    result = ScanResult(download_only={1004: ["torrents/Pack2/a.mkv"]})

    candidates = classify_download_orphans(result, root, qbit_paths={"torrents/Pack"})

    assert len(candidates) == 1


def test_qbit_unreachable_fails_closed(tmp_path):
    root = str(tmp_path)
    _make_file(os.path.join(root, "torrents", "seed.mkv"))
    result = ScanResult(download_only={333: ["torrents/seed.mkv"]})

    candidates = classify_download_orphans(result, root, qbit_paths=None)

    assert candidates == []


# --- classify_media_orphans ----------------------------------------------

def test_is_tv_path_matches_subdir_and_nested_files():
    tv_subdirs = {"media/tv", "media/tv-no-backup"}
    assert is_tv_path("media/tv/Show/ep.mkv", tv_subdirs) is True
    assert is_tv_path("media/tv-no-backup/Show/ep.mkv", tv_subdirs) is True
    assert is_tv_path("media/movies/Movie/movie.mkv", tv_subdirs) is False


def test_is_tv_path_does_not_prefix_match_a_similar_subdir_name():
    """'media/tv2' must not be treated as inside 'media/tv'."""
    assert is_tv_path("media/tv2/something.mkv", {"media/tv"}) is False



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


def test_size_bytes_counts_a_hardlinked_file_once(tmp_path):
    """Two paths for one inode are two names for ONE file — summing their
    sizes double-counts the space a delete would actually reclaim."""
    root = str(tmp_path)
    original = os.path.join(root, "media", "movies", "movie.mkv")
    _make_file(original, content=b"x" * 50000)
    dupe = os.path.join(root, "media", "movies-no-backup", "movie.mkv")
    os.makedirs(os.path.dirname(dupe), exist_ok=True)
    os.link(original, dupe)

    result = ScanResult(
        media_only={
            1234: ["media/movies/movie.mkv", "media/movies-no-backup/movie.mkv"]
        }
    )
    candidates = classify_media_orphans(
        result, root, tv_subdirs={"media/tv", "media/tv-no-backup"},
        sonarr_paths=set(), radarr_paths=set(),
        plex_episode_paths=set(), plex_movie_paths=set(),
    )

    assert len(candidates) == 1
    assert candidates[0].size_bytes == 50000


# --- delete_orphan ---------------------------------------------------

def test_delete_orphan_removes_file(tmp_path):
    root = str(tmp_path)
    path = os.path.join(root, "torrents", "seed.mkv")
    _make_file(path)

    delete_orphan(root, "torrents/seed.mkv", "torrents")

    assert not os.path.exists(path)


def test_delete_orphan_prunes_empty_parent_dirs(tmp_path):
    root = str(tmp_path)
    path = os.path.join(root, "torrents", "Some Release", "seed.mkv")
    _make_file(path)

    delete_orphan(root, "torrents/Some Release/seed.mkv", "torrents")

    assert not os.path.exists(os.path.join(root, "torrents", "Some Release"))
    # data_root itself and its direct "torrents" child must not be touched
    assert os.path.isdir(os.path.join(root, "torrents"))


def test_delete_orphan_stops_at_two_level_scan_root(tmp_path):
    """The real scan roots are two levels below data_root (media/movies),
    so a depth-from-data_root rule would delete Radarr's root folder."""
    root = str(tmp_path)
    path = os.path.join(root, "media", "movies", "Movie (2020)", "movie.mkv")
    _make_file(path)

    delete_orphan(root, "media/movies/Movie (2020)/movie.mkv", "media/movies")

    assert not os.path.exists(os.path.join(root, "media", "movies", "Movie (2020)"))
    assert os.path.isdir(os.path.join(root, "media", "movies"))
    assert os.path.isdir(os.path.join(root, "media"))


def test_delete_orphan_prunes_nested_dirs_up_to_boundary(tmp_path):
    root = str(tmp_path)
    path = os.path.join(root, "media", "tv", "Show", "Season 01", "ep.mkv")
    _make_file(path)

    delete_orphan(root, "media/tv/Show/Season 01/ep.mkv", "media/tv")

    assert not os.path.exists(os.path.join(root, "media", "tv", "Show"))
    assert os.path.isdir(os.path.join(root, "media", "tv"))


def test_delete_orphan_stops_pruning_at_nonempty_dir(tmp_path):
    root = str(tmp_path)
    _make_file(os.path.join(root, "torrents", "Pack", "keep.mkv"))
    target = os.path.join(root, "torrents", "Pack", "seed.mkv")
    _make_file(target)

    delete_orphan(root, "torrents/Pack/seed.mkv", "torrents")

    assert not os.path.exists(target)
    assert os.path.isdir(os.path.join(root, "torrents", "Pack"))
    assert os.path.exists(os.path.join(root, "torrents", "Pack", "keep.mkv"))


def test_delete_orphan_missing_file_raises(tmp_path):
    root = str(tmp_path)
    os.makedirs(os.path.join(root, "torrents"))

    with pytest.raises(OSError):
        delete_orphan(root, "torrents/does-not-exist.mkv", "torrents")


def test_delete_orphan_refuses_path_outside_its_boundary(tmp_path):
    root = str(tmp_path)
    path = os.path.join(root, "media", "movies", "movie.mkv")
    _make_file(path)

    with pytest.raises(ValueError):
        delete_orphan(root, "media/movies/movie.mkv", "torrents")

    assert os.path.exists(path)
