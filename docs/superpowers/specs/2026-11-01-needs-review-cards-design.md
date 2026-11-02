# Needs Review, One Group at a Time — Design Spec

## Problem

The target audience is less confident homelabbers. Today's Needs Review tab puts every decision on screen at once:

- 86 rows on the 2026-11-01 scan
- a red Delete button on every row, including the two Keep groups
- a select-all checkbox, five collapsible group headers, Expand all / Collapse all, and a Grouped / Flat toggle

A nervous user sees a wall of red buttons next to files the page itself says to keep. The browser's native `confirm()` for bulk delete is a grey system box, which doesn't look like part of the app.

## Goal

Someone opening Needs Review sees one group, what to do with each file in it, and exactly one way to delete. For files the page says to keep, deleting takes deliberate extra steps.

A mockup built from the live scan was approved on 2026-11-01. Mike chose to judge the finer points hands-on rather than from the mockup, so this spec fixes the structure and leaves polish to real use.

## Scope

**In scope.** The Needs Review tab, and the shared bottom action bar (its look changes on both tabs).

**Out of scope, for later:**

- Unlinked Downloads keeps its per-row Delete and native confirm.
- Results still vanish on reload or after a bulk delete.
- Sizes stay in GB.
- Wording renames (Plex Extras, Orphaned Downloads) are not part of this.
- No recycle folder.

## Design

### Group picker

A row of five cards sits above the table, one per verdict, in today's decision order: junk, wanted, plex, identify, call. Each card shows three things:

- **A small uppercase label:** `Delete`, `Keep`, `Keep`, `Look first`, `Look first`.
- **A title:**
  - `Probably junk`
  - `Sonarr/Radarr wants it`
  - `Plex can't see it`
  - `Identify it`
  - `Your call`

  The "Keep:" prefix goes, because the label above now carries it.
- **A count line:** `N file(s) · X.XX GB`.

Card colours reuse today's bucket colours. Your call uses the warn amber.

Clicking a card shows only that group's rows. Under the cards sits one header strip for the current group, with three parts:

- its title
- today's one-line description of the group
- a mode line:
  - Keep groups: `Nothing to delete here. Do the step under each file.`
  - all other groups: `Tick the ones to delete.`

Which group is showing:

- The current group is remembered per browser.
- On first visit, or when the remembered group is now empty, the page shows the first non-empty group.
- An empty group still has its card. Picking it shows `Nothing left in this group.`
- A scan with no review rows at all shows `Nothing needs review.` in place of the cards and the table.

**Removed:** the five collapsible group headers, Expand all / Collapse all, the Grouped / Flat toggle and the Delete column. The File and Size headers stay sortable *within* the current group. The default order is path ascending, which keeps one release's extras together.

**Ticks carry across groups.** Switching groups only hides rows. The header select-all checkbox acts on the current group only, and is hidden on Keep groups.

### Rows

Each row has four cells.

1. **Tick or keep mark.**
   - Rows in a deletable group have a checkbox.
   - Rows in a Keep group have a ✓ mark (title "Keep") and **no checkbox**, so they can never ride along in a bulk delete.
2. **File.** This cell holds, top to bottom:
   - **A readable name.** This is the file name without its extension. If the name has no spaces, dots and underscores become spaces.
   - **Chips.** These carry what the old badges carried: the sidecar count, `+N more` hardlink paths, and the superseded / tracks-sample chips (shown only when the row has no verdict).
   - **The folder.** This is the path between the top-level library folder and the file, joined with ` / `, in muted small text.
   - **The verdict action line.** It is coloured and starts with `→`.
   - **The reason.** It is muted.
3. **Size.** Right-aligned.
4. **A `⋯` menu.** It contains:
   - `Copy path`, on every row. It copies the full display path. It has to work over plain http, because the app runs at `http://<nas>:8585`, so it can't rely on the async clipboard API alone.
   - `Delete anyway…`, on Keep rows only.

The verdict-first rule from CLAUDE.md still holds: every row says what to do and why.

### The one Delete

The bottom action bar is the only Delete on the Needs Review tab. It shows whenever the visible tab has ticked rows. It contains three things:

- the summary `N selected · X.XX GB`
- `Clear`, which unticks everything in that tab
- `Delete N file(s)…`

The bar is neutral, dark grey with a light border, with the red reserved for its Delete button. It replaces today's red-glow bar on both tabs.

Needs Review's own top "Delete selected" button goes. Its form keeps a hidden submit button, so the post path is unchanged.

### Confirm dialog

Needs Review deletes confirm in a styled modal `<dialog>`, not `confirm()`. The modal contains, in order:

- **Title:** `Delete N file(s) (X.XX GB)?`
- **A list** of the readable names, each with its size.
- **A sidecar line**, when any of the files have sidecars: `Plus N subtitle/metadata file(s) named after them.`
- **A red-edged note:** `Deleted files can't be recovered. Each one is re-checked first, and anything that has since shown up in Sonarr, Radarr or Plex is skipped.`
- **Buttons:** `Cancel`, which has focus, and `Delete`. Esc and Cancel close the dialog without doing anything.

`Delete anyway…` on a Keep row opens the same dialog for that one file, with two differences:

- An amber note goes above the list: `The suggestion is to keep this file: <verdict action>`.
- The confirm button reads `Delete anyway`.

Confirming sends that row's existing single-file DELETE. The row shows as deleting until the response swaps in.

After any delete, the card counts and the bar update without a rescan.

## Server

No route changes. A review row gets its readable name and folder from a helper in `main.py`, and the five groups come from a constant there, so the template renders the cards' counts itself and tests can check them.
