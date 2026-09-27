# Orphan Grouping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse a fully-orphaned download directory (e.g. a 300-file BDMV rip) into one expandable, deletable row in the Unlinked Downloads table.

**Architecture:** A new pure function (`grouping.group_download_orphans`) post-processes the flat Unlinked Downloads candidate list after classification, using every download-side file the scan found as ground truth. `run_scan` caches the resulting groups by root path, next to the existing per-inode `_scan_cache`. The template renders each table "unit" (standalone row or group) as its own `<tbody>` so client-side sorting keeps a group's child rows attached. A new `POST /orphans/groups/delete` route deletes a group best-effort after re-verifying, and the existing bulk form learns a `group_roots` field.

**Tech Stack:** Python 3, FastAPI 0.138, Jinja2 3.1, HTMX 2.0.3 (CDN, already loaded), pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-20-orphan-grouping-design.md`

## Global Constraints

- Grouping applies to the **Unlinked Downloads** table only. Needs Review rendering and behavior stay as they are (download-only v1 scope, confirmed by Mike 2026-09-27).
- A group root is always **strictly inside** a download scan subdir (`torrents`, `usenet`), never the subdir itself.
- Rollup picks the **topmost** fully-orphaned directory. No nested groups, no tree view.
- Expanded child rows show paths **relative to the group root** (not bare filename, not full path).
- Grouping never changes what is classified as an orphan. It only changes presentation and adds a way to delete many candidates at once.
- Group delete is **best-effort**: continue past per-file failures, report `N of M deletes failed — check logs`.
- Every delete re-verifies with a fresh `run_scan()` first (existing race guard). A group delete only ever deletes inodes that were members of that group at scan time.
- A posted group root is only ever used as a key into the server-side group cache. It is never used as a filesystem path directly.
- Tests run from `app/`: `cd app && python3 -m pytest -q`. Baseline on `main` at plan time: 103 passing.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Decisions made while planning (flag to Mike at review)

1. **A "group" with only one candidate renders as an ordinary standalone row.** The spec only says a file with no eligible parent stays standalone. It doesn't cover a single orphan alone in its own folder (a single-file torrent in a subfolder). A one-file group adds an expand toggle that reveals the same file again, which is noise. `delete_orphan` already prunes that folder when the one file goes.
2. **The collapsed group row's Delete button reports failures inline, not via redirect flash.** It's an HTMX button like the per-row Delete, which already reports errors inline by swapping its row. A redirect would wipe the scan results off the page. The message text matches the spec: `N of M deletes failed — check logs`. The bulk form keeps using the flash redirect, unchanged.
3. **Adds the missing bulk-delete submit button and select-all wiring to the Unlinked Downloads form.** The spec's collapsed-row checkbox "selects the whole group as a unit for the existing bulk-delete form", but that form has never had a submit button. It was explicitly deferred in the 2026-09-09 fix wave, and `select-all-download` has no JS behind it. Without this, the group checkbox does nothing. Needs Review's form is left alone, consistent with the download-only scope.
4. **Group delete also removes empty subdirectories that never held files.** BDMV rips routinely ship empty `AUXDATA/`, `BDJO/`, `JAR/`, `META/` dirs. `delete_orphan`'s per-file upward pruning never visits those, so without this the group root survives as an empty shell. That contradicts the spec's "prunes the resulting empty directory tree".
5. **A candidate whose hardlinks span directories never joins a group** unless every one of its paths rolls up to the same root. Otherwise deleting "this folder" would silently delete a file somewhere else.

## Review Focus

- A candidate with two hardlink paths in different directories must not be pulled into a group whose root doesn't contain both paths. Deleting the group must not remove a file outside the group's folder. Pinned in Task 1.
- A disc rip with empty subdirectories (`BDMV/AUXDATA/`) must leave no empty group-root shell behind after a successful group delete. Pinned in Tasks 2 and 4.
- A stale group root (page scanned, then rescanned elsewhere) or a hand-crafted root like `../../etc` posted to the group-delete route must delete nothing. Pinned in Task 4.
- A group member that stopped being an orphan between scan and click (torrent re-added in qBittorrent) must be skipped, not deleted, and the now-live folder's empty subdirectories must not be pruned either. The response must say so. Pinned in Task 4.
- Checking both a group's checkbox and one of its child checkboxes in the bulk form must delete each file exactly once, with no spurious "failed" flash from a second delete of an already-gone file. Pinned in Task 5.

---

## File Structure

- Create `app/grouping.py`: `OrphanGroup` dataclass plus `group_download_orphans()`. Pure function over path lists, no I/O.
- Create `app/test_grouping.py`: unit tests for the above.
- Modify `app/orphans.py`: add `prune_empty_tree()` next to `delete_orphan()`, since it's the same pruning concern.
- Modify `app/test_orphans.py`: tests for `prune_empty_tree()`.
- Modify `app/main.py`: `_group_cache`, grouping call in `run_scan`, enrichment for groups, the new group-delete route, `group_roots` support in `bulk_delete_orphans`.
- Create `app/templates/_orphan_group.html`: one group rendered as a `<tbody>`.
- Modify `app/templates/_orphan_row.html`: optional `group-child` class.
- Modify `app/templates/orphans.html`: per-unit `<tbody>` in both tables, group CSS, expand toggle, unit-level sorting, bulk-delete button, and select-all for the download table.
- Modify `app/test_orphans_routes.py`: route and render tests.

---

### Task 1: Grouping function

**Files:**
- Create: `app/grouping.py`
- Test: `app/test_grouping.py`

**Interfaces:**
- Consumes: `orphans.OrphanCandidate(inode: int, paths: list[str], category: str, size_bytes: int)` (existing).
- Produces:
  - `grouping.OrphanGroup(root: str, members: list[OrphanCandidate])` with property `size_bytes -> int`. `members` is sorted by `size_bytes` descending.
  - `grouping.group_download_orphans(candidates: list[OrphanCandidate], download_files: list[str], boundaries: set[str]) -> tuple[list[OrphanGroup], list[OrphanCandidate]]`. Returns `(groups, standalone)`. Every input candidate appears exactly once across the two outputs. All paths are relative to data_root, `/`-separated.

- [ ] **Step 1: Write the failing tests**

Create `app/test_grouping.py`:

```python
"""Tests for rolling Unlinked Downloads candidates up into directory groups."""
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
    two groups - never one group rooted at 'torrents'."""
    cands = [
        _c(1, "torrents/A/x.mkv"), _c(2, "torrents/A/y.mkv"),
        _c(3, "torrents/B/x.mkv"), _c(4, "torrents/B/y.mkv"),
    ]

    groups, _ = group_download_orphans(cands, _files(cands), BOUNDS)

    assert sorted(g.root for g in groups) == ["torrents/A", "torrents/B"]


def test_usenet_is_a_boundary_too():
    cands = [_c(1, "usenet/complete/Show/a.mkv"), _c(2, "usenet/complete/Show/b.mkv")]

    groups, _ = group_download_orphans(cands, _files(cands), BOUNDS)

    assert [g.root for g in groups] == ["usenet/complete"]


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
        _c(1, "torrents/A/shared.mkv", "torrents/B/shared.mkv"),
        _c(2, "torrents/A/y.mkv"), _c(3, "torrents/A/z.mkv"),
    ]
    files = _files(cands, "torrents/B/keep.mkv")

    groups, standalone = group_download_orphans(cands, files, BOUNDS)

    assert [c.inode for c in standalone] == [1]
    assert len(groups) == 1
    assert groups[0].root == "torrents/A"
    assert {m.inode for m in groups[0].members} == {2, 3}


def test_candidate_with_both_hardlinks_inside_one_group_joins_it():
    cands = [
        _c(1, "torrents/A/x.mkv", "torrents/A/sub/x-copy.mkv"),
        _c(2, "torrents/A/y.mkv"),
    ]

    groups, standalone = group_download_orphans(cands, _files(cands), BOUNDS)

    assert standalone == []
    assert {m.inode for m in groups[0].members} == {1, 2}


def test_name_prefix_sibling_does_not_block_rollup():
    """'torrents/Pack2/keep.mkv' is not inside 'torrents/Pack'."""
    cands = [_c(1, "torrents/Pack/a.mkv"), _c(2, "torrents/Pack/b.mkv")]
    files = _files(cands, "torrents/Pack2/keep.mkv")

    groups, _ = group_download_orphans(cands, files, BOUNDS)

    assert [g.root for g in groups] == ["torrents/Pack"]


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd app && python3 -m pytest test_grouping.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'grouping'`.

- [ ] **Step 3: Implement**

Create `app/grouping.py`:

```python
"""Roll Unlinked Downloads candidates up into per-directory groups.

Classification is per-inode, so one orphaned torrent that happens to be a
raw disc rip fragments into hundreds of rows. qBittorrent has already
forgotten the torrent by the time its files are orphans, so there's no
torrent name left to group by - grouping is inferred purely from directory
structure: a directory rolls up only if every file the scan found under
it is an orphan candidate.
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
    strictly inside a boundary. None if the immediate parent is already
    blocked, or the path isn't under any boundary at all."""
    root = None
    for directory in _ancestors(path):
        if directory in boundaries:
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd app && python3 -m pytest test_grouping.py -q`
Expected: 14 passed. Then run `python3 -m pytest -q`. Expected: 117 passed.

- [ ] **Step 5: Commit**

```bash
git add app/grouping.py app/test_grouping.py
git commit -m "feat: group fully-orphaned download directories into one unit

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Prune an emptied directory tree

**Files:**
- Modify: `app/orphans.py` (add after `delete_orphan`, end of file)
- Test: `app/test_orphans.py`

**Interfaces:**
- Produces: `orphans.prune_empty_tree(data_root: str, root_rel: str, boundary: str) -> None`. Removes every empty directory at or under `root_rel` (bottom-up), then prunes now-empty parents up to but never including `boundary`. Never removes a file or a non-empty directory. Raises `ValueError` if `root_rel` is not strictly inside `boundary`. A `root_rel` that no longer exists is not an error.

- [ ] **Step 1: Write the failing tests**

In `app/test_orphans.py`, add `prune_empty_tree` to the `from orphans import (...)` list. Append:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd app && python3 -m pytest test_orphans.py -q`
Expected: `ImportError: cannot import name 'prune_empty_tree'`.

- [ ] **Step 3: Implement**

Append to `app/orphans.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd app && python3 -m pytest -q`
Expected: 123 passed.

- [ ] **Step 5: Commit**

```bash
git add app/orphans.py app/test_orphans.py
git commit -m "feat: prune a whole emptied directory tree, not just file ancestors

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Compute groups during scan and render them

**Files:**
- Modify: `app/main.py` (imports; module constants near line 43; `run_scan` near line 350; `_enrich_candidate` and the orphans routes near lines 380-450)
- Create: `app/templates/_orphan_group.html`
- Modify: `app/templates/_orphan_row.html`
- Modify: `app/templates/orphans.html`
- Test: `app/test_orphans_routes.py`

**Interfaces:**
- Consumes: `group_download_orphans`, `OrphanGroup` (Task 1).
- Produces:
  - `main._group_cache: dict[str, OrphanGroup]`, keyed by group root. It's rebuilt on every `run_scan()`, like `_scan_cache`.
  - `main._group_dom_id(root: str) -> str` returns `"orphan-group-" + sha1(root)[:12]`. Tasks 4 and 5 use it for error rows.
  - Template context key `download_units: list[dict]`, replacing `download_candidates`. Each dict has `kind` set to `"file"` (the `_enrich_candidate` shape) or `"group"` (`root, dom_id, display_path, file_count, size_bytes, size_gb, children`). `children` holds `_enrich_candidate` dicts with `display_path` relative to the root and `is_child: True`.
  - Each unit in both tables renders as its own `<tbody class="orphan-unit" data-path=... data-size-bytes=...>`. A group's tbody also has class `orphan-group` and `id=dom_id`.

- [ ] **Step 1: Write the failing tests**

Append to `app/test_orphans_routes.py`:

```python
# --- orphan grouping -------------------------------------------------

from contextlib import contextmanager


@contextmanager
def _services(qbit_paths=()):
    with patch("main.QBitClient", return_value=_mock_client(get_all_content_paths=set(qbit_paths))), \
         patch("main.SonarrClient", return_value=_mock_client(get_all_episode_paths=set(), get_all_queue_paths=set())), \
         patch("main.RadarrClient", return_value=_mock_client(get_all_movie_paths=set(), get_all_queue_paths=set())), \
         patch("main.PlexClient", return_value=_mock_client(
             get_all_movie_paths=set(), get_all_episode_paths=set()
         )):
        yield


BLUEBIRD = "torrents/completed/radarr/BLUEBIRD"
OTHER_MOVIE = "torrents/completed/radarr/Other.Movie"


def _make_bluebird(root):
    """The spec's motivating shape: a fully orphaned multi-level disc rip
    (with an empty, never-populated subdir) next to a torrent qBit still
    tracks."""
    import os
    base = os.path.join(root, *BLUEBIRD.split("/"))
    _make_file(os.path.join(base, "BDMV", "STREAM", "00000.m2ts"), content=b"x" * 5000)
    _make_file(os.path.join(base, "BDMV", "BACKUP", "CLIPINF", "00153.clpi"), content=b"x" * 10)
    _make_file(os.path.join(base, "BDMV", "index.bdmv"), content=b"x" * 20)
    os.makedirs(os.path.join(base, "BDMV", "AUXDATA"))
    _make_file(os.path.join(root, *OTHER_MOVIE.split("/"), "movie.mkv"), content=b"x" * 300)


def test_fully_orphaned_directory_renders_as_one_collapsed_group(tmp_path):
    _make_bluebird(str(tmp_path))

    with _services(qbit_paths={OTHER_MOVIE}):
        response = TestClient(app).post("/orphans/scan")

    region = _table_region(response.text, "download-table")
    assert f'data-path="{BLUEBIRD}"' in region
    assert 'data-size-bytes="5030"' in region
    assert "(3 files)" in region
    assert 'class="orphan-unit orphan-group"' in region  # collapsed: no "expanded"
    assert region.count('class="group-child"') == 3
    assert main._group_cache[BLUEBIRD].size_bytes == 5030


def test_group_children_show_paths_relative_to_group_root(tmp_path):
    _make_bluebird(str(tmp_path))

    with _services(qbit_paths={OTHER_MOVIE}):
        response = TestClient(app).post("/orphans/scan")

    region = _table_region(response.text, "download-table")
    assert "BDMV/BACKUP/CLIPINF/00153.clpi" in region
    assert f"{BLUEBIRD}/BDMV/BACKUP/CLIPINF/00153.clpi" not in region


def test_group_does_not_swallow_a_still_tracked_sibling(tmp_path):
    _make_bluebird(str(tmp_path))

    with _services(qbit_paths={OTHER_MOVIE}):
        response = TestClient(app).post("/orphans/scan")

    assert "Other.Movie" not in _table_region(response.text, "download-table")


def test_standalone_orphans_still_render_as_ordinary_units(tmp_path):
    import os
    _make_file(os.path.join(str(tmp_path), "torrents", "seed.mkv"), content=b"x" * 5000)

    with _services():
        response = TestClient(app).post("/orphans/scan")

    region = _table_region(response.text, "download-table")
    assert '<tbody class="orphan-unit" data-path="torrents/seed.mkv" data-size-bytes="5000">' in region
    assert "orphan-group" not in region
    assert main._group_cache == {}


def test_needs_review_rows_are_never_grouped(tmp_path):
    import os
    root = str(tmp_path)
    _make_file(os.path.join(root, "media", "movies", "Film (2020)", "a.mkv"))
    _make_file(os.path.join(root, "media", "movies", "Film (2020)", "b.mkv"))

    with _services():
        response = TestClient(app).post("/orphans/scan")

    region = _table_region(response.text, "review-table")
    assert "a.mkv" in region and "b.mkv" in region
    assert "orphan-group" not in region
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd app && python3 -m pytest test_orphans_routes.py -q`
Expected: the 5 new tests FAIL. Examples: `AttributeError: module 'main' has no attribute '_group_cache'`, or `"(3 files)"` not in region.

- [ ] **Step 3: Implement the backend**

In `app/main.py`:

Add `import hashlib` to the stdlib imports. Add `from grouping import OrphanGroup, group_download_orphans` after `from inode_scan import scan`.

Below `_scan_cache` (line 43):

```python
_group_cache: dict[str, OrphanGroup] = {}
```

In `run_scan`, replace:

```python
    _scan_cache.clear()
    for c in candidates:
        _scan_cache[c.inode] = c
```

with:

```python
    _scan_cache.clear()
    for c in candidates:
        _scan_cache[c.inode] = c

    # Ground truth for grouping is every file found under the download
    # roots, orphaned or not: download_only covers both orphans and files
    # qBit/*arr still track, and linked files that happen to live under a
    # download root are real contents of those directories too.
    download_files = _flatten(result.download_only) + [
        p for p in result.linked
        if any(p == sub or p.startswith(sub + "/") for sub in DOWNLOAD_SUBDIRS)
    ]
    groups, _ = group_download_orphans(
        [c for c in candidates if c.category == "unlinked download"],
        download_files,
        set(DOWNLOAD_SUBDIRS),
    )
    _group_cache.clear()
    for g in groups:
        _group_cache[g.root] = g
```

Replace `_enrich_candidate` with this version (adds `kind`), and add the group helpers right after it:

```python
def _enrich_candidate(c: OrphanCandidate) -> dict:
    return {
        "kind": "file",
        "inode": c.inode,
        "display_path": c.paths[0],
        "extra_paths": len(c.paths) - 1,
        "category": c.category,
        "size_gb": _format_gb(c.size_bytes),
        "size_bytes": c.size_bytes,
    }


def _group_dom_id(root: str) -> str:
    """Stable, attribute-safe element id for a group - root paths contain
    spaces, brackets and dots that can't go in an id selector as-is."""
    return "orphan-group-" + hashlib.sha1(root.encode()).hexdigest()[:12]


def _enrich_group(g: OrphanGroup) -> dict:
    return {
        "kind": "group",
        "root": g.root,
        "dom_id": _group_dom_id(g.root),
        "display_path": g.root + "/",
        "file_count": len(g.members),
        "size_bytes": g.size_bytes,
        "size_gb": _format_gb(g.size_bytes),
        "children": [
            {
                **_enrich_candidate(m),
                "display_path": os.path.relpath(m.paths[0], g.root),
                "is_child": True,
            }
            for m in g.members
        ],
    }


def _download_units(download_candidates: list[dict]) -> list[dict]:
    """Unlinked Downloads table rows: one unit per cached group, plus
    every candidate that isn't a member of any group."""
    grouped = {m.inode for g in _group_cache.values() for m in g.members}
    units = [_enrich_group(g) for g in _group_cache.values()]
    units += [c for c in download_candidates if c["inode"] not in grouped]
    return units
```

Rename the key in `_EMPTY_ORPHANS_CONTEXT`:

```python
_EMPTY_ORPHANS_CONTEXT = {"download_units": [], "review_candidates": [], "status_lines": []}
```

In `orphans_scan`, replace the context entry `"download_candidates": download_candidates,` with `"download_units": _download_units(download_candidates),`.

- [ ] **Step 4: Implement the templates**

Replace `app/templates/_orphan_row.html` with:

```html
<tr id="orphan-row-{{ c.inode }}"{% if c.is_child %} class="group-child"{% endif %} data-path="{{ c.display_path }}" data-size-bytes="{{ c.size_bytes }}">
  <td><input type="checkbox" name="inodes" value="{{ c.inode }}" class="orphan-cb"></td>
  <td>{{ c.display_path }}{% if c.extra_paths > 0 %} (+{{ c.extra_paths }} more){% endif %}</td>
  <td>{{ c.size_gb }} GB</td>
  <td>
    <button hx-delete="/orphans/{{ c.inode }}"
            hx-target="#orphan-row-{{ c.inode }}"
            hx-swap="outerHTML"
            hx-confirm="Delete {{ c.display_path }}?"
            hx-disabled-elt="this">
      Delete
    </button>
  </td>
</tr>
```

Create `app/templates/_orphan_group.html`. The Delete button's `hx-post` target route comes in Task 4. Until then the button is inert in tests.

```html
<tbody id="{{ g.dom_id }}" class="orphan-unit orphan-group" data-path="{{ g.root }}" data-size-bytes="{{ g.size_bytes }}">
  <tr class="group-header">
    <td><input type="checkbox" name="group_roots" value="{{ g.root }}" class="orphan-cb"></td>
    <td>
      <button type="button" class="group-toggle" aria-expanded="false" title="Show files">&#9656;</button>
      {{ g.display_path }} <span class="group-count">({{ g.file_count }} files)</span>
    </td>
    <td>{{ g.size_gb }} GB</td>
    <td>
      <button class="group-delete"
              hx-post="/orphans/groups/delete"
              hx-vals='{"root": {{ g.root|tojson }}}'
              hx-target="#{{ g.dom_id }}"
              hx-swap="outerHTML"
              hx-confirm="Delete all {{ g.file_count }} files under {{ g.display_path }}?"
              hx-disabled-elt="this">
        Delete
      </button>
    </td>
  </tr>
  {% for c in g.children %}
    {% include "_orphan_row.html" %}
  {% endfor %}
</tbody>
```

(`tojson` HTML-escapes `'`, so a root containing an apostrophe can't break out of the single-quoted `hx-vals` attribute.)

In `app/templates/orphans.html`:

1. Add to the `<style>` block, after the `button[hx-delete]:hover` rule:

```css
    button.group-delete { padding: 4px 10px; background: var(--danger); color: white; border: none; border-radius: 4px; cursor: pointer; }
    button.group-delete:hover { background: var(--danger-hover); }
    .group-toggle { background: none; border: none; color: var(--accent); cursor: pointer; font-size: 1em; padding: 0 6px 0 0; }
    .orphan-group.expanded .group-toggle { display: inline-block; transform: rotate(90deg); }
    .group-count { color: var(--text-muted); }
    .orphan-group:not(.expanded) tr.group-child { display: none; }
    tr.group-child td:nth-child(2) { padding-left: 36px; color: var(--text-muted); }
```

2. Replace the download table's `<tbody>...</tbody>` with:

```html
      {% for u in download_units %}
        {% if u.kind == "group" %}
          {% set g = u %}{% include "_orphan_group.html" %}
        {% else %}
          {% set c = u %}
          <tbody class="orphan-unit" data-path="{{ c.display_path }}" data-size-bytes="{{ c.size_bytes }}">
            {% include "_orphan_row.html" %}
          </tbody>
        {% endif %}
      {% endfor %}
```

3. Replace the review table's `<tbody>...</tbody>` with:

```html
        {% for c in review_candidates %}
          <tbody class="orphan-unit" data-path="{{ c.display_path }}" data-size-bytes="{{ c.size_bytes }}">
            {% include "_orphan_row.html" %}
          </tbody>
        {% endfor %}
```

4. In the `<script>`, update the comment above `sortStates` and replace `cellValue` and `applySort` so they sort whole units. That keeps a group's children attached to it:

```js
  // Default sort: size descending, so the real space-hogs surface above
  // the sea of near-zero metadata-file rows. Each table "unit" (a single
  // orphan, or a whole group with its hidden child rows) is its own
  // <tbody>, and units are what get sorted - sorting bare <tr>s would
  // scatter a group's children away from its header row. Download and
  // Review tables sort independently of each other.
  var sortStates = {
    'download-table': { column: 'size', dir: 'desc' },
    'review-table': { column: 'size', dir: 'desc' }
  };

  function cellValue(unit, column) {
    if (column === 'size') { return parseInt(unit.dataset.sizeBytes, 10) || 0; }
    return unit.dataset.path || '';
  }

  function applySort(tableId) {
    var state = sortStates[tableId];
    var table = document.getElementById(tableId);
    if (!table) { return; }
    var units = Array.prototype.slice.call(table.querySelectorAll(':scope > tbody.orphan-unit'));
    units.sort(function (a, b) {
      var av = cellValue(a, state.column), bv = cellValue(b, state.column);
      var cmp = av < bv ? -1 : av > bv ? 1 : 0;
      return state.dir === 'desc' ? -cmp : cmp;
    });
    units.forEach(function (unit) { table.appendChild(unit); });

    table.querySelectorAll('th[data-sort]').forEach(function (th) {
      th.classList.remove('sort-asc', 'sort-desc');
      if (th.dataset.sort === state.column) { th.classList.add('sort-' + state.dir); }
    });
  }
```

5. In the same `<script>`, add the expand/collapse handler immediately after the existing `document.addEventListener('click', ...)` sort handler:

```js
  document.addEventListener('click', function (e) {
    var toggle = e.target.closest('.group-toggle');
    if (!toggle) { return; }
    var group = toggle.closest('tbody.orphan-group');
    var expanded = group.classList.toggle('expanded');
    toggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    toggle.title = expanded ? 'Hide files' : 'Show files';
  });
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd app && python3 -m pytest -q`
Expected: 128 passed. The existing tests still pass: `data-size-bytes`/`data-path` still appear on both the `<tr>` and its unit `<tbody>`, and `id="select-all-download"`/`id="download-form"` are unchanged.

- [ ] **Step 6: Commit**

```bash
git add app/main.py app/templates/_orphan_group.html app/templates/_orphan_row.html app/templates/orphans.html app/test_orphans_routes.py
git commit -m "feat: render fully-orphaned download directories as collapsible groups

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Group delete route

**Files:**
- Modify: `app/main.py` (import `prune_empty_tree`; new helper and route after `delete_single_orphan`)
- Test: `app/test_orphans_routes.py`

**Interfaces:**
- Consumes: `_group_cache`, `_group_dom_id` (Task 3); `prune_empty_tree` (Task 2); existing `run_scan`, `_delete_candidate`, `_boundary_for`, `_current_data_root`.
- Produces:
  - `main._delete_group(data_root: str, group: OrphanGroup, fresh: list[OrphanCandidate]) -> tuple[int, int, int]` returns `(deleted, failed, skipped)`. Task 5 reuses it.
  - Route `POST /orphans/groups/delete`, form field `root: str`. On full success it returns 200 with an empty body, which removes the group's tbody. Otherwise it returns a replacement `<tbody id="{dom_id}">` with a one-cell message row.

- [ ] **Step 1: Write the failing tests**

Append to `app/test_orphans_routes.py`:

```python
def test_group_delete_removes_every_file_and_the_emptied_tree(tmp_path):
    import os
    root = str(tmp_path)
    _make_bluebird(root)

    with _services(qbit_paths={OTHER_MOVIE}):
        client = TestClient(app)
        client.post("/orphans/scan")
        response = client.post("/orphans/groups/delete", data={"root": BLUEBIRD})

    assert response.status_code == 200
    assert response.text == ""
    assert not os.path.exists(os.path.join(root, *BLUEBIRD.split("/")))  # incl. empty AUXDATA/
    assert os.path.exists(os.path.join(root, *OTHER_MOVIE.split("/"), "movie.mkv"))


def test_group_delete_is_best_effort_and_survivors_come_back_standalone(tmp_path):
    import os
    root = str(tmp_path)
    _make_bluebird(root)
    clpi = os.path.join(root, *BLUEBIRD.split("/"), "BDMV", "BACKUP", "CLIPINF", "00153.clpi")
    real_delete = main.delete_orphan

    def flaky_delete(data_root, relative_path, boundary):
        if relative_path.endswith("00153.clpi"):
            raise OSError("permission denied")
        return real_delete(data_root, relative_path, boundary)

    with _services(qbit_paths={OTHER_MOVIE}):
        client = TestClient(app)
        client.post("/orphans/scan")
        with patch("main.delete_orphan", side_effect=flaky_delete):
            response = client.post("/orphans/groups/delete", data={"root": BLUEBIRD})
        rescan = client.post("/orphans/scan")

    assert "1 of 3 deletes failed" in response.text
    assert f'id="{main._group_dom_id(BLUEBIRD)}"' in response.text
    assert os.path.exists(clpi)
    assert not os.path.exists(os.path.join(root, *BLUEBIRD.split("/"), "BDMV", "STREAM"))

    region = _table_region(rescan.text, "download-table")
    assert f"{BLUEBIRD}/BDMV/BACKUP/CLIPINF/00153.clpi" in region  # full path, standalone
    assert "orphan-group" not in region


def test_group_delete_skips_members_that_are_no_longer_orphans(tmp_path):
    import os
    root = str(tmp_path)
    _make_bluebird(root)

    with _services(qbit_paths={OTHER_MOVIE}):
        client = TestClient(app)
        client.post("/orphans/scan")
    # Between scan and click, the torrent was re-added in qBittorrent.
    with _services(qbit_paths={OTHER_MOVIE, BLUEBIRD}):
        response = client.post("/orphans/groups/delete", data={"root": BLUEBIRD})

    assert response.status_code == 200
    assert "no longer" in response.text.lower()
    assert os.path.exists(os.path.join(root, *BLUEBIRD.split("/"), "BDMV", "STREAM", "00000.m2ts"))
    # A live torrent's empty subdirs are left alone too.
    assert os.path.isdir(os.path.join(root, *BLUEBIRD.split("/"), "BDMV", "AUXDATA"))


def test_group_delete_with_unknown_root_deletes_nothing(tmp_path):
    import os
    root = str(tmp_path)
    _make_bluebird(root)

    with _services(qbit_paths={OTHER_MOVIE}):
        client = TestClient(app)
        client.post("/orphans/scan")
        stale = client.post("/orphans/groups/delete", data={"root": "torrents/completed/radarr"})
        forged = client.post("/orphans/groups/delete", data={"root": "../../etc"})

    assert stale.status_code == 200 and stale.text == ""
    assert forged.status_code == 200 and forged.text == ""
    assert os.path.exists(os.path.join(root, *BLUEBIRD.split("/"), "BDMV", "STREAM", "00000.m2ts"))


def test_group_delete_reports_reverify_failure_without_deleting(tmp_path):
    import os
    root = str(tmp_path)
    _make_bluebird(root)

    with _services(qbit_paths={OTHER_MOVIE}):
        client = TestClient(app)
        client.post("/orphans/scan")
        with patch("main.run_scan", side_effect=RuntimeError("disk fell off")):
            response = client.post("/orphans/groups/delete", data={"root": BLUEBIRD})

    assert "Re-verify failed" in response.text
    assert os.path.exists(os.path.join(root, *BLUEBIRD.split("/"), "BDMV", "index.bdmv"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd app && python3 -m pytest test_orphans_routes.py -q -k group_delete`
Expected: 5 FAIL. FastAPI answers 404 or 405 for the unknown route.

- [ ] **Step 3: Implement**

In `app/main.py`, add `prune_empty_tree` to the `from orphans import (...)` list.

Add after `delete_single_orphan`:

```python
def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root + "/")


def _delete_group(
    data_root: str, group: OrphanGroup, fresh: list[OrphanCandidate]
) -> tuple[int, int, int]:
    """Best-effort delete of a group's members, re-verified against a
    fresh scan. Returns (deleted, failed, skipped).

    Only inodes that were members at scan time are touched - a file that
    newly appeared in the folder since then was never shown to the user
    as part of this group. A member missing from the fresh scan (tracked
    again) or that grew a hardlink outside the group root is skipped
    rather than deleted, and any skip also cancels empty-tree pruning.
    """
    fresh_by_inode = {c.inode: c for c in fresh if c.category == "unlinked download"}
    deleted = failed = skipped = 0
    for member in group.members:
        candidate = fresh_by_inode.get(member.inode)
        if candidate is None or not all(_under(p, group.root) for p in candidate.paths):
            skipped += 1
            continue
        try:
            _delete_candidate(data_root, candidate)
            deleted += 1
        except (OSError, ValueError):
            failed += 1
    # A skipped member means the folder is live again (torrent re-added)
    # - don't touch even its empty subdirectories.
    if not skipped:
        try:
            prune_empty_tree(data_root, group.root, _boundary_for(group.root))
        except (OSError, ValueError):
            pass
    return deleted, failed, skipped


def _group_message(dom_id: str, message: str, error: bool = False) -> Response:
    style = ' style="color:red"' if error else ""
    return Response(
        status_code=200,
        media_type="text/html",
        content=f'<tbody id="{dom_id}"><tr><td colspan="4"{style}>{escape(message)}</td></tr></tbody>',
    )


@app.post("/orphans/groups/delete")
async def delete_orphan_group(root: str = Form(...)):
    # The posted root is only a cache key - never a filesystem path. An
    # unknown root (stale page, or anything hand-crafted) deletes nothing.
    group = _group_cache.get(root)
    if group is None:
        return Response(status_code=200, content="")
    dom_id = _group_dom_id(root)

    try:
        fresh, _ = await asyncio.to_thread(run_scan)
    except Exception as e:
        return _group_message(dom_id, f"Re-verify failed: {e}", error=True)

    deleted, failed, skipped = _delete_group(_current_data_root(), group, fresh)
    total = len(group.members)
    if failed:
        return _group_message(dom_id, f"{failed} of {total} deletes failed — check logs", error=True)
    if skipped:
        return _group_message(dom_id, f"Deleted {deleted}; {skipped} no longer orphans — skipped")
    return Response(status_code=200, content="")
```

Add `from html import escape` to the stdlib imports at the top of `main.py`. The message includes exception text, and this is hand-built HTML outside Jinja's autoescaping.

`_delete_group` reads `group.members` from the pre-scan object. `run_scan()` inside the route rebuilds `_group_cache`, but the local `group` reference captured before the scan is unaffected.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd app && python3 -m pytest -q`
Expected: 133 passed.

- [ ] **Step 5: Commit**

```bash
git add app/main.py app/test_orphans_routes.py
git commit -m "feat: delete a whole orphan group best-effort after re-verifying

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Bulk delete with group checkboxes

**Files:**
- Modify: `app/main.py` (`bulk_delete_orphans`)
- Modify: `app/templates/orphans.html` (download form button, select-all script)
- Test: `app/test_orphans_routes.py`

**Interfaces:**
- Consumes: `_group_cache`, `_delete_group` (Tasks 3-4).
- Produces: `POST /orphans/delete` accepts form fields `inodes: list[int]` and `group_roots: list[str]`. Both are optional and default to empty. The redirect and flash behavior is unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `app/test_orphans_routes.py`:

```python
def test_download_form_has_a_bulk_delete_button(tmp_path):
    with _services():
        response = TestClient(app).post("/orphans/scan")

    start = response.text.index('id="download-form"')
    form = response.text[start:response.text.index("</form>", start)]
    assert 'id="bulk-delete-btn"' in form
    assert 'type="submit"' in form


def test_bulk_delete_accepts_a_group_root(tmp_path):
    import os
    root = str(tmp_path)
    _make_bluebird(root)

    with _services(qbit_paths={OTHER_MOVIE}):
        client = TestClient(app, follow_redirects=False)
        client.post("/orphans/scan")
        response = client.post("/orphans/delete", data={"group_roots": [BLUEBIRD]})

    assert response.status_code == 302
    assert "flash=" not in response.headers["location"]
    assert not os.path.exists(os.path.join(root, *BLUEBIRD.split("/")))


def test_bulk_delete_with_group_and_its_child_both_checked_deletes_once(tmp_path):
    """The child's inode is also a group member - deleting it twice would
    fail the second time and flash a spurious 'deletes failed'."""
    import os
    root = str(tmp_path)
    _make_bluebird(root)

    with _services(qbit_paths={OTHER_MOVIE}):
        client = TestClient(app, follow_redirects=False)
        client.post("/orphans/scan")
        child_inode = main._group_cache[BLUEBIRD].members[0].inode
        response = client.post(
            "/orphans/delete",
            data={"group_roots": [BLUEBIRD], "inodes": [str(child_inode)]},
        )

    assert response.status_code == 302
    assert "flash=" not in response.headers["location"]
    assert not os.path.exists(os.path.join(root, *BLUEBIRD.split("/")))


def test_bulk_delete_with_nothing_selected_is_a_no_op_redirect(tmp_path):
    with _services():
        client = TestClient(app, follow_redirects=False)
        client.post("/orphans/scan")
        response = client.post("/orphans/delete", data={})

    assert response.status_code == 302
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd app && python3 -m pytest test_orphans_routes.py -q -k "bulk"`
Expected: the 4 new tests FAIL. The existing required `inodes` field gives 422 for group-only or empty posts, and there's no `bulk-delete-btn` in the form.

- [ ] **Step 3: Implement the route**

Replace `bulk_delete_orphans` in `app/main.py` with:

```python
@app.post("/orphans/delete")
async def bulk_delete_orphans(
    inodes: list[int] = Form(default=[]),
    group_roots: list[str] = Form(default=[]),
):
    # Resolve groups BEFORE the re-verify scan - run_scan rebuilds
    # _group_cache, and membership has to be what the user was shown.
    groups = [_group_cache[r] for r in group_roots if r in _group_cache]
    try:
        fresh_candidates, _ = await asyncio.to_thread(run_scan)
        fresh_by_inode = {c.inode: c for c in fresh_candidates}
    except Exception:
        return RedirectResponse(
            url=f"/orphans?flash={quote('Re-verify scan failed — no files deleted')}",
            status_code=302,
        )

    data_root = _current_data_root()
    failed = 0
    attempted = 0
    handled: set[int] = set()
    for group in groups:
        _, group_failed, _ = _delete_group(data_root, group, fresh_candidates)
        failed += group_failed
        attempted += len(group.members)
        handled.update(m.inode for m in group.members)

    for inode in dict.fromkeys(inodes):
        if inode in handled:
            continue
        attempted += 1
        candidate = fresh_by_inode.get(inode)
        if candidate is None:
            continue
        try:
            _delete_candidate(data_root, candidate)
        except (OSError, ValueError):
            failed += 1

    if failed:
        msg = quote(f"{failed} of {attempted} deletes failed — check logs")
        return RedirectResponse(url=f"/orphans?flash={msg}", status_code=302)

    return RedirectResponse(url="/orphans", status_code=302)
```

- [ ] **Step 4: Implement the template**

In `app/templates/orphans.html`, inside `<form ... id="download-form">`, add immediately before `<table id="download-table">`:

```html
    <p><button type="submit" id="bulk-delete-btn" disabled
               onclick="return confirm('Delete every selected file and folder?');">Delete selected</button></p>
```

In the `<script>`, add after the group-toggle click handler from Task 3:

```js
  // Select-all and the bulk button for Unlinked Downloads. The group
  // checkbox (name="group_roots") and child checkboxes (name="inodes") are
  // independent; the server de-duplicates a file selected both ways.
  function refreshBulkButton() {
    var btn = document.getElementById('bulk-delete-btn');
    if (!btn) { return; }
    btn.disabled = !document.querySelector('#download-table .orphan-cb:checked');
  }

  document.addEventListener('change', function (e) {
    if (e.target.id === 'select-all-download') {
      document.querySelectorAll('#download-table .orphan-cb').forEach(function (cb) {
        cb.checked = e.target.checked;
      });
    }
    if (e.target.closest('#download-table')) { refreshBulkButton(); }
  });

  document.addEventListener('htmx:afterSwap', refreshBulkButton);
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd app && python3 -m pytest -q`
Expected: 137 passed. The existing `test_bulk_delete_orphans` and `test_bulk_delete_reports_failures_via_flash_instead_of_silently_dropping_them` still pass unchanged.

- [ ] **Step 6: Commit**

```bash
git add app/main.py app/templates/orphans.html app/test_orphans_routes.py
git commit -m "feat: bulk-delete orphan groups, wire the missing bulk button and select-all

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Verify on the real NAS

No code. This is the spec's existing real-NAS-scan checklist plus the grouping checks. Deploy the branch before merging, following the established branch-first, merge-last order.

- [ ] **Step 1: Deploy the branch**

Run the preflight `nc -z -G 2 192.168.1.30 22`, then:

```bash
rsync -a --exclude __pycache__ --exclude .pytest_cache --rsync-path=/usr/bin/rsync app/ TerraFermi:/volume1/docker/qbit-prunarr/app/
```

Mike rebuilds, in `/volume1/docker/projects/qbit-prunarr-compose`:

```bash
sudo docker rm -f qbit-prunarr; sudo docker compose build --no-cache && sudo docker compose up -d
```

- [ ] **Step 2: Scan and check in a browser** at `http://TerraFermi:8585/orphans`

- All four services report `ok`.
- If `BIG_TRBL_LTL_CHN_BLUEBIRD` still exists, it shows as one row with about 38 GB and "(N files)", collapsed. If it's been deleted since 2026-09-20, pick any other multi-file group that appears.
- The expand toggle reveals relative paths. Check whether a flat list of about 300 BDMV paths reads clearly. The spec asks for this to be watched, so note the answer for a possible v2 tree view.
- Size sort, ascending and descending, keeps each group's children attached to it.
- Select-all enables the "Delete selected" button. Unchecking everything disables it again.
- Needs Review looks unchanged.

- [ ] **Step 3: Delete one real group** (Mike's call on which one) with its row's Delete button. Rescan and confirm the folder is gone from disk and from the table.
