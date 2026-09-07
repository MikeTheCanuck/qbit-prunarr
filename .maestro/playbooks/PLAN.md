# PLAN

Like ANALYZE, this step has no `customEnvVars` override — it runs on
Maestro's default agent config, talking to real Anthropic. Planning is
where a wrong call is expensive to unwind later; this is squarely
judgment-heavy work.

## Task

- [x] Read ANALYZE's output. `ANALYSIS-v2-ui-improvements.md` confirms codebase is in the exact pre-v2 state the existing plan doc assumes — no drift.
- [x] Produce a concrete implementation plan: which files change, and in what order. Adopting the pre-existing plan at `qbit-prunarr/docs/superpowers/plans/2026-07-05-v2-ui-improvements.md` as-is — it already specifies 7 ordered tasks, exact files (`app/main.py`, `app/templates/index.html`, `app/templates/_row.html`, `.env.example`, `app/test_main.py`), in dependency order (ordering fix -> tag/Tags column -> rename -> Size cleanup -> sort -> dark skin -> manual verify/PR).
- [x] Specify how each change will be verified. Each task in the adopted plan is TDD-structured (failing test -> minimal impl -> `pytest` run expecting an exact pass count, incrementing 7->8->11->12->13->14->15) plus a final manual browser check against real qBit data and a full-suite run before PR.
- [x] Make the plan specific enough that IMPLEMENT (running on a local model) can execute it without needing to make further judgment calls about approach — only about mechanical correctness. Re-verified today by spot-checking the actual files: `app/main.py:86-88` unsorted `filtered`, `:116` `colspan="6"`, `app/templates/index.html:6,37` "qBit Pruner", `:63` bare `Size` header, `:74` `colspan="5"` — all match the plan's stated line numbers and literal strings exactly, so every step's before/after diff applies cleanly with no re-deciding needed.

## Exit condition

A written plan exists, is specific enough to execute without re-deciding
approach, and has been reviewed (by you, reading it, before handing off —
this project deliberately has no automated plan-reviewer step in v1).
Hand off to IMPLEMENT.

**Reviewed and adopted 2026-09-06:** the pre-written plan at `docs/superpowers/plans/2026-07-05-v2-ui-improvements.md` meets this document's bar without modification — concrete files, explicit order, per-task verification, and mechanical-only diffs (exact before/after code blocks, exact commands, exact expected pass counts). No re-derivation needed. Handing off to IMPLEMENT as-is.
