"""Tests for path-prefix normalization."""
from pathmap import to_relative


def test_strips_matching_prefix():
    assert to_relative("/downloads/completed/movie.mkv", "/downloads") == "completed/movie.mkv"


def test_no_prefix_strips_leading_slash_only():
    assert to_relative("/data/media/movies/movie.mkv", "") == "data/media/movies/movie.mkv"


def test_prefix_equal_to_whole_path():
    assert to_relative("/downloads", "/downloads") == ""


def test_trailing_slash_on_prefix_is_tolerated():
    assert to_relative("/downloads/movie.mkv", "/downloads/") == "movie.mkv"


def test_non_matching_prefix_only_strips_leading_slash():
    assert to_relative("/other/movie.mkv", "/downloads") == "other/movie.mkv"
