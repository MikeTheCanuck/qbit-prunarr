# CLAUDE.md

## Reasoning Captures

### 2026-10-11 — Needs Review rows need verdicts, not labels

**Context:** We were designing how to make the extras and specials in Needs Review understandable.

**What we discovered:** Descriptive badges such as Sample, Special and "Plex ignores this folder" didn't help Mike decide anything. What worked was giving each row a verdict grouped by action: Probably junk, Keep (Sonarr/Radarr wants it), Keep (Plex can't see it), Identify it, or Your call. Each verdict comes with a concrete action and a reason.

**Why it's not obvious:** The badge design read fine as text and got a "sounds plausible". The gap only showed up when Mike looked at a mockup built from real data. He could see what each file *was*, but still not whether to toss it or hoist it into Plex or Sonarr.

**Implication going forward:** Any new Needs Review signal goes into a verdict's action or reason, not into a standalone badge. A row that only describes a file without saying what to do with it is incomplete.

### 2026-10-11 — Sonarr special matching false-positive traps

**Context:** We were matching Needs Review files to Sonarr's missing season-0 episodes by title.

**What we discovered:** On the live library, three guards were each needed to stop a wrong match:
- **Two-sided token ratio.** It stops "Take a Walk on Serenity" from matching the special "Serenity".
- **Skipping files with a regular `SxxEyy` code.** It stops "S01E01 Serenity - Scene 1" from matching that same special.
- **A season guard.** Without it, every Larry Sanders outtakes file matched "Outtakes - Season 2", because number tokens get thrown away as noise.

A file's own `S00Exx` code can't be trusted either: the SCTV files carry codes Sonarr assigns to different episodes.

**Why it's not obvious:** Each guard looks like over-engineering until you see the real false positive it prevents. All three only showed up when the matcher ran against real file names.

**Implication going forward:** Don't loosen or simplify `match_sonarr_special` without re-running it against the live-scan cases in its tests. Match on the title, never on the file's own S00 code.

### 2026-10-11 — Plex's API decides extras, never names

**Context:** We were deciding how to tell which Needs Review files are extras Plex already shows.

**What we discovered:** Plex ignores nested extras folders. Firefly's `Featurettes/*.mkv` were confirmed, but `Featurettes/Deleted Scenes/*` was not. Also, `/library/sections/N/all` never lists extras; only `/library/metadata/{key}/extras` does.

**Why it's not obvious:** Matching Plex's documented folder names and suffixes looks equivalent, but it would wrongly confirm the nested files. Those files would then leave Needs Review as if Plex had them, while Plex doesn't actually show them.

**Implication going forward:** Only Plex's extras endpoint may move a file into Extras. Name rules are allowed only to *suggest* a move target, never to confirm one.
