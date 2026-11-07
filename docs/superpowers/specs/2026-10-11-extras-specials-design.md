# Extras and Specials in Needs Review — Design Spec

## Problem

Needs Review lists media files that Sonarr/Radarr and Plex don't both
account for. The 2026-10-10 live scan put 146 files (~104 GB) there, and
almost none of it is junk. Most of it is bonus material the user collected
on purpose. That material falls into three groups:

- extras Plex already shows
- extras Plex can't see because of where they sit or how they're named
- specials that Sonarr lists as missing, even though the file is sitting right there

The table gives no way to tell these apart, so every row means a manual
investigation, and the real question ("toss it, or get it into Plex/Sonarr?")
goes unanswered.

Root cause for the biggest group: `PlexClient` reads
`/library/sections/{id}/all`, which only ever returns main movies and
episodes. A correctly named extra can never be confirmed, so it lands in
Needs Review forever.

## Goal

Every Needs Review row says what to do with the file and why. Files that
need no decision (extras Plex already has) leave Needs Review entirely.

Success: the user can work through Needs Review deciding toss-or-hoist row
by row, without querying Sonarr/Radarr/Plex by hand.

Validated with two mockups built from the real scan and live
Plex/Sonarr/Radarr answers (2026-10-11). The second one, grouped by action,
is the one this spec describes.

## Scope

**In scope**

1. **Extras tab.** Files Plex has attached as local extras move out of Needs Review into a read-only tab.
2. **Verdicts.** Every remaining Needs Review row gets one of five verdicts, plus a suggested action and a reason. The table is grouped by verdict.
3. **Matching.** Specials are matched to Sonarr's missing season-0 episodes by title.
4. **Move targets.** Extras Plex ignores get the target path Plex would recognize.

**Out of scope**

- Moving, renaming or importing files from the UI. Suggestions are text only, and the user acts in Finder, Sonarr or Radarr.
- A general per-row \*arr status column (hasFile/monitored for regular episodes). The verdicts cover the cases that matter here; revisit if "Your call" stays large.
- The ongoing cataloguing routine. That is a working session the user runs with Claude once this ships, not code.

## Verified facts this design rests on

- `GET /library/metadata/{ratingKey}/extras` returns local extras. Each has `Media[].Part[].file` set to the real path. Online trailers come back in the same list with no `file`; skip them. (Live probe, 2026-10-10.)
- Movie extras hang off the movie's ratingKey. TV extras hang off the show's ratingKey. Season-level extras were empty for every show probed, but including the season keys costs little.
- Plex ignores nested extras folders. Firefly's `Featurettes/*.mkv` were confirmed, but `Featurettes/Deleted Scenes/*` and `Featurettes/Specials/**` were not. So a naming rule would over-confirm, and Plex's API has to be the authority.
- Episode items in `/all?type=4` carry `parentRatingKey` (season) and `grandparentRatingKey` (show).
- Plex's movie extras folders: `Behind The Scenes`, `Deleted Scenes`, `Featurettes`, `Interviews`, `Scenes`, `Shorts`, `Trailers`, `Other`. Inline suffixes: `-behindthescenes`, `-deleted`, `-featurette`, `-interview`, `-scene`, `-short`, `-trailer`, `-other`. (support.plex.tv/articles/local-files-for-trailers-and-extras/. The TV equivalent page returned 403, so TV placement follows the live probe: `<Show>/Featurettes/` works.)
- Sonarr's season-0 episodes, with titles, come from `GET /api/v3/episode?seriesId=N`. On the live library they matched 25 of the Needs Review files by title, including all 22 Larry Sanders interviews/outtakes and Supernatural "The Long Road Home" (S00E09). Because the titles come from Sonarr's own episode list, a match means Sonarr already has an episode slot to import the file into.

## Data flow

All of this runs inside `run_scan()` after `classify_media_orphans`. Nothing
here changes what counts as an orphan; it only re-sorts and annotates the
media-side candidates.

### Plex

The two separate Plex fetches become one session, `_fetch_plex()`, which
returns both file maps from the WIP client patch
(`handoff_extras_plex_client.patch`, already tested):

- `get_movie_files()`: path -> [movie ratingKey]
- `get_episode_files()`: path -> [show ratingKey, season ratingKey]

The existing `plex_movie_paths` / `plex_episode_paths` sets are their keys,
so classification is unchanged.

Next, take the title folders (`orphans._title_folder`) of every
`orphaned media` candidate. Collect the rating keys of Plex files that live
in those folders, and call `get_extra_paths(keys)` in the same session. That
costs one request per title that has candidates (55 on the live library),
not one per library item.

Paths are normalized with `PLEX_PATH_PREFIX` like every other Plex path.

### Sonarr

The new client method is `get_missing_specials(series_ids)`. It returns,
for each series id, that series' season-0 episodes with `hasFile=false` as
`(code, title, monitored)`, where code is like `"S00E09"`.

It is called only for series whose folder contains a TV candidate. The
series list (`/api/v3/series`) is already fetched for episode paths;
`get_all_episode_paths` is extended to also return each series' `path` and
`id`, so no second series call is needed.

### Radarr

`get_all_movie_paths` is extended to also return, for each movie, its
folder `path`, `title`, `year`, and whether it has a file. Same single
`/api/v3/movie` call. This feeds the "Radarr has the movie but no file"
case.

### Failure handling (fail closed, same as today)

- If the extras fetch fails, or Plex is unreachable or unusable, no candidate moves to Extras. Everything stays in Needs Review, which is today's behaviour. The Plex status line adds "extras not checked".
- If the Sonarr specials fetch fails, there are no Sonarr matches. Those files fall through to later verdicts ("Plex can't see it", "Identify it", "Your call"), and nothing is ever marked junk because of a missing lookup.
- If Radarr's movie metadata is unavailable, the "Radarr wants it" and "superseded" verdicts can't fire. The files fall through the same way.

## Classification

### Step 1: split out confirmed extras

The new pure function is
`split_plex_extras(candidates, extra_paths) -> (review, extras)`. A
candidate is an extra when any of its paths is in `extra_paths`. Plex alone
vouches for it, because Sonarr and Radarr never track video extras.

Confirmed extras are stored in a new `_extras_cache` for rendering. They
**never** enter `_scan_cache`, and every delete route looks up
`_scan_cache`, so no delete path can reach an extra.

### Step 2: verdict per Needs Review candidate

`assign_verdict(candidate, context) -> Verdict(kind, action, reason)` is a
pure function in `orphans.py`. `context` carries the Sonarr missing
specials, the Radarr movie map and the TV subdirs. Rules apply in this
order, and the first match wins:

1. **junk: sample.**
   - Applies when "sample" appears as a whole word in the file name or any folder, *and* the file is under 500 MB.
   - Action: "Delete it."
   - If Radarr's tracked file for this movie *is* this sample, the reason adds "then run a Rescan in Radarr so it picks up the real file".
2. **junk: superseded.**
   - Applies to an existing `superseded_by` candidate.
   - Action: "Delete it (older copy)."
   - Reason: "Radarr tracks a different file in this folder: X".
3. **wanted: Radarr tracks a sample.**
   - Applies to an existing `tracks_sample` candidate.
   - Action: "This is probably the real movie. Delete the sample Radarr tracks, then Rescan."
4. **wanted: Sonarr special.**
   - Applies to a TV candidate that `match_sonarr_special` matches (below).
   - Action: `Import as S00Exx "<title>" via Sonarr's Manual Import.` If Sonarr has the episode unmonitored, add "turn monitoring on first".
   - If the file's own `S00Exx` code differs from the match, the reason says so ("the file calls itself S00E10; go by the title").
5. **wanted: Radarr has no file.**
   - Applies to a movie candidate over 1 GB whose title folder is a Radarr movie with no file.
   - Action: `Get it into Radarr as "<title> (<year>)" with Manual Import.`
6. **plex: Plex can't see it.**
   - `extras_target(path)` returns where Plex would pick the file up (below).
   - Action: "Move to `<target>`".
   - Reason: Plex only finds extras directly inside an extras folder in the title's own folder, or named with an extras suffix.
7. **identify.**
   - Applies to a TV candidate that looks like a special but matched nothing. It looks like a special when:
     - its name has `S00Exx` or `SxxE00`, or
     - its *immediate* parent folder is `Specials`, `Season 00` or `Season 0`, or
     - "special" is a whole word in the name.
   - Action: "Watch it and work out what it is."
   - Reason: either none of Sonarr's missing specials for this show match, or Sonarr has no series at this folder.
8. **call: loose file.**
   - Applies to a file sitting directly in a library root (`media/tv/x.avi`).
   - Action: "Move it into a show/movie folder, or delete it."
   - Reason: Sonarr, Radarr and Plex only see files inside a title's folder.
9. **call.**
   - Everything else.
   - Action: "Your call."
   - Reason: "Nothing here says whether it's a duplicate or something worth keeping."

`superseded_by` and `tracks_sample` stay as they are computed today
(`mark_superseded`). The verdict replaces their badges in the UI.

### `match_sonarr_special(path, series_missing) -> episode | None`

This is a pure function, tuned against the live library.

- Skip files whose name has a regular episode code (`SxxEyy`, both non-zero). These are deleted scenes from a normal episode, e.g. `S01E01 Serenity - Scene 1`, and would otherwise match the "Serenity" special.
- Normalize the file name (minus extension) and each missing episode title:
  - lowercase
  - split on non-alphanumerics
  - drop release noise: resolutions, codecs, sources, fps/kbit, bare numbers, `SxxEyy`/`Sxx` codes
- **Exact match first:** if the cleaned title is longer than 8 characters and the cleaned file name ends with it, it's a match. This catches titles made only of stopwords plus the series name, like "In The Newsroom".
- **Otherwise, token match:**
  - Significant tokens leave out stopwords, generic bonus words (interview, deleted, scenes, bonus, visit, garry, …) and the series' own name tokens.
  - Score = min(|shared| / |title tokens|, |shared| / |file tokens|).
  - It is a match at score ≥ 0.5, provided the shared tokens add up to ≥ 4 characters.
  - The highest score wins.
  - The two-sided ratio stops "Take a Walk on Serenity" from matching the special "Serenity".
- **Season guard:** when the file name has a season marker (`S03`) and the title has "Season N", they must agree. Without this, every Larry Sanders outtakes file matched "Outtakes - Season 2".

Test cases come straight from the live scan; see Testing.

### `extras_target(path) -> str | None`

- It returns a target when the file sits under an extras-like folder *below* the title folder, or its name contains bonus/outtakes/introduction/trailer/interview/gag. An extras-like folder is a Plex extras folder name, or anything containing "extras" or "bonus".
- **TV:** the target is `<Show>/Featurettes/<name>`. That location is proven to work by the live probe.
- **Movies:** the folder is picked by keyword:
  - "trailer" goes to `Trailers`
  - "interview" goes to `Interviews`
  - "deleted" goes to `Deleted Scenes`
  - "making" or "story of" goes to `Behind The Scenes`
  - anything else goes to `Featurettes`
- Otherwise it returns `None`.

## UI

### Tabs

The tabs are Unlinked Downloads (unchanged), Needs Review, and **Extras**.
The Extras badge shows count · GB, like the others.

### Needs Review

- **Default view groups by verdict.** This replaces "Grouped by folder", and "Flat list" (sorted by size) stays. The buckets run in this order:

  | Bucket | Subtitle |
  |---|---|
  | Probably junk | Safe to delete once you've glanced at the reason. |
  | Keep: Sonarr/Radarr wants it | Real content your library is missing. Import it instead of deleting it. |
  | Keep: Plex can't see it | Bonus material in a place or under a name Plex ignores. Moving it makes it show up as an extra. |
  | Identify it | Looks like a special, but nothing matched. Watch it, then rename it or treat it as an extra. |
  | Your call | No evidence either way. |

- **Bucket headers** have a chevron, the title, a "N files · X GB" meta line with a space or gap after the title (mockup v2 ran them together), and the subtitle. Buckets can be collapsed, and Expand all / Collapse all apply to buckets.
- **Each row** shows:
  - the path relative to `media/`
  - an arrow line with the action, in the bucket's colour
  - a muted reason line
  - size and Delete

  Rows within a bucket are sorted by path, so one show's files sit together.
- **Delete stays available on every row.** In the two Keep buckets the row's Delete button is greyed and confirms first: "The suggestion is to keep this. Delete anyway?" There is no bucket-level select-all in Keep buckets. The page-level select-all only selects rows in junk, identify and call.
- **Colours:** junk is red, wanted is blue, plex is green, identify is purple, call is the existing warn amber. These match mockup v2.

### Extras

The Extras tab is read-only: no checkboxes and no delete bar. Rows are
grouped under title-folder headers ("N extras · X GB"). Its subtitle is
"Plex has these attached as extras to a movie or show, so they're kept on
purpose."

## Testing

Pure functions get unit tests in `test_orphans.py`, built from live-scan
paths:

- **`split_plex_extras`:**
  - a path in `extra_paths` moves to extras
  - others stay
  - `extra_paths=None` moves nothing
- **`match_sonarr_special`:**
  - `LARRY SANDERS S01 bonus - interview Jeremy Piven` matches S00E17 "Interview with Jeremy Piven"
  - `S05 bonus - Duchovny` matches "Garry Interviews David Duchovny"
  - `S03 outtakes` matches "Outtakes - Season 3", not Season 2
  - `In The Newsroom.mkv` matches "In The Newsroom" (exact path)
  - `Supernatural.S15E00.The.Long.Road.Home…` matches S00E09 "Supernatural: The Long Road Home"
  - `S00E10 - The Shmenges_ The Last Polka` matches S00E07, with a code mismatch
  - `S01E01 Serenity - Scene 1` gives no match (regular episode code)
  - `Take a Walk on Serenity` gives no match
  - `S06 bonus - deleted scenes` gives no match
- **`extras_target`:**
  - Firefly nested `Featurettes/Deleted Scenes/x.mkv` goes to `Firefly/Featurettes/x.mkv`
  - Gambit `Extras/Trailer.mkv` goes to `…/Trailers/Trailer.mkv`
  - a plain movie file gives `None`
- **`assign_verdict`:**
  - one case per rule, plus rule-order cases: a sample in an extras folder is junk, and a Larry Sanders interview with a Sonarr match is wanted, not plex
  - the "looks like a special" rule uses the *immediate* parent only, so Serenity's nested featurettes are plex, not identify
- **Client tests** (pytest-httpx), following the existing patterns:
  - the PlexClient patch's 3 tests
  - `get_missing_specials`
  - the extended Sonarr and Radarr returns
- **Route tests** in `test_orphans_routes.py`:
  - the Extras tab renders confirmed extras
  - a confirmed extra's inode can't be deleted through `/orphans/delete`, because it isn't in `_scan_cache`
  - when the extras fetch fails, everything stays in Needs Review
  - bucket headers and the action/reason lines render

Manual check: deploy to the NAS, run a scan, and compare bucket counts
with mockup v2 (1 / 32 / 35 / 7 / 6, give or take files moved since).

## Unverified, flagged in the UI or here

- **Crystal Lake Memories is split into pt1/pt2.** It is unverified whether Radarr's Manual Import accepts a multi-part movie. The "Radarr has no file" reason should not claim either way; it just says Radarr has the movie with no file.
- **Exactly where Sonarr's Manual Import puts a season-0 file** (Season 00 vs Specials folder) depends on the user's Sonarr naming settings. The UI only says to use Manual Import.
