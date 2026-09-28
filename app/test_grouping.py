"""Tests for rolling Unlinked Downloads candidates into directory groups."""
from grouping import OrphanGroup, group_download_orphans
from orphans import OrphanCandidate

BOUNDS = {"torrents", "usenet"}


def _c(inode, *paths, size=100):
    return OrphanCandidate(
        inode=inode, paths=list(paths), category="unlinked download", size_bytes=size
    )


def _files(candidates, *non_orphans):
    """Ground truth: every orphan path plus any still-needed files."""
    return [p for c in candidates for p in c.paths] + list(non_orphans)


def test_fully_orphaned_deep_tree_rolls_up_to_topmost_dir():
    """The BDMV shape: several nesting levels, all orphaned, next to an
    unrelated still-tracked torrent that stops the climb."""
    base = "torrents/completed/radarr/BLUEBIRD"
    cands = [
        _c(1, f"{base}/BDMV/STREAM/00000.m2ts", size=5000),
        _c(2, f"{base}/BDMV/BACKUP/CLIPINF/00153.clpi", size=10),
        _c(3, f"{base}/BDMV/index.bdmv", size=20),
    ]
    files = _files(cands, "torrents/completed/radarr/Other.Movie/movie.mkv")

    groups, standalone = group_download_orphans(cands, files, BOUNDS)

    assert standalone == []
    assert len(groups) == 1
    assert groups[0].root == base
    assert groups[0].size_bytes == 5030
    assert [m.inode for m in groups[0].members] == [1, 3, 2]  # size desc


def test_directory_with_a_still_needed_file_does_not_roll_up():
    cands = [_c(1, "torrents/Pack/a.mkv"), _c(2, "torrents/Pack/b.mkv")]
    files = _files(cands, "torrents/Pack/keep.mkv")

    groups, standalone = group_download_orphans(cands, files, BOUNDS)

    assert groups == []
    assert {c.inode for c in standalone} == {1, 2}


def test_fully_orphaned_subdir_inside_mixed_dir_groups_at_the_subdir():
    cands = [_c(1, "torrents/Pack/Extras/a.mkv"), _c(2, "torrents/Pack/Extras/b.mkv")]
    files = _files(cands, "torrents/Pack/keep.mkv")

    groups, standalone = group_download_orphans(cands, files, BOUNDS)

    assert standalone == []
    assert [g.root for g in groups] == ["torrents/Pack/Extras"]


def test_file_directly_in_scan_root_stays_standalone():
    cands = [_c(1, "torrents/seed.mkv")]

    groups, standalone = group_download_orphans(cands, _files(cands), BOUNDS)

    assert groups == []
    assert [c.inode for c in standalone] == [1]


def test_sibling_orphaned_dirs_form_separate_groups_not_one():
    cands = [
        _c(1, "torrents/radarr/A/x.mkv"), _c(2, "torrents/radarr/A/y.nfo"),
        _c(3, "torrents/radarr/B/x.mkv"), _c(4, "torrents/radarr/B/y.nfo"),
    ]
    files = _files(cands, "torrents/radarr/C/keep.mkv")

    groups, standalone = group_download_orphans(cands, files, BOUNDS)

    assert standalone == []
    assert sorted(g.root for g in groups) == ["torrents/radarr/A", "torrents/radarr/B"]


def test_rollup_never_climbs_into_the_scan_root_itself():
    """With nothing non-orphaned anywhere, two top-level dirs must still be
    two groups - never one group rooted at 'torrents/completed' (a direct
    child of the scan root) and never at 'torrents' itself. Also covers:
    a directory two levels below the boundary still groups normally."""
    cands = [
        _c(1, "torrents/completed/A/x.mkv"), _c(2, "torrents/completed/A/y.mkv"),
        _c(3, "torrents/completed/B/x.mkv"), _c(4, "torrents/completed/B/y.mkv"),
    ]

    groups, _ = group_download_orphans(cands, _files(cands), BOUNDS)

    assert sorted(g.root for g in groups) == ["torrents/completed/A", "torrents/completed/B"]


def test_usenet_is_a_boundary_too():
    """'usenet/complete' is itself a direct child of the 'usenet' scan
    root, so the group must root one level deeper, at 'Show'."""
    cands = [_c(1, "usenet/complete/Show/a.mkv"), _c(2, "usenet/complete/Show/b.mkv")]

    groups, _ = group_download_orphans(cands, _files(cands), BOUNDS)

    assert [g.root for g in groups] == ["usenet/complete/Show"]


def test_direct_child_of_scan_root_is_never_a_group_root():
    """The live NAS case: qBittorrent's own incoming/ directory, not a
    torrent - its stray top-level orphans must never roll up into a group
    rooted at 'torrents/incoming' itself."""
    cands = [
        _c(1, "torrents/incoming/.DS_Store"),
        _c(2, "torrents/incoming/x.torrent"),
        _c(3, "torrents/incoming/radarr/Movie/movie.mkv"),
    ]

    groups, standalone = group_download_orphans(cands, _files(cands), BOUNDS)

    assert groups == []
    assert {c.inode for c in standalone} == {1, 2, 3}


def test_single_orphan_alone_in_its_folder_stays_standalone():
    cands = [_c(1, "torrents/radarr/Lonely/movie.mkv")]
    files = _files(cands, "torrents/radarr/Other/keep.mkv")

    groups, standalone = group_download_orphans(cands, files, BOUNDS)

    assert groups == []
    assert [c.inode for c in standalone] == [1]


def test_candidate_with_hardlinks_in_two_dirs_never_joins_a_group():
    """Deleting a group deletes every path of every member - a member with
    a second name outside the group's folder would silently lose that
    file too."""
    cands = [
        _c(1, "torrents/radarr/A/shared.mkv", "torrents/radarr/B/shared.mkv"),
        _c(2, "torrents/radarr/A/y.mkv"), _c(3, "torrents/radarr/A/z.mkv"),
    ]
    files = _files(cands, "torrents/radarr/B/keep.mkv")

    groups, standalone = group_download_orphans(cands, files, BOUNDS)

    assert [c.inode for c in standalone] == [1]
    assert len(groups) == 1
    assert groups[0].root == "torrents/radarr/A"
    assert {m.inode for m in groups[0].members} == {2, 3}


def test_candidate_with_both_hardlinks_inside_one_group_joins_it():
    cands = [
        _c(1, "torrents/radarr/A/x.mkv", "torrents/radarr/A/sub/x-copy.mkv"),
        _c(2, "torrents/radarr/A/y.mkv"),
    ]

    groups, standalone = group_download_orphans(cands, _files(cands), BOUNDS)

    assert standalone == []
    assert {m.inode for m in groups[0].members} == {1, 2}


def test_name_prefix_sibling_does_not_block_rollup():
    """'torrents/radarr/Pack2/keep.mkv' is not inside 'torrents/radarr/Pack'."""
    cands = [_c(1, "torrents/radarr/Pack/a.mkv"), _c(2, "torrents/radarr/Pack/b.mkv")]
    files = _files(cands, "torrents/radarr/Pack2/keep.mkv")

    groups, _ = group_download_orphans(cands, files, BOUNDS)

    assert [g.root for g in groups] == ["torrents/radarr/Pack"]


def test_path_outside_every_boundary_stays_standalone():
    cands = [_c(1, "elsewhere/A/x.mkv"), _c(2, "elsewhere/A/y.mkv")]

    groups, standalone = group_download_orphans(cands, _files(cands), BOUNDS)

    assert groups == []
    assert {c.inode for c in standalone} == {1, 2}


def test_no_candidates_means_no_groups():
    assert group_download_orphans([], ["torrents/a.mkv"], BOUNDS) == ([], [])


def test_group_size_sums_members():
    g = OrphanGroup(root="torrents/A", members=[_c(1, "torrents/A/x", size=7), _c(2, "torrents/A/y", size=5)])
    assert g.size_bytes == 12
