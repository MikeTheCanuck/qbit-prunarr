"""Tests for inode-based hardlink scanning."""
import os

from inode_scan import scan


def _make_file(path: str, content: bytes = b"x") -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)


def test_linked_file_is_not_flagged(tmp_path):
    root = str(tmp_path)
    media_path = os.path.join(root, "media", "movies", "Movie (2020)", "movie.mkv")
    download_path = os.path.join(root, "torrents", "completed", "movie.mkv")
    _make_file(media_path, b"movie-bytes")
    os.makedirs(os.path.dirname(download_path), exist_ok=True)
    os.link(media_path, download_path)

    result = scan(root, ["media/movies"], ["torrents"])

    assert any(p.endswith("movie.mkv") for p in result.linked)
    assert result.media_only == {}
    assert result.download_only == {}


def test_media_only_file_is_flagged(tmp_path):
    root = str(tmp_path)
    media_path = os.path.join(root, "media", "movies", "Solo (2020)", "solo.mkv")
    _make_file(media_path)

    result = scan(root, ["media/movies"], ["torrents"])

    assert len(result.media_only) == 1
    paths = next(iter(result.media_only.values()))
    assert any(p.endswith("solo.mkv") for p in paths)
    assert result.download_only == {}


def test_download_only_file_is_flagged(tmp_path):
    root = str(tmp_path)
    download_path = os.path.join(root, "torrents", "completed", "seed.mkv")
    _make_file(download_path)

    result = scan(root, ["media/movies"], ["torrents"])

    assert len(result.download_only) == 1
    paths = next(iter(result.download_only.values()))
    assert any(p.endswith("seed.mkv") for p in paths)
    assert result.media_only == {}


def test_multiple_media_subdirs_are_all_walked(tmp_path):
    root = str(tmp_path)
    _make_file(os.path.join(root, "media", "tv", "Show", "ep1.mkv"))
    _make_file(os.path.join(root, "media", "tv-no-backup", "Other", "ep1.mkv"))

    result = scan(root, ["media/tv", "media/tv-no-backup"], ["torrents"])

    assert len(result.media_only) == 2


def test_missing_directory_is_treated_as_empty(tmp_path):
    root = str(tmp_path)
    os.makedirs(os.path.join(root, "media"))
    # "media/movies" does not exist at all

    result = scan(root, ["media/movies"], ["torrents"])

    assert result.linked == set()
    assert result.media_only == {}
    assert result.download_only == {}
