# ANALYZE

This step runs on Maestro's default Claude Code agent config — no
`customEnvVars` override. That means it talks to real Anthropic, plain,
unproxied. This is deliberate: understanding a codebase or a bug well
enough to hand off a real plan is exactly the "pop a Mentat" judgment work
this whole project exists to protect, not something to route to a local
model by default.

Maestro spawns a fresh, independent agent session for each Playbook
document — ANALYZE, PLAN, and IMPLEMENT do not share conversational
memory with each other. The only thing that survives across documents in
one Auto Run job is the filesystem, specifically the
`/Users/mike/code/qbit-prunarr/.maestro/playbooks/Working` directory. Writing your output only in chat
means the next document can never see it — write it to a real file.

## Task

- [x] Read the target repository and identify what the current behavior is, with file/line references. `main` HEAD `4055701` already has v2-plan Task 1 (sort fix); Tasks 2-7 exist only on worktree `qbit-v2-ui` branch `worktree-qbit-v2-ui` (HEAD `cd18ccc`, 21/21 tests), with Task 7 polish still uncommitted there. Details in analysis doc.
- [x] Identify what's actually being asked for, distinguished from what was literally requested if they differ. Literal plan text says "implement tasks 1-7"; real remaining work is reconciling/landing the already-implemented worktree branch onto `main` (dropping a duplicate Task-1 commit), finishing the uncommitted Task 7 polish, then PR — not writing new app code.
- [x] Note any constraints discovered by reading the code that weren't visible from the task description alone. Duplicate content-identical Task-1 commits on `main` (`4055701`) vs worktree (`0086473`) will conflict on naive rebase/merge; two copies of templates exist and only the worktree copy is live for manual verification; no JS test harness for the client-side sort; live `.env` sits uncommitted in the worktree. Full detail in analysis doc.
- [x] Write all three findings to `/Users/mike/code/qbit-prunarr/.maestro/playbooks/Working/analysis.md` as a single analysis document. Create the `Working` directory first if it doesn't exist. Written.

## Exit condition

`/Users/mike/code/qbit-prunarr/.maestro/playbooks/Working/analysis.md` exists and covers all three
points above. Hand off to PLAN.
