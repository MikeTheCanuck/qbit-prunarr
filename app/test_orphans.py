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
    prune_empty_tree,
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

    candidates = classify_download_orphans(result, root, qbit_paths=set(), arr_queue_paths=set())

    assert len(candidates) == 1
    assert candidates[0].category == "unlinked download"
    assert candidates[0].inode == 111


def test_download_only_file_tracked_by_qbit_is_kept(tmp_path):
    root = str(tmp_path)
    _make_file(os.path.join(root, "torrents", "active.mkv"))
    result = ScanResult(download_only={222: ["torrents/active.mkv"]})

    candidates = classify_download_orphans(
        result, root, qbit_paths={"torrents/active.mkv"}, arr_queue_paths=set()
    )

    assert candidates == []


def test_download_only_file_tracked_by_arr_queue_is_kept(tmp_path):
    """A file stuck 'unable to import automatically' can be dropped from
    qBittorrent (per the *arr app's own cleanup settings) well before
    Sonarr/Radarr give up on it - the queue signal has to be able to save
    it on its own, independent of qbit_paths."""
    root = str(tmp_path)
    _make_file(os.path.join(root, "torrents", "stuck-import.mkv"))
    result = ScanResult(download_only={223: ["torrents/stuck-import.mkv"]})

    candidates = classify_download_orphans(
        result, root, qbit_paths=set(), arr_queue_paths={"torrents/stuck-import.mkv"}
    )

    assert candidates == []


def test_arr_queue_unreachable_fails_closed(tmp_path):
    root = str(tmp_path)
    _make_file(os.path.join(root, "torrents", "seed.mkv"))
    result = ScanResult(download_only={224: ["torrents/seed.mkv"]})

    candidates = classify_download_orphans(result, root, qbit_paths=set(), arr_queue_paths=None)

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
        result, root, qbit_paths={"torrents/completed/Show.S01.1080p-GRP"}, arr_queue_paths=set()
    )

    assert candidates == []


def test_multifile_torrent_dir_with_trailing_slash_covers_its_files(tmp_path):
    root = str(tmp_path)
    _make_file(os.path.join(root, "torrents", "Pack", "a.mkv"))
    result = ScanResult(download_only={1003: ["torrents/Pack/a.mkv"]})

    candidates = classify_download_orphans(
        result, root, qbit_paths={"torrents/Pack/"}, arr_queue_paths=set()
    )

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

    candidates = classify_download_orphans(result, root, qbit_paths={""}, arr_queue_paths=set())

    assert candidates == []


def test_path_tracked_empty_tracked_set_matches_nothing():
    assert path_tracked("torrents/seed.mkv", set()) is False


def test_sibling_dir_with_shared_name_prefix_is_still_an_orphan(tmp_path):
    """'torrents/Pack2/a.mkv' must NOT be considered covered by 'torrents/Pack'."""
    root = str(tmp_path)
    _make_file(os.path.join(root, "torrents", "Pack2", "a.mkv"))
    result = ScanResult(download_only={1004: ["torrents/Pack2/a.mkv"]})

    candidates = classify_download_orphans(
        result, root, qbit_paths={"torrents/Pack"}, arr_queue_paths=set()
    )

    assert len(candidates) == 1


def test_qbit_unreachable_fails_closed(tmp_path):
    root = str(tmp_path)
    _make_file(os.path.join(root, "torrents", "seed.mkv"))
    result = ScanResult(download_only={333: ["torrents/seed.mkv"]})

    candidates = classify_download_orphans(result, root, qbit_paths=None, arr_queue_paths=set())

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



def test_subtitle_sidecar_is_never_flagged_for_review(tmp_path):
    """Sonarr/Radarr's API only reports the primary video file per
    episode/movie - a subtitle sitting next to a perfectly tracked
    episode would fail this check forever, no matter how correctly it's
    organized, since the *arr apps never report sidecar paths at all."""
    root = str(tmp_path)
    _make_file(os.path.join(root, "media", "tv", "Show", "ep.srt"))
    result = ScanResult(media_only={666: ["media/tv/Show/ep.srt"]})

    candidates = classify_media_orphans(
        result, root, tv_subdirs={"media/tv", "media/tv-no-backup"},
        sonarr_paths=set(), radarr_paths=set(),
        plex_episode_paths=set(), plex_movie_paths=set(),
    )

    assert candidates == []


def test_sample_directory_video_is_never_flagged_for_review(tmp_path):
    """Sample/ is a scene-release convention - a short preview clip
    bundled with a torrent to check quality before committing to the
    real download. No *arr app or Plex tracks it as real content."""
    root = str(tmp_path)
    _make_file(os.path.join(root, "media", "movies", "Movie (2020)", "Sample", "movie-sample.mkv"))
    result = ScanResult(media_only={777: ["media/movies/Movie (2020)/Sample/movie-sample.mkv"]})

    candidates = classify_media_orphans(
        result, root, tv_subdirs={"media/tv", "media/tv-no-backup"},
        sonarr_paths=set(), radarr_paths=set(),
        plex_episode_paths=set(), plex_movie_paths=set(),
    )

    assert candidates == []


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

    candidates = classify_download_orphans(result, root, qbit_paths=set(), arr_queue_paths=set())

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


# --- prune_empty_tree ------------------------------------------------

def test_prune_empty_tree_removes_never_populated_subdirs(tmp_path):
    """Disc rips ship empty AUXDATA/BDJO/META dirs that per-file pruning
    never visits - the group root would otherwise survive as a shell."""
    root = str(tmp_path)
    os.makedirs(os.path.join(root, "torrents", "radarr", "BLUEBIRD", "BDMV", "AUXDATA"))
    os.makedirs(os.path.join(root, "torrents", "radarr", "BLUEBIRD", "BDMV", "META", "DL"))
    _make_file(os.path.join(root, "torrents", "radarr", "Other", "keep.mkv"))

    prune_empty_tree(root, "torrents/radarr/BLUEBIRD", "torrents")

    assert not os.path.exists(os.path.join(root, "torrents", "radarr", "BLUEBIRD"))
    assert os.path.isdir(os.path.join(root, "torrents", "radarr"))


def test_prune_empty_tree_climbs_to_but_not_past_boundary(tmp_path):
    root = str(tmp_path)
    os.makedirs(os.path.join(root, "torrents", "radarr", "BLUEBIRD", "BDMV"))

    prune_empty_tree(root, "torrents/radarr/BLUEBIRD", "torrents")

    assert not os.path.exists(os.path.join(root, "torrents", "radarr"))
    assert os.path.isdir(os.path.join(root, "torrents"))


def test_prune_empty_tree_leaves_files_and_their_dirs(tmp_path):
    root = str(tmp_path)
    survivor = os.path.join(root, "torrents", "A", "sub", "failed-delete.clpi")
    _make_file(survivor)
    os.makedirs(os.path.join(root, "torrents", "A", "empty"))

    prune_empty_tree(root, "torrents/A", "torrents")

    assert os.path.exists(survivor)
    assert not os.path.exists(os.path.join(root, "torrents", "A", "empty"))


def test_prune_empty_tree_tolerates_already_removed_root(tmp_path):
    root = str(tmp_path)
    os.makedirs(os.path.join(root, "torrents", "radarr"))

    prune_empty_tree(root, "torrents/radarr/GONE", "torrents")

    assert not os.path.exists(os.path.join(root, "torrents", "radarr"))
    assert os.path.isdir(os.path.join(root, "torrents"))


def test_prune_empty_tree_refuses_the_boundary_itself(tmp_path):
    root = str(tmp_path)
    os.makedirs(os.path.join(root, "torrents", "empty"))

    with pytest.raises(ValueError):
        prune_empty_tree(root, "torrents", "torrents")

    assert os.path.isdir(os.path.join(root, "torrents", "empty"))


def test_prune_empty_tree_refuses_root_outside_boundary(tmp_path):
    root = str(tmp_path)
    os.makedirs(os.path.join(root, "media", "movies", "empty"))

    with pytest.raises(ValueError):
        prune_empty_tree(root, "media/movies/empty", "torrents")

    assert os.path.isdir(os.path.join(root, "media", "movies", "empty"))


def test_mark_superseded_flags_an_old_copy_beside_radarrs_file():
    from orphans import OrphanCandidate, mark_superseded
    folder = "media/movies/Return of the Living Dead II 1080p WEBRip"
    old = OrphanCandidate(inode=1, paths=[f"{folder}/ROTLD II WEBRip.mp4"], category="orphaned media", size_bytes=1)
    mark_superseded([old], {f"{folder}/ROTLD II (1988) Bluray-1080p.mp4"}, {"media/tv"})
    assert old.superseded_by == "ROTLD II (1988) Bluray-1080p.mp4"


def test_mark_superseded_leaves_radarrs_own_file_alone():
    """Radarr's tracked file can land in Needs Review when Plex doesn't know
    it yet. It's the current copy, never a superseded one."""
    from orphans import OrphanCandidate, mark_superseded
    tracked = "media/movies/Film (2001)/Film (2001).mp4"
    c = OrphanCandidate(inode=1, paths=[tracked], category="orphaned media", size_bytes=1)
    mark_superseded([c], {tracked}, {"media/tv"})
    assert c.superseded_by is None


def test_mark_superseded_ignores_tv_and_other_folders_and_unknown_radarr():
    from orphans import OrphanCandidate, mark_superseded
    tv = OrphanCandidate(inode=1, paths=["media/tv/Show/S01/extra.mkv"], category="orphaned media", size_bytes=1)
    lone = OrphanCandidate(inode=2, paths=["media/movies/Other/old.avi"], category="orphaned media", size_bytes=1)
    radarr = {"media/tv/Show/S01/ep.mkv", "media/movies/Film/Film.mp4"}
    mark_superseded([tv, lone], radarr, {"media/tv"})
    assert tv.superseded_by is None and lone.superseded_by is None
    mark_superseded([lone], None, {"media/tv"})  # Radarr unreachable: no labels, no crash
    assert lone.superseded_by is None
