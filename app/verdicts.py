"""Verdicts for Needs Review: what to do with each media-side orphan, and why.

Pure functions only. main.run_scan() fetches the Sonarr/Radarr/Plex data,
normalizes every path to be relative to the data root, and passes it in.

Before loosening any matching rule here, read the 2026-10-11 Reasoning
Captures in CLAUDE.md: every guard below exists because of a real false
match on the live library.
"""
import re
from dataclasses import dataclass


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


def _words(text: str) -> list[str]:
    """Lowercase words with release noise removed. Parenthesized and
    bracketed text is dropped first: it's almost always quality tags or
    a release group, e.g. "(1080p BluRay x265 Silence)" or "[rarbg]"."""
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
    if _REGULAR_EPISODE.search(name):
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
