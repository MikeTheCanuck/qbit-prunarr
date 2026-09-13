# Orphan Trawler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `/orphans` page to qbit-prunarr that finds files orphaned by
broken hardlinks between `media/` and `torrents/`+`usenet/` on TerraFermi, and
lets Mike review and delete them through an approval-queue UI.

**Architecture:** New pure-logic modules (`inode_scan.py`, `pathmap.py`,
`orphans.py`) handle filesystem scanning and classification with no I/O
side effects beyond stat/delete calls, fully unit-testable without a real
NAS. New thin API-client modules (`sonarr.py`, `radarr.py`, `plex.py`, plus
an addition to the existing `qbit.py`) each expose one method that returns
a set of file paths the service currently knows about. `main.py` wires it
together: a scan route builds an in-memory candidate list, a delete route
re-verifies each candidate against fresh data before removing it.

**Tech Stack:** FastAPI, Jinja2, HTMX 2.0.3, httpx, pytest + pytest-httpx —
all already in use by this app, no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-06-orphan-trawler-design.md`

## Global Constraints

- Python 3.11 (per `app/Dockerfile`'s `python:3.11-slim` base) — use only
  stdlib + already-vendored packages (`httpx`, `fastapi`, `jinja2`,
  `python-multipart`), no new entries in `requirements.txt`.
- One file per external service client (`qbit.py`, `sonarr.py`, `radarr.py`,
  `plex.py`), matching the existing `qbit.py` convention: a class with
  `__init__`, `__enter__`/`__exit__`/`close()`, and one httpx `Client`.
- Tests live next to the code they test in `app/` (`test_<module>.py`), not
  in a separate `tests/` directory — matches `test_main.py`/`test_qbit.py`.
- Route handlers never raise past FastAPI — every route catches and returns
  a 200 with an inline error (existing pattern in `main.py`'s
  `delete_torrent`/`index`), because HTMX only swaps on a 2xx response.
- **Fail closed**: any external API (Sonarr/Radarr/Plex/qBittorrent) that
  errors or isn't configured must make its files "keep, uncertain," never
  "orphan." This applies in every classification function below.
- v1 media scope is fixed to `media/movies`, `media/movies-no-backup`,
  `media/tv`, `media/tv-no-backup`. Download scope is `torrents/` and
  `usenet/` (all subfolders, walked recursively). No other subdirectories
  of `media/` are touched.

---

### Task 1: Inode-based filesystem scan

**Files:**
- Create: `app/inode_scan.py`
- Test: `app/test_inode_scan.py`

**Interfaces:**
- Consumes: nothing (stdlib `os` only)
- Produces: `ScanResult` dataclass with fields `linked: set[str]`,
  `media_only: dict[int, list[str]]`, `download_only: dict[int, list[str]]`
  (paths are relative to `data_root`, using OS-native separators).
  `scan(data_root: str, media_subdirs: list[str], download_subdirs: list[str]) -> ScanResult`.
  Later tasks import `ScanResult` and call `scan(...)`.

This is the core matching mechanism from the spec: filenames don't match
between the two sides, but hardlinked files share an inode number, so we
walk both trees and group by `st_ino`.

- [ ] **Step 1: Write the failing tests**

```python
# app/test_inode_scan.py
"""Tests for inode-based hardlink scanning."""
import os

from inode_scan import scan


def _make_file(path: str, content: bytes = b"x") -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)


def test_linked_file_is_not_flagged(tmp_path):
    root = str(tmp_path)
    media_path = os.path.join(root, "media", "movies", "Movie (2020)", "movie.mkv")
    download_path = os.path.join(root, "torrents", "completed", "movie.mkv")
    _make_file(media_path, b"movie-bytes")
    os.link(media_path, download_path)

    result = scan(root, ["media/movies"], ["torrents"])

    assert any(p.endswith("movie.mkv") for p in result.linked)
    assert result.media_only == {}
    assert result.download_only == {}


def test_media_only_file_is_flagged(tmp_path):
    root = str(tmp_path)
    media_path = os.path.join(root, "media", "movies", "Solo (2020)", "solo.mkv")
    _make_file(media_path)

    result = scan(root, ["media/movies"], ["torrents"])

    assert len(result.media_only) == 1
    paths = next(iter(result.media_only.values()))
    assert any(p.endswith("solo.mkv") for p in paths)
    assert result.download_only == {}


def test_download_only_file_is_flagged(tmp_path):
    root = str(tmp_path)
    download_path = os.path.join(root, "torrents", "completed", "seed.mkv")
    _make_file(download_path)

    result = scan(root, ["media/movies"], ["torrents"])

    assert len(result.download_only) == 1
    paths = next(iter(result.download_only.values()))
    assert any(p.endswith("seed.mkv") for p in paths)
    assert result.media_only == {}


def test_multiple_media_subdirs_are_all_walked(tmp_path):
    root = str(tmp_path)
    _make_file(os.path.join(root, "media", "tv", "Show", "ep1.mkv"))
    _make_file(os.path.join(root, "media", "tv-no-backup", "Other", "ep1.mkv"))

    result = scan(root, ["media/tv", "media/tv-no-backup"], ["torrents"])

    assert len(result.media_only) == 2


def test_missing_directory_is_treated_as_empty(tmp_path):
    root = str(tmp_path)
    os.makedirs(os.path.join(root, "media"))
    # "media/movies" does not exist at all

    result = scan(root, ["media/movies"], ["torrents"])

    assert result.linked == set()
    assert result.media_only == {}
    assert result.download_only == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd app && python3 -m pytest test_inode_scan.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'inode_scan'`

- [ ] **Step 3: Write the implementation**

```python
# app/inode_scan.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd app && python3 -m pytest test_inode_scan.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add app/inode_scan.py app/test_inode_scan.py
git commit -m "feat: add inode-based hardlink scan for orphan detection"
```

---

### Task 2: Path-prefix normalization

**Files:**
- Create: `app/pathmap.py`
- Test: `app/test_pathmap.py`

**Interfaces:**
- Consumes: nothing
- Produces: `to_relative(raw_path: str, prefix: str) -> str`. Later tasks
  (Sonarr/Radarr/Plex/qBit clients) call this to normalize paths reported
  by each external service into paths relative to the shared data root,
  so they can be compared against `inode_scan`'s output.

Sonarr, Radarr, Plex, and qBittorrent each run in their own container and
may be bind-mounted to the same underlying files at a different mount
point than this app's `/data`. (This exact problem was already flagged in
a prior tool's design notes: "Cleanuparr needs to know what qBittorrent
calls /downloads maps to on the actual filesystem.") Each service gets its
own configurable prefix to strip.

- [ ] **Step 1: Write the failing tests**

```python
# app/test_pathmap.py
"""Tests for path-prefix normalization."""
from pathmap import to_relative


def test_strips_matching_prefix():
    assert to_relative("/downloads/completed/movie.mkv", "/downloads") == "completed/movie.mkv"


def test_no_prefix_strips_leading_slash_only():
    assert to_relative("/data/media/movies/movie.mkv", "") == "data/media/movies/movie.mkv"


def test_prefix_equal_to_whole_path():
    assert to_relative("/downloads", "/downloads") == ""


def test_trailing_slash_on_prefix_is_tolerated():
    assert to_relative("/downloads/movie.mkv", "/downloads/") == "movie.mkv"


def test_non_matching_prefix_only_strips_leading_slash():
    assert to_relative("/other/movie.mkv", "/downloads") == "other/movie.mkv"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd app && python3 -m pytest test_pathmap.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pathmap'`

- [ ] **Step 3: Write the implementation**

```python
# app/pathmap.py
"""Path-prefix normalization for comparing paths across containers.

Different containers can be bind-mounted to the same underlying files at
different mount points (e.g. qBittorrent sees "/downloads/completed/x.mkv"
for a file this app sees as "/data/torrents/completed/x.mkv"). Stripping
each service's own prefix makes paths comparable regardless of mount point.
"""


def to_relative(raw_path: str, prefix: str) -> str:
    """Strip prefix from raw_path, returning a path relative to the shared root."""
    prefix = prefix.rstrip("/")
    if prefix and raw_path == prefix:
        return ""
    if prefix and raw_path.startswith(prefix + "/"):
        return raw_path[len(prefix) + 1 :]
    return raw_path.lstrip("/")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd app && python3 -m pytest test_pathmap.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add app/pathmap.py app/test_pathmap.py
git commit -m "feat: add path-prefix normalization for cross-container comparison"
```

---

### Task 3: Orphan classification

**Files:**
- Create: `app/orphans.py`
- Test: `app/test_orphans.py`

**Interfaces:**
- Consumes: `inode_scan.ScanResult`, `inode_scan.scan` (Task 1)
- Produces: `OrphanCandidate` dataclass with fields `inode: int`,
  `paths: list[str]`, `category: str`, `size_bytes: int`.
  `classify_download_orphans(result: ScanResult, data_root: str, qbit_paths: set[str] | None) -> list[OrphanCandidate]`.
  `classify_media_orphans(result: ScanResult, data_root: str, tv_subdirs: set[str], sonarr_paths: set[str] | None, radarr_paths: set[str] | None, plex_episode_paths: set[str] | None, plex_movie_paths: set[str] | None) -> list[OrphanCandidate]`.
  Later tasks (main.py routes) call both and concatenate the results.

This function takes **already-normalized** path sets (relative to
`data_root`, prefix already stripped by `pathmap.to_relative`) — it does
no normalization itself, keeping it trivially testable with plain sets.

- [ ] **Step 1: Write the failing tests**

```python
# app/test_orphans.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd app && python3 -m pytest test_orphans.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'orphans'`

- [ ] **Step 3: Write the implementation**

```python
# app/orphans.py
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
        is_tv = any(p.split(os.sep, 1)[0] in tv_subdirs for p in paths)
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd app && python3 -m pytest test_orphans.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add app/orphans.py app/test_orphans.py
git commit -m "feat: add orphan classification with fail-closed API handling"
```

---

### Task 4: Orphan deletion

**Files:**
- Modify: `app/orphans.py`
- Modify: `app/test_orphans.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `delete_orphan(data_root: str, relative_path: str) -> None`.
  Task 9 (delete routes) calls this after re-verification.

Deletes the file and prunes now-empty parent directories back up to (but
never including) `data_root`, so a fully-emptied release folder doesn't
linger.

- [ ] **Step 1: Write the failing tests**

```python
# append to app/test_orphans.py
import pytest

from orphans import delete_orphan


def test_delete_orphan_removes_file(tmp_path):
    root = str(tmp_path)
    path = os.path.join(root, "torrents", "seed.mkv")
    _make_file(path)

    delete_orphan(root, "torrents/seed.mkv")

    assert not os.path.exists(path)


def test_delete_orphan_prunes_empty_parent_dirs(tmp_path):
    root = str(tmp_path)
    path = os.path.join(root, "torrents", "Some Release", "seed.mkv")
    _make_file(path)

    delete_orphan(root, "torrents/Some Release/seed.mkv")

    assert not os.path.exists(os.path.join(root, "torrents", "Some Release"))
    # data_root itself and its direct "torrents" child must not be touched
    assert os.path.isdir(os.path.join(root, "torrents"))


def test_delete_orphan_stops_pruning_at_nonempty_dir(tmp_path):
    root = str(tmp_path)
    _make_file(os.path.join(root, "torrents", "Pack", "keep.mkv"))
    target = os.path.join(root, "torrents", "Pack", "seed.mkv")
    _make_file(target)

    delete_orphan(root, "torrents/Pack/seed.mkv")

    assert not os.path.exists(target)
    assert os.path.isdir(os.path.join(root, "torrents", "Pack"))
    assert os.path.exists(os.path.join(root, "torrents", "Pack", "keep.mkv"))


def test_delete_orphan_missing_file_raises(tmp_path):
    root = str(tmp_path)
    os.makedirs(os.path.join(root, "torrents"))

    with pytest.raises(OSError):
        delete_orphan(root, "torrents/does-not-exist.mkv")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd app && python3 -m pytest test_orphans.py -v -k delete_orphan`
Expected: FAIL with `ImportError: cannot import name 'delete_orphan'`

- [ ] **Step 3: Write the implementation**

```python
# append to app/orphans.py

def delete_orphan(data_root: str, relative_path: str) -> None:
    """Delete an orphan file, then prune now-empty parent dirs up to data_root."""
    full_path = os.path.join(data_root, relative_path)
    os.remove(full_path)

    root = os.path.abspath(data_root)
    parent = os.path.dirname(full_path)
    while os.path.abspath(parent) != root:
        try:
            os.rmdir(parent)
        except OSError:
            break
        parent = os.path.dirname(parent)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd app && python3 -m pytest test_orphans.py -v`
Expected: 13 passed

- [ ] **Step 5: Commit**

```bash
git add app/orphans.py app/test_orphans.py
git commit -m "feat: add orphan deletion with empty-parent-dir pruning"
```

---

### Task 5: Sonarr client

**Files:**
- Create: `app/sonarr.py`
- Test: `app/test_sonarr.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `SonarrClient(base_url: str, api_key: str)` with
  `get_all_episode_paths() -> set[str]` (raw paths, as Sonarr reports
  them — not yet normalized). Task 9 wraps this with `pathmap.to_relative`.

Sonarr's `/api/v3/episodefile` requires a `seriesId` — there's no
single-call "give me every file," so this fetches the series list first,
then one `episodefile` call per series.

- [ ] **Step 1: Write the failing tests**

```python
# app/test_sonarr.py
"""Tests for SonarrClient."""
import pytest
from pytest_httpx import HTTPXMock

from sonarr import SonarrClient

BASE_URL = "http://sonarr:8989"


@pytest.fixture
def client():
    return SonarrClient(base_url=BASE_URL, api_key="key123")


def test_get_all_episode_paths_across_series(client: SonarrClient, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}/api/v3/series",
        json=[{"id": 1, "title": "Show A"}, {"id": 2, "title": "Show B"}],
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}/api/v3/episodefile?seriesId=1",
        json=[{"id": 10, "path": "/tv/Show A/ep1.mkv"}],
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}/api/v3/episodefile?seriesId=2",
        json=[{"id": 20, "path": "/tv/Show B/ep1.mkv"}, {"id": 21, "path": "/tv/Show B/ep2.mkv"}],
    )

    paths = client.get_all_episode_paths()

    assert paths == {"/tv/Show A/ep1.mkv", "/tv/Show B/ep1.mkv", "/tv/Show B/ep2.mkv"}


def test_get_all_episode_paths_no_series_returns_empty(client: SonarrClient, httpx_mock: HTTPXMock):
    httpx_mock.add_response(method="GET", url=f"{BASE_URL}/api/v3/series", json=[])

    assert client.get_all_episode_paths() == set()


def test_sends_api_key_header(client: SonarrClient, httpx_mock: HTTPXMock):
    httpx_mock.add_response(method="GET", url=f"{BASE_URL}/api/v3/series", json=[])
    client.get_all_episode_paths()

    request = httpx_mock.get_requests()[0]
    assert request.headers["x-api-key"] == "key123"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd app && python3 -m pytest test_sonarr.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sonarr'`

- [ ] **Step 3: Write the implementation**

```python
# app/sonarr.py
"""Sonarr API client."""
import httpx


class SonarrClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._session = httpx.Client(headers={"X-Api-Key": api_key})

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self) -> None:
        self._session.close()

    def get_all_episode_paths(self) -> set[str]:
        """Return every episode file path Sonarr currently tracks, across all series."""
        series_resp = self._session.get(f"{self._base_url}/api/v3/series")
        series_resp.raise_for_status()

        paths: set[str] = set()
        for series in series_resp.json():
            files_resp = self._session.get(
                f"{self._base_url}/api/v3/episodefile",
                params={"seriesId": series["id"]},
            )
            files_resp.raise_for_status()
            for f in files_resp.json():
                paths.add(f["path"])
        return paths
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd app && python3 -m pytest test_sonarr.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add app/sonarr.py app/test_sonarr.py
git commit -m "feat: add SonarrClient for episode file path lookup"
```

---

### Task 6: Radarr client

**Files:**
- Create: `app/radarr.py`
- Test: `app/test_radarr.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `RadarrClient(base_url: str, api_key: str)` with
  `get_all_movie_paths() -> set[str]` (raw paths). Task 9 wraps this with
  `pathmap.to_relative`.

Radarr's `/api/v3/movie` returns every movie in one call, each with an
embedded `movieFile.path` when downloaded — simpler than Sonarr, no
per-item follow-up call needed.

- [ ] **Step 1: Write the failing tests**

```python
# app/test_radarr.py
"""Tests for RadarrClient."""
import pytest
from pytest_httpx import HTTPXMock

from radarr import RadarrClient

BASE_URL = "http://radarr:7878"


@pytest.fixture
def client():
    return RadarrClient(base_url=BASE_URL, api_key="key456")


def test_get_all_movie_paths(client: RadarrClient, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}/api/v3/movie",
        json=[
            {"id": 1, "title": "Movie A", "hasFile": True, "movieFile": {"path": "/movies/Movie A/a.mkv"}},
            {"id": 2, "title": "Movie B", "hasFile": False},
        ],
    )

    paths = client.get_all_movie_paths()

    assert paths == {"/movies/Movie A/a.mkv"}


def test_get_all_movie_paths_empty_library(client: RadarrClient, httpx_mock: HTTPXMock):
    httpx_mock.add_response(method="GET", url=f"{BASE_URL}/api/v3/movie", json=[])

    assert client.get_all_movie_paths() == set()


def test_sends_api_key_header(client: RadarrClient, httpx_mock: HTTPXMock):
    httpx_mock.add_response(method="GET", url=f"{BASE_URL}/api/v3/movie", json=[])
    client.get_all_movie_paths()

    request = httpx_mock.get_requests()[0]
    assert request.headers["x-api-key"] == "key456"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd app && python3 -m pytest test_radarr.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'radarr'`

- [ ] **Step 3: Write the implementation**

```python
# app/radarr.py
"""Radarr API client."""
import httpx


class RadarrClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._session = httpx.Client(headers={"X-Api-Key": api_key})

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self) -> None:
        self._session.close()

    def get_all_movie_paths(self) -> set[str]:
        """Return every movie file path Radarr currently tracks."""
        resp = self._session.get(f"{self._base_url}/api/v3/movie")
        resp.raise_for_status()

        paths: set[str] = set()
        for movie in resp.json():
            movie_file = movie.get("movieFile")
            if movie_file and movie_file.get("path"):
                paths.add(movie_file["path"])
        return paths
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd app && python3 -m pytest test_radarr.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add app/radarr.py app/test_radarr.py
git commit -m "feat: add RadarrClient for movie file path lookup"
```

---

### Task 7: Plex client

**Files:**
- Create: `app/plex.py`
- Test: `app/test_plex.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `PlexClient(base_url: str, token: str)` with
  `get_all_movie_paths() -> set[str]` and
  `get_all_episode_paths() -> set[str]` (raw paths). Task 9 wraps both
  with `pathmap.to_relative`.

Plex's `/library/sections` lists libraries with a `type` (`movie` or
`show`); `/library/sections/{key}/all?type=N` (1 = movie, 4 = episode)
returns items whose `Media[].Part[].file` gives the on-disk path —
`type=4` against a *show* section flattens straight to episodes, so no
per-show follow-up call is needed here either.

- [ ] **Step 1: Write the failing tests**

```python
# app/test_plex.py
"""Tests for PlexClient."""
import pytest
from pytest_httpx import HTTPXMock

from plex import PlexClient

BASE_URL = "http://plex:32400"


@pytest.fixture
def client():
    return PlexClient(base_url=BASE_URL, token="tok789")


def _sections_response(directories):
    return {"MediaContainer": {"Directory": directories}}


def _items_response(items):
    return {"MediaContainer": {"Metadata": items}}


def test_get_all_movie_paths(client: PlexClient, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}/library/sections",
        json=_sections_response([
            {"key": "1", "type": "movie", "title": "Movies"},
            {"key": "2", "type": "show", "title": "TV"},
        ]),
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}/library/sections/1/all?type=1",
        json=_items_response([
            {"title": "Movie A", "Media": [{"Part": [{"file": "/movies/a.mkv"}]}]},
        ]),
    )

    paths = client.get_all_movie_paths()

    assert paths == {"/movies/a.mkv"}


def test_get_all_episode_paths(client: PlexClient, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}/library/sections",
        json=_sections_response([
            {"key": "1", "type": "movie", "title": "Movies"},
            {"key": "2", "type": "show", "title": "TV"},
        ]),
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}/library/sections/2/all?type=4",
        json=_items_response([
            {"title": "Ep1", "Media": [{"Part": [{"file": "/tv/Show/ep1.mkv"}]}]},
            {"title": "Ep2", "Media": [{"Part": [{"file": "/tv/Show/ep2.mkv"}]}]},
        ]),
    )

    paths = client.get_all_episode_paths()

    assert paths == {"/tv/Show/ep1.mkv", "/tv/Show/ep2.mkv"}


def test_no_libraries_returns_empty(client: PlexClient, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET", url=f"{BASE_URL}/library/sections", json=_sections_response([])
    )

    assert client.get_all_movie_paths() == set()


def test_sends_plex_token_header(client: PlexClient, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET", url=f"{BASE_URL}/library/sections", json=_sections_response([])
    )
    client.get_all_movie_paths()

    request = httpx_mock.get_requests()[0]
    assert request.headers["x-plex-token"] == "tok789"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd app && python3 -m pytest test_plex.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'plex'`

- [ ] **Step 3: Write the implementation**

```python
# app/plex.py
"""Plex API client."""
import httpx


class PlexClient:
    def __init__(self, base_url: str, token: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._session = httpx.Client(
            headers={"X-Plex-Token": token, "Accept": "application/json"}
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self) -> None:
        self._session.close()

    def _file_paths_for_section(self, section_key: str, item_type: int) -> set[str]:
        resp = self._session.get(
            f"{self._base_url}/library/sections/{section_key}/all",
            params={"type": item_type},
        )
        resp.raise_for_status()
        paths: set[str] = set()
        for item in resp.json()["MediaContainer"].get("Metadata", []):
            for media in item.get("Media", []):
                for part in media.get("Part", []):
                    if part.get("file"):
                        paths.add(part["file"])
        return paths

    def _sections_of_type(self, section_type: str) -> list[str]:
        resp = self._session.get(f"{self._base_url}/library/sections")
        resp.raise_for_status()
        directories = resp.json()["MediaContainer"].get("Directory", [])
        return [d["key"] for d in directories if d.get("type") == section_type]

    def get_all_movie_paths(self) -> set[str]:
        """Return every file path Plex has indexed across all movie libraries."""
        paths: set[str] = set()
        for key in self._sections_of_type("movie"):
            paths |= self._file_paths_for_section(key, item_type=1)
        return paths

    def get_all_episode_paths(self) -> set[str]:
        """Return every file path Plex has indexed across all TV show libraries."""
        paths: set[str] = set()
        for key in self._sections_of_type("show"):
            paths |= self._file_paths_for_section(key, item_type=4)
        return paths
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd app && python3 -m pytest test_plex.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add app/plex.py app/test_plex.py
git commit -m "feat: add PlexClient for movie and episode path lookup"
```

---

### Task 8: qBittorrent client — content paths

**Files:**
- Modify: `app/qbit.py`
- Modify: `app/test_qbit.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `QBitClient.get_all_content_paths() -> set[str]` (raw paths,
  qBittorrent's `content_path` field). Task 9 wraps this with
  `pathmap.to_relative`.

- [ ] **Step 1: Write the failing test**

```python
# append to app/test_qbit.py

def test_get_all_content_paths(client: QBitClient, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}/api/v2/torrents/info",
        json=[
            {"name": "A", "hash": "h1", "content_path": "/downloads/completed/a.mkv"},
            {"name": "B", "hash": "h2", "content_path": "/downloads/completed/b.mkv"},
        ],
    )

    paths = client.get_all_content_paths()

    assert paths == {"/downloads/completed/a.mkv", "/downloads/completed/b.mkv"}


def test_get_all_content_paths_skips_missing_field(client: QBitClient, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}/api/v2/torrents/info",
        json=[{"name": "A", "hash": "h1"}],
    )

    assert client.get_all_content_paths() == set()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd app && python3 -m pytest test_qbit.py -v -k content_paths`
Expected: FAIL with `AttributeError: 'QBitClient' object has no attribute 'get_all_content_paths'`

- [ ] **Step 3: Write the implementation**

```python
# append to app/qbit.py, inside class QBitClient

    def get_all_content_paths(self) -> set[str]:
        """Return content_path for every torrent qBittorrent currently knows about."""
        response = self._session.get(f"{self._base_url}/api/v2/torrents/info")
        response.raise_for_status()
        return {t["content_path"] for t in response.json() if t.get("content_path")}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd app && python3 -m pytest test_qbit.py -v`
Expected: 13 passed

- [ ] **Step 5: Commit**

```bash
git add app/qbit.py app/test_qbit.py
git commit -m "feat: add get_all_content_paths to QBitClient"
```

---

### Task 9: Scan orchestration and `/orphans` page

**Files:**
- Modify: `app/main.py`
- Create: `app/templates/orphans.html`
- Create: `app/templates/_orphan_row.html`
- Create: `app/test_orphans_routes.py`

**Interfaces:**
- Consumes: `inode_scan.scan`, `orphans.classify_download_orphans`,
  `orphans.classify_media_orphans`, `orphans.OrphanCandidate`,
  `pathmap.to_relative`, `SonarrClient.get_all_episode_paths`,
  `RadarrClient.get_all_movie_paths`, `PlexClient.get_all_movie_paths`,
  `PlexClient.get_all_episode_paths`, `QBitClient.get_all_content_paths`
- Produces: module-level `_scan_cache: dict[int, OrphanCandidate]` keyed
  by inode (Task 10 reads and mutates this same cache for delete/re-verify).
  `run_scan() -> list[OrphanCandidate]` — the orchestration function that
  fetches from every client (each wrapped to return `None` on failure),
  normalizes paths, runs both classifiers, and populates `_scan_cache`.

This wires Tasks 1-8 together behind `GET /orphans` (empty-state shell,
matching `index.html`'s light theme and layout conventions — the app's
`main` branch does not yet have the dark Servarr skin from the parked v2
UI work, so this follows what's actually on `main` today) and
`POST /orphans/scan` (HTMX-triggered, runs the scan, returns the results
table partial).

- [ ] **Step 1: Write the failing tests**

```python
# app/test_orphans_routes.py
"""Tests for /orphans scan routes in main.py."""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture(autouse=True)
def set_env(monkeypatch, tmp_path):
    monkeypatch.setenv("QBIT_URL", "http://qbit:8080")
    monkeypatch.setenv("QBIT_USERNAME", "admin")
    monkeypatch.setenv("QBIT_PASSWORD", "secret")
    monkeypatch.setenv("SONARR_URL", "http://sonarr:8989")
    monkeypatch.setenv("SONARR_API_KEY", "sonarr-key")
    monkeypatch.setenv("RADARR_URL", "http://radarr:7878")
    monkeypatch.setenv("RADARR_API_KEY", "radarr-key")
    monkeypatch.setenv("PLEX_URL", "http://plex:32400")
    monkeypatch.setenv("PLEX_TOKEN", "plex-token")
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))


def _mock_client(**method_returns):
    instance = MagicMock()
    instance.__enter__ = MagicMock(return_value=instance)
    instance.__exit__ = MagicMock(return_value=False)
    for name, value in method_returns.items():
        getattr(instance, name).return_value = value
    return instance


def _make_file(path, content=b"x" * 1000):
    import os
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)


def test_orphans_page_renders_empty_state():
    client = TestClient(app)
    response = client.get("/orphans")
    assert response.status_code == 200
    assert "Scan" in response.text


def test_scan_finds_download_orphan(tmp_path):
    import os
    _make_file(os.path.join(str(tmp_path), "torrents", "seed.mkv"))

    with patch("main.QBitClient", return_value=_mock_client(get_all_content_paths=set())), \
         patch("main.SonarrClient", return_value=_mock_client(get_all_episode_paths=set())), \
         patch("main.RadarrClient", return_value=_mock_client(get_all_movie_paths=set())), \
         patch("main.PlexClient", return_value=_mock_client(
             get_all_movie_paths=set(), get_all_episode_paths=set()
         )):
        client = TestClient(app)
        response = client.post("/orphans/scan")

    assert response.status_code == 200
    assert "seed.mkv" in response.text
    assert "unlinked download" in response.text


def test_scan_with_unreachable_apis_flags_nothing(tmp_path):
    import os
    _make_file(os.path.join(str(tmp_path), "media", "movies", "movie.mkv"))
    _make_file(os.path.join(str(tmp_path), "torrents", "seed.mkv"))

    with patch("main.QBitClient", side_effect=ConnectionError("refused")), \
         patch("main.SonarrClient", side_effect=ConnectionError("refused")), \
         patch("main.RadarrClient", side_effect=ConnectionError("refused")), \
         patch("main.PlexClient", side_effect=ConnectionError("refused")):
        client = TestClient(app)
        response = client.post("/orphans/scan")

    assert response.status_code == 200
    assert "movie.mkv" not in response.text
    assert "seed.mkv" not in response.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd app && python3 -m pytest test_orphans_routes.py -v`
Expected: FAIL — `GET /orphans` returns 404 (route doesn't exist yet)

- [ ] **Step 3: Write the implementation**

```python
# add near the top of app/main.py, alongside the existing "from qbit import QBitClient"
from inode_scan import scan
from orphans import OrphanCandidate, classify_download_orphans, classify_media_orphans
from pathmap import to_relative
from plex import PlexClient
from radarr import RadarrClient
from sonarr import SonarrClient

DATA_ROOT = os.environ.get("DATA_ROOT", "/data")
MEDIA_SUBDIRS = ["media/movies", "media/movies-no-backup", "media/tv", "media/tv-no-backup"]
TV_SUBDIRS = {"media/tv", "media/tv-no-backup"}
DOWNLOAD_SUBDIRS = ["torrents", "usenet"]

_scan_cache: dict[int, OrphanCandidate] = {}


def _safe(fn):
    """Call fn(), returning None (instead of raising) on any failure — the
    fail-closed contract: a None result means the caller must treat every
    file that would need this data as 'keep, uncertain'."""
    try:
        return fn()
    except Exception:
        return None


def _fetch_qbit_paths() -> set[str]:
    with _get_client() as client:
        client.login()
        return client.get_all_content_paths()


def _fetch_sonarr_paths() -> set[str]:
    with SonarrClient(os.environ["SONARR_URL"], os.environ["SONARR_API_KEY"]) as client:
        return client.get_all_episode_paths()


def _fetch_radarr_paths() -> set[str]:
    with RadarrClient(os.environ["RADARR_URL"], os.environ["RADARR_API_KEY"]) as client:
        return client.get_all_movie_paths()


def _fetch_plex_movie_paths() -> set[str]:
    with PlexClient(os.environ["PLEX_URL"], os.environ["PLEX_TOKEN"]) as client:
        return client.get_all_movie_paths()


def _fetch_plex_episode_paths() -> set[str]:
    with PlexClient(os.environ["PLEX_URL"], os.environ["PLEX_TOKEN"]) as client:
        return client.get_all_episode_paths()


def run_scan() -> list[OrphanCandidate]:
    """Scan the filesystem and classify orphans against every external API."""
    result = scan(DATA_ROOT, MEDIA_SUBDIRS, DOWNLOAD_SUBDIRS)

    qbit_prefix = os.environ.get("QBIT_PATH_PREFIX", "")
    raw_qbit = _safe(_fetch_qbit_paths)
    qbit_paths = {to_relative(p, qbit_prefix) for p in raw_qbit} if raw_qbit is not None else None

    sonarr_prefix = os.environ.get("SONARR_PATH_PREFIX", "")
    raw_sonarr = _safe(_fetch_sonarr_paths)
    sonarr_paths = {to_relative(p, sonarr_prefix) for p in raw_sonarr} if raw_sonarr is not None else None

    radarr_prefix = os.environ.get("RADARR_PATH_PREFIX", "")
    raw_radarr = _safe(_fetch_radarr_paths)
    radarr_paths = {to_relative(p, radarr_prefix) for p in raw_radarr} if raw_radarr is not None else None

    plex_prefix = os.environ.get("PLEX_PATH_PREFIX", "")
    raw_plex_movies = _safe(_fetch_plex_movie_paths)
    plex_movie_paths = (
        {to_relative(p, plex_prefix) for p in raw_plex_movies} if raw_plex_movies is not None else None
    )
    raw_plex_episodes = _safe(_fetch_plex_episode_paths)
    plex_episode_paths = (
        {to_relative(p, plex_prefix) for p in raw_plex_episodes} if raw_plex_episodes is not None else None
    )

    candidates = classify_download_orphans(result, DATA_ROOT, qbit_paths)
    candidates += classify_media_orphans(
        result, DATA_ROOT, TV_SUBDIRS, sonarr_paths, radarr_paths, plex_episode_paths, plex_movie_paths
    )

    _scan_cache.clear()
    for c in candidates:
        _scan_cache[c.inode] = c
    return candidates


def _enrich_candidate(c: OrphanCandidate) -> dict:
    return {
        "inode": c.inode,
        "display_path": c.paths[0],
        "extra_paths": len(c.paths) - 1,
        "category": c.category,
        "size_gb": round(c.size_bytes / 1e9, 2),
    }


@app.get("/orphans", response_class=HTMLResponse)
async def orphans_page(request: Request):
    return templates.TemplateResponse(request, "orphans.html", {"candidates": []})


@app.post("/orphans/scan", response_class=HTMLResponse)
async def orphans_scan(request: Request):
    candidates = [_enrich_candidate(c) for c in run_scan()]
    return templates.TemplateResponse(request, "orphans.html", {"candidates": candidates})
```

```html
<!-- app/templates/orphans.html -->
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Orphan Trawler</title>
  <script src="https://unpkg.com/htmx.org@2.0.3"></script>
  <style>
    body { font-family: sans-serif; max-width: 1200px; margin: 0 auto; padding: 16px; }
    h1 { margin-top: 0; }
    table { border-collapse: collapse; width: 100%; }
    th, td { padding: 6px 12px; text-align: left; border-bottom: 1px solid #ddd; }
    th { background: #f8f8f8; }
    #scan-btn { padding: 8px 16px; background: #0d6efd; color: white; border: none; border-radius: 4px; cursor: pointer; }
    #bulk-delete-btn { padding: 8px 16px; background: #dc3545; color: white; border: none; border-radius: 4px; cursor: pointer; }
    #bulk-delete-btn:disabled { background: #aaa; cursor: default; }
    button[hx-delete] { padding: 4px 10px; background: #dc3545; color: white; border: none; border-radius: 4px; cursor: pointer; }
  </style>
</head>
<body>

<h1>Orphan Trawler</h1>
<button id="scan-btn" hx-post="/orphans/scan" hx-target="#orphan-table" hx-swap="outerHTML" hx-select="#orphan-table">
  Scan Now
</button>

<form method="post" action="/orphans/delete" id="bulk-form">
  <table id="orphan-table">
    <thead>
      <tr>
        <th><input type="checkbox" id="select-all"></th>
        <th>Path</th>
        <th>Size</th>
        <th>Category</th>
        <th>Delete</th>
      </tr>
    </thead>
    <tbody>
      {% for c in candidates %}
        {% include "_orphan_row.html" %}
      {% endfor %}
    </tbody>
  </table>
</form>

</body>
</html>
```

```html
<!-- app/templates/_orphan_row.html -->
<tr id="orphan-row-{{ c.inode }}">
  <td><input type="checkbox" name="inodes" value="{{ c.inode }}" class="orphan-cb"></td>
  <td>{{ c.display_path }}{% if c.extra_paths > 0 %} (+{{ c.extra_paths }} more){% endif %}</td>
  <td>{{ c.size_gb }} GB</td>
  <td>{{ c.category }}</td>
  <td>
    <button hx-delete="/orphans/{{ c.inode }}"
            hx-target="#orphan-row-{{ c.inode }}"
            hx-swap="outerHTML"
            hx-confirm="Delete {{ c.display_path }}?">
      Delete
    </button>
  </td>
</tr>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd app && python3 -m pytest test_orphans_routes.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add app/main.py app/templates/orphans.html app/templates/_orphan_row.html app/test_orphans_routes.py
git commit -m "feat: add /orphans scan page wiring all classifiers together"
```

---

### Task 10: Delete routes with re-verification

**Files:**
- Modify: `app/main.py`
- Modify: `app/test_orphans_routes.py`

**Interfaces:**
- Consumes: `run_scan`, `_scan_cache`, `orphans.delete_orphan` (Task 4)
- Produces: `DELETE /orphans/{inode}` and `POST /orphans/delete` routes.

Before deleting, re-run `run_scan()` and check the inode is still present
in the fresh candidate list — closes the race where Sonarr grabs a
replacement or a torrent resumes between when the page was scanned and
when the user clicks delete.

- [ ] **Step 1: Write the failing tests**

```python
# append to app/test_orphans_routes.py
# Also add this import alongside the existing "from main import app" at the
# top of the file — these tests reach into main._scan_cache directly:
#   import main

def test_delete_single_orphan_after_reverify(tmp_path):
    import os
    path = os.path.join(str(tmp_path), "torrents", "seed.mkv")
    _make_file(path)

    with patch("main.QBitClient", return_value=_mock_client(get_all_content_paths=set())), \
         patch("main.SonarrClient", return_value=_mock_client(get_all_episode_paths=set())), \
         patch("main.RadarrClient", return_value=_mock_client(get_all_movie_paths=set())), \
         patch("main.PlexClient", return_value=_mock_client(
             get_all_movie_paths=set(), get_all_episode_paths=set()
         )):
        client = TestClient(app)
        client.post("/orphans/scan")  # populate _scan_cache
        inode = next(iter(main._scan_cache))
        response = client.delete(f"/orphans/{inode}")

    assert response.status_code == 200
    assert not os.path.exists(path)


def test_delete_skips_if_no_longer_orphan(tmp_path):
    import os
    path = os.path.join(str(tmp_path), "torrents", "seed.mkv")
    _make_file(path)

    with patch("main.QBitClient", return_value=_mock_client(get_all_content_paths=set())), \
         patch("main.SonarrClient", return_value=_mock_client(get_all_episode_paths=set())), \
         patch("main.RadarrClient", return_value=_mock_client(get_all_movie_paths=set())), \
         patch("main.PlexClient", return_value=_mock_client(
             get_all_movie_paths=set(), get_all_episode_paths=set()
         )):
        client = TestClient(app)
        client.post("/orphans/scan")
        inode = next(iter(main._scan_cache))

        # Between scan and delete, qBit now reports this path as active.
        with patch("main.QBitClient", return_value=_mock_client(
            get_all_content_paths={"torrents/seed.mkv"}
        )):
            response = client.delete(f"/orphans/{inode}")

    assert response.status_code == 200
    assert os.path.exists(path)
    assert "no longer" in response.text.lower()


def test_bulk_delete_orphans(tmp_path):
    import os
    path_a = os.path.join(str(tmp_path), "torrents", "a.mkv")
    path_b = os.path.join(str(tmp_path), "torrents", "b.mkv")
    _make_file(path_a)
    _make_file(path_b)

    with patch("main.QBitClient", return_value=_mock_client(get_all_content_paths=set())), \
         patch("main.SonarrClient", return_value=_mock_client(get_all_episode_paths=set())), \
         patch("main.RadarrClient", return_value=_mock_client(get_all_movie_paths=set())), \
         patch("main.PlexClient", return_value=_mock_client(
             get_all_movie_paths=set(), get_all_episode_paths=set()
         )):
        client = TestClient(app, follow_redirects=False)
        client.post("/orphans/scan")
        inodes = list(main._scan_cache.keys())
        response = client.post("/orphans/delete", data={"inodes": [str(i) for i in inodes]})

    assert response.status_code == 302
    assert not os.path.exists(path_a)
    assert not os.path.exists(path_b)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd app && python3 -m pytest test_orphans_routes.py -v -k delete`
Expected: FAIL — 404, routes don't exist yet

- [ ] **Step 3: Write the implementation**

```python
# add to app/main.py, near the other delete routes
from orphans import delete_orphan


def _reverify(inode: int) -> OrphanCandidate | None:
    """Re-run the scan and return the fresh candidate for inode, or None
    if it's no longer flagged as an orphan."""
    fresh = run_scan()
    for c in fresh:
        if c.inode == inode:
            return c
    return None


@app.delete("/orphans/{inode}")
async def delete_single_orphan(inode: int):
    candidate = _scan_cache.get(inode)
    if candidate is None:
        return Response(status_code=200, content="")

    fresh = _reverify(inode)
    if fresh is None:
        return Response(
            status_code=200,
            media_type="text/html",
            content=f'<tr id="orphan-row-{inode}"><td colspan="5">No longer an orphan — skipped</td></tr>',
        )

    try:
        delete_orphan(DATA_ROOT, fresh.paths[0])
        return Response(status_code=200, content="")
    except OSError as e:
        return Response(
            status_code=200,
            media_type="text/html",
            content=f'<tr id="orphan-row-{inode}"><td colspan="5" style="color:red">Delete failed: {e}</td></tr>',
        )


@app.post("/orphans/delete")
async def bulk_delete_orphans(inodes: list[int] = Form(...)):
    fresh_by_inode = {c.inode: c for c in run_scan()}
    for inode in inodes:
        candidate = fresh_by_inode.get(inode)
        if candidate is None:
            continue
        try:
            delete_orphan(DATA_ROOT, candidate.paths[0])
        except OSError:
            continue
    return RedirectResponse(url="/orphans", status_code=302)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd app && python3 -m pytest test_orphans_routes.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add app/main.py app/test_orphans_routes.py
git commit -m "feat: add orphan delete routes with re-verify-before-delete"
```

---

### Task 11: Deploy wiring — compose mount and env vars

**Files:**
- Modify: `compose.yaml`
- Modify: `app/.env.example` (create if it doesn't already have these entries)

**Interfaces:**
- Consumes: nothing (config only)
- Produces: documented env vars and a commented compose example that the
  NAS-specific compose file (`/volume1/docker/projects/qbit-prunarr-compose/compose.yaml`,
  which already diverges from this repo on purpose with absolute paths —
  established precedent, not new) needs applied manually at deploy time.

This app has never had filesystem access before — this task's whole job
is documenting exactly what has to change on the NAS side, since the
generic repo `compose.yaml` doesn't know the real host path.

- [ ] **Step 1: Check current `.env.example` contents**

Run: `cat app/.env.example`

- [ ] **Step 2: Add the new variables**

```bash
# app/.env.example — append these lines
SONARR_URL=http://sonarr:8989
SONARR_API_KEY=
SONARR_PATH_PREFIX=
RADARR_URL=http://radarr:7878
RADARR_API_KEY=
RADARR_PATH_PREFIX=
PLEX_URL=http://plex:32400
PLEX_TOKEN=
PLEX_PATH_PREFIX=
QBIT_PATH_PREFIX=
DATA_ROOT=/data
```

- [ ] **Step 3: Document the required bind mount in compose.yaml**

```yaml
# compose.yaml — add inside services.qbit-prunarr, as a comment (the real
# absolute host path is filled in on the NAS-specific compose copy, same
# pattern already used for build.context and env_file there):
    # On the NAS-specific compose (qbit-prunarr-compose/compose.yaml), add:
    #   volumes:
    #     - /volume1/data:/data
    volumes: []
```

- [ ] **Step 4: Commit**

```bash
git add compose.yaml app/.env.example
git commit -m "docs: document orphan trawler env vars and required data mount"
```

---

## Manual verification (after all tasks land)

Automated tests use mocked APIs and temp directories throughout — nothing
above touches the real NAS. Before considering this done:

1. Run the full suite once more: `cd app && python3 -m pytest -v` — confirm
   all tests across every module still pass together.
2. Deploy to TerraFermi per the existing qbit-prunarr deploy process
   (rebuild container, apply the NAS-specific compose volume + env changes
   from Task 11 using Mike's real Sonarr/Radarr/Plex URLs and API keys).
3. Visit `/orphans`, click **Scan Now**, confirm the known live orphan
   (`torrents/completed/Abraham's.Boys.2025...REMUX...mkv`, found during
   design) shows up in the results with category "unlinked download."
4. Spot-check one "orphaned media" result (if any) by hand — confirm in
   Sonarr/Radarr's own UI that it really has no file record, and in Plex
   that it really doesn't appear, before trusting the tool's classification
   generally.
5. Delete one small, clearly-safe orphan through the UI and confirm the
   file and its empty parent folder are actually gone on disk.
