"""Tests for verdicts.py. Cases are real files from the 2026-10-10 scan."""
from verdicts import MissingSpecial, SeriesSpecials, match_sonarr_special

LARRY = SeriesSpecials("The Larry Sanders Show", (
    MissingSpecial("S00E06", "Garry Interviews Alec Baldwin", True),
    MissingSpecial("S00E07", "Garry Interviews Carol Burnett", True),
    MissingSpecial("S00E08", "Garry Interviews David Duchovny", True),
    MissingSpecial("S00E12", "Garry Interviews Sharon Stone", True),
    MissingSpecial("S00E15", "Interview with Garry Shandling", True),
    MissingSpecial("S00E17", "Interview with Jeremy Piven", True),
    MissingSpecial("S00E18", "Interview with Linda Doucett", True),
    MissingSpecial("S00E54", "Deleted Scenes - The Mr. Sharon Stone Show", True),
    MissingSpecial("S00E56", "Garry Shandling Interviews Linda Doucett", True),
    MissingSpecial("S00E60", "Outtakes - Season 2", True),
    MissingSpecial("S00E64", "Outtakes - Season 3", True),
))
FIREFLY = SeriesSpecials("Firefly", (
    MissingSpecial("S00E01", "Serenity", True),
    MissingSpecial("S00E02", "Done the Impossible", True),
    MissingSpecial("S00E06", "Serenity: The 10th Character", True),
))
NEWSROOM = SeriesSpecials("The Newsroom", (
    MissingSpecial("S00E01", "Escape from the Newsroom", True),
    MissingSpecial("S00E02", "In The Newsroom", True),
    MissingSpecial("S00E03", "Inside The Newsroom", True),
))
SCTV = SeriesSpecials("Second City Television", (
    MissingSpecial("S00E01", "The Origins of SCTV", True),
    MissingSpecial("S00E07", "The Shmenges: The Last Polka", True),
    MissingSpecial("S00E08", "Biographies: The Enigma of Bobby Bittman", True),
))
SUPERNATURAL = SeriesSpecials("Supernatural", (
    MissingSpecial("S00E02", "A Very Special Supernatural", True),
    MissingSpecial("S00E09", "Supernatural: The Long Road Home", True),
))
SPACED = SeriesSpecials("Spaced", (MissingSpecial("S00E01", "Skip To The End", True),))
SCTV90 = SeriesSpecials("SCTV Network 90", (MissingSpecial("S00E23", "SCTV Reunion", False),))


def _code(path, specials):
    m = match_sonarr_special(path, specials)
    return m.code if m else None


def test_interview_matches_by_guest_name():
    assert _code("media/tv/Larry Sanders/LARRY SANDERS S01 bonus - interview Jeremy Piven.mp4", LARRY) == "S00E17"


def test_visit_matches_garry_interviews_title():
    assert _code("media/tv/Larry Sanders/LARRY SANDERS S02 bonus - visit Alec Baldwin.mp4", LARRY) == "S00E06"
    assert _code("media/tv/Larry Sanders/LARRY SANDERS S01 bonus Carol Burnett.mp4", LARRY) == "S00E07"


def test_better_score_wins_over_a_weaker_overlap():
    # "Sharon Stone" also appears in S00E54's title, at a lower score.
    assert _code("media/tv/Larry Sanders/LARRY SANDERS S03 bonus - visit Sharon Stone.mp4", LARRY) == "S00E12"
    # S00E56 also names Linda Doucett, but scores only 0.5.
    assert _code("media/tv/Larry Sanders/LARRY SANDERS S03 bonus - interview Linda Doucett.mp4", LARRY) == "S00E18"


def test_season_guard_picks_the_right_outtakes():
    assert _code("media/tv/Larry Sanders/LARRY SANDERS S03 outtakes.mp4", LARRY) == "S00E64"
    assert _code("media/tv/Larry Sanders/LARRY SANDERS S02 bonus - outtakes.mp4", LARRY) == "S00E60"


def test_half_overlap_is_not_a_match():
    # Shares only "garry" with "Interview with Garry Shandling": exactly 0.5.
    assert _code("media/tv/Larry Sanders/LARRY SANDERS S02 bonus - Garry address.mp4", LARRY) is None
    # One of two title tokens: exactly 0.5, so falls through to the Plex verdict.
    assert _code("media/tv/Larry Sanders/LARRY SANDERS S05 bonus - Duchovny.mp4", LARRY) is None


def test_generic_only_names_never_match():
    assert _code("media/tv/Larry Sanders/LARRY SANDERS S06 bonus - deleted scenes.mp4", LARRY) is None
    assert _code("media/tv/Larry Sanders/LARRY SANDERS BONUS 1.mp4", LARRY) is None


def test_exact_title_match_for_stopword_titles():
    assert _code("media/tv/The Newsroom (1996)/2004 Season 2/Bonus Materials/In The Newsroom.mkv", NEWSROOM) == "S00E02"
    assert _code("media/tv/The Newsroom (1996)/1996 Season 1/Bonus Materials/Inside The Newsroom.mkv", NEWSROOM) == "S00E03"
    assert _code("media/tv/The Newsroom (1996)/2002 Escape from the Newsroom/Escape from the Newsroom.mkv", NEWSROOM) == "S00E01"


def test_release_tags_in_parentheses_are_ignored():
    assert _code("media/tv/Firefly/Featurettes/Specials/S00E02 - Done the Impossible (1080p WEB x265 Silence).mkv", FIREFLY) == "S00E02"
    assert _code("media/tv/Firefly/Featurettes/Specials/Serenity (2005)/S00E01 - Serenity (2005) (1080p BluRay x265 Silence).mkv", FIREFLY) == "S00E01"


def test_dotted_release_name_matches():
    assert _code("media/tv-no-backup/Supernatural/Supernatural.S15E00.The.Long.Road.Home.1080p.WEB.h264-BAE.mkv", SUPERNATURAL) == "S00E09"
    assert _code("media/tv/Spaced/Skip_To_the_End-Documentary.mp4", SPACED) == "S00E01"


def test_match_by_title_even_when_the_file_code_is_wrong():
    assert _code("media/tv/Second City Television/Specials/S00E10 - The Shmenges_ The Last Polka (480p_30fps_H264-128kbit_AAC).mp4", SCTV) == "S00E07"
    assert _code("media/tv/Second City Television/Specials/S00E11 - (1988) The Enigma of Bobby Bittman (360p_30fps_H264-128kbit_AAC).mp4", SCTV) == "S00E08"


def test_regular_episode_deleted_scene_never_matches_a_special():
    assert _code("media/tv/Firefly/Featurettes/Deleted Scenes/S01E01 Serenity - Scene 1.mkv", FIREFLY) is None
    assert _code("media/tv/Firefly/Featurettes/Deleted Scenes/S01E01 Serenity - Scene 75 & 76.mkv", FIREFLY) is None


def test_featurette_sharing_one_word_is_not_the_special():
    assert _code("media/tv/Firefly/Featurettes/Specials/Serenity (2005)/Featurettes/Take a Walk on Serenity.mkv", FIREFLY) is None


def test_odd_characters_do_not_crash():
    assert _code("media/tv/SCTV Network 90/specials/#StarsInTheHouse #60_ SCTV Cast Members (720p_30fps_H264-128kbit_AAC).mp4", SCTV90) is None
    assert _code("media/tv/SCTV Network 90/specials/'PMS- Premenstrual Syndrome' - David Letterman's Holiday Film Festival (1985).mp4", SCTV90) is None


def test_empty_missing_list_matches_nothing():
    assert _code("media/tv/Firefly/S00E01 - Serenity.mkv", SeriesSpecials("Firefly", ())) is None
