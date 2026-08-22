"""Artist-name interpretation: splitting, merging, capitalizing, sanitizing."""
from collections import Counter

import pytest
from conftest import make_track

import MusicOrganizer as org

# --------------------------------------------------------------------------- #
# splitting a collaborative tag down to the lead artist
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("raw, expected", [
    ("Gracie Abrams",                      "Gracie Abrams"),
    ("  Radiohead  ",                      "Radiohead"),
    # featuring
    ("Adele feat. Someone",                "Adele"),
    ("Adele ft Someone",                   "Adele"),
    ("Adele (feat. Someone)",              "Adele"),
    ("Adele [Feat. Someone]",              "Adele"),
    ("Drake featuring Rihanna",            "Drake"),
    # hard separators
    ("Beyonce, JAY-Z",                     "Beyonce"),
    ("Daft Punk / Pharrell",               "Daft Punk"),
    ("Daft Punk; Pharrell",                "Daft Punk"),
    ("Daft Punk|Pharrell",                 "Daft Punk"),
    ("Frozy/ Mwizz/ George Kipa",          "Frozy"),
    ("Los Lobos, Someone",                 "Los Lobos"),
    ("Artist A\x00Artist B",               "Artist A"),   # ID3 multi-value
    # names that merely look like collaborations
    ("AC/DC",                              "AC/DC"),
    ("Au/Ra",                              "Au/Ra"),
    ("Tyler, The Creator",                 "Tyler, The Creator"),
    ("Crosby, Stills & Nash",              "Crosby, Stills & Nash"),
    ("Simon & Garfunkel",                  "Simon & Garfunkel"),
    ("Earth, Wind & Fire",                 "Earth, Wind & Fire"),
    ("Florence + The Machine",             "Florence + The Machine"),
    ("Panic! At The Disco",                "Panic! At The Disco"),
    ("RY X",                               "RY X"),
    ("Allie X",                            "Allie X"),
    # "with" is not a featuring marker - real names contain it
    ("All the Other Kids With the Pumped Up Kicks",
     "All the Other Kids With the Pumped Up Kicks"),
    # a two-word head means the article really is a second artist
    ("Taylor Swift, the Civil Wars",       "Taylor Swift"),
    # placeholders
    ("Unknown Artist",                     None),
    ("Various Artists",                    None),
    ("N/A",                                None),
    ("",                                   None),
    ("   ",                                None),
])
def test_primary_artist(raw, expected):
    assert org.primary_artist(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("Eminem & Rihanna",         "Eminem"),
    ("Calvin Harris + Dua Lipa", "Calvin Harris"),
    ("Simon & Garfunkel",        "Simon & Garfunkel"),   # keep-list still wins
])
def test_primary_artist_split_ampersand(raw, expected):
    assert org.primary_artist(raw, split_ampersand=True) == expected


def test_split_x_is_opt_in():
    assert org.primary_artist("Jack U x Justin Bieber", split_ampersand=True) \
        == "Jack U x Justin Bieber"
    assert org.primary_artist("Jack U x Justin Bieber",
                              split_ampersand=True, split_x=True) == "Jack U"


# --------------------------------------------------------------------------- #
# folding spellings together
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("group", [
    ["Gracie Abrams", "gracie abrams", "GRACIE ABRAMS", "Gracie  Abrams"],
    ["The Beatles", "beatles", "THE BEATLES"],
    ["Beyonce", "Beyoncé", "BEYONCÉ"],
    ["Simon & Garfunkel", "Simon and Garfunkel"],
    ["Jay-Z", "JAY Z", "jay z"],
    ["Sigur Rós", "Sigur Ros"],
])
def test_spellings_merge(group):
    assert len({org.normalize_key(name) for name in group}) == 1


@pytest.mark.parametrize("a, b", [
    ("Beatles", "Beach Boys"),
    ("Adele", "Adele Roberts"),
    ("Drake", "Drake Bell"),
    ("Zhavia", "Zhavia Ward"),
])
def test_distinct_artists_stay_distinct(a, b):
    assert org.normalize_key(a) != org.normalize_key(b)


def test_keep_the_disables_article_folding():
    org.CONFIG.strip_leading_the = False
    assert org.normalize_key("The Beatles") != org.normalize_key("Beatles")


# --------------------------------------------------------------------------- #
# choosing the spelling that becomes the folder name
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("variants, expected", [
    ({"gracie abrams": 3, "Gracie Abrams": 1}, "Gracie Abrams"),  # quality beats count
    ({"GRACIE ABRAMS": 2},                     "Gracie Abrams"),
    ({"the beatles": 1},                       "The Beatles"),
    ({"kendrick lamar": 1},                    "Kendrick Lamar"),
    ({"o'brien": 1},                           "O'Brien"),
    # short all-caps names are acronyms, not shouting
    ({"AC/DC": 1}, "AC/DC"),
    ({"ABBA": 1},  "ABBA"),
    ({"MGMT": 3},  "MGMT"),
    ({"SZA": 1},   "SZA"),
])
def test_choose_display_name(variants, expected):
    assert org.choose_display_name(Counter(variants)) == expected


def test_no_recase_keeps_tags_verbatim():
    org.CONFIG.recase = False
    assert org.choose_display_name(Counter({"gracie abrams": 1})) == "gracie abrams"


# --------------------------------------------------------------------------- #
# turning a name into a safe path component
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("raw, expected", [
    ("AC/DC",                "AC-DC"),      # a slash can't survive in a path
    ("Where do we go now?",  "Where do we go now"),
    ('a<b>c:d|e*f',          "a_b_c_d_e_f"),
    ("...",                  "Unknown"),
    ("",                     "Unknown"),
    ("CON",                  "_CON"),       # reserved on Windows
    ("trailing dot.",        "trailing dot"),
    ("  spaced  out  ",      "spaced out"),
])
def test_sanitize(raw, expected):
    assert org.sanitize(raw) == expected


def test_sanitize_truncates():
    assert len(org.sanitize("x" * 500, max_length=20)) == 20


def test_sanitize_strips_control_characters():
    assert "\n" not in org.sanitize("bad\nname")


# --------------------------------------------------------------------------- #
# near-duplicate folder detection (reported, never merged automatically)
# --------------------------------------------------------------------------- #

def test_similar_artists_reports_but_does_not_merge():
    artists = {"zhavia": "Zhavia", "zhavia ward": "Zhavia Ward", "queen": "Queen"}
    counts = Counter({"zhavia": 2, "zhavia ward": 2, "queen": 5})
    pairs = org.similar_artists(artists, counts)
    assert ("zhavia", "zhavia ward") in pairs
    assert not any("queen" in pair for pair in pairs)


def test_aliases_merge_on_request(options):
    opts = options("--alias", "Zhavia=Zhavia Ward")
    tracks = [make_track("Zhavia", title="Man Down"), make_track("Zhavia Ward", title="Deep Down")]
    org.resolve_artists(tracks, opts)
    assert {t.artist for t in tracks} == {"Zhavia Ward"}
