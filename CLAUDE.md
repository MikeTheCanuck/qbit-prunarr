# CLAUDE.md

## Reasoning Captures

### 2026-11-08 — Keep the repo; PR history is proof

**Context:** Deciding how far to scrub real library titles and release-group tags (YTS, rarbg) out of qbit-prunarr's history before a public launch under Mike's name.

**What we discovered:** The risk is reputational (a recruiter skimming), not legal. Release-group tags were the real tell, because show names alone could come from ripped discs. I first recommended deleting the repo and pushing a fresh one. Mike rejected that: the 12 PRs, four months of commits, specs and reasoning captures are the evidence that this wasn't vibe-coded, and that matters for the AI-skeptical audience. The fix was current files (#12), plus PR #5 and #9 descriptions edited and their old revisions deleted. Old PR diffs still contain the real titles, which is accepted.

**Why it's not obvious:** A fresh repo is the only complete scrub, so it looks like the careful choice. But it throws away the project's credibility to defend against someone who would have to open a months-old PR's "Files changed" tab.

**Implication going forward:** Don't delete or recreate this repo to hide history. Never put real titles, release groups or guest names in tests, docs, commits or PR text. Use the invented same-shape names. If the old diffs need to go later, use filter-repo plus a GitHub Support purge of the PR refs, not a wipe.

### 2026-11-07 — Fail-closed results look like success

**Context:** Mike asked how he'd know all four services were OK after rebuilding the hardened image on the NAS.

**What we discovered:** The only signal was a collapsed "Service status" line that looked the same whether everything worked or not. A down service never errors. It removes results: Sonarr down empties TV from Needs Review, and either \*arr down empties Unlinked Downloads. So the scan that most needs a warning looks like the tidiest library. Now any service that isn't `ok` opens a "This scan is incomplete" box naming the missing results, and a clean scan says "All 4 services OK".

**Why it's not obvious:** Failing closed is the right safety call, so it reads as finished. But it turns an outage into a quiet false negative. Showing the status but leaving it collapsed felt like enough until someone asked what to look for.

**Implication going forward:** Any new fail-closed path must say on screen, without a click, which results it removed. The "All OK" summary only shows when every status, including Plex extras, is `ok`.

### 2026-11-07 — Demo fakes the services, not the app

**Context:** We were building a demo mode for README screenshots and a "try it in 30 seconds" path that doesn't show Mike's real library.

**What we discovered:** `app/demo.py` runs fake qBittorrent, Sonarr, Radarr and Plex HTTP APIs and a sandbox library of sparse files, and the real app talks to them with no `DEMO` flag in its code. The first version reported qBittorrent and Radarr as `unusable`. Every path they tracked was hardlinked, so none of it was in the download-only or media-only scan sets that the overlap check compares against. The fix: put some seeding Linux ISOs on disk that no library file links to, and make one Radarr movie a usenet import with no hardlink.

**Why it's not obvious:** A tidy, fully hardlinked fake library looks like the ideal demo. The `unusable` check only looks at files the scan found unlinked, so a perfect library looks misconfigured.

**Implication going forward:** Don't add demo branches to `main.py`. Change `demo.py`'s library or its fake APIs instead. Each service needs at least one tracked file that isn't hardlinked. `test_demo.py` fails if any service stops reporting `ok` or any verdict group goes empty, so treat that failure as the demo drifting, not test noise.

### 2026-11-07 — Document a default, don't add a toggle

**Context:** We were deciding whether the delete dialog should let people keep a video's sidecars (subtitles, `.nfo`, artwork) while deleting the video.

**What we discovered:** No one could name a reason to keep a sidecar without its video. Adding a toggle (on or off by default) would still add a decision to every delete. The audience is less confident homelabbers who want things tidy, and more choices is exactly the climb that made Cleanuparr hard for Mike to adopt. So sidecars always go with their video, and the README's "Assumptions and trade-offs" section says so. The same goes for the edge case where a sidecar appears between the scan and the delete.

**Why it's not obvious:** A toggle feels like the safe, respectful choice for control-minded users. But each toggle makes the app harder for the main audience, and it hides the assumption in a setting instead of stating it. A written assumption is a tripwire: someone hitting a strange case can see what the app bet on and why, and can file a targeted issue.

**Implication going forward:** When a behaviour could be made optional, pick the sensible default and add it to the README's "Assumptions and trade-offs" section. Add a setting only after someone describes a real use case for it in an issue. Every corner cut or edge-case-unfriendly UX decision gets a line in that section.

### 2026-11-07 — Progress text names the files, no time estimates

**Context:** Mike was trying out Delete anyway and bulk deletes on the NAS.

**What we discovered:** Three bits of wording each misled him:
- A dimmed row with a spinner visible only on hover read as stalled.
- "Re-checking and deleting" made him expect fresh scan results on screen.
- "making sure nothing has claimed it (about 15 seconds)" left it unclear what "it" was: the video, or the video plus its sidecars? The time estimate didn't help him decide anything, because the delete was already confirmed.

The fix: the row says, in words, "Checking that qBittorrent, Sonarr, Radarr and Plex still don't use this file, then deleting the file and its N sidecars." Buttons just say "Deleting…", and the spinner shows it's still running.

**Why it's not obvious:** Each phrase reads fine to the person who wrote the code. "It" seems obvious, "re-check" is accurate, and a number feels informative. The confusion only showed up when someone used the page who didn't build it.

**Implication going forward:** Status and progress text must say which files and which apps it means, never a bare "it". Don't use words like "rescan" or "re-check" that suggest the screen will update. Show a time only when it would change what the user does next, such as before they confirm, not while it's running.

### 2026-10-11 — Needs Review rows need verdicts, not labels

**Context:** We were designing how to make the extras and specials in Needs Review understandable.

**What we discovered:** Descriptive badges such as Sample, Special and "Plex ignores this folder" didn't help Mike decide anything. What worked was giving each row a verdict grouped by action: Probably junk, Keep (Sonarr/Radarr wants it), Keep (Plex can't see it), Identify it, or Your call. Each verdict comes with a concrete action and a reason.

**Why it's not obvious:** The badge design read fine as text and got a "sounds plausible". The gap only showed up when Mike looked at a mockup built from real data. He could see what each file *was*, but still not whether to toss it or hoist it into Plex or Sonarr.

**Implication going forward:** Any new Needs Review signal goes into a verdict's action or reason, not into a standalone badge. A row that only describes a file without saying what to do with it is incomplete.

### 2026-10-11 — Sonarr special matching false-positive traps

**Context:** We were matching Needs Review files to Sonarr's missing season-0 episodes by title.

**What we discovered:** On the live library, three guards were each needed to stop a wrong match:
- **Two-sided token ratio.** It stops "Take a Walk on Lodestar" from matching the special "Lodestar".
- **Skipping files with a regular `SxxEyy` code.** It stops "S01E01 Lodestar - Scene 1" from matching that same special.
- **A season guard.** Without it, every Barry Flanders outtakes file matched "Outtakes - Season 2", because number tokens get thrown away as noise.

A file's own `S00Exx` code can't be trusted either: the TCTV files carry codes Sonarr assigns to different episodes.

**Why it's not obvious:** Each guard looks like over-engineering until you see the real false positive it prevents. All three only showed up when the matcher ran against real file names.

**Implication going forward:** Don't loosen or simplify `match_sonarr_special` without re-running it against the live-scan cases in its tests. Match on the title, never on the file's own S00 code.

### 2026-10-11 — Plex's API decides extras, never names

**Context:** We were deciding how to tell which Needs Review files are extras Plex already shows.

**What we discovered:** Plex ignores nested extras folders. Driftwood's `Featurettes/*.mkv` were confirmed, but `Featurettes/Deleted Scenes/*` was not. Also, `/library/sections/N/all` never lists extras; only `/library/metadata/{key}/extras` does.

**Why it's not obvious:** Matching Plex's documented folder names and suffixes looks equivalent, but it would wrongly confirm the nested files. Those files would then leave Needs Review as if Plex had them, while Plex doesn't actually show them.

**Implication going forward:** Only Plex's extras endpoint may move a file into Extras. Name rules are allowed only to *suggest* a move target, never to confirm one.
