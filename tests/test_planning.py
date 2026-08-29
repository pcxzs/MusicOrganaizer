"""Second-pass resolution and destination planning."""
import pytest
from conftest import make_track

import MusicOrganizer as org

# --------------------------------------------------------------------------- #
# evidence-based collaboration splitting
# --------------------------------------------------------------------------- #

def test_ampersand_splits_when_a_side_is_a_known_artist(options):
    opts = options()
    tracks = [
        make_track("Nova Kane", title="Low Tide"),             # establishes the artist
        make_track("Nova Kane & Rex Miller", title="Second Wind"),
    ]
    org.resolve_artists(tracks, opts)
    assert tracks[1].artist == "Nova Kane"
    assert tracks[1].artist_source == "tag-split"


def test_ampersand_splits_when_only_the_right_side_is_known(options):
    """The right-hand name is known, so the tag is a collaboration - keep the lead."""
    opts = options()
    tracks = [
        make_track("Rex Miller", title="Paper Boats"),
        make_track("Vera Cole & Rex Miller", title="Night Drive"),
    ]
    org.resolve_artists(tracks, opts)
    assert tracks[1].artist == "Vera Cole"


def test_ampersand_kept_when_neither_side_is_known(options):
    """The ampersand is part of a band name, and nothing here says otherwise."""
    opts = options()
    tracks = [make_track("Salt & Ash", title="Undertow")]
    org.resolve_artists(tracks, opts)
    assert tracks[0].artist == "Salt & Ash"


def test_no_smart_split_switch(options):
    opts = options("--no-smart-split")
    tracks = [make_track("Nova Kane", title="Low Tide"),
              make_track("Nova Kane & Rex Miller", title="Second Wind")]
    org.resolve_artists(tracks, opts)
    assert tracks[1].artist == "Nova Kane & Rex Miller"


# --------------------------------------------------------------------------- #
# recovering artists from filenames
# --------------------------------------------------------------------------- #

def test_filename_matches_a_known_artist_either_way_round(options):
    opts = options()
    tracks = [
        make_track("Rex Miller", title="Paper Boats"),
        make_track(None, name="Night Drive   Rex Miller.mp3"),    # Title then Artist
        make_track(None, name="Rex Miller - Overtime.mp3"),       # Artist then Title
    ]
    org.resolve_artists(tracks, opts)
    assert tracks[1].artist == "Rex Miller"
    assert tracks[1].artist_source == "library"
    assert tracks[2].artist == "Rex Miller"


def test_filename_dash_fallback(options):
    opts = options()
    tracks = [make_track(None, name="Vera Cole – Paper Boats.mp3")]
    org.resolve_artists(tracks, opts)
    assert tracks[0].artist == "Vera Cole"
    assert tracks[0].artist_source == "filename"


def test_filename_guess_library_never_invents_an_artist(options):
    opts = options("--filename-guess", "library")
    tracks = [make_track(None, name="Some Unknown Person – A Song.mp3")]
    org.resolve_artists(tracks, opts)
    assert tracks[0].artist is None


def test_filename_guess_off(options):
    opts = options("--filename-guess", "off")
    tracks = [make_track("Kestrel", title="Low Tide"),
              make_track(None, name="Kestrel – Night Signals.mp3")]
    org.resolve_artists(tracks, opts)
    assert tracks[1].artist is None


def test_underscored_filename(options):
    opts = options()
    tracks = [make_track(None, name="Nova_Kane_-_Low_Tide_feat_Rex_Miller.mp3")]
    org.resolve_artists(tracks, opts)
    assert tracks[0].artist == "Nova Kane"


# --------------------------------------------------------------------------- #
# where a track ends up
# --------------------------------------------------------------------------- #

def plan_one(track, opts):
    artists, albums = org.build_name_maps([track])
    return org.destination_for(track, artists, albums, opts)


def test_default_layout(options):
    opts = options()
    track = make_track("Nova Kane", "Night Signals", "Low Tide", track_no=5, name="x.mp3")
    assert plan_one(track, opts).relative_to(opts.destination).as_posix() \
        == "Nova Kane/Night Signals/05 - Low Tide.mp3"


def test_untagged_goes_to_others(options):
    opts = options()
    track = make_track(None, name="mystery.mp3")
    assert plan_one(track, opts).relative_to(opts.destination).as_posix() == "Others/mystery.mp3"


def test_missing_album_goes_to_unknown_album(options):
    opts = options()
    track = make_track("Vera Cole", None, "Paper Boats", name="h.m4a")
    assert plan_one(track, opts).relative_to(opts.destination).as_posix() \
        == "Vera Cole/Unknown Album/Paper Boats.m4a"


@pytest.mark.parametrize("switches, expected", [
    (("--layout", "artist"),            "Nova Kane/05 - Low Tide.mp3"),
    (("--layout", "flat"),              "05 - Low Tide.mp3"),
    (("--layout", "artist/year-album"), "Nova Kane/2023 - Night Signals/05 - Low Tide.mp3"),
    (("--no-track-numbers",),           "Nova Kane/Night Signals/Low Tide.mp3"),
    (("--artist-in-filename",),         "Nova Kane/Night Signals/05 - Nova Kane - Low Tide.mp3"),
    (("--keep-filenames",),             "Nova Kane/Night Signals/x.mp3"),
    (("--others-name", "Misc"),         "Nova Kane/Night Signals/05 - Low Tide.mp3"),
])
def test_layout_switches(options, switches, expected):
    opts = options(*switches)
    track = make_track("Nova Kane", "Night Signals", "Low Tide",
                       track_no=5, year="2023", name="x.mp3")
    assert plan_one(track, opts).relative_to(opts.destination).as_posix() == expected


def test_singles_in_artist_root(options):
    opts = options("--singles-in-artist-root")
    track = make_track("Vera Cole", None, "Paper Boats", name="h.m4a")
    assert plan_one(track, opts).relative_to(opts.destination).as_posix() \
        == "Vera Cole/Paper Boats.m4a"


def test_others_name_switch(options):
    opts = options("--others-name", "Misc")
    track = make_track(None, name="mystery.mp3")
    assert plan_one(track, opts).relative_to(opts.destination).as_posix() == "Misc/mystery.mp3"


def test_filename_uses_canonical_artist_not_the_raw_tag(options):
    """Folder and filename must agree even when the tag is oddly cased."""
    opts = options("--artist-in-filename")
    tracks = [make_track("vera cole", None, "Paper Boats", name="h.m4a")]
    artists, albums = org.build_name_maps(tracks)
    assert org.destination_for(tracks[0], artists, albums, opts).name \
        == "Vera Cole - Paper Boats.m4a"


def test_disc_number_prefix(options):
    opts = options()
    track = make_track("A", "B", "T", track_no=3, disc_no=2, name="x.mp3")
    assert plan_one(track, opts).name == "2-03 - T.mp3"


def test_unique_path_avoids_collisions(tmp_path):
    target = tmp_path / "song.mp3"
    target.write_bytes(b"x")
    taken = set()
    assert org.unique_path(target, taken).name == "song (2).mp3"
    assert org.unique_path(target, taken).name == "song (3).mp3"


# --------------------------------------------------------------------------- #
# tag value helpers
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("raw, expected", [("3", 3), ("3/12", 3), ("07", 7), (None, None), ("x", None)])
def test_parse_number(raw, expected):
    assert org.parse_number(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("2023", "2023"), ("1980-07-25", "1980"), ("25/07/1980", "1980"), ("garbage", None), (None, None),
])
def test_parse_year(raw, expected):
    assert org.parse_year(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("Nova Kane", "Nova Kane"), ("Unknown Artist", None), ("  ", None), (None, None),
    ("Various", None),
])
def test_clean_value(raw, expected):
    assert org.clean_value(raw) == expected
