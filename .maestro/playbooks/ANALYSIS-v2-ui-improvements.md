---
type: analysis
title: qbit-prunarr v2 UI Improvements — Analysis
created: 2026-09-06
tags:
  - qbit-prunarr
  - analysis
related:
  - '[[2026-07-05-v2-ui-improvements]]'
---

# ANALYZE output: qbit-prunarr v2 UI improvements

**Target repository:** `/Users/mike/code/qbit-prunarr`
**Task source:** `docs/superpowers/plans/2026-07-05-v2-ui-improvements.md` — a fully-written 7-task implementation plan already exists in the target repo (not authored by this Mentats run). Codebase inspected below to confirm the plan's assumptions still hold before handing off to Mentats' own PLAN step.

## 1. Current behavior (file/line references)

- `app/main.py:58` and `app/main.py:136` — tag filter is hardcoded to the literal string `"only-for-ratio"` in both `index()` and `widget()`. No `QBIT_TAG` env var exists anywhere in the file.
- `app/main.py:86-88` — `filtered` is built from `enriched` and passed straight to `_bucket_torrents()` with no `.sort()` call. Row order within a bucket is whatever `client.get_torrents()` returned (qBit's arbitrary API order) — confirmed bug, not yet fixed.
- `app/main.py:116` — single-delete error fragment hardcodes `colspan="6"`, matching today's 6-column table (checkbox, Name, Size, Inactive, Category, Delete).
- `app/templates/index.html:6` and `:37` — title/heading both read "qBit Pruner" (not yet renamed to "qBit Prunarr").
- `app/templates/index.html:63` and `app/templates/_row.html:8` — Size column header is bare `Size`, cell renders `{{ t.size_gb }} GB` (suffix inline, left-aligned, no `.num` class).
- `app/templates/index.html:74` — bucket-header row uses `colspan="5"` (5 columns after the checkbox column).
- `app/templates/index.html:8-30` — light theme only; no CSS custom properties, no dark skin, no `.sortable`/`.sort-asc`/`.sort-desc` classes.
- No column sort exists anywhere — no `data-sort`, `data-name`, `data-size`, `data-inactive` attributes, no sort JS.
- `app/test_main.py` — exactly 7 tests exist today (`test_index_happy_path`, `test_index_min_days_filter`, `test_index_qbit_unreachable`, `test_delete_single_torrent_happy`, `test_delete_single_torrent_failure`, `test_bulk_delete_redirects`, `test_widget_returns_json`), all passing pre-change. This matches the existing plan's stated baseline exactly — **the codebase is in the exact pre-change (v1) state the plan assumes.** None of the 6 v2 items are implemented yet.

## 2. What's actually being asked (vs. literal task description)

The literal ANALYZE.md task text is generic ("read the target repository, identify current behavior...") and names no specific feature — by itself it doesn't point at a task. The actual work item is defined by the pre-existing plan doc at `docs/superpowers/plans/2026-07-05-v2-ui-improvements.md`, which is addressed to "agentic workers" and already written to task-by-task, TDD-style detail (failing test → minimal impl → passing test → commit, for 6 features across 7 tasks).

What's really being asked of *this* ANALYZE step, then, is narrower than "analyze the whole app": confirm that plan's factual claims about the current codebase (file paths, line ranges, test count, column counts) are still accurate before Mentats' PLAN step treats that document as ready to execute. They are — see section 1. No drift between the plan's assumptions and current `main.py`/`index.html`/`_row.html`/`test_main.py`.

## 3. Constraints discovered from the code that weren't visible from the task description alone

- **Colspan coupling:** `main.py:116`'s hardcoded `colspan="6"` in the delete-error-fragment string and `index.html:74`'s `colspan="5"` bucket-header row are two independent literals that must both be bumped in lockstep with any column-count change (Task 2 adds a Tags column: 6→7 and 5→6 respectively). Missing either breaks table layout silently — this is called out in the plan's Global Constraints but is easy to miss since the two colspans live in different files (`.py` f-string vs `.html` template).
- **No JS test harness:** the stack is pytest + FastAPI TestClient only — no npm/jest. The column-sort feature (Task 5) can only get automated coverage for the server-rendered `data-*` attributes; the actual sort interaction is manual-browser-only. This constrains what "tests pass" can mean for that task specifically.
- **`.env` compatibility constraint:** the NAS's live `.env` has no `QBIT_TAG` key. The plan's default (`only-for-ratio` via `os.environ.get("QBIT_TAG", "only-for-ratio")`) is required to keep prod deployment a zero-config change — this isn't stated in ANALYZE.md but is load-bearing for Task 2 and for the final deploy step.
- **No `customEnvVars` override on this Mentats stage:** per ANALYZE.md's own preamble, this analysis step (and PLAN) run on real Anthropic, unproxied — deliberately, since judging whether a pre-written plan still matches reality is exactly the kind of call this pipeline reserves for a real model rather than the local model IMPLEMENT will use.

## Handoff

All three ANALYZE findings above confirm the existing plan document is current and ready to execute as-is. PLAN's job is to formally adopt `docs/superpowers/plans/2026-07-05-v2-ui-improvements.md` (already meets PLAN.md's bar: concrete files, order, and per-task verification) or explicitly re-derive it — no code changes were made in this step.
