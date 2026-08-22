import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import MusicOrganizer as org  # noqa: E402


@pytest.fixture(autouse=True)
def reset_config():
    """Several switches are global; put them back after every test."""
    saved = (org.CONFIG.strip_leading_the, org.CONFIG.recase, org.CONFIG.audio_only_hash)
    yield
    (org.CONFIG.strip_leading_the, org.CONFIG.recase, org.CONFIG.audio_only_hash) = saved


@pytest.fixture
def options(tmp_path):
    """Real parsed options, so tests exercise the actual defaults."""
    def build(*extra):
        return org.parse_args([str(tmp_path / "src"), str(tmp_path / "dst"), *extra])
    return build


def make_track(artist=None, album=None, title=None, name="song.mp3",
               artist_raw=None, **fields):
    """A Track as scan_file would have produced it, without needing a real file."""
    track = org.Track(path=Path(name), size=fields.pop("size", 1000))
    track.artist = artist
    track.artist_raw = artist if artist_raw is None else artist_raw
    track.album = album
    track.title = title
    for key, value in fields.items():
        setattr(track, key, value)
    track.artist_key = org.normalize_key(artist) if artist else ""
    track.album_key = org.normalize_key(album) if album else ""
    if artist:
        track.artist_source = "tag"
    return track
