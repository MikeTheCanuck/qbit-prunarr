# ANALYZE

This step runs on Maestro's default Claude Code agent config — no
`customEnvVars` override. That means it talks to real Anthropic, plain,
unproxied. This is deliberate: understanding a codebase or a bug well
enough to hand off a real plan is exactly the "pop a Mentat" judgment work
this whole project exists to protect, not something to route to a local
model by default.

## Task

- [x] Read the target repository and identify what the current behavior is, with file/line references. Target repo = qbit-prunarr (`/Users/mike/code/qbit-prunarr`); confirmed codebase is in the exact pre-v2 (v1) state assumed by the existing plan doc — 7 passing tests, hardcoded tag filter, unsorted buckets, "qBit Pruner" title, etc. Details in analysis doc.
- [x] Identify what's actually being asked for, distinguished from what was literally requested if they differ. ANALYZE.md's literal text names no concrete feature; the real task is the pre-written plan at `qbit-prunarr/docs/superpowers/plans/2026-07-05-v2-ui-improvements.md` — this step's real job was verifying that plan's factual claims about the codebase still hold, not analyzing from scratch.
- [x] Note any constraints discovered by reading the code that weren't visible from the task description alone. Colspan coupling across two files, no JS test harness for the sort feature, NAS `.env` compatibility requirement for `QBIT_TAG` default. Details in analysis doc.
- [x] Write up all three findings as a single analysis document. Written to `ANALYSIS-v2-ui-improvements.md` in this same folder.

## Exit condition

A written analysis document exists and covers all three points above. Hand
off to PLAN.
