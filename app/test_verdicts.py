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


from orphans import OrphanCandidate
from verdicts import RadarrMovie, VerdictContext, assign_verdict, extras_target, looks_special

TV = {"media/tv", "media/tv-no-backup"}


def _c(path, size=100_000_000, **kw):
    return OrphanCandidate(inode=1, paths=[path], category="orphaned media", size_bytes=size, **kw)


def _ctx(specials=None, radarr_movies=None, radarr_paths=None):
    return VerdictContext(tv_subdirs=TV, specials=specials if specials is not None else {},
                          radarr_movies=radarr_movies if radarr_movies is not None else {},
                          radarr_paths=radarr_paths if radarr_paths is not None else set())


def test_extras_target_flattens_nested_tv_extras_into_featurettes():
    assert extras_target("media/tv/Firefly/Featurettes/Deleted Scenes/S01E01 Serenity - Scene 75 & 76.mkv", TV) == \
        "Firefly/Featurettes/S01E01 Serenity - Scene 75 & 76.mkv"


def test_extras_target_picks_movie_folder_by_keyword():
    assert extras_target("media/movies/Gambit.1966/Extras/Trailer.mkv", TV) == "Gambit.1966/Trailers/Trailer.mkv"
    assert extras_target("media/movies/H3/H3.Extras-Grym/On-set.Interviews.with.Barker-Grym.mkv", TV) == \
        "H3/Interviews/On-set.Interviews.with.Barker-Grym.mkv"
    assert extras_target("media/movies/H3/H3.Extras-Grym/Hell.on.Earth-The.Story.of.Hellraiser.III-Grym.mkv", TV) == \
        "H3/Behind The Scenes/Hell.on.Earth-The.Story.of.Hellraiser.III-Grym.mkv"


def test_extras_target_uses_bonus_keyword_in_a_show_folder():
    assert extras_target("media/tv/Larry Sanders/LARRY SANDERS BONUS 1.mp4", TV) == "Larry Sanders/Featurettes/LARRY SANDERS BONUS 1.mp4"


def test_extras_target_none_for_plain_files_loose_files_and_already_placed():
    assert extras_target("media/movies/Film/Film.mkv", TV) is None
    assert extras_target("media/tv/Schoolhouse_Rock.mp4", TV) is None
    assert extras_target("media/movies/Film/Trailers/Trailer.mkv", TV) is None


def test_looks_special_uses_codes_names_and_the_immediate_parent_only():
    assert looks_special("media/tv/Supernatural/Supernatural.S15E00.The.Long.Road.Home.mkv")
    assert looks_special("media/tv/SCTV/specials/Softball Game.mp4")
    assert looks_special("media/tv/Wellington/Wellington.Paranormal.S02.Xmas.Special.2019.mkv")
    assert not looks_special("media/tv/Firefly/Featurettes/Specials/Serenity (2005)/Featurettes/Outtakes.mkv")


def test_small_sample_is_junk():
    v = assign_verdict(_c("media/movies/IM3/Sample,Screens/IM3 (Sample).mkv", size=85_000_000), _ctx())
    assert v.kind == "junk" and v.action == "Delete it."


def test_sample_radarr_tracks_gets_rescan_advice():
    p = "media/movies/IM3/Sample,Screens/IM3 (Sample).mkv"
    v = assign_verdict(_c(p, size=85_000_000), _ctx(radarr_paths={p}))
    assert "Rescan" in v.reason


def test_big_file_with_sample_in_title_is_not_junk():
    v = assign_verdict(_c("media/movies/Free Sample (2020)/Free Sample.mkv", size=4_000_000_000), _ctx())
    assert v.kind != "junk"


def test_superseded_is_junk_and_names_the_tracked_file():
    v = assign_verdict(_c("media/movies/Film/Film.WEBRip.mkv", superseded_by="Film.BluRay.mkv"), _ctx())
    assert v.kind == "junk" and "Film.BluRay.mkv" in v.reason


def test_tracks_sample_is_wanted():
    v = assign_verdict(_c("media/movies/IM3/IM3.mkv", tracks_sample=True), _ctx())
    assert v.kind == "wanted"


def test_sonarr_match_is_wanted_with_code_and_title():
    from verdicts import MissingSpecial, SeriesSpecials
    specials = {"media/tv/Supernatural": SeriesSpecials("Supernatural", (
        MissingSpecial("S00E09", "Supernatural: The Long Road Home", False),))}
    v = assign_verdict(_c("media/tv/Supernatural/Supernatural.S15E00.The.Long.Road.Home.mkv"), _ctx(specials=specials))
    assert v.kind == "wanted"
    assert 'S00E09 "Supernatural: The Long Road Home"' in v.action
    assert "monitoring" in v.action


def test_wrong_own_code_is_called_out():
    from verdicts import MissingSpecial, SeriesSpecials
    specials = {"media/tv/SCTV": SeriesSpecials("Second City Television", (
        MissingSpecial("S00E07", "The Shmenges: The Last Polka", True),))}
    v = assign_verdict(_c("media/tv/SCTV/Specials/S00E10 - The Shmenges_ The Last Polka.mp4"), _ctx(specials=specials))
    assert "S00E10" in v.reason


def test_sonarr_match_beats_plex_move():
    from verdicts import MissingSpecial, SeriesSpecials
    specials = {"media/tv/Larry Sanders": SeriesSpecials("The Larry Sanders Show", (
        MissingSpecial("S00E17", "Interview with Jeremy Piven", True),))}
    v = assign_verdict(_c("media/tv/Larry Sanders/LARRY SANDERS S01 bonus - interview Jeremy Piven.mp4"), _ctx(specials=specials))
    assert v.kind == "wanted"


def test_radarr_movie_without_a_file_is_wanted():
    movies = {"media/movies/Crystal Lake": RadarrMovie("Crystal Lake Memories", 2013, False)}
    v = assign_verdict(_c("media/movies/Crystal Lake/Crystal Lake - pt1.mp4", size=4_700_000_000), _ctx(radarr_movies=movies))
    assert v.kind == "wanted" and '"Crystal Lake Memories (2013)"' in v.action


def test_nested_extra_is_plex_with_target():
    v = assign_verdict(_c("media/tv/Firefly/Featurettes/Specials/Serenity (2005)/Featurettes/Outtakes.mkv"), _ctx())
    assert v.kind == "plex" and v.action == "Move to Firefly/Featurettes/Outtakes.mkv"


def test_sample_in_an_extras_folder_is_still_junk():
    v = assign_verdict(_c("media/movies/Film/Extras/film-sample.mkv", size=20_000_000), _ctx())
    assert v.kind == "junk"


def test_unmatched_special_is_identify_and_says_why():
    from verdicts import SeriesSpecials
    specials = {"media/tv/Wellington Paranormal": SeriesSpecials("Wellington Paranormal", ())}
    p = "media/tv/Wellington Paranormal/Wellington.Paranormal.S02.Xmas.Special.2019.mkv"
    assert "none of Sonarr's" in assign_verdict(_c(p), _ctx(specials=specials)).reason
    assert "no series" in assign_verdict(_c(p), _ctx(specials={})).reason
    assert "couldn't be checked" in assign_verdict(_c(p), VerdictContext(TV, None, {}, set())).reason


def test_loose_file_at_library_root_is_your_call_with_advice():
    v = assign_verdict(_c("media/tv/South.Park.S14E14.Creme.Fraiche.avi"), _ctx())
    assert v.kind == "call" and "Loose file" in v.reason


def test_everything_else_is_your_call():
    v = assign_verdict(_c("media/tv/SCTV Network 90/S04E03 - SCTV Network 90 - #108.m4v"), _ctx())
    assert v == assign_verdict(_c("media/tv/SCTV Network 90/S04E03 - SCTV Network 90 - #108.m4v"), _ctx())
    assert v.kind == "call" and v.action == "Your call."


def test_missing_radarr_data_never_produces_a_radarr_verdict():
    v = assign_verdict(_c("media/movies/Crystal Lake/Crystal Lake - pt1.mp4", size=4_700_000_000),
                       VerdictContext(TV, {}, None, None))
    assert v.kind == "call"


def test_episode_titled_sample_is_not_junk():
    v = assign_verdict(_c("media/tv/Show/Season 1/S01E05 - The Sample.mkv", size=300_000_000), _ctx())
    assert v.kind != "junk"


def test_delimited_sample_names_are_junk():
    for p in ("media/movies/Movie/Movie.2020.1080p-sample.mkv", "media/movies/Movie/sample.mkv"):
        assert assign_verdict(_c(p, size=50_000_000), _ctx()).kind == "junk"


def test_title_words_do_not_trigger_extras_keywords():
    assert extras_target("media/tv/Trailer Park Boys/Season 1/Trailer Park Boys S01E01.mkv", TV) is None
    assert extras_target("media/movies/Interview with the Vampire (1994)/Interview with the Vampire.mkv", TV) is None


def test_file_already_in_one_extras_folder_stays_put():
    assert extras_target("media/movies/Film/Trailers/Teaser.mkv", TV) is None
    assert extras_target("media/movies/Film/Featurettes/Making Of.mkv", TV) is None
    assert extras_target("media/tv/Firefly/Featurettes/Deleted Scenes/x.mkv", TV) == "Firefly/Featurettes/x.mkv"


def test_extras_target_none_without_a_slash():
    assert extras_target("x.mkv", TV) is None
