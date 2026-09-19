---
type: analysis
title: v2 UI Improvements — ANALYZE findings
created: 2026-09-12
tags:
  - qbit-prunarr
  - v2-ui
related:
  - '[[2026-07-05-v2-ui-improvements]]'
---

# ANALYZE findings

## 1. Current behavior (main branch, HEAD `4055701`)

`ANALYZE.md`/`PLAN.md` name no concrete feature themselves (generic template
text only). The only candidate task artifact sitting in the repo is
`docs/superpowers/plans/2026-07-05-v2-ui-improvements.md` (untracked in the
main working tree as of this run) — a fully-specified 7-task plan for a v2 UI
pass. Treating that as the real target (same call the previous ANALYZE run
made per the git history of this file), here is where `main` actually stands
against it:

- `main` HEAD is `4055701` — "fix: sort torrents by last_activity ascending
  within each age bucket". This is **Task 1 of the plan, already done**,
  applied directly to `main` (not via a worktree branch). 14/14 tests pass
  (`cd app && python3 -m pytest -q`).
- `app/main.py` (141 lines) and `app/qbit.py` (50 lines) are the only app
  modules; `app/templates/index.html` and `app/templates/_row.html` are still
  in **v1 shape**: no `QBIT_TAG` env var / Tags column, no title rename, no
  Size-column cleanup, no client-side sort, no dark skin, no column-width
  `<colgroup>` control. None of Tasks 2-7 exist on `main`.
- Tasks 2-7 are **already implemented**, just not on `main`: worktree
  `.claude/worktrees/qbit-v2-ui` (branch `worktree-qbit-v2-ui`, HEAD
  `cd18ccc`) has committed history `d449eb5 → 0086473 → 88115ba → e54e276 →
  0e14d8c → 48570e6 → c6d415e → cd18ccc` covering QBIT_TAG+Tags column, title
  rename, Size column, client-side band-preserving sort, Servarr dark skin,
  and a sort-reset hardening fix. 21/21 tests pass there.
  - On top of that committed history, the worktree also has **uncommitted**
    edits to `app/templates/index.html`, `app/templates/_row.html`, and
    `app/test_main.py` — column-width (`<colgroup>`/`table-layout: fixed`),
    numeric-alignment, and bucket-label-indent polish from live browser
    verification (Task 7), per prior session notes. These are real,
    unreviewed, uncommitted changes sitting on disk right now.

## 2. What's actually being asked for (vs. the literal plan text)

The plan document, read literally, says "implement tasks 1-7." That is
**not** the real remaining work. Tasks 1-6 are already implemented and
committed — on a branch, not on `main`. The actual ask is:

- **Reconcile `worktree-qbit-v2-ui` onto `main`**, not re-implement anything.
  `main`'s Task 1 commit (`4055701`) and the worktree's Task 1 commit
  (`0086473`) are **content-identical diffs** (verified via `git diff
  d449eb5 4055701 -- app/main.py` vs `git diff d449eb5 0086473 --
  app/main.py`) under different SHAs/messages — a duplicate-work artifact
  from Task 1 having been done twice, once on each branch independently.
  Landing the worktree branch means dropping/skipping that duplicate commit,
  not merging it a second time.
- **Finish and commit Task 7** (column-width/alignment polish) in the
  worktree — it's functionally complete per prior live-verification rounds
  but still sits uncommitted, and its own plan step ("get sign-off,
  commit, push, open PR") was never closed out.
- Only after both of the above does a PR against `main` make sense.

## 3. Constraints discovered by reading the code (not visible from the plan alone)

- **Rebase/merge hazard:** because `main`'s `4055701` and the worktree's
  `0086473` produce byte-identical file content from the same base
  (`d449eb5`), a naive `git rebase main` or `git merge` of
  `worktree-qbit-v2-ui` onto current `main` will hit a conflict/no-op on the
  very first commit (patch context won't apply — the change is already
  present). The correct move is to drop that one commit from the replay
  (e.g. `git rebase --onto main d449eb5 worktree-qbit-v2-ui` style skip, or
  an explicit `--empty=drop` during interactive rebase), not to resolve it
  as a normal textual conflict.
- **Two copies of the templates exist and only one is "live"** for manual
  verification: the dev server used for all prior Task-7 browser checks
  serves `.claude/worktrees/qbit-v2-ui/app/templates/*`, not
  `/Users/mike/code/qbit-prunarr/app/templates/*`. A previous session
  accidentally edited the main-checkout copy first and had to revert it.
  Any further template/CSS work for this task must target the worktree
  path.
- **`app/main.py`'s `TemplateResponse` call uses the newer Starlette
  signature** (`TemplateResponse(request, name, context)`) — confirmed
  present in the current `main.py`; the old `(name, {"request": request,
  ...})` signature silently breaks under Python 3.14, so any future edits to
  response-building code must preserve the new-style call.
- **No JS test harness** exists for the client-side band-preserving sort
  feature (Task 3) — its correctness so far has only been verified by eye
  in the browser, not by an automated test. This is a real coverage gap,
  not a missing-but-planned test.
- **`main` has also picked up unrelated commits** since the plan was
  written: two orphan-trawler documentation commits (`1bd45d8`, `b165782`)
  sit between the plan-adoption commit (`622338b`) and the Task-1 fix
  (`4055701`). They don't touch `app/`, so they don't conflict with v2-ui
  work, but they mean `main`'s history is not a clean base equal to
  `d449eb5` — anyone diffing "what v2-ui changed" against `main` needs to
  diff against `4055701`, not the initial commit.
- **A live `.env` with real qBittorrent credentials was copied into the
  worktree** (gitignored, uncommitted) to smoke-test Task 7 against real
  data on `localhost:8586`. That file must not be swept up by any generic
  "clean the worktree" step before landing this work.

## Recommendation for PLAN

Treat this as a branch-reconciliation task, not a fresh implementation:
land `worktree-qbit-v2-ui`'s already-working Tasks 2-6 onto `main` (dropping
the duplicate Task-1 commit), finish/commit the uncommitted Task 7 polish
in that same worktree first, re-run the full test suite post-rebase, then
open the PR. No new application code needs to be written from scratch.
