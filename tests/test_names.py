"""Artist-name interpretation: splitting, merging, capitalizing, sanitizing."""
from collections import Counter

import pytest
from conftest import make_track

import MusicOrganizer as org

# --------------------------------------------------------------------------- #
# splitting a collaborative tag down to the lead artist
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("raw, expected", [
    ("Nova Kane",                          "Nova Kane"),
    ("  Kestrel  ",                        "Kestrel"),
    # featuring
    ("Nova Kane feat. Rex Miller",         "Nova Kane"),
    ("Nova Kane ft Rex Miller",            "Nova Kane"),
    ("Nova Kane (feat. Rex Miller)",       "Nova Kane"),
    ("Nova Kane [Feat. Rex Miller]",       "Nova Kane"),
    ("Nova Kane featuring Rex Miller",     "Nova Kane"),
    # hard separators
    ("Nova Kane, Rex Miller",              "Nova Kane"),
    ("Nova Kane / Rex Miller",             "Nova Kane"),
    ("Nova Kane; Rex Miller",              "Nova Kane"),
    ("Nova Kane|Rex Miller",               "Nova Kane"),
    ("Kestrel/ Vera Cole/ Rex Miller",     "Kestrel"),
    ("Las Palomas, Rex Miller",            "Las Palomas"),
    ("Artist A\x00Artist B",               "Artist A"),   # ID3 multi-value
    # names that merely look like collaborations
    ("AC/DC",                              "AC/DC"),
    ("Tyler, The Creator",                 "Tyler, The Creator"),
    ("Crosby, Stills & Nash",              "Crosby, Stills & Nash"),
    ("Simon & Garfunkel",                  "Simon & Garfunkel"),
    ("Earth, Wind & Fire",                 "Earth, Wind & Fire"),
    ("Florence + The Machine",             "Florence + The Machine"),
    ("Panic! At The Disco",                "Panic! At The Disco"),
    ("Vera X",                             "Vera X"),       # a trailing x is not a separator
    # "with" is not a featuring marker - real names contain it
    ("Coffee With Strangers",              "Coffee With Strangers"),
    # a two-word head means the article really is a second artist
    ("Nova Kane, the Wildfires",           "Nova Kane"),
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
    ("Nova Kane & Rex Miller",  "Nova Kane"),
    ("Vera Cole + Rex Miller",  "Vera Cole"),
    ("Simon & Garfunkel",       "Simon & Garfunkel"),   # keep-list still wins
])
def test_primary_artist_split_ampersand(raw, expected):
    assert org.primary_artist(raw, split_ampersand=True) == expected


def test_split_x_is_opt_in():
    assert org.primary_artist("Nova Kane x Rex Miller", split_ampersand=True) \
        == "Nova Kane x Rex Miller"
    assert org.primary_artist("Nova Kane x Rex Miller",
                              split_ampersand=True, split_x=True) == "Nova Kane"


# --------------------------------------------------------------------------- #
# folding spellings together
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("group", [
    ["Nova Kane", "nova kane", "NOVA KANE", "Nova  Kane"],
    ["The Wildfires", "wildfires", "THE WILDFIRES"],
    ["Renee Adair", "Renée Adair", "RENÉE ADAIR"],
    ["Simon & Garfunkel", "Simon and Garfunkel"],
    ["Rex-Miller", "REX MILLER", "rex miller"],
    ["Sölvi Rós", "Solvi Ros"],
])
def test_spellings_merge(group):
    assert len({org.normalize_key(name) for name in group}) == 1


@pytest.mark.parametrize("a, b", [
    ("Wildfires", "Wild Horses"),
    ("Nova", "Nova Kane"),
    ("Vera", "Vera Cole"),
    ("Kestrel", "Kestrel Bay"),
])
def test_distinct_artists_stay_distinct(a, b):
    assert org.normalize_key(a) != org.normalize_key(b)


def test_keep_the_disables_article_folding():
    org.CONFIG.strip_leading_the = False
    assert org.normalize_key("The Wildfires") != org.normalize_key("Wildfires")


# --------------------------------------------------------------------------- #
# choosing the spelling that becomes the folder name
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("variants, expected", [
    ({"nova kane": 3, "Nova Kane": 1}, "Nova Kane"),   # quality beats count
    ({"RENEE ADAIR": 2},               "Renee Adair"),   # shouted, not an acronym
    ({"the wildfires": 1},             "The Wildfires"),
    ({"vera cole": 1},                 "Vera Cole"),
    ({"o'brien": 1},                   "O'Brien"),
    # short all-caps names are acronyms, not shouting
    ({"AC/DC": 1}, "AC/DC"),
    ({"ABBA": 1},  "ABBA"),
    ({"MGMT": 3},  "MGMT"),
    ({"ELO": 1},   "ELO"),
])
def test_choose_display_name(variants, expected):
    assert org.choose_display_name(Counter(variants)) == expected


def test_no_recase_keeps_tags_verbatim():
    org.CONFIG.recase = False
    assert org.choose_display_name(Counter({"nova kane": 1})) == "nova kane"


# --------------------------------------------------------------------------- #
# turning a name into a safe path component
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("raw, expected", [
    ("AC/DC",                "AC-DC"),      # a slash can't survive in a path
    ("Where next?",          "Where next"),
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
    artists = {"nova": "Nova", "nova kane": "Nova Kane", "kestrel": "Kestrel"}
    counts = Counter({"nova": 2, "nova kane": 2, "kestrel": 5})
    pairs = org.similar_artists(artists, counts)
    assert ("nova", "nova kane") in pairs
    assert not any("kestrel" in pair for pair in pairs)


def test_aliases_merge_on_request(options):
    opts = options("--alias", "Nova=Nova Kane")
    tracks = [make_track("Nova", title="Low Tide"), make_track("Nova Kane", title="Overtime")]
    org.resolve_artists(tracks, opts)
    assert {t.artist for t in tracks} == {"Nova Kane"}
