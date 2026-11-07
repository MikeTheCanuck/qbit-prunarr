# Needs Review, One Group at a Time — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Needs Review shows one verdict group at a time, keep rows can't be bulk-deleted, and the only Delete is the bottom bar, which confirms in a styled dialog.

**Architecture:** The server renders five group cards, with counts, from a `REVIEW_BUCKETS` constant in `main.py`. A new `_review_row.html` partial renders each row with a readable name and folder from `_review_title()`. Page JS in `orphans.html` then does three things:

- It hides every row outside the current group. This replaces the old folder-head grouping, flat mode and Expand/Collapse all.
- It runs the `⋯` menus.
- It drives a native `<dialog>` for confirms.

There are no route changes.

**Tech Stack:** FastAPI, Jinja2, HTMX 2.0.3, vanilla JS, pytest.

**Spec:** `docs/superpowers/specs/2026-11-01-needs-review-cards-design.md`

## Global Constraints

- **Scope:** the Unlinked Downloads table and `_orphan_row.html` / `_orphan_group.html` stay functionally unchanged. The download tab keeps its per-row Delete and native `confirm()`.
- **No route or server-side delete changes.** `POST /orphans/delete`, `DELETE /orphans/{inode}` and their responses stay as they are.
- **Show and hide with the `hidden` attribute or a JS-toggled class, never CSS `:has()`.** Firefox didn't re-evaluate a `:has` rule after JS changed a class (see `test_expand_collapse_all_is_toggled_by_script_not_has`).
- **Copy is verbatim from the spec.** That covers card labels and titles, mode lines, empty states, dialog title, notes and buttons.
- **Keep kinds are `wanted` and `plex`** (`verdicts.KEEP_KINDS`). Keep rows render no `name="inodes"` checkbox at all.
- **Sizes stay in GB.** Python uses `_format_gb`. JS uses the existing `formatGB(bytes)`, which gives 2 decimals plus `" GB"`.
- **Run tests from `app/`** with `.venv/bin/python -m pytest -q`. If `.venv` is missing, create it per the README's Development section. Baseline: 239 passing.
- **Comments match the file's existing density.** Write short "why" comments above non-obvious blocks, not line-by-line narration.

## Review Focus

1. **A rescan while a group is selected.** The page swaps `#scan-results`. The remembered group must be re-applied after `htmx:afterSwap`, and must fall back to the first non-empty group if it's now empty. Task 1 owns this; it's a manual-check item, because the tests don't run JS.
2. **Ticked rows in a hidden group.** They must still post on bulk delete and still count in the bar. A reasonable person expects "3 selected" to mean the 3 they ticked, wherever those rows are. Tasks 1 and 3 own this (manual check). Task 3 also asserts that the bar counts `#review-table .orphan-cb:checked` without filtering by visibility.
3. **A keep row that is somehow posted.** It must still delete only through `Delete anyway…`. Task 2 pins this: the test asserts that a keep row has no `name="inodes"` input.
4. **Copy path over plain http.** `navigator.clipboard` is undefined outside a secure context, so the hidden-textarea `execCommand('copy')` fallback must run. Task 2 asserts that the fallback is in the page.
5. **A single delete from the dialog whose re-check fails or skips.** The server swaps in a `<tr>` with colspan 4 and no `data-size-bytes`. Card counts must drop that row, and the row must not stay greyed as "deleting". Task 3's recount counts only `tr[data-size-bytes]`. Manual check.

---

### Task 1: Group cards replace grouping, flat mode and Expand/Collapse

**Files:**
- Modify: `app/main.py`. Add `REVIEW_BUCKETS` and `_review_buckets()`, and pass `review_buckets` into the scan context. `_EMPTY_ORPHANS_CONTEXT` gets `"review_buckets": []`.
- Modify: `app/templates/orphans.html`. Change the Needs Review markup, the CSS, and the JS in `applySort`, `applyVerdictGrouping`, `closedBuckets`, the folder toggles and the sort-mode handlers.
- Test: `app/test_orphans_routes.py`.

**Interfaces:**
- **Produces:** `REVIEW_BUCKETS: list[dict]`. Each entry has the keys `kind`, `label`, `title`, `sub`, in this order:

  | kind | label | title | sub |
  |---|---|---|---|
  | `junk` | `Delete` | `Probably junk` | today's `sub` |
  | `wanted` | `Keep` | `Sonarr/Radarr wants it` | today's |
  | `plex` | `Keep` | `Plex can't see it` | today's |
  | `identify` | `Look first` | `Identify it` | today's |
  | `call` | `Look first` | `Your call` | today's |

  The `sub` strings come from the current JS `BUCKETS` in `orphans.html:319-325`, moved verbatim.
- **Produces:** `_review_buckets(review_candidates: list[dict]) -> list[dict]`. It returns every bucket, empty ones included, each as `{**bucket, "keep": bool, "count": int, "size_bytes": int, "size_gb": str}`. A candidate whose `verdict` is `None` counts as `call`.
- **Produces, in the DOM, for Tasks 2 and 3:**
  - `#review-buckets`, which holds `button.bucket[data-kind]`, each with `.b-meta` text `N file(s) · X GB`.
  - `.group-head[data-kind]`, one per bucket. The JS shows only the current one.
  - `#review-table[data-current]`, set by the JS.
  - `tbody.orphan-unit[data-verdict]`, as today.
  - The JS functions `showBucket(kind)` and `recountBuckets()`.

- [ ] **Step 1: Write the failing tests.** Add these tests to `test_orphans_routes.py`:

```python
def test_review_buckets_count_every_kind_including_empty():
    rows = [{"verdict": "junk", "size_bytes": 2_000_000_000}, {"verdict": None, "size_bytes": 5}]
    b = {x["kind"]: x for x in main._review_buckets(rows)}
    assert [x["kind"] for x in main.REVIEW_BUCKETS] == ["junk", "wanted", "plex", "identify", "call"]
    assert b["junk"]["count"] == 1 and b["junk"]["size_gb"] == "2.0"
    assert b["call"]["count"] == 1          # no verdict counts as Your call
    assert b["wanted"]["count"] == 0 and b["wanted"]["keep"] is True
    assert b["junk"]["keep"] is False


def test_needs_review_shows_group_cards_after_a_scan(tmp_path):
    response = _scan_with(tmp_path, _plex_with_extras())
    swapped = _swapped_region(response.text)
    cards = swapped[swapped.index('id="review-buckets"'):swapped.index('id="review-form"')]
    assert 'data-kind="junk"' in cards and "Probably junk" in cards and ">Delete<" in cards
    assert "Sonarr/Radarr wants it" in cards and "Keep: " not in cards
    assert "Nothing to delete here. Do the step under each file." in swapped
    assert "Tick the ones to delete." in swapped


def test_needs_review_with_nothing_says_so(tmp_path):
    with _services():
        html = TestClient(app).post("/orphans/scan").text
    assert "Nothing needs review." in html
    assert 'id="review-buckets"' not in html


def test_needs_review_drops_flat_mode_and_expand_collapse():
    html = TestClient(app).get("/orphans").text
    assert 'data-mode="flat"' not in html and 'data-folders="expand"' not in html
    assert "folder-all" not in html and "orphans-review-mode" not in html
    assert "showBucket" in html and "orphans-review-bucket" in html
```

- [ ] **Step 2: Run them and confirm they fail.**

Run: `.venv/bin/python -m pytest -q -k "review_buckets or group_cards or nothing_says_so or drops_flat"`
Expected: 4 failures (an AttributeError on `REVIEW_BUCKETS`, and missing markup).

- [ ] **Step 3: Implement the server side.** Add `REVIEW_BUCKETS` and `_review_buckets()` to `main.py`. Put `"review_buckets": _review_buckets(review_candidates)` in the scan context next to `review_candidates`, and `"review_buckets": []` in `_EMPTY_ORPHANS_CONTEXT`.

- [ ] **Step 4: Implement the template.** In the Needs Review section, make these changes:
  - **Before the form,** when `scanned and review_candidates` is true, render `<div id="review-buckets" class="buckets">` with one `<button type="button" class="bucket k-{kind}" data-kind="{kind}" aria-pressed="false">` per bucket. Each button holds `.b-kind` (the label), `.b-title` and `.b-meta`.
  - **Next to the cards,** render one `.group-head.k-{kind}[data-kind][hidden]` per bucket. Each holds `.g-title`, `.g-sub` and `.g-mode`, where `.g-mode` is the keep or tick mode line from the spec.
  - **Add an empty-group message:** `<p class="group-empty" hidden>Nothing left in this group.</p>`.
  - **When `scanned` is true and `review_candidates` is empty,** render only `<p class="not-scanned">Nothing needs review.</p>`, with no cards and no table.
  - **Remove** `.sort-modes`, `.folder-all` and their buttons.
  - **Keep** `.review-actions` only if it still has content after Task 3. For now, leave `#review-delete-btn` in place.
  - **CSS:** port `.buckets`, `.bucket`, `.k-*`, `.group-head` and their children from the approved mockup (the styles summarized below). Delete the `tbody.folder-head*`, `.bucket-title`, `.bucket-sub`, `.folder-toggle`, `.folder-hidden`, `#review-table.folder-mode`, `.review-actions .folder-all*`, `.sort-modes` and `.sort-mode*` rules.

  Mockup styles to port:
  - grid of 5 equal columns, which becomes 2 columns under 760px
  - 3px top border in the bucket colour
  - the pressed card gets `--header-bg` plus an inset 1px ring in its colour

  The bucket colours are the existing `#c8302a/#f5b8bb`, `#5a8fd9/#9cc3f5`, `#2f8f5b/#a6dcb3`, `#8c6ad9/#c9b8f5`, and `--warn-border/--warn-text`.

- [ ] **Step 5: Implement the JS.**
  - **Delete** `BUCKETS`, `applyVerdictGrouping`, `closedBuckets`/`saveClosedBuckets`/`setFolderOpen`/`toggleFolder`/`folderUnits`/`refreshFolderState`, the `.folder-toggle`/`[data-folders]` click handler, the `.sort-mode` click handler, and the `orphans-review-mode` localStorage read.
  - **`sortStates['review-table']`** defaults to `{ column: 'path', dir: 'asc' }`. `applySort('review-table')` still orders all units and then calls `showBucket(current)`.
  - **Add `showBucket(kind)`.** It does five things:
    - sets `aria-pressed` on the cards
    - un-hides the matching `.group-head` and hides the others
    - sets the `bucket-hidden` class on units whose `data-verdict` (default `call`) isn't `kind`; CSS is `.bucket-hidden { display: none; }`
    - shows `.group-empty` when no visible unit has a `tr[data-size-bytes]`
    - hides `#select-all-review` on keep kinds (a JS `KEEP = { wanted: true, plex: true }`), and otherwise syncs its checked/indeterminate state from the current group's checkboxes

    Store `kind` in localStorage under `orphans-review-bucket`, inside a try/catch.
  - **Add `recountBuckets()`.** For each card, count the units of that kind containing `tr[data-size-bytes]`, then rewrite `.b-meta` as `N file(s) · formatGB(bytes)`. It returns the counts by kind.
  - **Choosing the current group,** on load and after every `htmx:afterSwap`: use the remembered kind if its count is above 0, otherwise the first bucket in card order with a count above 0, otherwise `junk`.
  - **The `#select-all-review` change handler** ticks or unticks only `.orphan-cb` inside units that aren't `.bucket-hidden`.
  - **Clicking a card** calls `showBucket(card.dataset.kind)` and then `refreshSticky()`.

- [ ] **Step 6: Update the tests this task makes obsolete.**
  - Delete `test_expand_collapse_all_is_toggled_by_script_not_has` and `test_needs_review_offers_verdict_grouping`.
  - In `test_page_has_sticky_delete_bar_and_folder_controls`, drop the `data-folders` assertion and rename the test to `test_page_has_sticky_delete_bar`.
  - Then run the full suite.

Run: `.venv/bin/python -m pytest -q`
Expected: all pass. The count is 239 − 2 + 4 = 241.

- [ ] **Step 7: Commit.**

```bash
git add app/main.py app/templates/orphans.html app/test_orphans_routes.py
git commit -m "feat: Needs Review shows one verdict group at a time"
```

---

### Task 2: Review rows lead with the name, keep rows lose their checkbox

**Files:**
- Create: `app/templates/_review_row.html`.
- Modify: `app/main.py`. Add `_review_title()`, and add the `title` and `folder` keys in `_enrich_candidate`.
- Modify: `app/templates/orphans.html`. The review `<thead>` and loop include `_review_row.html`. Add the row and menu CSS and the menu JS.
- Test: `app/test_orphans_routes.py`.

**Interfaces:**
- **Consumes:** Task 1's `tbody.orphan-unit[data-verdict]` wrapper, `showBucket`, and `recountBuckets`.
- **Produces:** `_review_title(display_path: str) -> tuple[str, str]`, which returns `(name, folder)`.
  - `name` is the basename with its extension removed by `os.path.splitext`. If it has no space, runs of `.` and `_` become single spaces.
  - `folder` is the path's directory parts after the first segment (`media`), joined with `" / "`. It is `""` when there are none.
- **Produces, in each review `<tr>`:**
  - `id="orphan-row-{inode}"`, `data-path`, `data-size-bytes`, `data-sidecars` (all as today)
  - new `data-name="{title}"` and `data-action="{verdict_action}"`
  - a `.more` cell holding `button.more-btn` and `.menu`, with `button.copy-path[data-path]` and, on keep rows only, `button.delete-anyway[data-inode]`

  Task 3 reads `data-name`, `data-action` and `.delete-anyway`.

- [ ] **Step 1: Write the failing tests.**

```python
@pytest.mark.parametrize("path,expected", [
    ("media/tv/Lucky Hank/Lucky.Hank.S01E07.1080p.WEB.h264-ETHEL.mkv",
     ("Lucky Hank S01E07 1080p WEB h264-ETHEL", "tv / Lucky Hank")),
    ("media/movies/Iron Man 3 2013/Sample,Screens/Iron Man 3 (Sample).mkv",
     ("Iron Man 3 (Sample)", "movies / Iron Man 3 2013 / Sample,Screens")),
    ("media/tv/American_Dad_S07E08.mkv", ("American Dad S07E08", "tv")),
    ("media/x.mkv", ("x", "")),
])
def test_review_title_splits_name_and_folder(path, expected):
    assert main._review_title(path) == expected


def test_keep_rows_have_no_checkbox_and_delete_hides_in_a_menu(tmp_path):
    response = _scan_with(tmp_path, _plex_with_extras())
    review = _table_region(response.text, "review-table")
    row = _row_for(review, "Extras/Trailer.mkv")
    assert 'name="inodes"' not in row
    assert 'class="keep-mark"' in row
    assert 'class="delete-anyway"' in row and "Delete anyway" in row
    assert "<button hx-delete" not in row   # the old red per-row Delete button is gone


def test_deletable_rows_keep_a_checkbox_and_no_delete_button(tmp_path):
    response = _scan_with(tmp_path, _plex_with_extras())
    row = _row_for(_table_region(response.text, "review-table"), "film-sample.mkv")
    assert 'name="inodes"' in row and "delete-anyway" not in row
    assert ">film-sample<" in row or "film-sample</" in row   # readable name, extension dropped
    assert 'class="copy-path"' in row


def test_review_table_has_no_delete_column():
    html = TestClient(app).get("/orphans").text
    review = html[html.index('id="review-table"'):html.index("</thead>", html.index('id="review-table"'))]
    assert "col-delete" not in review and ">Delete<" not in review
    assert ">File<" in review


def test_copy_path_works_over_plain_http():
    html = TestClient(app).get("/orphans").text
    assert "execCommand('copy')" in html
```

- [ ] **Step 2: Run them and confirm they fail.**

Run: `.venv/bin/python -m pytest -q -k "review_title or no_checkbox or keep_a_checkbox or no_delete_column or plain_http"`
Expected: failures, including an AttributeError on `_review_title`.

- [ ] **Step 3: Implement.**
  - **In `main.py`,** add `_review_title`, and add `"title"` and `"folder"` to `_enrich_candidate`. They're harmless extra keys for download rows.
  - **Create `_review_row.html`** with the four cells from the spec's Rows section:
    - **Checkbox cell:** `<input type="checkbox" name="inodes" value=… class="orphan-cb">` for non-keep rows. Keep rows get `<span class="keep-mark" title="Keep">✓</span>`.
    - **Name cell:** `.name`, with `title` set to the full display path, followed by the chips. The chips reuse today's sidecar, `+N more`, superseded and tracks-sample conditions and titles from `_orphan_row.html`, restyled as `.chip`. Then come `.folder`, the `.verdict-action.verdict-{kind}` line (`→ …`) and `.verdict-reason`.
    - **Size cell:** `<td class="size">{{ c.size_gb }} GB</td>`.
    - **Menu cell:** `.more`.

    This task does **not** use the dialog yet. Until Task 3 replaces it, `Delete anyway…` is a `<button class="delete-anyway" data-inode=… hx-delete="/orphans/{inode}" hx-target="#orphan-row-{inode}" hx-swap="outerHTML" hx-params="none" hx-confirm="The suggestion is to keep {path}. Delete anyway?">`. The class attribute comes first, so the `<button hx-delete` assertion still holds.
  - **The review `<thead>`** becomes: select-all, `File` (`sortable`, `data-sort="path"`), `Size` (`sortable col-size`, `data-sort="size"`), and an empty `<th class="col-more">`. Keep the `th.col-size` width and replace `th.col-delete` with `th.col-more { width: 44px; }`. Keep the existing `test_review_columns_have_fixed_widths` scoped to the download table's `col-delete`, and update its review assertions to `col-more`.
  - **CSS:** port `.name`, `.folder`, `.chip`, `.keep-mark`, `.more`, `.menu` and `tr.selected` from the mockup. Rows use `vertical-align: top`.
  - **Menu JS:**
    - Clicking `.more-btn` toggles `.open` on its `.more`, and a click anywhere else closes open menus.
    - `.copy-path` first tries `navigator.clipboard.writeText` when `window.isSecureContext`. Otherwise it falls back to a temporary `<textarea>` plus `document.execCommand('copy')`. It then shows `Copied` on the button for 1.5 s.
    - Ticking a row checkbox toggles `tr.selected`.

- [ ] **Step 4: Update the tests this task makes obsolete.**
  - `test_keep_rows_guard_their_delete`: replace it with the new keep-row test.
  - `test_unreachable_plex_keeps_extras_in_review_and_says_not_checked`: replace `assert "keep-cb" in row` with `assert 'name="inodes"' not in row`.
  - `test_review_confirm_warns_about_hand_ticked_keeps`: delete it. Keep rows can no longer be ticked.
  - Also drop the now-dead keep-cb branch from the review confirm JS (`#review-table .keep-cb:checked`) and the `.keep-cb` / `button.keep-delete` CSS.

Run: `.venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit.**

```bash
git add app/main.py app/templates/_review_row.html app/templates/orphans.html app/test_orphans_routes.py
git commit -m "feat: review rows lead with the name; keeps lose their checkbox"
```

---

### Task 3: One Delete in a neutral bar, confirmed in a styled dialog

**Files:**
- Modify: `app/templates/orphans.html`. Change the sticky bar markup, CSS and JS; add the `<dialog>`; replace the review `confirm()` handler; make `.delete-anyway` use the dialog.
- Modify: `app/templates/_review_row.html`. Drop the `hx-*` attributes from `.delete-anyway`.
- Modify: `README.md`. Rewrite the "Working through Needs Review" section's last paragraph and its group titles.
- Test: `app/test_orphans_routes.py`.

**Interfaces:**
- **Consumes:**
  - Task 2's `tr[data-name][data-action]` and `button.delete-anyway[data-inode]`
  - Task 1's `recountBuckets()` and `showBucket()`
  - the existing `refreshSticky()`, `activeTableId()` and `formatGB()`
- **Produces:** `openDeleteDialog(rows: HTMLTableRowElement[], opts: { keep?: boolean, onConfirm: () => void })`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_review_deletes_confirm_in_a_styled_dialog():
    html = TestClient(app).get("/orphans").text
    dialog = html[html.index('<dialog id="delete-dialog"'):html.index("</dialog>")]
    assert "Deleted files can't be recovered. Each one is re-checked first, and anything that has since shown up in Sonarr, Radarr or Plex is skipped." in dialog
    assert ">Cancel<" in dialog and "autofocus" in dialog
    assert "showModal()" in html
    assert "The suggestion is to keep this file: " in html
    assert "subtitle/metadata" in html


def test_sticky_bar_has_clear_and_is_the_review_tabs_only_delete(tmp_path):
    response = _scan_with(tmp_path, _plex_with_extras())
    html = response.text
    bar = html[html.index('id="sticky-delete"'):html.index("</div>", html.index('id="sticky-delete"'))]
    assert 'id="sticky-clear"' in bar and ">Clear<" in bar
    form = html[html.index('id="review-form"'):html.index("</form>", html.index('id="review-form"'))]
    assert 'id="review-delete-btn"' in form and 'type="submit"' in form
    assert '<button type="submit" id="review-delete-btn" hidden' in form


def test_delete_anyway_goes_through_the_dialog_not_hx_confirm(tmp_path):
    response = _scan_with(tmp_path, _plex_with_extras())
    row = _row_for(_table_region(response.text, "review-table"), "Extras/Trailer.mkv")
    assert 'class="delete-anyway"' in row and "hx-confirm" not in row and "hx-delete" not in row


def test_review_confirm_no_longer_uses_native_confirm():
    html = TestClient(app).get("/orphans").text
    assert "None of them are in your library" not in html     # the old confirm() text
    assert "confirm('Delete every selected file and folder?')" in html   # download tab unchanged
```

- [ ] **Step 2: Run them and confirm they fail.**

Run: `.venv/bin/python -m pytest -q -k "styled_dialog or has_clear or through_the_dialog or native_confirm"`
Expected: 4 failures.

- [ ] **Step 3: Implement the bar.**
  - **Markup:** `#sticky-delete` becomes `<span id="sticky-summary"></span><button type="button" id="sticky-clear">Clear</button><button type="button" id="sticky-delete-btn">Delete selected</button>`.
  - **CSS:** restyle it per the mockup's `#bar`, which looks like this:
    - background `#2d2f35`, `1px solid #4a4d54` border, 10px radius, the existing drop shadow
    - no red glow and no slide-in animation
    - `#sticky-clear` is a neutral `.btn`, and `#sticky-delete-btn` stays red
  - **`refreshSticky()`:**
    - The summary text becomes `N selected · formatGB(bytes)`.
    - The delete button reads `Delete N file(s)…` on the review tab and stays `Delete selected` on the download tab.
    - Keep counting every checked `.orphan-cb` in the active table, hidden groups included.
  - **`#sticky-clear`** unticks every `.orphan-cb`, `#select-all-*` and `.folder-cb` in the active table, clears `indeterminate` and `tr.selected`, then calls `refreshSticky()`, `refreshBulkButton()` and `refreshReviewButton()`.
  - **`#review-delete-btn`** stays a submit inside `#review-form`, but rendered with the `hidden` attribute.
  - **Clicking `#sticky-delete-btn` on the review tab** collects the checked rows (`#review-table .orphan-cb:checked` → `closest('tr')`). It calls `openDeleteDialog(rows, { onConfirm: () => form.requestSubmit(reviewBtn) })`. The existing `submit` listener keeps its busy labelling.
  - **On the download tab,** it keeps clicking `#bulk-delete-btn`, so the native confirm stays.
  - **Delete the old `review-delete-btn` confirm handler** at `orphans.html:625-639`.

- [ ] **Step 4: Implement the dialog.**
  - **Markup:** add `<dialog id="delete-dialog">` after the bar. It contains the following, in order, using the exact strings from the spec:
    - `<h3 id="dd-title">`
    - `<p class="dd-keep" hidden>`
    - `<p>These files will be removed:</p>`
    - `<ul id="dd-list">`
    - `<p class="dd-sidecars" hidden>`
    - the red-edged `<p class="dd-warn">` with the spec's note
    - a footer with `<button type="button" id="dd-cancel" autofocus>Cancel</button>` and `<button type="button" id="dd-ok" class="danger">`
  - **CSS** comes from the mockup's `.modal`, with `dialog::backdrop { background: rgba(0,0,0,.6); }`.
  - **`openDeleteDialog(rows, opts)`:**
    - **Title:** `Delete N file(s) (formatGB(sum of data-size-bytes))?`.
    - **List:** one `<li>` per row, `data-name · size`.
    - **Sidecar line:** if the sum of `data-sidecars` is above 0, show `Plus N subtitle/metadata file(s) named after them.`
    - **Keep variant:** if `opts.keep` is set, show `.dd-keep` with `The suggestion is to keep this file: ` plus the row's `data-action`, and set the OK label to `Delete anyway`. Otherwise the label is `Delete`.
    - Then call `dialog.showModal()`.
    - **OK** closes the dialog and calls `opts.onConfirm()`. **Cancel** closes it. Esc closes it natively.
    - **Escaping:** build the list with `textContent`, never `innerHTML`, because file names are untrusted.
  - **`.delete-anyway` click:**
    - Close the menu.
    - Call `openDeleteDialog([tr], { keep: true, onConfirm })`.
    - `onConfirm` adds `deleting` to the row and calls `htmx.ajax('DELETE', '/orphans/' + inode, { target: '#orphan-row-' + inode, swap: 'outerHTML' })`.
  - **Remove the `hx-*` attributes** from `.delete-anyway` in `_review_row.html`.
  - **Add `recountBuckets(); refreshSticky();`** to the existing `htmx:afterSwap` handlers, so card counts drop after a single delete. Keep the existing `deleted-row` fade.

- [ ] **Step 5: Update the README.**
  - In "Working through Needs Review", rename the two Keep bullets to `**Sonarr/Radarr wants it** (Keep)` and `**Plex can't see it** (Keep)`.
  - Open the section with: `Needs Review shows one group at a time; pick one from the cards along the top.`
  - Replace the "Delete is still there on every row…" paragraph with this, keeping its sidecar sentences verbatim:

    > Rows in the two Keep groups have no checkbox, so they can't be swept up in a bulk delete. If you really want one gone, it's under the row's `⋯` menu as **Delete anyway…**. Everything else is ticked and deleted from the bar at the bottom, which confirms with a list of exactly what's going.

  - In "Development", change "selection, grouping and the sticky delete bar" to "selection, the group cards, the delete bar and the confirm dialog".

- [ ] **Step 6: Run the full suite.**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 7: Check it by hand in a browser.** The tests don't run JS. Use a local server with `.env` copied in, or the NAS after Mike rebuilds, and check these items:
  - The cards switch groups.
  - The remembered group survives a rescan.
  - Ticking in two groups gives a bar that counts both.
  - Clear empties the selection.
  - The dialog lists the right files, Esc cancels it, and Delete posts.
  - Delete anyway on a keep row shows the amber note, and the row swaps to "Deleted …".
  - Copy path works over `http://`.
  - The download tab still uses its own per-row Delete and native confirm.

  Run the copy-path check on the NAS deploy, not on localhost, because localhost counts as a secure context.

- [ ] **Step 8: Commit.**

```bash
git add app/templates/orphans.html app/templates/_review_row.html app/test_orphans_routes.py README.md
git commit -m "feat: one Delete in a neutral bar, confirmed in a styled dialog"
```
