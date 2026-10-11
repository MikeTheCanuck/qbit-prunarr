# Extras and Specials in Needs Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Plex-confirmed extras move out of Needs Review into a read-only Extras tab. Every remaining Needs Review row gets a verdict (what to do, and why), and the table is grouped by verdict.

**Architecture:**
- **Pure logic.** A new `app/verdicts.py` holds all of it: Sonarr special matching, the Plex extras move target, and the verdict rules. `orphans.py` gains `split_plex_extras` and a `verdict` field on `OrphanCandidate`.
- **Fetching.** `main.run_scan()` fetches three more things, each through its own `_safe` call, so a failure in any of them falls back to today's behaviour:
  - Plex extras for the title folders that have candidates
  - Sonarr's missing season-0 episodes for the affected series
  - Radarr's movie list
- **Wiring.** `run_scan()` splits extras into `_extras_cache` (never `_scan_cache`), then assigns verdicts.
- **UI.** The template gets an Extras tab, and its existing folder grouping becomes verdict grouping.

**Tech Stack:** Python 3, FastAPI, Jinja2, HTMX, plain JS, httpx, pytest + pytest-httpx.

**Spec:** `docs/superpowers/specs/2026-10-11-extras-specials-design.md`. Read it before starting any task. Also read the three Reasoning Captures in the repo's `CLAUDE.md`. They explain why the matcher has the guards it has.

## Global Constraints

- All commands run from the worktree's `app/` directory: `cd /Users/mike/code/qbit-prunarr/.claude/worktrees/extras-specials/app`.
- Run tests with `python3 -m pytest -q` (the full suite has 167 tests after Task 1). Every task ends with the full suite green.
- **Git:** call it as `/usr/bin/git -C /Users/mike/code/qbit-prunarr/.claude/worktrees/extras-specials …`. Plain `git` is rewritten by an rtk hook, which the worktree guard refuses.
- Every commit message ends with a blank line and then `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Fail closed:** a failed or skipped fetch may only *withhold* a verdict or an extras split. It must never make a file look more deletable than it does today.
- **Safety:** a confirmed extra must never be in `_scan_cache` and never be returned by `run_scan()`. Every delete route depends on both.
- **Verdict kinds:** exactly `junk`, `wanted`, `plex`, `identify` and `call`. The Keep kinds are `wanted` and `plex`.
- **Thresholds:** sample = whole word "sample" and under `500_000_000` bytes. "Radarr has no file" = movie candidate over `1_000_000_000` bytes.
- **UI copy:** use these strings exactly.

  | Bucket title | Subtitle |
  |---|---|
  | Probably junk | Safe to delete once you've glanced at the reason. |
  | Keep: Sonarr/Radarr wants it | Real content your library is missing. Import it instead of deleting it. |
  | Keep: Plex can't see it | Bonus material in a place or under a name Plex ignores. Moving it makes it show up as an extra. |
  | Identify it | Looks like a special, but nothing matched. Watch it, then rename it or treat it as an extra. |
  | Your call | No evidence either way. |

## Deviations from the spec (decided while planning, with live data)

1. **The Plex extras fetch uses its own `PlexClient` session**, instead of sharing one with the path fetch. The cost is one more `/all` request per library section per scan. In exchange, an extras failure can't mark Plex itself unreachable, and existing route-test mocks keep working unchanged.
2. **The matcher threshold is `score > 0.5`, not `>= 0.5`**, and "garry" is *not* a generic word. Running against live data showed `S02 bonus - Garry address` matching "Interview with Garry Shandling" at exactly 0.5. The strict threshold removes that false match and loses no true match. Duchovny and Ellen (also exactly 0.5) fall through to "Keep: Plex can't see it", which is still a Keep verdict. Final live result: 28 Sonarr matches, zero false positives.
3. **The matcher strips parenthesized and bracketed text before tokenizing**, e.g. `(1080p BluRay x265 Silence)` and `[rarbg]`. Release-group names then don't need a hardcoded noise list.
4. **The verdict logic lives in `app/verdicts.py`, not `orphans.py`.** `orphans.py` is already 382 lines, and the verdict code has one job.
5. **"Expand all" / "Collapse all" no longer flip the table to flat mode.** This was an existing bug: those buttons carry the `.sort-mode` class, so the mode handler caught them too.

## Review Focus

1. **One hardlink path is a Plex extra and another isn't.** The candidate counts as an extra, because Plex vouches for the inode. Pinned in Task 4.
2. **An extras lookup fails partway (one rating key errors).** The whole extras set is `None`, every candidate stays in Needs Review, and the status says "Plex extras: not checked". Pinned in Task 5.
3. **Odd characters in names** (`&`, `#`, `'`, `_`, unicode) must never crash the matcher or `extras_target`. Pinned in Task 3 (`#StarsInTheHouse`, `Scene 75 & 76`).
4. **A Sonarr series path with a trailing slash or a container prefix** still maps to the scan's title folder. Pinned in Task 5.
5. **Someone deletes an extra** through a stale page or a hand-crafted POST. It is skipped and the file survives. Pinned in Task 5.

---

### Task 1: Plex client — files with rating keys, and extras

**Files:**
- Modify: `app/plex.py`
- Test: `app/test_plex.py`

**Interfaces:**
- Produces:
  - `PlexClient.get_movie_files() -> dict[str, list[str]]`: raw path → [movie ratingKey]
  - `PlexClient.get_episode_files() -> dict[str, list[str]]`: raw path → [show ratingKey, season ratingKey]
  - `PlexClient.get_extra_paths(rating_keys: set[str]) -> set[str]`: raw paths
  - `get_all_movie_paths()` / `get_all_episode_paths()` stay, unchanged in behaviour.

This code already exists as a tested patch from the homelab session.

- [ ] **Step 1: Apply the patch**

```bash
/usr/bin/git -C /Users/mike/code/qbit-prunarr/.claude/worktrees/extras-specials apply /Users/mike/.claude/projects/-Users-mike-code-qbit-prunarr/memory/handoff_extras_plex_client.patch
```

- [ ] **Step 2: Read the result.** Check that `app/plex.py` has the following:
  - `_files_for_section`
  - `get_movie_files`, `get_episode_files` and `get_extra_paths`
  - `get_all_*_paths` as wrappers

  Also check that `app/test_plex.py` has three new tests: `test_movie_files_carry_rating_key`, `test_episode_files_carry_show_and_season_keys` and `test_extra_paths_skip_online_trailers`.

- [ ] **Step 3: Run the suite**

Run: `python3 -m pytest -q`
Expected: `167 passed`

- [ ] **Step 4: Commit**

```bash
/usr/bin/git -C /Users/mike/code/qbit-prunarr/.claude/worktrees/extras-specials add app/plex.py app/test_plex.py
/usr/bin/git -C /Users/mike/code/qbit-prunarr/.claude/worktrees/extras-specials commit -m "feat: Plex client can list a title's local extras

The library listing never returns extras, so a correctly named
Featurettes/ file could never be confirmed.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Sonarr and Radarr client additions

**Files:**
- Modify: `app/sonarr.py` (add two methods after `get_all_episode_paths`)
- Modify: `app/radarr.py` (add one method after `get_all_movie_paths`)
- Test: `app/test_sonarr.py`, `app/test_radarr.py`

**Interfaces:**
- Produces:
  - `SonarrClient.get_series() -> list[dict]`, each `{"id": int, "title": str, "path": str}` (raw path)
  - `SonarrClient.get_missing_specials(series_id: int) -> list[dict]`, each `{"code": "S00E09", "title": str, "monitored": bool}`
  - `RadarrClient.get_movies() -> list[dict]`, each `{"path": str, "title": str, "year": int | None, "has_file": bool}` (raw folder path)

- [ ] **Step 1: Write the failing Sonarr tests** (append to `app/test_sonarr.py`)

```python
def test_get_series_returns_id_title_and_folder(client: SonarrClient, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}/api/v3/series",
        json=[{"id": 7, "title": "Firefly", "path": "/data/media/tv/Firefly", "monitored": True}],
    )

    assert client.get_series() == [{"id": 7, "title": "Firefly", "path": "/data/media/tv/Firefly"}]


def test_get_missing_specials_keeps_only_season_zero_without_a_file(client: SonarrClient, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}/api/v3/episode?seriesId=7",
        json=[
            {"seasonNumber": 0, "episodeNumber": 1, "title": "Serenity", "hasFile": False, "monitored": True},
            {"seasonNumber": 0, "episodeNumber": 4, "title": "R. Tam Sessions", "hasFile": True, "monitored": True},
            {"seasonNumber": 0, "episodeNumber": 12, "title": "Gag Reel", "hasFile": False, "monitored": False},
            {"seasonNumber": 1, "episodeNumber": 1, "title": "Serenity", "hasFile": False, "monitored": True},
        ],
    )

    assert client.get_missing_specials(7) == [
        {"code": "S00E01", "title": "Serenity", "monitored": True},
        {"code": "S00E12", "title": "Gag Reel", "monitored": False},
    ]
```

- [ ] **Step 2: Write the failing Radarr test** (append to `app/test_radarr.py`, which has the same `client`/`BASE_URL` fixture shape as the Sonarr tests)

```python
def test_get_movies_returns_folder_title_year_and_has_file(client: RadarrClient, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}/api/v3/movie",
        json=[
            {"title": "Crystal Lake Memories", "year": 2013, "path": "/data/media/movies/Crystal Lake"},
            {"title": "Gambit", "year": 1966, "path": "/data/media/movies/Gambit",
             "movieFile": {"path": "/data/media/movies/Gambit/Gambit.mkv"}},
        ],
    )

    assert client.get_movies() == [
        {"path": "/data/media/movies/Crystal Lake", "title": "Crystal Lake Memories", "year": 2013, "has_file": False},
        {"path": "/data/media/movies/Gambit", "title": "Gambit", "year": 1966, "has_file": True},
    ]
```

- [ ] **Step 3: Run them to confirm they fail**

Run: `python3 -m pytest -q test_sonarr.py test_radarr.py`
Expected: 3 failures with `AttributeError: 'SonarrClient' object has no attribute 'get_series'` (and similar).

- [ ] **Step 4: Implement.** Add these methods to `app/sonarr.py` after `get_all_episode_paths`:

```python
    def get_series(self) -> list[dict]:
        """Every series as {"id", "title", "path"}; path is the series folder as Sonarr sees it."""
        resp = self._session.get(f"{self._base_url}/api/v3/series")
        resp.raise_for_status()
        return [{"id": s["id"], "title": s["title"], "path": s["path"]} for s in resp.json()]

    def get_missing_specials(self, series_id: int) -> list[dict]:
        """Season-0 episodes Sonarr knows about but has no file for.

        Each is {"code": "S00E09", "title", "monitored"}. These come from
        Sonarr's own episode list, so a file matched to one has a real slot
        to be imported into.
        """
        resp = self._session.get(f"{self._base_url}/api/v3/episode", params={"seriesId": series_id})
        resp.raise_for_status()
        return [
            {
                "code": f"S00E{e['episodeNumber']:02d}",
                "title": e.get("title", ""),
                "monitored": bool(e.get("monitored")),
            }
            for e in resp.json()
            if e.get("seasonNumber") == 0 and not e.get("hasFile")
        ]
```

Then add this to `app/radarr.py` after `get_all_movie_paths`:

```python
    def get_movies(self) -> list[dict]:
        """Every movie as {"path", "title", "year", "has_file"}; path is the
        movie's folder as Radarr sees it, whether or not it has a file yet."""
        resp = self._session.get(f"{self._base_url}/api/v3/movie")
        resp.raise_for_status()
        return [
            {
                "path": m.get("path", ""),
                "title": m.get("title", ""),
                "year": m.get("year"),
                "has_file": bool(m.get("movieFile")),
            }
            for m in resp.json()
        ]
```

- [ ] **Step 5: Run the suite**

Run: `python3 -m pytest -q`
Expected: `170 passed`

- [ ] **Step 6: Commit**

```bash
/usr/bin/git -C /Users/mike/code/qbit-prunarr/.claude/worktrees/extras-specials add app/sonarr.py app/radarr.py app/test_sonarr.py app/test_radarr.py
/usr/bin/git -C /Users/mike/code/qbit-prunarr/.claude/worktrees/extras-specials commit -m "feat: Sonarr missing specials and Radarr movie folders

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Verdict types and Sonarr special matching

**Files:**
- Create: `app/verdicts.py`
- Create: `app/test_verdicts.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces (all in `verdicts.py`):
  - `MissingSpecial(code: str, title: str, monitored: bool)`, a frozen dataclass
  - `SeriesSpecials(series: str, missing: tuple[MissingSpecial, ...])`, a frozen dataclass
  - `RadarrMovie(title: str, year: int | None, has_file: bool)`, a frozen dataclass
  - `Verdict(kind: str, action: str, reason: str)`, a frozen dataclass
  - `KEEP_KINDS = {"wanted", "plex"}`
  - `match_sonarr_special(path: str, specials: SeriesSpecials) -> MissingSpecial | None`

`path` is relative to the data root, e.g. `media/tv/Firefly/Featurettes/x.mkv`.

- [ ] **Step 1: Write the failing tests** (`app/test_verdicts.py`). Every case comes from the 2026-10-10 live scan.

```python
"""Tests for verdicts.py. Cases are real files from the 2026-10-10 scan."""
from verdicts import MissingSpecial, SeriesSpecials, match_sonarr_special

LARRY = SeriesSpecials("The Larry Sanders Show", (
    MissingSpecial("S00E06", "Garry Interviews Alec Baldwin", True),
    MissingSpecial("S00E07", "Garry Interviews Carol Burnett", True),
    MissingSpecial("S00E08", "Garry Interviews David Duchovny", True),
    MissingSpecial("S00E12", "Garry Interviews Sharon Stone", True),
    MissingSpecial("S00E15", "Interview with Garry Shandling", True),
    MissingSpecial("S00E17", "Interview with Jeremy Piven", True),
    MissingSpecial("S00E18", "Interview with Linda Doucett", True),
    MissingSpecial("S00E54", "Deleted Scenes - The Mr. Sharon Stone Show", True),
    MissingSpecial("S00E56", "Garry Shandling Interviews Linda Doucett", True),
    MissingSpecial("S00E60", "Outtakes - Season 2", True),
    MissingSpecial("S00E64", "Outtakes - Season 3", True),
))
FIREFLY = SeriesSpecials("Firefly", (
    MissingSpecial("S00E01", "Serenity", True),
    MissingSpecial("S00E02", "Done the Impossible", True),
    MissingSpecial("S00E06", "Serenity: The 10th Character", True),
))
NEWSROOM = SeriesSpecials("The Newsroom", (
    MissingSpecial("S00E01", "Escape from the Newsroom", True),
    MissingSpecial("S00E02", "In The Newsroom", True),
    MissingSpecial("S00E03", "Inside The Newsroom", True),
))
SCTV = SeriesSpecials("Second City Television", (
    MissingSpecial("S00E01", "The Origins of SCTV", True),
    MissingSpecial("S00E07", "The Shmenges: The Last Polka", True),
    MissingSpecial("S00E08", "Biographies: The Enigma of Bobby Bittman", True),
))
SUPERNATURAL = SeriesSpecials("Supernatural", (
    MissingSpecial("S00E02", "A Very Special Supernatural", True),
    MissingSpecial("S00E09", "Supernatural: The Long Road Home", True),
))
SPACED = SeriesSpecials("Spaced", (MissingSpecial("S00E01", "Skip To The End", True),))
SCTV90 = SeriesSpecials("SCTV Network 90", (MissingSpecial("S00E23", "SCTV Reunion", False),))


def _code(path, specials):
    m = match_sonarr_special(path, specials)
    return m.code if m else None


def test_interview_matches_by_guest_name():
    assert _code("media/tv/Larry Sanders/LARRY SANDERS S01 bonus - interview Jeremy Piven.mp4", LARRY) == "S00E17"


def test_visit_matches_garry_interviews_title():
    assert _code("media/tv/Larry Sanders/LARRY SANDERS S02 bonus - visit Alec Baldwin.mp4", LARRY) == "S00E06"
    assert _code("media/tv/Larry Sanders/LARRY SANDERS S01 bonus Carol Burnett.mp4", LARRY) == "S00E07"


def test_better_score_wins_over_a_weaker_overlap():
    # "Sharon Stone" also appears in S00E54's title, at a lower score.
    assert _code("media/tv/Larry Sanders/LARRY SANDERS S03 bonus - visit Sharon Stone.mp4", LARRY) == "S00E12"
    # S00E56 also names Linda Doucett, but scores only 0.5.
    assert _code("media/tv/Larry Sanders/LARRY SANDERS S03 bonus - interview Linda Doucett.mp4", LARRY) == "S00E18"


def test_season_guard_picks_the_right_outtakes():
    assert _code("media/tv/Larry Sanders/LARRY SANDERS S03 outtakes.mp4", LARRY) == "S00E64"
    assert _code("media/tv/Larry Sanders/LARRY SANDERS S02 bonus - outtakes.mp4", LARRY) == "S00E60"


def test_half_overlap_is_not_a_match():
    # Shares only "garry" with "Interview with Garry Shandling": exactly 0.5.
    assert _code("media/tv/Larry Sanders/LARRY SANDERS S02 bonus - Garry address.mp4", LARRY) is None
    # One of two title tokens: exactly 0.5, so falls through to the Plex verdict.
    assert _code("media/tv/Larry Sanders/LARRY SANDERS S05 bonus - Duchovny.mp4", LARRY) is None


def test_generic_only_names_never_match():
    assert _code("media/tv/Larry Sanders/LARRY SANDERS S06 bonus - deleted scenes.mp4", LARRY) is None
    assert _code("media/tv/Larry Sanders/LARRY SANDERS BONUS 1.mp4", LARRY) is None


def test_exact_title_match_for_stopword_titles():
    assert _code("media/tv/The Newsroom (1996)/2004 Season 2/Bonus Materials/In The Newsroom.mkv", NEWSROOM) == "S00E02"
    assert _code("media/tv/The Newsroom (1996)/1996 Season 1/Bonus Materials/Inside The Newsroom.mkv", NEWSROOM) == "S00E03"
    assert _code("media/tv/The Newsroom (1996)/2002 Escape from the Newsroom/Escape from the Newsroom.mkv", NEWSROOM) == "S00E01"


def test_release_tags_in_parentheses_are_ignored():
    assert _code("media/tv/Firefly/Featurettes/Specials/S00E02 - Done the Impossible (1080p WEB x265 Silence).mkv", FIREFLY) == "S00E02"
    assert _code("media/tv/Firefly/Featurettes/Specials/Serenity (2005)/S00E01 - Serenity (2005) (1080p BluRay x265 Silence).mkv", FIREFLY) == "S00E01"


def test_dotted_release_name_matches():
    assert _code("media/tv-no-backup/Supernatural/Supernatural.S15E00.The.Long.Road.Home.1080p.WEB.h264-BAE.mkv", SUPERNATURAL) == "S00E09"
    assert _code("media/tv/Spaced/Skip_To_the_End-Documentary.mp4", SPACED) == "S00E01"


def test_match_by_title_even_when_the_file_code_is_wrong():
    assert _code("media/tv/Second City Television/Specials/S00E10 - The Shmenges_ The Last Polka (480p_30fps_H264-128kbit_AAC).mp4", SCTV) == "S00E07"
    assert _code("media/tv/Second City Television/Specials/S00E11 - (1988) The Enigma of Bobby Bittman (360p_30fps_H264-128kbit_AAC).mp4", SCTV) == "S00E08"


def test_regular_episode_deleted_scene_never_matches_a_special():
    assert _code("media/tv/Firefly/Featurettes/Deleted Scenes/S01E01 Serenity - Scene 1.mkv", FIREFLY) is None
    assert _code("media/tv/Firefly/Featurettes/Deleted Scenes/S01E01 Serenity - Scene 75 & 76.mkv", FIREFLY) is None


def test_featurette_sharing_one_word_is_not_the_special():
    assert _code("media/tv/Firefly/Featurettes/Specials/Serenity (2005)/Featurettes/Take a Walk on Serenity.mkv", FIREFLY) is None


def test_odd_characters_do_not_crash():
    assert _code("media/tv/SCTV Network 90/specials/#StarsInTheHouse #60_ SCTV Cast Members (720p_30fps_H264-128kbit_AAC).mp4", SCTV90) is None
    assert _code("media/tv/SCTV Network 90/specials/'PMS- Premenstrual Syndrome' - David Letterman's Holiday Film Festival (1985).mp4", SCTV90) is None


def test_empty_missing_list_matches_nothing():
    assert _code("media/tv/Firefly/S00E01 - Serenity.mkv", SeriesSpecials("Firefly", ())) is None
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `python3 -m pytest -q test_verdicts.py`
Expected: collection error `ModuleNotFoundError: No module named 'verdicts'`

- [ ] **Step 3: Implement** (`app/verdicts.py`)

```python
"""Verdicts for Needs Review: what to do with each media-side orphan, and why.

Pure functions only. main.run_scan() fetches the Sonarr/Radarr/Plex data,
normalizes every path to be relative to the data root, and passes it in.

Before loosening any matching rule here, read the 2026-10-11 Reasoning
Captures in CLAUDE.md: every guard below exists because of a real false
match on the live library.
"""
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class MissingSpecial:
    code: str  # "S00E09"
    title: str
    monitored: bool


@dataclass(frozen=True)
class SeriesSpecials:
    series: str
    missing: tuple[MissingSpecial, ...]


@dataclass(frozen=True)
class RadarrMovie:
    title: str
    year: int | None
    has_file: bool


@dataclass(frozen=True)
class Verdict:
    kind: str  # "junk" | "wanted" | "plex" | "identify" | "call"
    action: str
    reason: str


# Verdicts whose suggestion is to keep the file: the UI guards their delete.
KEEP_KINDS = {"wanted", "plex"}

_STOP = {"the", "a", "an", "of", "and", "with", "to", "in", "on", "at", "for", "from", "vs", "by"}
# Words that say what kind of bonus a file is, not which one it is.
_GENERIC = {
    "interview", "interviews", "deleted", "scene", "scenes", "behind", "disk", "disc", "season",
    "episode", "making", "special", "specials", "visit", "bonus", "part", "pt", "extended",
    "featurette", "featurettes", "trailer", "documentary",
}
_NOISE = re.compile(
    r"^(\d+|\d{3,4}[pi]|x26[45]|h26[45]|hevc|avc|web|webrip|dl|bluray|brrip|bdrip|hdtv|dvdrip|"
    r"aac\d*|ac3|dts|flac|\d+fps|\d+kbit|s\d+e\d+|s\d+|e\d+)$"
)
# A normal episode's code (both numbers non-zero): its deleted scenes are
# not specials, even when named after an episode that shares a special's title.
_REGULAR_EPISODE = re.compile(r"s(?!00)\d+e(?!00)\d+", re.I)
_FILE_SEASON = re.compile(r"\bs(\d+)(?:e\d+)?\b", re.I)
_TITLE_SEASON = re.compile(r"\bseason (\d+)\b", re.I)


def _words(text: str) -> list[str]:
    """Lowercase words with release noise removed. Parenthesized and
    bracketed text is dropped first: it's almost always quality tags or
    a release group, e.g. "(1080p BluRay x265 Silence)" or "[rarbg]"."""
    text = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", text)
    return [w for w in re.split(r"[^a-z0-9]+", text.lower()) if w and not _NOISE.match(w)]


def _significant(words: list[str], series_tokens: set[str]) -> set[str]:
    return {w for w in words if len(w) > 1 and w not in _STOP and w not in _GENERIC and w not in series_tokens}


def match_sonarr_special(path: str, specials: SeriesSpecials) -> MissingSpecial | None:
    """The missing season-0 episode this file most likely is, by title.

    Never trusts the file's own S00Exx code: on the live library those
    codes pointed at different episodes than Sonarr's. An exact
    title-at-end-of-name match wins first. Otherwise the shared
    significant words must cover MORE than half of both the title's and
    the file's words, so one shared word can't drag in an unrelated file.
    """
    name = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    if _REGULAR_EPISODE.search(name):
        return None
    series_tokens = set(_words(specials.series)) - _STOP
    file_season = _FILE_SEASON.search(name)
    candidates = []
    for ep in specials.missing:
        title_season = _TITLE_SEASON.search(ep.title)
        if file_season and title_season and int(file_season.group(1)) != int(title_season.group(1)):
            continue
        candidates.append(ep)

    file_words = _words(name)
    for ep in candidates:
        title_words = _words(ep.title)
        if len(" ".join(title_words)) > 8 and file_words[-len(title_words):] == title_words:
            return ep

    file_sig = _significant(file_words, series_tokens)
    best, best_score = None, 0.0
    for ep in candidates:
        title_sig = _significant(_words(ep.title), series_tokens)
        shared = file_sig & title_sig
        if not shared or sum(len(w) for w in shared) < 4:
            continue
        score = min(len(shared) / len(title_sig), len(shared) / len(file_sig))
        if score > 0.5 and score > best_score:
            best, best_score = ep, score
    return best
```

- [ ] **Step 4: Run the new tests**

Run: `python3 -m pytest -q test_verdicts.py`
Expected: `14 passed`. If a live-data case fails, fix the code, not the expectation. Each expectation was checked against the live library.

- [ ] **Step 5: Run the suite**

Run: `python3 -m pytest -q`
Expected: `184 passed`

- [ ] **Step 6: Commit**

```bash
/usr/bin/git -C /Users/mike/code/qbit-prunarr/.claude/worktrees/extras-specials add app/verdicts.py app/test_verdicts.py
/usr/bin/git -C /Users/mike/code/qbit-prunarr/.claude/worktrees/extras-specials commit -m "feat: match Needs Review files to Sonarr's missing specials by title

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Extras split, move targets, and verdict rules

**Files:**
- Modify: `app/orphans.py`:
  - add a `verdict` field to `OrphanCandidate`
  - add `split_plex_extras` after `attach_sidecars`
  - rename `_title_folder` to `title_folder`, since `verdicts.py` and `main.py` now use it too
- Modify: `app/verdicts.py` (append)
- Test: `app/test_orphans.py`, `app/test_verdicts.py`

**Interfaces:**
- Consumes: Task 3's types and `match_sonarr_special`.
- Produces:
  - `orphans.title_folder(path: str) -> str` (renamed; update the two internal callers in `mark_superseded`)
  - `OrphanCandidate.verdict: "Verdict | None" = None`
  - `orphans.split_plex_extras(candidates: list[OrphanCandidate], extra_paths: set[str] | None) -> tuple[list[OrphanCandidate], list[OrphanCandidate]]`, returning `(kept, extras)`
  - `verdicts.VerdictContext(tv_subdirs: set[str], specials: dict[str, SeriesSpecials] | None, radarr_movies: dict[str, RadarrMovie] | None, radarr_paths: set[str] | None)`, a dataclass
  - `verdicts.extras_target(path: str, tv_subdirs: set[str]) -> str | None`
  - `verdicts.looks_special(path: str) -> bool`
  - `verdicts.assign_verdict(c: OrphanCandidate, ctx: VerdictContext) -> Verdict`

- [ ] **Step 1: Write the failing `split_plex_extras` tests** (append to `app/test_orphans.py`)

```python
from orphans import OrphanCandidate, split_plex_extras


def _media(inode, *paths):
    return OrphanCandidate(inode=inode, paths=list(paths), category="orphaned media", size_bytes=10)


def test_split_plex_extras_moves_confirmed_extras_out():
    extra = _media(1, "media/movies/Film/Featurettes/Making Of.mkv")
    other = _media(2, "media/movies/Film/Extras/Trailer.mkv")
    kept, extras = split_plex_extras([extra, other], {"media/movies/Film/Featurettes/Making Of.mkv"})
    assert extras == [extra]
    assert kept == [other]


def test_split_plex_extras_counts_any_hardlink_path():
    c = _media(3, "media/tv/Show/Bonus/x.mkv", "media/tv/Show/Featurettes/x.mkv")
    kept, extras = split_plex_extras([c], {"media/tv/Show/Featurettes/x.mkv"})
    assert extras == [c] and kept == []


def test_split_plex_extras_without_plex_data_moves_nothing():
    c = _media(4, "media/movies/Film/Featurettes/Making Of.mkv")
    assert split_plex_extras([c], None) == ([c], [])


def test_split_plex_extras_never_touches_download_candidates():
    d = OrphanCandidate(inode=5, paths=["torrents/x.mkv"], category="unlinked download", size_bytes=1)
    assert split_plex_extras([d], {"torrents/x.mkv"}) == ([d], [])
```

- [ ] **Step 2: Write the failing verdict tests** (append to `app/test_verdicts.py`)

```python
from orphans import OrphanCandidate
from verdicts import RadarrMovie, VerdictContext, assign_verdict, extras_target, looks_special

TV = {"media/tv", "media/tv-no-backup"}


def _c(path, size=100_000_000, **kw):
    return OrphanCandidate(inode=1, paths=[path], category="orphaned media", size_bytes=size, **kw)


def _ctx(specials=None, radarr_movies=None, radarr_paths=None):
    return VerdictContext(tv_subdirs=TV, specials=specials if specials is not None else {},
                          radarr_movies=radarr_movies if radarr_movies is not None else {},
                          radarr_paths=radarr_paths if radarr_paths is not None else set())


def test_extras_target_flattens_nested_tv_extras_into_featurettes():
    assert extras_target("media/tv/Firefly/Featurettes/Deleted Scenes/S01E01 Serenity - Scene 75 & 76.mkv", TV) == \
        "Firefly/Featurettes/S01E01 Serenity - Scene 75 & 76.mkv"


def test_extras_target_picks_movie_folder_by_keyword():
    assert extras_target("media/movies/Gambit.1966/Extras/Trailer.mkv", TV) == "Gambit.1966/Trailers/Trailer.mkv"
    assert extras_target("media/movies/H3/H3.Extras-Grym/On-set.Interviews.with.Barker-Grym.mkv", TV) == \
        "H3/Interviews/On-set.Interviews.with.Barker-Grym.mkv"
    assert extras_target("media/movies/H3/H3.Extras-Grym/Hell.on.Earth-The.Story.of.Hellraiser.III-Grym.mkv", TV) == \
        "H3/Behind The Scenes/Hell.on.Earth-The.Story.of.Hellraiser.III-Grym.mkv"


def test_extras_target_uses_bonus_keyword_in_a_show_folder():
    assert extras_target("media/tv/Larry Sanders/LARRY SANDERS BONUS 1.mp4", TV) == "Larry Sanders/Featurettes/LARRY SANDERS BONUS 1.mp4"


def test_extras_target_none_for_plain_files_loose_files_and_already_placed():
    assert extras_target("media/movies/Film/Film.mkv", TV) is None
    assert extras_target("media/tv/Schoolhouse_Rock.mp4", TV) is None
    assert extras_target("media/movies/Film/Trailers/Trailer.mkv", TV) is None


def test_looks_special_uses_codes_names_and_the_immediate_parent_only():
    assert looks_special("media/tv/Supernatural/Supernatural.S15E00.The.Long.Road.Home.mkv")
    assert looks_special("media/tv/SCTV/specials/Softball Game.mp4")
    assert looks_special("media/tv/Wellington/Wellington.Paranormal.S02.Xmas.Special.2019.mkv")
    assert not looks_special("media/tv/Firefly/Featurettes/Specials/Serenity (2005)/Featurettes/Outtakes.mkv")


def test_small_sample_is_junk():
    v = assign_verdict(_c("media/movies/IM3/Sample,Screens/IM3 (Sample).mkv", size=85_000_000), _ctx())
    assert v.kind == "junk" and v.action == "Delete it."


def test_sample_radarr_tracks_gets_rescan_advice():
    p = "media/movies/IM3/Sample,Screens/IM3 (Sample).mkv"
    v = assign_verdict(_c(p, size=85_000_000), _ctx(radarr_paths={p}))
    assert "Rescan" in v.reason


def test_big_file_with_sample_in_title_is_not_junk():
    v = assign_verdict(_c("media/movies/Free Sample (2020)/Free Sample.mkv", size=4_000_000_000), _ctx())
    assert v.kind != "junk"


def test_superseded_is_junk_and_names_the_tracked_file():
    v = assign_verdict(_c("media/movies/Film/Film.WEBRip.mkv", superseded_by="Film.BluRay.mkv"), _ctx())
    assert v.kind == "junk" and "Film.BluRay.mkv" in v.reason


def test_tracks_sample_is_wanted():
    v = assign_verdict(_c("media/movies/IM3/IM3.mkv", tracks_sample=True), _ctx())
    assert v.kind == "wanted"


def test_sonarr_match_is_wanted_with_code_and_title():
    from verdicts import MissingSpecial, SeriesSpecials
    specials = {"media/tv/Supernatural": SeriesSpecials("Supernatural", (
        MissingSpecial("S00E09", "Supernatural: The Long Road Home", False),))}
    v = assign_verdict(_c("media/tv/Supernatural/Supernatural.S15E00.The.Long.Road.Home.mkv"), _ctx(specials=specials))
    assert v.kind == "wanted"
    assert 'S00E09 "Supernatural: The Long Road Home"' in v.action
    assert "monitoring" in v.action


def test_wrong_own_code_is_called_out():
    from verdicts import MissingSpecial, SeriesSpecials
    specials = {"media/tv/SCTV": SeriesSpecials("Second City Television", (
        MissingSpecial("S00E07", "The Shmenges: The Last Polka", True),))}
    v = assign_verdict(_c("media/tv/SCTV/Specials/S00E10 - The Shmenges_ The Last Polka.mp4"), _ctx(specials=specials))
    assert "S00E10" in v.reason


def test_sonarr_match_beats_plex_move():
    from verdicts import MissingSpecial, SeriesSpecials
    specials = {"media/tv/Larry Sanders": SeriesSpecials("The Larry Sanders Show", (
        MissingSpecial("S00E17", "Interview with Jeremy Piven", True),))}
    v = assign_verdict(_c("media/tv/Larry Sanders/LARRY SANDERS S01 bonus - interview Jeremy Piven.mp4"), _ctx(specials=specials))
    assert v.kind == "wanted"


def test_radarr_movie_without_a_file_is_wanted():
    movies = {"media/movies/Crystal Lake": RadarrMovie("Crystal Lake Memories", 2013, False)}
    v = assign_verdict(_c("media/movies/Crystal Lake/Crystal Lake - pt1.mp4", size=4_700_000_000), _ctx(radarr_movies=movies))
    assert v.kind == "wanted" and '"Crystal Lake Memories (2013)"' in v.action


def test_nested_extra_is_plex_with_target():
    v = assign_verdict(_c("media/tv/Firefly/Featurettes/Specials/Serenity (2005)/Featurettes/Outtakes.mkv"), _ctx())
    assert v.kind == "plex" and v.action == "Move to Firefly/Featurettes/Outtakes.mkv"


def test_sample_in_an_extras_folder_is_still_junk():
    v = assign_verdict(_c("media/movies/Film/Extras/film-sample.mkv", size=20_000_000), _ctx())
    assert v.kind == "junk"


def test_unmatched_special_is_identify_and_says_why():
    from verdicts import SeriesSpecials
    specials = {"media/tv/Wellington Paranormal": SeriesSpecials("Wellington Paranormal", ())}
    p = "media/tv/Wellington Paranormal/Wellington.Paranormal.S02.Xmas.Special.2019.mkv"
    assert "none of Sonarr's" in assign_verdict(_c(p), _ctx(specials=specials)).reason
    assert "no series" in assign_verdict(_c(p), _ctx(specials={})).reason
    assert "couldn't be checked" in assign_verdict(_c(p), VerdictContext(TV, None, {}, set())).reason


def test_loose_file_at_library_root_is_your_call_with_advice():
    v = assign_verdict(_c("media/tv/South.Park.S14E14.Creme.Fraiche.avi"), _ctx())
    assert v.kind == "call" and "Loose file" in v.reason


def test_everything_else_is_your_call():
    v = assign_verdict(_c("media/tv/SCTV Network 90/S04E03 - SCTV Network 90 - #108.m4v"), _ctx())
    assert v == assign_verdict(_c("media/tv/SCTV Network 90/S04E03 - SCTV Network 90 - #108.m4v"), _ctx())
    assert v.kind == "call" and v.action == "Your call."


def test_missing_radarr_data_never_produces_a_radarr_verdict():
    v = assign_verdict(_c("media/movies/Crystal Lake/Crystal Lake - pt1.mp4", size=4_700_000_000),
                       VerdictContext(TV, {}, None, None))
    assert v.kind == "call"
```

- [ ] **Step 3: Run them to confirm they fail**

Run: `python3 -m pytest -q test_orphans.py test_verdicts.py`
Expected: import errors for `split_plex_extras`, `VerdictContext`, `assign_verdict`, `extras_target` and `looks_special`.

- [ ] **Step 4: Implement `orphans.py` changes**

At the top of `app/orphans.py`, after `from dataclasses import dataclass, field`, add:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from verdicts import Verdict
```

Then add this as the last field of `OrphanCandidate`:

```python
    # What to do with a Needs Review file, and why. Set by run_scan after
    # classification; None for download-side candidates.
    verdict: "Verdict | None" = None
```

Next, rename `_title_folder` to `title_folder`, both the `def` and its two uses in `mark_superseded`. Then append:

```python
def split_plex_extras(
    candidates: list[OrphanCandidate], extra_paths: set[str] | None
) -> tuple[list[OrphanCandidate], list[OrphanCandidate]]:
    """Pull out media candidates Plex has attached as local extras.

    Plex alone vouches for these: Sonarr and Radarr never track video
    extras, so the usual "both must confirm" rule can't apply. Any one
    hardlink path being a Plex extra is enough. None (Plex unreachable,
    or the extras lookup failed) moves nothing.
    """
    if extra_paths is None:
        return list(candidates), []
    kept, extras = [], []
    for c in candidates:
        if c.category == "orphaned media" and any(p in extra_paths for p in c.paths):
            extras.append(c)
        else:
            kept.append(c)
    return kept, extras
```

- [ ] **Step 5: Implement the `verdicts.py` additions.** Append to `app/verdicts.py`, then add `import os` and `from orphans import OrphanCandidate, is_tv_path, title_folder` to its imports:

```python
SAMPLE_MAX_BYTES = 500_000_000
RADARR_WANTED_MIN_BYTES = 1_000_000_000
_PLEX_EXTRAS_DIRS = {
    "behind the scenes", "deleted scenes", "featurettes", "interviews",
    "scenes", "shorts", "trailers", "other",
}
_EXTRAS_KEYWORDS = ("bonus", "outtakes", "introduction", "trailer", "interview", "gag")
_SPECIALS_DIRS = {"specials", "season 00", "season 0"}


@dataclass
class VerdictContext:
    tv_subdirs: set[str]
    # Title folder ("media/tv/Firefly") -> that series' missing specials.
    # A folder is present iff Sonarr has a series there. None: not checked.
    specials: dict[str, SeriesSpecials] | None
    # Movie folder -> Radarr's record. None: Radarr not checked.
    radarr_movies: dict[str, RadarrMovie] | None
    # Radarr's tracked files. None: Radarr not checked.
    radarr_paths: set[str] | None


def _word(word: str, text: str) -> bool:
    return re.search(rf"(?<![a-z]){word}(?![a-z])", text.lower()) is not None


def _is_loose(path: str) -> bool:
    """Directly in a library root, e.g. media/tv/x.avi: in no title's folder."""
    return path.count("/") == 2


def looks_special(path: str) -> bool:
    """S00Exx or SxxE00 in the name, "special" as a word, or sitting
    directly in a Specials/Season 00 folder. Only the immediate parent
    counts: Firefly keeps a movie's featurettes in a folder nested under
    Specials/, and those aren't specials."""
    name = os.path.basename(path)
    parent = os.path.basename(os.path.dirname(path)).lower()
    return bool(
        re.search(r"s00e\d+", name, re.I)
        or re.search(r"s\d+e00(?!\d)", name, re.I)
        or parent in _SPECIALS_DIRS
        or _word("special", name)
    )


def extras_target(path: str, tv_subdirs: set[str]) -> str | None:
    """Where Plex would pick this file up as an extra, shown relative to the
    library root (e.g. "Firefly/Featurettes/x.mkv"), or None.

    Only a suggestion: a name rule never confirms an extra (see CLAUDE.md).
    TV goes to <Show>/Featurettes/, the one TV placement proven on the
    live library; movies get the folder Plex's docs give for the kind.
    """
    if _is_loose(path):
        return None
    folder = title_folder(path)
    *dirs, name = path[len(folder) + 1:].split("/")
    odd_dir = any(d.lower() in _PLEX_EXTRAS_DIRS or "extras" in d.lower() or "bonus" in d.lower() for d in dirs)
    keyword = any(_word(k, name) for k in _EXTRAS_KEYWORDS)
    if not (odd_dir or keyword):
        return None
    if is_tv_path(path, tv_subdirs):
        sub = "Featurettes"
    else:
        plain = re.sub(r"[^a-z0-9]+", " ", name.lower())
        sub = (
            "Trailers" if "trailer" in plain
            else "Interviews" if "interview" in plain
            else "Deleted Scenes" if "deleted" in plain
            else "Behind The Scenes" if "making" in plain or "story of" in plain
            else "Featurettes"
        )
    if path == f"{folder}/{sub}/{name}":
        return None
    return f"{os.path.basename(folder)}/{sub}/{name}"


def assign_verdict(c: OrphanCandidate, ctx: VerdictContext) -> Verdict:
    """First matching rule wins; the order is the spec's. A rule whose data
    wasn't fetched (None in ctx) never fires, so missing data only ever
    pushes a file toward "Your call", never toward "junk"."""
    path = c.paths[0]
    folder = title_folder(path)
    tv = any(is_tv_path(p, ctx.tv_subdirs) for p in c.paths)

    if c.size_bytes < SAMPLE_MAX_BYTES and _word("sample", path):
        reason = "A preview clip from the release, not the real thing."
        if ctx.radarr_paths is not None and any(p in ctx.radarr_paths for p in c.paths):
            reason += (" Radarr is tracking this sample as the movie, so after deleting it,"
                       " run a Rescan in Radarr so it picks up the real file.")
        return Verdict("junk", "Delete it.", reason)
    if c.superseded_by:
        return Verdict("junk", "Delete it (older copy).",
                       f"Radarr tracks a different file in this folder: {c.superseded_by}")
    if c.tracks_sample:
        return Verdict("wanted",
                       "Keep it: this is probably the real movie. Delete the sample Radarr tracks, then run a Rescan in Radarr.",
                       "Radarr's file for this movie is a sample clip.")
    if tv and ctx.specials is not None and folder in ctx.specials:
        ep = match_sonarr_special(path, ctx.specials[folder])
        if ep:
            action = f'Import as {ep.code} "{ep.title}" with Manual Import in Sonarr.'
            if not ep.monitored:
                action += " Turn monitoring on for it first."
            reason = f'Sonarr lists {ep.code} "{ep.title}" as missing, and this file\'s name matches it.'
            own = re.search(r"s00e(\d+)", os.path.basename(path), re.I)
            if own and f"S00E{int(own.group(1)):02d}" != ep.code:
                reason += f" The file calls itself S00E{int(own.group(1)):02d}; go by the title."
            return Verdict("wanted", action, reason)
    if not tv and ctx.radarr_movies is not None and c.size_bytes > RADARR_WANTED_MIN_BYTES:
        movie = ctx.radarr_movies.get(folder)
        if movie and not movie.has_file:
            year = f" ({movie.year})" if movie.year else ""
            return Verdict("wanted", f'Get it into Radarr as "{movie.title}{year}" with Manual Import.',
                           "Radarr has this movie but no file for it.")
    target = extras_target(path, ctx.tv_subdirs)
    if target:
        return Verdict("plex", f"Move to {target}",
                       "Bonus material, but Plex only finds extras directly inside a Featurettes/, "
                       "Trailers/ (etc.) folder in the title's own folder.")
    if tv and looks_special(path):
        if ctx.specials is None:
            reason = "Looks like a special, but Sonarr couldn't be checked this scan."
        elif folder not in ctx.specials:
            reason = "Looks like a special, but Sonarr has no series in this folder."
        else:
            reason = "Looks like a special, but none of Sonarr's missing specials for this show matches the name."
        return Verdict("identify", "Watch it and work out what it is.", reason)
    if _is_loose(path):
        return Verdict("call", "Move it into a show or movie folder, or delete it.",
                       "Loose file at the top of the library. Sonarr, Radarr and Plex only see files inside a title's folder.")
    return Verdict("call", "Your call.", "Nothing here says whether it's a duplicate or something worth keeping.")
```

- [ ] **Step 6: Run the new tests**

Run: `python3 -m pytest -q test_orphans.py test_verdicts.py`
Expected: all pass.

- [ ] **Step 7: Run the suite** (this also checks the `title_folder` rename didn't break `mark_superseded`)

Run: `python3 -m pytest -q`
Expected: `208 passed`

- [ ] **Step 8: Commit**

```bash
/usr/bin/git -C /Users/mike/code/qbit-prunarr/.claude/worktrees/extras-specials add app/orphans.py app/verdicts.py app/test_orphans.py app/test_verdicts.py
/usr/bin/git -C /Users/mike/code/qbit-prunarr/.claude/worktrees/extras-specials commit -m "feat: verdict rules and Plex extras split for Needs Review

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Wire it into the scan

**Files:**
- Modify: `app/main.py`:
  - imports
  - new fetchers next to `_fetch_plex_episode_paths`
  - `_extras_cache` next to `_group_cache`
  - `run_scan()` between `attach_sidecars(...)` and the `_scan_cache` rebuild
  - `_enrich_candidate`
  - `_EMPTY_ORPHANS_CONTEXT` and `orphans_scan`
- Test: `app/test_orphans_routes.py`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces, for Task 6's templates:
  - each enriched candidate dict gains `"verdict"` (kind or `None`), `"verdict_action"`, `"verdict_reason"` and `"keep"` (bool)
  - the template context gains `"extras_groups"`: a list of `{"folder", "count", "size_bytes", "size_gb", "files": [{"name", "size_gb"}]}`, biggest first
  - `run_scan()` keeps its `(candidates, statuses)` signature; extras are never in `candidates`

- [ ] **Step 1: Write the failing route tests** (append to `app/test_orphans_routes.py`)

```python
FILM = "media/movies/Film (2020)"


def _plex_with_extras(extra_paths=(), raises=False):
    plex = _mock_client(
        get_all_movie_paths={f"{FILM}/Film.mkv"}, get_all_episode_paths=set(),
        get_movie_files={f"{FILM}/Film.mkv": ["7"]}, get_episode_files={},
        get_extra_paths=set(extra_paths),
    )
    if raises:
        plex.get_extra_paths.side_effect = RuntimeError("plex 500 on one key")
    return plex


def _scan_with(tmp_path, plex, sonarr=None, radarr=None):
    import os
    root = str(tmp_path)
    _make_file(os.path.join(root, *FILM.split("/"), "Film.mkv"))
    _make_file(os.path.join(root, *FILM.split("/"), "Featurettes", "Making Of.mkv"))
    _make_file(os.path.join(root, *FILM.split("/"), "Extras", "Trailer.mkv"))
    _make_file(os.path.join(root, *FILM.split("/"), "film-sample.mkv"))
    with patch("main.QBitClient", return_value=_mock_client(get_all_content_paths=set())), \
         patch("main.SonarrClient", return_value=sonarr or _mock_client(get_all_episode_paths=set(), get_all_queue_paths=set())), \
         patch("main.RadarrClient", return_value=radarr or _mock_client(
             get_all_movie_paths={f"{FILM}/Film.mkv"}, get_all_queue_paths=set(), get_movies=[])), \
         patch("main.PlexClient", return_value=plex):
        return TestClient(app).post("/orphans/scan")


def test_confirmed_extra_is_never_in_the_scan_cache(tmp_path):
    import os
    _scan_with(tmp_path, _plex_with_extras({f"{FILM}/Featurettes/Making Of.mkv"}))
    inode = os.stat(os.path.join(str(tmp_path), *FILM.split("/"), "Featurettes", "Making Of.mkv")).st_ino
    assert inode not in main._scan_cache
    assert any("Making Of.mkv" in c.paths[0] for c in main._extras_cache)


def test_bulk_delete_of_an_extra_skips_it(tmp_path):
    import os
    path = os.path.join(str(tmp_path), *FILM.split("/"), "Featurettes", "Making Of.mkv")
    plex = _plex_with_extras({f"{FILM}/Featurettes/Making Of.mkv"})
    _scan_with(tmp_path, plex)
    with patch("main.QBitClient", return_value=_mock_client(get_all_content_paths=set())), \
         patch("main.SonarrClient", return_value=_mock_client(get_all_episode_paths=set(), get_all_queue_paths=set())), \
         patch("main.RadarrClient", return_value=_mock_client(
             get_all_movie_paths={f"{FILM}/Film.mkv"}, get_all_queue_paths=set(), get_movies=[])), \
         patch("main.PlexClient", return_value=plex):
        TestClient(app).post("/orphans/delete", data={"inodes": [str(os.stat(path).st_ino)]}, follow_redirects=False)
    assert os.path.exists(path)


def test_failed_extras_lookup_keeps_everything_in_review(tmp_path):
    response = _scan_with(tmp_path, _plex_with_extras(raises=True))
    review = _table_region(response.text, "review-table")
    assert "Making Of.mkv" in review
    assert "Plex extras: not checked" in _swapped_region(response.text)


```

- [ ] **Step 2: Run them to confirm they fail**

Run: `python3 -m pytest -q test_orphans_routes.py -k "extra"`
Expected: 3 failures: `AttributeError: module 'main' has no attribute '_extras_cache'`, a deleted extra, and no "Plex extras: not checked" line. The tests that need the new template (Extras tab, verdict lines) are written in Task 6.

- [ ] **Step 3: Implement the `main.py` imports.** Extend the `from orphans import (...)` list with `split_plex_extras` and `title_folder`, then add:

```python
from verdicts import KEEP_KINDS, MissingSpecial, RadarrMovie, SeriesSpecials, VerdictContext, assign_verdict
```

- [ ] **Step 4: Add the cache.** Add this under `_group_cache: dict[str, OrphanGroup] = {}`:

```python
# Media candidates Plex has attached as local extras. Display only: these
# never enter _scan_cache and run_scan never returns them, so no delete
# route can reach one.
_extras_cache: list[OrphanCandidate] = []
```

- [ ] **Step 5: Add the fetchers.** Add these after `_fetch_plex_episode_paths`:

```python
def _fetch_plex_extras(title_folders: set[str], prefix: str) -> set[str]:
    """Relative paths of every file Plex has attached as a local extra to a
    title whose folder is in title_folders. Its own session, so a failure
    here can't make Plex itself look unreachable."""
    with PlexClient(os.environ["PLEX_URL"], os.environ["PLEX_TOKEN"]) as client:
        files = {**client.get_movie_files(), **client.get_episode_files()}
        keys: set[str] = set()
        for raw, item_keys in files.items():
            if title_folder(to_relative(raw, prefix)) in title_folders:
                keys.update(item_keys)
        if not keys:
            return set()
        return {to_relative(p, prefix) for p in client.get_extra_paths(keys)}


def _fetch_sonarr_specials(tv_folders: set[str], prefix: str) -> dict[str, SeriesSpecials]:
    """Missing season-0 episodes for each Sonarr series whose folder holds a
    Needs Review file, keyed by that folder. A series with nothing missing
    still gets an entry, so "no series here" stays distinguishable from
    "nothing matched"."""
    with SonarrClient(os.environ["SONARR_URL"], os.environ["SONARR_API_KEY"]) as client:
        out: dict[str, SeriesSpecials] = {}
        for series in client.get_series():
            folder = to_relative(series["path"], prefix).rstrip("/")
            if folder in tv_folders:
                missing = tuple(MissingSpecial(**e) for e in client.get_missing_specials(series["id"]))
                out[folder] = SeriesSpecials(series=series["title"], missing=missing)
        return out


def _fetch_radarr_movies(prefix: str) -> dict[str, RadarrMovie]:
    with RadarrClient(os.environ["RADARR_URL"], os.environ["RADARR_API_KEY"]) as client:
        return {
            to_relative(m["path"], prefix).rstrip("/"): RadarrMovie(m["title"], m["year"], m["has_file"])
            for m in client.get_movies()
        }
```

- [ ] **Step 6: Change `run_scan()`.** Insert this right after `attach_sidecars(candidates, data_root)` and before `_scan_cache.clear()`:

```python
    # Extras: Plex alone vouches for these, so pull them out of Needs
    # Review before anything else looks at it. Plex unusable/unreachable
    # or a failed lookup leaves extra_paths None: nothing moves.
    review_folders = {title_folder(c.paths[0]) for c in candidates if c.category == "orphaned media"}
    extra_paths = None
    if plex_movie_paths is not None and plex_episode_paths is not None:
        extra_paths = _safe(lambda: _fetch_plex_extras(review_folders, plex_prefix)) if review_folders else set()
        if extra_paths is None:
            plex_extras_status = "not checked"
        else:
            plex_extras_status = "ok"
    else:
        plex_extras_status = None
    candidates, extras = split_plex_extras(candidates, extra_paths)
    _extras_cache.clear()
    _extras_cache.extend(extras)

    tv_folders = {
        title_folder(c.paths[0]) for c in candidates
        if c.category == "orphaned media" and is_tv_path(c.paths[0], TV_SUBDIRS)
    }
    if sonarr_paths is None:
        specials = None
    elif tv_folders:
        specials = _safe(lambda: _fetch_sonarr_specials(tv_folders, sonarr_prefix))
    else:
        specials = {}
    radarr_movies = _safe(lambda: _fetch_radarr_movies(radarr_prefix)) if radarr_paths is not None else None
    ctx = VerdictContext(TV_SUBDIRS, specials, radarr_movies, radarr_paths)
    for c in candidates:
        if c.category == "orphaned media":
            c.verdict = assign_verdict(c, ctx)
```

At the bottom of `run_scan()`, after the `statuses = {...}` dict is built, add:

```python
    # Only worth a line when Plex itself was fine but its extras weren't:
    # otherwise the Plex line already explains why nothing moved.
    if plex_extras_status == "not checked":
        statuses["Plex extras"] = "not checked"
```

- [ ] **Step 7: Extend `_enrich_candidate`.** Add these keys to its returned dict:

```python
        "verdict": c.verdict.kind if c.verdict else None,
        "verdict_action": c.verdict.action if c.verdict else None,
        "verdict_reason": c.verdict.reason if c.verdict else None,
        "keep": bool(c.verdict and c.verdict.kind in KEEP_KINDS),
```

- [ ] **Step 8: Add `_extras_groups()`** below `_download_units`:

```python
def _extras_groups() -> list[dict]:
    """Extras tab rows: one header per movie/show folder, biggest first."""
    by_folder: dict[str, list[OrphanCandidate]] = {}
    for c in _extras_cache:
        by_folder.setdefault(title_folder(c.paths[0]), []).append(c)
    groups = []
    for folder, members in by_folder.items():
        size = sum(m.size_bytes for m in members)
        groups.append({
            "folder": folder,
            "count": len(members),
            "size_bytes": size,
            "size_gb": _format_gb(size),
            "files": [
                {"name": os.path.relpath(m.paths[0], folder), "size_gb": _format_gb(m.size_bytes)}
                for m in sorted(members, key=lambda m: m.paths[0])
            ],
        })
    return sorted(groups, key=lambda g: -g["size_bytes"])
```

- [ ] **Step 9: Pass it to the template.** Add `"extras_groups": []` to `_EMPTY_ORPHANS_CONTEXT`, and `"extras_groups": _extras_groups(),` to the success context dict in `orphans_scan`.

- [ ] **Step 10: Run the suite**

Run: `python3 -m pytest -q`
Expected: `211 passed`. If any *existing* test fails, stop and investigate: unconfigured mock methods return empty iterables, so existing scans should behave exactly as before.

- [ ] **Step 11: Commit**

```bash
/usr/bin/git -C /Users/mike/code/qbit-prunarr/.claude/worktrees/extras-specials add app/main.py app/test_orphans_routes.py
/usr/bin/git -C /Users/mike/code/qbit-prunarr/.claude/worktrees/extras-specials commit -m "feat: split out Plex extras and assign Needs Review verdicts in the scan

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Templates — verdict buckets and the Extras tab

**Files:**
- Modify: `app/templates/_orphan_row.html`
- Modify: `app/templates/orphans.html` (CSS, tabs, review tbody, Extras panel, JS)
- Modify: `app/test_orphans_routes.py` (`test_needs_review_offers_folder_grouping`)
- Modify: `README.md`

**Interfaces:**
- Consumes: Task 5's candidate keys (`verdict`, `verdict_action`, `verdict_reason`, `keep`) and `extras_groups`.

- [ ] **Step 1: Update the existing mode test and add a tab test** in `app/test_orphans_routes.py`. Replace `test_needs_review_offers_folder_grouping` with:

```python
def test_needs_review_offers_verdict_grouping():
    response = TestClient(app).get("/orphans")
    assert 'data-mode="verdict"' in response.text and 'data-mode="flat"' in response.text


def test_extras_tab_exists_without_counts_before_a_scan():
    response = TestClient(app).get("/orphans")
    assert 'data-tab="extras"' in response.text
    assert 'data-panel="extras"' in response.text
    assert 'class="tab-count"' not in response.text


def test_keep_rows_guard_their_delete(tmp_path):
    response = _scan_with(tmp_path, _plex_with_extras())
    review = _table_region(response.text, "review-table")
    trailer_row = review[review.index("Extras/Trailer.mkv") - 600: review.index("Extras/Trailer.mkv") + 1500]
    assert "keep-cb" in trailer_row
    assert "The suggestion is to keep" in trailer_row


def test_plex_confirmed_extra_moves_to_extras_tab(tmp_path):
    response = _scan_with(tmp_path, _plex_with_extras({f"{FILM}/Featurettes/Making Of.mkv"}))
    review = _table_region(response.text, "review-table")
    extras = _table_region(response.text, "extras-table")
    assert "Making Of.mkv" not in review
    assert "Making Of.mkv" in extras
    assert "Trailer.mkv" in review


def test_review_rows_carry_their_verdict(tmp_path):
    response = _scan_with(tmp_path, _plex_with_extras())
    review = _table_region(response.text, "review-table")
    assert 'data-verdict="junk"' in review          # film-sample.mkv
    assert 'data-verdict="plex"' in review          # Extras/Trailer.mkv
    assert "Move to Film (2020)/Trailers/Trailer.mkv" in review


def test_sonarr_series_folder_with_prefix_and_trailing_slash_still_maps(tmp_path, monkeypatch):
    import os
    monkeypatch.setenv("SONARR_PATH_PREFIX", "/data")
    root = str(tmp_path)
    _make_file(os.path.join(root, "media", "tv", "Show", "Season 01", "ep1.mkv"))
    _make_file(os.path.join(root, "media", "tv", "Show", "Show.S01E00.The.Pilot.Story.mkv"))
    sonarr = _mock_client(
        get_all_episode_paths={"/data/media/tv/Show/Season 01/ep1.mkv"}, get_all_queue_paths=set(),
        get_series=[{"id": 3, "title": "Show", "path": "/data/media/tv/Show/"}],
        get_missing_specials=[{"code": "S00E01", "title": "The Pilot Story", "monitored": True}],
    )
    plex = _mock_client(get_all_movie_paths=set(), get_all_episode_paths={"media/tv/Show/Season 01/ep1.mkv"},
                        get_movie_files={}, get_episode_files={"media/tv/Show/Season 01/ep1.mkv": ["1", "2"]},
                        get_extra_paths=set())
    with patch("main.QBitClient", return_value=_mock_client(get_all_content_paths=set())), \
         patch("main.SonarrClient", return_value=sonarr), \
         patch("main.RadarrClient", return_value=_mock_client(get_all_movie_paths=set(), get_all_queue_paths=set(), get_movies=[])), \
         patch("main.PlexClient", return_value=plex):
        response = TestClient(app).post("/orphans/scan")
    assert 'Import as S00E01 "The Pilot Story"' in _table_region(response.text, "review-table")
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `python3 -m pytest -q test_orphans_routes.py -k "verdict or extras or keep or sonarr_series"`
Expected: failures on `data-mode="verdict"`, `data-tab="extras"`, `extras-table`, `data-verdict`, `Import as` and `keep-cb`.

- [ ] **Step 3: Update the row template** (`app/templates/_orphan_row.html`). Replace the whole file with:

```html
<tr id="orphan-row-{{ c.inode }}"{% if c.is_child %} class="group-child"{% endif %} data-path="{{ c.display_path }}" data-size-bytes="{{ c.size_bytes }}" data-sidecars="{{ (c.sidecars or []) | length }}">
  <td><input type="checkbox" name="inodes" value="{{ c.inode }}" class="orphan-cb{% if c.keep %} keep-cb{% endif %}"></td>
  <td>{{ c.display_path }}{% if c.extra_paths > 0 %} (+{{ c.extra_paths }} more){% endif %}
    {%- if c.superseded_by and not c.verdict %}
    <span class="superseded" title="Radarr tracks {{ c.superseded_by }} in this folder">Superseded: Radarr has a newer copy in this folder</span>
    {%- endif %}
    {%- if c.sidecars %}
    <span class="sidecars" title="Also deleted with it: {{ c.sidecars | join(', ') }}">+{{ c.sidecars | length }} sidecar{{ 's' if c.sidecars | length != 1 }}</span>
    {%- endif %}
    {%- if c.tracks_sample and not c.verdict %}
    <span class="tracks-sample" title="Radarr's file for this movie is a sample clip, so this is probably the real movie. Fix it in Radarr instead of deleting.">Radarr is tracking a sample: likely the real movie</span>
    {%- endif %}
    {%- if c.verdict %}
    <div class="verdict-action verdict-{{ c.verdict }}">&rarr; {{ c.verdict_action }}</div>
    <div class="verdict-reason">{{ c.verdict_reason }}</div>
    {%- endif %}</td>
  <td>{{ c.size_gb }} GB</td>
  <td>
    <button hx-delete="/orphans/{{ c.inode }}"
            hx-target="#orphan-row-{{ c.inode }}"
            hx-swap="outerHTML"
            {% if c.keep %}class="keep-delete"
            hx-confirm="The suggestion is to keep {{ c.display_path }}. Delete anyway?{% if c.sidecars %} Its {{ c.sidecars | length }} sidecar file(s) go with it.{% endif %}"
            {% else %}hx-confirm="Delete {{ c.display_path }}?{% if c.sidecars %} Its {{ c.sidecars | length }} sidecar file(s) ({{ c.sidecars | join(', ') }}) go with it.{% endif %}"
            {% endif %}hx-params="none"
            hx-disabled-elt="this">
      Delete
    </button>
  </td>
</tr>
```

- [ ] **Step 4: Add the CSS.** Append inside `<style>` in `orphans.html`, just before `</style>`:

```css
    .verdict-action { font-weight: 600; margin-top: 3px; }
    .verdict-reason { font-size: 12.5px; color: var(--text-muted); margin-top: 2px; }
    .verdict-junk { color: #f5b8bb; } .verdict-wanted { color: #9cc3f5; } .verdict-plex { color: #a6dcb3; }
    .verdict-identify { color: #c9b8f5; } .verdict-call { color: var(--warn-text); }
    button.keep-delete { background: #4a4d54; color: var(--text-muted); }
    button.keep-delete:hover { background: var(--danger); color: #fff; }
    .bucket-title { font-weight: 700; font-size: 16px; }
    tbody.folder-head .bucket-title + .folder-meta { margin-left: 12px; }
    .bucket-sub { color: var(--text-muted); font-size: 13px; font-weight: 400; margin: 3px 0 0 26px; }
    tbody.folder-head.bucket-junk td { border-top-color: #c8302a; } tbody.folder-head.bucket-junk .bucket-title { color: #f5b8bb; }
    tbody.folder-head.bucket-wanted td { border-top-color: #5a8fd9; } tbody.folder-head.bucket-wanted .bucket-title { color: #9cc3f5; }
    tbody.folder-head.bucket-plex td { border-top-color: #2f8f5b; } tbody.folder-head.bucket-plex .bucket-title { color: #a6dcb3; }
    tbody.folder-head.bucket-identify td { border-top-color: #8c6ad9; } tbody.folder-head.bucket-identify .bucket-title { color: #c9b8f5; }
    .tabs button.extras-tab[aria-selected="true"] { border-top-color: #2f8f5b; color: #a6dcb3; }
    .tabs button.extras-tab[aria-selected="true"] .tab-count { background: #2f8f5b; }
    .extras-box { background: #1b2a21; border: 2px solid #2f5a3c; border-radius: 6px; padding: 4px 20px 20px; }
    .extras-box h2 { color: #a6dcb3; margin-top: 20px; }
    .extras-box .section-subtitle { color: #a6dcb3; opacity: 0.85; }
    tbody.extras-head td { background: var(--header-bg); color: #a6dcb3; font-weight: 600; padding-top: 10px; border-top: 2px solid #2f5a3c; }
    tbody.extras-head .folder-meta { color: var(--text-muted); font-weight: 400; margin-left: 12px; }
    #extras-table tr.extras-file td:first-child { padding-left: 32px; color: var(--text-muted); }
```

- [ ] **Step 5: Add the Extras tab button.** Add it right after the Needs Review tab button in `<nav class="tabs">`:

```html
    {% set extras_count = extras_groups | sum(attribute="count") %}
    {% set extras_bytes = extras_groups | sum(attribute="size_bytes") %}
    <button type="button" role="tab" data-tab="extras" class="extras-tab">Extras{% if scanned %}
      <span class="tab-count">{{ extras_count }} · {{ "%.1f" % (extras_bytes / 1e9) }} GB</span>{% endif %}</button>
```

- [ ] **Step 6: Update the Needs Review panel**
  - Replace its subtitle `<p class="section-subtitle">…</p>` with:

```html
    <p class="section-subtitle">Files Sonarr, Radarr and Plex don't account for, sorted by what to do about them. Each row says what to do and why.</p>
```

  - Replace the "Grouped by folder" button with:

```html
          <button type="button" class="sort-mode" data-mode="verdict">Grouped by what to do</button>
```

  - Add `data-verdict="{{ c.verdict or 'call' }}"` to the review `<tbody class="orphan-unit" …>`.

- [ ] **Step 7: Add the Extras panel** right after the review `</section>`:

```html
  <section class="tab-panel" data-panel="extras" role="tabpanel">
  <div class="extras-box">
    <h2>Extras</h2>
    <p class="section-subtitle">Plex has these attached as extras to a movie or show, so they're kept on purpose. Listed for reference only: nothing here can be deleted from this page.</p>
    {% if extras_groups %}
    <table id="extras-table">
      <thead><tr><th>Path</th><th>Size</th></tr></thead>
      {% for g in extras_groups %}
      <tbody class="extras-head"><tr><td colspan="2">{{ g.folder }}/<span class="folder-meta">{{ g.count }} extra{{ 's' if g.count != 1 }} · {{ g.size_gb }} GB</span></td></tr></tbody>
      <tbody>{% for f in g.files %}<tr class="extras-file"><td>{{ f.name }}</td><td>{{ f.size_gb }} GB</td></tr>{% endfor %}</tbody>
      {% endfor %}
    </table>
    {% elif scanned %}
    <p class="not-scanned">No Plex extras among the files this scan found.</p>
    {% endif %}
  </div>
  </section>
```

- [ ] **Step 8: Replace the folder grouping JS with verdict grouping.** In the `<script>` in `orphans.html`:

  1. **Default view.** In `sortStates`, change `'review-table': { column: 'folder', dir: 'asc' }` to `'review-table': { column: 'verdict', dir: 'asc' }`.

  2. **The grouping code.** Delete everything from the comment `// Group by the movie or show folder` through the end of `function refreshFolderState(...) { ... }`. That covers `titleFolder`, `parentDir`, `formatGB`, `applyFolderGrouping`, `OPEN_KEY`, `openFolders`, `saveOpenFolders`, `setFolderOpen`, `toggleFolder`, `folderUnits` and `refreshFolderState`. Replace it with:

```js
  // Needs Review groups by verdict: what to do with each file. Order is
  // the decision order: clear-cut deletes first, the files to keep next,
  // the ones needing a look last.
  var BUCKETS = [
    { kind: 'junk', title: 'Probably junk', sub: "Safe to delete once you've glanced at the reason." },
    { kind: 'wanted', title: 'Keep: Sonarr/Radarr wants it', sub: 'Real content your library is missing. Import it instead of deleting it.' },
    { kind: 'plex', title: "Keep: Plex can't see it", sub: 'Bonus material in a place or under a name Plex ignores. Moving it makes it show up as an extra.' },
    { kind: 'identify', title: 'Identify it', sub: 'Looks like a special, but nothing matched. Watch it, then rename it or treat it as an extra.' },
    { kind: 'call', title: 'Your call', sub: 'No evidence either way.' }
  ];
  // Keep buckets get no select-all: ticking a whole "keep this" group by
  // accident is exactly the mistake this view exists to prevent.
  var KEEP = { wanted: true, plex: true };

  function formatGB(bytes) { return (bytes / 1e9).toFixed(2) + ' GB'; }

  function applyVerdictGrouping(table, units) {
    var byKind = {};
    units.forEach(function (u) {
      var kind = u.dataset.verdict || 'call';
      u.dataset.folder = kind;
      (byKind[kind] = byKind[kind] || []).push(u);
    });
    var cols = table.querySelectorAll('thead th').length;
    var closed = closedBuckets();
    BUCKETS.forEach(function (b) {
      var members = byKind[b.kind];
      if (!members) { return; }
      var bytes = members.reduce(function (n, u) { return n + (parseInt(u.dataset.sizeBytes, 10) || 0); }, 0);
      var head = document.createElement('tbody');
      head.className = 'folder-head bucket-' + b.kind;
      head.dataset.folder = b.kind;
      var row = head.insertRow();
      var cbCell = row.insertCell();
      if (!KEEP[b.kind]) {
        var cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.className = 'folder-cb';
        cb.title = 'Select every file in this group';
        cbCell.appendChild(cb);
      }
      var cell = row.insertCell();
      cell.colSpan = cols - 1;
      var toggle = document.createElement('button');
      toggle.type = 'button';
      toggle.className = 'folder-toggle';
      toggle.innerHTML = '<span class="group-chevron">&#9654;</span>';
      cell.appendChild(toggle);
      var title = document.createElement('span');
      title.className = 'bucket-title';
      title.textContent = b.title;
      cell.appendChild(title);
      var meta = document.createElement('span');
      meta.className = 'folder-meta';
      meta.textContent = members.length + (members.length === 1 ? ' file · ' : ' files · ') + formatGB(bytes);
      cell.appendChild(meta);
      var sub = document.createElement('div');
      sub.className = 'bucket-sub';
      sub.textContent = b.sub;
      cell.appendChild(sub);
      setFolderOpen(table, head, members, !closed.has(b.kind));
      table.appendChild(head);
      members
        .sort(function (a, c) { return a.dataset.path < c.dataset.path ? -1 : 1; })
        .forEach(function (u) { table.appendChild(u); });
      refreshFolderState(table, b.kind);
    });
  }

  // Buckets start open; remember the ones you close, so a rescan keeps them.
  var CLOSED_KEY = 'orphans-review-closed';
  function closedBuckets() {
    try { return new Set(JSON.parse(localStorage.getItem(CLOSED_KEY)) || []); } catch (e) { return new Set(); }
  }
  function saveClosedBuckets(set) {
    try { localStorage.setItem(CLOSED_KEY, JSON.stringify(Array.from(set))); } catch (e) {}
  }
  function setFolderOpen(table, head, units, open) {
    head.classList.toggle('expanded', open);
    units.forEach(function (u) { u.classList.toggle('folder-hidden', !open); });
  }
  function toggleFolder(head, open) {
    var table = head.closest('table');
    var kind = head.dataset.folder;
    setFolderOpen(table, head, folderUnits(table, kind), open);
    var set = closedBuckets();
    if (open) { set.delete(kind); } else { set.add(kind); }
    saveClosedBuckets(set);
  }

  function folderUnits(table, kind) {
    return Array.prototype.filter.call(table.querySelectorAll(':scope > tbody.orphan-unit'),
      function (u) { return u.dataset.folder === kind; });
  }

  // Tri-state bucket checkbox, same as group headers. Keep buckets have none.
  function refreshFolderState(table, kind) {
    var head = Array.prototype.find.call(table.querySelectorAll(':scope > tbody.folder-head'),
      function (h) { return h.dataset.folder === kind; });
    var folderCb = head && head.querySelector('.folder-cb');
    if (!folderCb) { return; }
    var cbs = [];
    folderUnits(table, kind).forEach(function (u) { cbs.push.apply(cbs, u.querySelectorAll('.orphan-cb')); });
    var checked = cbs.filter(function (c) { return c.checked; }).length;
    folderCb.checked = checked > 0 && checked === cbs.length;
    folderCb.indeterminate = checked > 0 && checked < cbs.length;
  }
```

  3. **`applySort`.** Replace each `'folder'` with `'verdict'`: in `table.classList.toggle('folder-mode', …)`, in the `.sort-mode` active check, and in `if (state.column === 'folder')`. Also replace the call `applyFolderGrouping(table, units)` with `applyVerdictGrouping(table, units)`.

  4. **The mode-button handler.** Replace the `.sort-mode` click handler with the version below. It fixes deviation 5: the Expand/Collapse all buttons share the class but have no `data-mode`.

```js
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.sort-mode');
    if (!btn || !btn.dataset.mode) { return; }
    sortStates['review-table'] = btn.dataset.mode === 'verdict'
      ? { column: 'verdict', dir: 'asc' } : { column: 'size', dir: 'desc' };
    try { localStorage.setItem('orphans-review-mode', btn.dataset.mode); } catch (e2) {}
    applySort('review-table');
  });
```

  5. **Select-all skips keep rows.** In the `change` handler, replace the `select-all-review` selector `'#review-table .orphan-cb, #review-table .folder-cb'` with `'#review-table .orphan-cb:not(.keep-cb), #review-table .folder-cb'`.

  6. **Sticky bar.** Make `activeTableId()` return `null` on the Extras tab, which has no selection:

```js
  function activeTableId() {
    var active = document.querySelector('.tab-panel.active');
    if (!active) { return null; }
    if (active.dataset.panel === 'review') { return 'review-table'; }
    if (active.dataset.panel === 'download') { return 'download-table'; }
    return null;
  }
```

  7. Check with `grep -n "titleFolder\|parentDir\|applyFolderGrouping\|openFolders\|'folder'" app/templates/orphans.html`. Expected: no output.

- [ ] **Step 9: Update the README** (`README.md`)
  - Replace the **Needs Review** bullet under how the scan works with:

```markdown
- **Needs Review**: media-side files that aren't confirmed by *both* the relevant \*arr (Sonarr for TV, Radarr for movies) *and* Plex. Each one gets a verdict saying what to do with it and why. Files Plex has attached as extras (a correctly placed `Featurettes/` file, say) move to their own read-only **Extras** tab instead, since Plex alone vouches for those.
```

  - Replace the four bullets under `### Working through Needs Review` with:

```markdown
Rows are grouped by what to do with them:

- **Probably junk**: sample clips, and older copies Radarr has replaced (Radarr never removes files it didn't import itself).
- **Keep: Sonarr/Radarr wants it**: a special that matches, by title, an episode Sonarr lists as missing (the row names the exact `S00Exx` to import it as), a movie Radarr has no file for, or the real movie when Radarr is tracking its sample.
- **Keep: Plex can't see it**: bonus material in a folder or under a name Plex ignores. The row gives the path to move it to.
- **Identify it**: looks like a special, but nothing in Sonarr matched. Watch it and work out what it is.
- **Your call**: no evidence either way.

Delete is still there on every row, but on the two Keep groups it's greyed and asks first, and select-all skips them. Deleting a video also deletes its sidecars in the same folder: `Film.srt`, `Film.en.srt`, `Film.nfo`, `Film-thumb.jpg`. If another video shares the name, nothing is claimed.
```

  - Delete the Limitations bullet that starts `- TV extras and specials that Sonarr hasn't matched still land in Needs Review.`

- [ ] **Step 10: Run the suite**

Run: `python3 -m pytest -q`
Expected: `216 passed` (211 + 6 new here − 1 replaced). If the count differs, check that every listed test exists rather than chasing the number.

- [ ] **Step 11: Check it in a browser** (the suite doesn't exercise the JS)

Run the dev server against fixture data. Use the existing manual-verification approach from earlier branches (`uvicorn main:app --port 8586` from `app/` with a `.env`). Then check:
- The bucket header shows a visible gap between the title and "N files · X GB".
- Buckets collapse and expand, and Expand all / Collapse all keep the grouped view (they no longer flip to flat).
- Keep buckets have no header checkbox, and select-all doesn't tick their rows.
- A Keep row's Delete shows "The suggestion is to keep … Delete anyway?".
- The Extras tab shows grouped files with no checkboxes, and the sticky bar stays hidden there.
- Flat list still sorts by size.

- [ ] **Step 12: Commit**

```bash
/usr/bin/git -C /Users/mike/code/qbit-prunarr/.claude/worktrees/extras-specials add app/templates/_orphan_row.html app/templates/orphans.html app/test_orphans_routes.py README.md
/usr/bin/git -C /Users/mike/code/qbit-prunarr/.claude/worktrees/extras-specials commit -m "feat: group Needs Review by what to do, add the Extras tab

Expand all / Collapse all no longer switch the table to flat mode: they
share the .sort-mode class, so the mode handler was catching them too.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Live check on the NAS

This needs Mike. Deploying means rebuilding the NAS container. Prepare the commands, but don't run the deploy without his go-ahead.

- [ ] **Step 1: Hand Mike the deploy commands.** Use the same steps as earlier PRs, from the project memory. Give one short command per block, because long chained commands get mangled on paste.
- [ ] **Step 2: After his scan, compare the bucket counts** with mockup v2. The mockup had junk 1, wanted 32, plex 35, identify 7, call 6, Extras 54. Expected differences:
  - "wanted" is lower by 2 and "plex" higher by 2: Duchovny and Ellen move to plex (deviation 2). So expect roughly junk 1, wanted 30, plex 37, identify 7, call 6, Extras 54.
  - Counts shift for any files Mike has moved since 2026-10-10.
  - Anything else is a finding to investigate before opening the PR.
