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
        make_track("Billie Eilish", title="bad guy"),          # establishes the artist
        make_track("Billie Eilish & Khalid", title="lovely"),
    ]
    org.resolve_artists(tracks, opts)
    assert tracks[1].artist == "Billie Eilish"
    assert tracks[1].artist_source == "tag-split"


def test_ampersand_splits_when_only_the_right_side_is_known(options):
    """'Calvin Harris & Dua Lipa' - Dua Lipa is known, so keep the lead name."""
    opts = options()
    tracks = [
        make_track("Dua Lipa", title="Levitating"),
        make_track("Calvin Harris & Dua Lipa", title="One Kiss"),
    ]
    org.resolve_artists(tracks, opts)
    assert tracks[1].artist == "Calvin Harris"


def test_ampersand_kept_when_neither_side_is_known(options):
    """'Milk & Bone' is one band, and nothing in the library says otherwise."""
    opts = options()
    tracks = [make_track("Milk & Bone", title="Pressure")]
    org.resolve_artists(tracks, opts)
    assert tracks[0].artist == "Milk & Bone"


def test_no_smart_split_switch(options):
    opts = options("--no-smart-split")
    tracks = [make_track("Billie Eilish", title="x"),
              make_track("Billie Eilish & Khalid", title="lovely")]
    org.resolve_artists(tracks, opts)
    assert tracks[1].artist == "Billie Eilish & Khalid"


# --------------------------------------------------------------------------- #
# recovering artists from filenames
# --------------------------------------------------------------------------- #

def test_filename_matches_a_known_artist_either_way_round(options):
    opts = options()
    tracks = [
        make_track("Bruno Mars", title="Locked Out of Heaven"),
        make_track(None, name="24K Magic   Bruno Mars.mp3"),      # Title then Artist
        make_track(None, name="Bruno Mars - Grenade.mp3"),        # Artist then Title
    ]
    org.resolve_artists(tracks, opts)
    assert tracks[1].artist == "Bruno Mars"
    assert tracks[1].artist_source == "library"
    assert tracks[2].artist == "Bruno Mars"


def test_filename_dash_fallback(options):
    opts = options()
    tracks = [make_track(None, name="Cara Delevingne – I want candy.mp3")]
    org.resolve_artists(tracks, opts)
    assert tracks[0].artist == "Cara Delevingne"
    assert tracks[0].artist_source == "filename"


def test_filename_guess_library_never_invents_an_artist(options):
    opts = options("--filename-guess", "library")
    tracks = [make_track(None, name="Some Unknown Person – A Song.mp3")]
    org.resolve_artists(tracks, opts)
    assert tracks[0].artist is None


def test_filename_guess_off(options):
    opts = options("--filename-guess", "off")
    tracks = [make_track("Queen", title="x"), make_track(None, name="Queen – Love Of My Life.mp3")]
    org.resolve_artists(tracks, opts)
    assert tracks[1].artist is None


def test_underscored_filename(options):
    opts = options()
    tracks = [make_track(None, name="Jah_Khalib_-_Leyla_feat_Makvin.mp3")]
    org.resolve_artists(tracks, opts)
    assert tracks[0].artist == "Jah Khalib"


# --------------------------------------------------------------------------- #
# where a track ends up
# --------------------------------------------------------------------------- #

def plan_one(track, opts):
    artists, albums = org.build_name_maps([track])
    return org.destination_for(track, artists, albums, opts)


def test_default_layout(options):
    opts = options()
    track = make_track("Gracie Abrams", "Good Riddance", "Amelie", track_no=5, name="x.mp3")
    assert plan_one(track, opts).relative_to(opts.destination).as_posix() \
        == "Gracie Abrams/Good Riddance/05 - Amelie.mp3"


def test_untagged_goes_to_others(options):
    opts = options()
    track = make_track(None, name="mystery.mp3")
    assert plan_one(track, opts).relative_to(opts.destination).as_posix() == "Others/mystery.mp3"


def test_missing_album_goes_to_unknown_album(options):
    opts = options()
    track = make_track("Adele", None, "Hello", name="h.m4a")
    assert plan_one(track, opts).relative_to(opts.destination).as_posix() \
        == "Adele/Unknown Album/Hello.m4a"


@pytest.mark.parametrize("switches, expected", [
    (("--layout", "artist"),           "Gracie Abrams/05 - Amelie.mp3"),
    (("--layout", "flat"),             "05 - Amelie.mp3"),
    (("--layout", "artist/year-album"), "Gracie Abrams/2023 - Good Riddance/05 - Amelie.mp3"),
    (("--no-track-numbers",),          "Gracie Abrams/Good Riddance/Amelie.mp3"),
    (("--artist-in-filename",),        "Gracie Abrams/Good Riddance/05 - Gracie Abrams - Amelie.mp3"),
    (("--keep-filenames",),            "Gracie Abrams/Good Riddance/x.mp3"),
    (("--others-name", "Misc"),        "Gracie Abrams/Good Riddance/05 - Amelie.mp3"),
])
def test_layout_switches(options, switches, expected):
    opts = options(*switches)
    track = make_track("Gracie Abrams", "Good Riddance", "Amelie",
                       track_no=5, year="2023", name="x.mp3")
    assert plan_one(track, opts).relative_to(opts.destination).as_posix() == expected


def test_singles_in_artist_root(options):
    opts = options("--singles-in-artist-root")
    track = make_track("Adele", None, "Hello", name="h.m4a")
    assert plan_one(track, opts).relative_to(opts.destination).as_posix() == "Adele/Hello.m4a"


def test_others_name_switch(options):
    opts = options("--others-name", "Misc")
    track = make_track(None, name="mystery.mp3")
    assert plan_one(track, opts).relative_to(opts.destination).as_posix() == "Misc/mystery.mp3"


def test_filename_uses_canonical_artist_not_the_raw_tag(options):
    """Folder and filename must agree even when the tag is oddly cased."""
    opts = options("--artist-in-filename")
    tracks = [make_track("adele", None, "Hello", name="h.m4a")]
    artists, albums = org.build_name_maps(tracks)
    assert org.destination_for(tracks[0], artists, albums, opts).name == "Adele - Hello.m4a"


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
    ("Adele", "Adele"), ("Unknown Artist", None), ("  ", None), (None, None), ("Various", None),
])
def test_clean_value(raw, expected):
    assert org.clean_value(raw) == expected
