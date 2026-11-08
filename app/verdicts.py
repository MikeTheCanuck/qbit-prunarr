"""Verdicts for Needs Review: what to do with each media-side orphan, and why.

Pure functions only. main.run_scan() fetches the Sonarr/Radarr/Plex data,
normalizes every path to be relative to the data root, and passes it in.

Before loosening any matching rule here, read the 2026-10-11 Reasoning
Captures in CLAUDE.md: every guard below exists because of a real false
match on the live library.
"""
import os
import re
from dataclasses import dataclass

from orphans import OrphanCandidate, is_tv_path, title_folder


@dataclass(frozen=True)
class MissingSpecial:
    code: str  # "S00E09"
    title: str
    monitored: bool


@dataclass(frozen=True)
class SeriesSpecials:
    series: str
    missing: tuple[MissingSpecial, ...]


@dataclass(frozen=True)
class RadarrMovie:
    title: str
    year: int | None
    has_file: bool


@dataclass(frozen=True)
class Verdict:
    kind: str  # "junk" | "wanted" | "plex" | "identify" | "call"
    action: str
    reason: str


# Verdicts whose suggestion is to keep the file: the UI guards their delete.
KEEP_KINDS = {"wanted", "plex"}

_STOP = {"the", "a", "an", "of", "and", "with", "to", "in", "on", "at", "for", "from", "vs", "by"}
# Words that say what kind of bonus a file is, not which one it is.
_GENERIC = {
    "interview", "interviews", "deleted", "scene", "scenes", "behind", "disk", "disc", "season",
    "episode", "making", "special", "specials", "visit", "bonus", "part", "pt", "extended",
    "featurette", "featurettes", "trailer", "documentary",
}
_NOISE = re.compile(
    r"^(\d+|\d{3,4}[pi]|x26[45]|h26[45]|hevc|avc|web|webrip|dl|bluray|brrip|bdrip|hdtv|dvdrip|"
    r"aac\d*|ac3|dts|flac|\d+fps|\d+kbit|s\d+e\d+|s\d+|e\d+)$"
)
# A normal episode's code (both numbers non-zero): its deleted scenes are
# not specials, even when named after an episode that shares a special's title.
_REGULAR_EPISODE = re.compile(r"s(?!00)\d+e(?!00)\d+", re.I)
_FILE_SEASON = re.compile(r"\bs(\d+)(?:e\d+)?\b", re.I)
_TITLE_SEASON = re.compile(r"\bseason (\d+)\b", re.I)
# A regular season's own folder ("Season 1", "season 01"), and the
# 1x01-style episode code some releases use instead of S01E01.
_SEASON_DIR = re.compile(r"season\s*0*([1-9]\d*)", re.I)
_NXNN_EPISODE = re.compile(r"\b\d{1,2}x\d{2,3}\b", re.I)


def _words(text: str) -> list[str]:
    """Lowercase words with release noise removed. Parenthesized and
    bracketed text is dropped first: it's almost always quality tags or
    a release group, e.g. "(1080p BluRay x265 Grp)" or "[group]"."""
    text = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", text)
    return [w for w in re.split(r"[^a-z0-9]+", text.lower()) if w and not _NOISE.match(w)]


def _significant(words: list[str], series_tokens: set[str]) -> set[str]:
    return {w for w in words if len(w) > 1 and w not in _STOP and w not in _GENERIC and w not in series_tokens}


def match_sonarr_special(path: str, specials: SeriesSpecials) -> MissingSpecial | None:
    """The missing season-0 episode this file most likely is, by title.

    Never trusts the file's own S00Exx code: on the live library those
    codes pointed at different episodes than Sonarr's. An exact
    title-at-end-of-name match wins first. Otherwise the shared
    significant words must cover MORE than half of both the title's and
    the file's words, so one shared word can't drag in an unrelated file.
    """
    name = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    if _REGULAR_EPISODE.search(name) or _NXNN_EPISODE.search(name):
        return None
    # A file sitting in a regular season's folder is that season's episode
    # (or its bonus), even without an SxxEyy code in its name.
    if _SEASON_DIR.fullmatch(os.path.basename(os.path.dirname(path)).strip()):
        return None
    series_tokens = set(_words(specials.series)) - _STOP
    file_season = _FILE_SEASON.search(name)
    candidates = []
    for ep in specials.missing:
        title_season = _TITLE_SEASON.search(ep.title)
        if file_season and title_season and int(file_season.group(1)) != int(title_season.group(1)):
            continue
        candidates.append(ep)

    file_words = _words(name)
    for ep in candidates:
        title_words = _words(ep.title)
        if len(" ".join(title_words)) > 8 and file_words[-len(title_words):] == title_words:
            return ep

    file_sig = _significant(file_words, series_tokens)
    best, best_score = None, 0.0
    for ep in candidates:
        title_sig = _significant(_words(ep.title), series_tokens)
        shared = file_sig & title_sig
        if not shared or sum(len(w) for w in shared) < 4:
            continue
        score = min(len(shared) / len(title_sig), len(shared) / len(file_sig))
        if score > 0.5 and score > best_score:
            best, best_score = ep, score
    return best


SAMPLE_MAX_BYTES = 500_000_000
RADARR_WANTED_MIN_BYTES = 1_000_000_000
_PLEX_EXTRAS_DIRS = {
    "behind the scenes", "deleted scenes", "featurettes", "interviews",
    "scenes", "shorts", "trailers", "other",
}
_EXTRAS_KEYWORDS = ("bonus", "outtakes", "introduction", "trailer", "interview", "gag")
_SPECIALS_DIRS = {"specials", "season 00", "season 0"}


@dataclass
class VerdictContext:
    tv_subdirs: set[str]
    # Title folder ("media/tv/Driftwood") -> that series' missing specials.
    # A folder is present iff Sonarr has a series there. None: not checked.
    specials: dict[str, SeriesSpecials] | None
    # Movie folder -> Radarr's record. None: Radarr not checked.
    radarr_movies: dict[str, RadarrMovie] | None
    # Radarr's tracked files. None: Radarr not checked.
    radarr_paths: set[str] | None


def _word(word: str, text: str) -> bool:
    return re.search(rf"(?<![a-z]){word}(?![a-z])", text.lower()) is not None


_SAMPLE_STEM = re.compile(r"(?:^|[.\-_(\[])sample(?:$|[.\-_)\]])", re.I)


def _title_words(folder: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", os.path.basename(folder).lower()))


def _without_words(text: str, words: set[str]) -> str:
    """text with each of words (whole words, any case) blanked out; the
    delimiters around them stay put."""
    for w in words:
        text = re.sub(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", " ", text, flags=re.I)
    return text


def _below_title(path: str) -> tuple[str, list[str], str]:
    """(title folder, the directories between it and the file, file name)."""
    folder = title_folder(path)
    rest = path[len(folder) + 1:] if path.startswith(folder + "/") else os.path.basename(path)
    *dirs, name = rest.split("/")
    return folder, dirs, name


def _is_sample_path(path: str) -> bool:
    """A release's preview clip: "sample" as a whole word in a folder below
    the title's folder, or delimited in the file stem (a bare space doesn't
    count, so an episode titled "The Sample" isn't caught). The title's own
    words never count: "Free Sample (2020)" and "Sample Show" are titles."""
    folder, dirs, name = _below_title(path)
    title = _title_words(folder)
    stem = _without_words(os.path.splitext(name)[0], title)
    return any(_word("sample", _without_words(d, title)) for d in dirs) or bool(_SAMPLE_STEM.search(stem))


def _is_extras_dir(d: str) -> bool:
    d = d.lower()
    return d in _PLEX_EXTRAS_DIRS or "extras" in d or "bonus" in d


def _in_extras_dir(path: str) -> bool:
    """Somewhere below the title's folder in an extras-like folder
    (Featurettes/, Extras/, Bonus Disc/...): bonus material, not the title."""
    if _is_loose(path):
        return False
    _, dirs, _ = _below_title(path)
    return any(_is_extras_dir(d) for d in dirs)


def _in_one_plex_extras_dir(path: str) -> bool:
    """Directly inside exactly one Plex extras folder in the title's folder,
    e.g. Film (2020)/Featurettes/Making Of.mkv: where Plex looks for extras."""
    if _is_loose(path):
        return False
    _, dirs, _ = _below_title(path)
    return len(dirs) == 1 and dirs[0].lower() in _PLEX_EXTRAS_DIRS


def _is_loose(path: str) -> bool:
    """Directly in a library root, e.g. media/tv/x.avi: in no title's folder."""
    return path.count("/") == 2


def looks_special(path: str) -> bool:
    """S00Exx or SxxE00 in the name, "special" as a word, or sitting
    directly in a Specials/Season 00 folder. Only the immediate parent
    counts: Driftwood keeps a movie's featurettes in a folder nested under
    Specials/, and those aren't specials."""
    name = os.path.basename(path)
    parent = os.path.basename(os.path.dirname(path)).lower()
    return bool(
        re.search(r"s00e\d+", name, re.I)
        or re.search(r"s\d+e00(?!\d)", name, re.I)
        or parent in _SPECIALS_DIRS
        or _word("special", name)
    )


def extras_target(path: str, tv_subdirs: set[str]) -> str | None:
    """Where Plex would pick this file up as an extra, shown relative to the
    library root (e.g. "Driftwood/Featurettes/x.mkv"), or None.

    Only a suggestion: a name rule never confirms an extra (see CLAUDE.md).
    TV goes to <Show>/Featurettes/, the one TV placement proven on the
    live library; movies get the folder Plex's docs give for the kind.
    """
    if "/" not in path or _is_loose(path):
        return None
    if _in_one_plex_extras_dir(path):
        return None  # already directly inside one Plex extras folder
    folder, dirs, name = _below_title(path)
    odd_dir = any(_is_extras_dir(d) for d in dirs)
    # The title's own words (Trailer Park Kings, Interview with the Werewolf)
    # aren't evidence of an extra.
    title_words = _title_words(folder)
    bare = " ".join(w for w in re.findall(r"[a-z0-9]+", name.lower()) if w not in title_words)
    keyword = any(_word(k, bare) for k in _EXTRAS_KEYWORDS)
    if not (odd_dir or keyword):
        return None
    if is_tv_path(path, tv_subdirs):
        sub = "Featurettes"
    else:
        plain = re.sub(r"[^a-z0-9]+", " ", name.lower())
        sub = (
            "Trailers" if "trailer" in plain
            else "Interviews" if "interview" in plain
            else "Deleted Scenes" if "deleted" in plain
            else "Behind The Scenes" if "making" in plain or "story of" in plain
            else "Featurettes"
        )
    if path == f"{folder}/{sub}/{name}":
        return None
    return f"{os.path.basename(folder)}/{sub}/{name}"


def assign_verdict(c: OrphanCandidate, ctx: VerdictContext) -> Verdict:
    """First matching rule wins; the order is the spec's. A rule whose data
    wasn't fetched (None in ctx) never fires, so missing data only ever
    pushes a file toward "Your call", never toward "junk"."""
    # folder, target and matching use paths[0]; `tv` deliberately checks every
    # path (any TV path disables the Radarr rule, the safe direction).
    path = c.paths[0]
    folder = title_folder(path)
    tv = any(is_tv_path(p, ctx.tv_subdirs) for p in c.paths)

    if c.size_bytes < SAMPLE_MAX_BYTES and any(_is_sample_path(p) for p in c.paths):
        reason = "A preview clip from the release, not the real thing."
        if ctx.radarr_paths is not None and any(p in ctx.radarr_paths for p in c.paths):
            reason += (" Radarr is tracking this sample as the movie, so after deleting it,"
                       " run a Rescan in Radarr so it picks up the real file.")
        return Verdict("junk", "Delete it.", reason)
    if c.superseded_by:
        return Verdict("junk", "Delete it (older copy).",
                       f"Radarr tracks a different file in this folder: {c.superseded_by}")
    if c.tracks_sample:
        return Verdict("wanted",
                       "Keep it: this is probably the real movie. Delete the sample Radarr tracks, then run a Rescan in Radarr.",
                       "Radarr's file for this movie is a sample clip.")
    if tv and ctx.specials is not None and folder in ctx.specials:
        ep = match_sonarr_special(path, ctx.specials[folder])
        if ep:
            action = f'Import as {ep.code} "{ep.title}" with Manual Import in Sonarr.'
            if not ep.monitored:
                action += " Turn monitoring on for it first."
            reason = f'Sonarr lists {ep.code} "{ep.title}" as missing, and this file\'s name matches it.'
            own = re.search(r"s00e(\d+)", os.path.basename(path), re.I)
            if own and f"S00E{int(own.group(1)):02d}" != ep.code:
                reason += f" The file calls itself S00E{int(own.group(1)):02d}; go by the title."
            return Verdict("wanted", action, reason)
    # A big file in the movie's Extras/ or Bonus Disc/ is bonus material,
    # not the missing movie itself.
    if not tv and ctx.radarr_movies is not None and c.size_bytes > RADARR_WANTED_MIN_BYTES \
            and not _in_extras_dir(path):
        movie = ctx.radarr_movies.get(folder)
        if movie and not movie.has_file:
            year = f" ({movie.year})" if movie.year else ""
            return Verdict("wanted", f'Get it into Radarr as "{movie.title}{year}" with Manual Import.',
                           "Radarr has this movie but no file for it.")
    target = extras_target(path, ctx.tv_subdirs)
    if target:
        return Verdict("plex", f"Move to {target}",
                       "Bonus material, but Plex only finds extras directly inside a Featurettes/, "
                       "Trailers/ (etc.) folder in the title's own folder.")
    if _in_one_plex_extras_dir(path):
        return Verdict("plex", "Leave it where it is.",
                       "Already in a Plex extras folder, but Plex didn't confirm it this scan "
                       "(the extras check failed, or Plex needs a metadata refresh).")
    if tv and looks_special(path):
        if ctx.specials is None:
            reason = "Looks like a special, but Sonarr couldn't be checked this scan."
        elif folder not in ctx.specials:
            reason = "Looks like a special, but Sonarr has no series in this folder."
        else:
            reason = "Looks like a special, but none of Sonarr's missing specials for this show matches the name."
        return Verdict("identify", "Watch it and work out what it is.", reason)
    if _is_loose(path):
        return Verdict("call", "Move it into a show or movie folder, or delete it.",
                       "Loose file at the top of the library. Sonarr, Radarr and Plex only see files inside a title's folder.")
    return Verdict("call", "Your call.", "Nothing here says whether it's a duplicate or something worth keeping.")
