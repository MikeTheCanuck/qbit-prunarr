# Orphan Grouping — Design Spec

## Problem

Orphan classification runs per-file, per-inode. A single orphaned torrent
that happens to be a raw BDMV BluRay rip can fragment into hundreds of rows
in the Unlinked Downloads table — one real, reclaimable file (the movie
stream, tens of GB) plus a few hundred near-zero-byte disc-authoring index
files scattered several directories deep (`BDMV/BACKUP/CLIPINF/*.clpi`,
`BDMV/STREAM/*.m2ts`, etc). Sort-by-size already surfaces the real file
first, but reclaiming the *whole* torrent still means selecting or deleting
every fragment individually — there's no way to act on "this torrent" as a
unit, because qBittorrent has already forgotten the torrent by the time
something is classified as orphaned; there's no name left to group by.

Confirmed live during design: `torrents/completed/radarr/BIG_TRBL_LTL_CHN_BLUEBIRD/`
— 38GB, ~300 files spanning `BDMV/STREAM/`, `BDMV/BACKUP/CLIPINF/`, and
several other subfolders, all orphaned, all currently rendered as separate
rows with no relationship shown between them.

## Scope (v1)

**In scope:** grouping on the **Unlinked Downloads** table only. This is
where the motivating problem lives (a scene-release/disc-rip directory tree
fragmenting into many files) and where every file in a candidate directory
is checked against the same single source of truth (qBittorrent), so "is
this directory 100% orphaned" has no cross-service ambiguity.

**Out of scope (v1): grouping on the Needs Review table.** Needs Review
candidates are already filtered to real video files (sidecar/Sample
exclusion, shipped separately) and rarely fragment into large counts the
way a raw disc rip does — one movie file, maybe a companion subtitle that's
excluded from consideration entirely. Revisit if real usage shows otherwise.

**Out of scope (v1): a tree/nested view when a group is expanded.** Flat
list of the group's contents, each shown as its path relative to the
group's root directory (not bare filename, not full absolute path) — enough
to see folder relationships without building a recursive UI component for a
case that hasn't come up. Watch during implementation/manual verification
whether the real BDMV case reads clearly as a flat list; revisit if not.

**Out of scope (v1): nested groups.** Rollup always picks the *topmost*
fully-orphaned directory, so a fully-orphaned directory never sits inside
another group's own rollup — it just becomes part of what that outer
group's expanded view shows. There is never a "group inside a group" to
render.

## Grouping algorithm

Runs once per scan, over the Unlinked Downloads candidate set, as a
post-processing step after `classify_download_orphans` already produced its
flat list — it doesn't change what's classified as an orphan, only how
orphans get presented.

1. Build the set of every **real file** that exists under the download-side
   scan roots (`torrents/`, `usenet/`) — not just the orphaned ones. This is
   `result.download_only`'s paths (the orphan candidates) plus the subset of
   `result.linked`'s paths that fall under a download subdir (files that
   exist there too, just still correctly tracked). Together these are every
   file the scan actually found on disk under those roots — the full
   "ground truth" a directory's contents get checked against.
2. For each orphan candidate's path, walk upward from its immediate parent
   directory. At each directory, check: does every real file that exists
   under it (recursively, using the full-ground-truth set from step 1)
   appear in the orphan-candidate set? If yes, that directory is a rollup
   candidate — keep climbing to its parent and repeat. Stop climbing (a)
   the first time a directory fails that check, or (b) at the boundary of
   the configured scan subdir itself (`torrents`, `usenet`) — a group is
   never one of those roots in its entirety, only something strictly inside
   one, mirroring the existing `_boundary_for()` concept `delete_orphan`
   already uses for prune-boundary safety.
3. The **last** directory that passed the check (the topmost one) is that
   file's group root. Cache per-directory results — many files under a deep
   tree share the same ancestors, so this stays cheap even for hundreds of
   files.
4. Group every orphan candidate by its group root. A candidate whose walk
   never finds a rollup-eligible directory (its immediate parent already
   contains a file that isn't an orphan) keeps rendering as a standalone
   row, exactly as it does today — nothing changes for the common case of
   an isolated orphaned file sitting next to files that are still needed.

**Example, the running BDMV case:** every file under
`torrents/completed/radarr/BIG_TRBL_LTL_CHN_BLUEBIRD/` is an orphan
candidate, so the walk climbs all the way from e.g.
`BDMV/BACKUP/CLIPINF/00153.clpi` up through `BDMV/BACKUP/`, `BDMV/`, to
`BIG_TRBL_LTL_CHN_BLUEBIRD/` itself — the next directory up
(`torrents/completed/radarr/`) contains *other*, unrelated real torrents
that aren't orphaned, so the climb stops there. One group, root
`torrents/completed/radarr/BIG_TRBL_LTL_CHN_BLUEBIRD/`, ~300 files.

## UI / interaction

A group renders as one row in the same table, same columns as an ordinary
orphan row: path shows the group's root directory, size is the sum of every
file inside it, plus an expand/collapse toggle.

**Collapsed** (default): behaves exactly like today's individual row — one
checkbox (selects the whole group as a unit for the existing bulk-delete
form) and one Delete button (deletes everything inside it immediately, see
below). Sort-by-size treats a group's row using its summed size, same as
any other row's `data-size-bytes`.

**Expanded:** reveals the group's contents as a flat list of ordinary rows,
each showing its path *relative to the group root* (e.g.
`BDMV/BACKUP/CLIPINF/00153.clpi`, not the full
`torrents/completed/radarr/BIG_TRBL_LTL_CHN_BLUEBIRD/BDMV/BACKUP/CLIPINF/00153.clpi`,
and not bare `00153.clpi`) — enough to see which files share a subfolder
without repeating the long common prefix on every single line. These child
rows have their own checkboxes/Delete buttons too, for deleting individual
files out of a group without taking the whole thing.

## Group delete flow

1. Re-verify (re-run classification for every file the group currently
   contains — same race-condition guard the existing single/bulk delete
   flows already use, closing the gap between scan and click).
2. Delete every file still confirmed orphaned, **best-effort** — continue
   past a per-file failure rather than stopping the whole group delete on
   the first error, matching the existing bulk-delete-orphans pattern
   (`N of M deletes failed — check logs` via the existing flash-message
   mechanism, not a new one).
3. Prune now-empty directories afterward, reusing `delete_orphan`'s existing
   pruning logic, just starting from deeper points since a group can span
   many nested now-empty directories.

**Known failure mode, accepted:** if some files in a group fail to delete
(permissions, a race), the survivors reappear as ordinary standalone rows
on the next scan — no memory that they used to belong to a group. They
still render with their full path (existing behavior, unchanged), which is
enough context to judge what they are and whether they're safe to remove
individually.

## Testing

Unit tests for the grouping function against constructed fake directory
trees: a fully-orphaned deep tree (the BDMV shape — multiple nesting
levels, all orphaned), a directory with a mix of orphaned and still-tracked
content (must not roll up as a whole), a standalone orphaned file with no
eligible parent (must not group), and two sibling fully-orphaned
directories under the same non-orphaned parent (must produce two separate
groups, not merge into one).

Route-level tests: a group renders collapsed by default with the correct
summed size; expanding it reveals the flat, relative-path list of its
contents; deleting a group removes every file inside it and prunes the
resulting empty directory tree; a partial-failure group delete leaves
survivors that show up as ordinary rows on a subsequent scan.

No new manual-verification step beyond what the existing real-NAS-scan
checklist already covers — this slots into that same checklist, specifically
re-checking the known `BIG_TRBL_LTL_CHN_BLUEBIRD` case now renders (and
deletes) as one group.
