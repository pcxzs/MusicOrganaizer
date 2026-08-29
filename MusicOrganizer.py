#!/usr/bin/env python3
"""Organize a music library into Artist/Album folders.

    python MusicOrganizer.py <source> <destination> [options]
    python MusicOrganizer.py                      # prompts for the two paths
    python MusicOrganizer.py --help               # every switch, grouped

What it does
  * reads tags from mp3, flac, m4a, ogg, opus, wma, wav, ape, wv ... (anything mutagen reads)
  * files land in  <destination>/<Artist>/<Album>/<track> - <title>.<ext>
  * tracks with no usable artist tag land in  <destination>/Others/
  * "artist name", "Artist Name" and "ARTIST NAME" all share one folder
  * "Artist A, Artist B" / "Artist A feat. Artist B" file under the first artist
  * duplicates are detected by hashing the *audio*, so the same song tagged two
    different ways is still recognized as a duplicate

Requires: pip install mutagen
"""

from __future__ import annotations

import argparse
import csv
import fnmatch
import hashlib
import os
import re
import shutil
import sys
import unicodedata
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

try:
    import mutagen
except ImportError:  # pragma: no cover - dependency check
    sys.exit("This script needs mutagen.  Install it with:  pip install mutagen")

__version__ = "0.9.0"


# --------------------------------------------------------------------------- #
# configuration
# --------------------------------------------------------------------------- #

AUDIO_EXTENSIONS = {
    ".mp3", ".flac", ".m4a", ".m4b", ".mp4", ".aac", ".alac",
    ".ogg", ".oga", ".opus", ".spx", ".wma", ".asf",
    ".wav", ".wave", ".aif", ".aiff", ".aifc",
    ".ape", ".wv", ".mpc", ".tta", ".dsf", ".dff",
}

# Acts whose own name contains a separator character.  A tag matching one of
# these is never split, so the seed list is what keeps the splitter from cutting
# a band in half.  Entries are written naturally: normalize_key() folds them at
# import, so case, accents and punctuation here are free.  Libraries with other
# separator-bearing names extend the set at runtime through --keep-name and
# --keep-names-file rather than by editing this literal.
KNOWN_SINGLE_ACTS_RAW = {
    "AC/DC", "Tyler, The Creator", "Earth, Wind & Fire", "Crosby, Stills & Nash",
    "Crosby, Stills, Nash & Young", "Emerson, Lake & Palmer", "Blood, Sweat & Tears",
    "Florence + The Machine", "Simon & Garfunkel", "Hall & Oates", "Sam & Dave",
    "Peter, Paul & Mary", "Kool & The Gang", "Huey Lewis & The News",
    "Derek & The Dominos", "Sly & The Family Stone", "Nick Cave & The Bad Seeds",
    "Belle & Sebastian", "Of Monsters and Men", "Mumford & Sons",
    "Angus & Julia Stone", "Ike & Tina Turner", "Captain & Tennille",
    "Iron & Wine", "Chase & Status", "Above & Beyond", "Hootie & The Blowfish",
    "Echo & The Bunnymen", "Bob Marley & The Wailers", "Tom Petty & The Heartbreakers",
    "Elvis Costello & The Attractions", "Panic! At The Disco", "The Mamas & The Papas",
    "Now, Now", "Matt & Kim", "She & Him", "Jay-Z", "will.i.am",
    "Antony & The Johnsons", "Marina & The Diamonds", "Sleaford Mods",
    "Alvin & The Chipmunks", "Booker T. & The M.G.'s", "Big Brother & The Holding Company",
    "Katrina & The Waves", "Martha & The Vandellas", "Diana Ross & The Supremes",
    "Gladys Knight & The Pips", "Sonny & Cher", "Ashford & Simpson", "Brooks & Dunn",
    "Edward Sharpe & The Magnetic Zeros", "Nico & Vinz",
    "Macklemore & Ryan Lewis", "Lykke Li", "Dan & Shay",
}

# Guest markers: everything from "feat.", "ft", "featuring" or "vs" onwards is
# dropped.  A bare "with" is deliberately not a marker - it occurs inside plenty
# of ordinary names, where treating it as one would truncate them.
FEATURING_RE = re.compile(
    r"""[\s\-,;/]*[\(\[\{]?\s*
        \b(?:feat|feats|featuring|ft|fts|vs|versus)\b\.?
        \s+""",
    re.IGNORECASE | re.VERBOSE,
)

# Separators that reliably mean "several artists".  A slash needs whitespace on
# at least one side so that AC/DC survives intact.
HARD_SPLIT_RE = re.compile(r"\s*[;|]\s*|\s+/\s*|\s*/\s+|\s*,\s*|\s+·\s+")

# Ambiguous separators: plenty of bands are themselves named "X & Y".  Applied
# only when one of the sides is separately a known artist (see resolve_artists),
# or when --split-ampersand forces the split unconditionally.
SOFT_SPLIT_RE = re.compile(r"\s+(?:&|\+)\s+")
SOFT_SPLIT_WITH_X_RE = re.compile(r"\s+(?:&|\+|x|X)\s+")

ARTICLE_RE = re.compile(r"^(?:the|a|an|los|las|les|die|der|das)\b", re.IGNORECASE)

# Filename fallbacks, used only when a file has no usable artist tag.
LEADING_TRACK_RE = re.compile(r"^\s*\d{1,3}\s*[.\-_)\s]\s*")
FILENAME_ARTIST_RE = re.compile(r"^(.{2,60}?)\s+[-–—]\s+")

# Words left lowercase when a name has to be re-capitalized.
SMALL_WORDS = {
    "a", "an", "and", "as", "at", "but", "by", "for", "from", "in", "into", "nor",
    "of", "on", "or", "the", "to", "vs", "with", "de", "del", "la", "le", "van", "von",
}

ILLEGAL_CHARS_RE = re.compile(r'[<>:"|?*\x00-\x1f]')
PATH_SEPARATOR_RE = re.compile(r"[/\\]")
RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {
    f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10)
}

_PLACEHOLDER_SOURCE = {
    "", "unknown", "unknown artist", "unknown album", "various", "various artists",
    "va", "none", "n/a", "na", "untitled", "no artist", "artist", "album", "null",
}

CHUNK = 1 << 20  # 1 MiB


class CONFIG:
    """Switches read by helpers that are called too deep to be passed options."""
    strip_leading_the = True   # --keep-the turns this off
    recase = True             # --no-recase turns this off
    audio_only_hash = True    # --exact-dupes turns this off


# --------------------------------------------------------------------------- #
# name handling
# --------------------------------------------------------------------------- #

def normalize_key(name: str) -> str:
    """Fold a name down to a comparison key.

    'The Artist', 'the artist' and 'Artist' -> 'artist'
    'Renee' and 'Renée'                     -> 'renee'
    'Salt & Ash'                            -> 'salt and ash'
    """
    text = unicodedata.normalize("NFKD", name)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    text = text.replace("&", " and ").replace("+", " and ")
    text = re.sub(r"[^0-9a-z]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if CONFIG.strip_leading_the and text.startswith("the "):
        text = text[4:]
    return text


# Compared against normalize_key() output, so they have to be folded the same way.
PLACEHOLDER_KEYS = {normalize_key(value) for value in _PLACEHOLDER_SOURCE}
KNOWN_SINGLE_ACTS = {normalize_key(name) for name in KNOWN_SINGLE_ACTS_RAW}


def looks_like_acronym(name: str) -> bool:
    """True for an all-caps name whose words are all four letters or fewer (ABBA, MGMT).

    Distinguishes a genuine acronym from a name that merely arrived SHOUTED.
    """
    runs = re.findall(r"[A-Za-z]+", name)
    return bool(runs) and all(len(run) <= 4 for run in runs)


def smart_title(name: str) -> str:
    """Capitalize a name that arrived all-lowercase or SHOUTED."""
    words = name.split()
    out = []
    for index, word in enumerate(words):
        lowered = word.lower()
        if index not in (0, len(words) - 1) and lowered in SMALL_WORDS:
            out.append(lowered)
        elif "'" in word:  # o'brien -> O'Brien, don't -> Don't
            head, _, tail = word.partition("'")
            out.append(head.capitalize() + "'" + (tail if len(tail) < 2 else tail.capitalize()))
        else:
            out.append(word[:1].upper() + word[1:].lower())
    return " ".join(out)


def choose_display_name(variants: Counter[str]) -> str:
    """Pick the nicest spelling out of everything seen for one key."""
    def rank(item: tuple[str, int]) -> tuple:
        name, count = item
        has_mixed_case = not name.isupper() and not name.islower()
        starts_upper = name[:1].isupper()
        return (-count, not has_mixed_case, not starts_upper, name)

    best = min(variants.items(), key=rank)[0]
    if CONFIG.recase and (best.islower() or (best.isupper() and not looks_like_acronym(best))):
        best = smart_title(best)
    return best.strip()


def sanitize(name: str, fallback: str = "Unknown", max_length: int = 120) -> str:
    """Make a string safe to use as a single path component."""
    cleaned = PATH_SEPARATOR_RE.sub("-", name)          # AC/DC -> AC-DC
    cleaned = ILLEGAL_CHARS_RE.sub("_", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip("_. ")
    if not cleaned:
        return fallback
    if cleaned.split(".")[0].upper() in RESERVED_NAMES:
        cleaned = "_" + cleaned
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip("_. ") or fallback
    return cleaned


def has_soft_separator(raw: str) -> bool:
    return bool(SOFT_SPLIT_RE.search(raw))


def primary_artist(raw: str, *, split_ampersand: bool = False, keep: set[str] = KNOWN_SINGLE_ACTS,
                   split_x: bool = False) -> str | None:
    """Reduce a possibly-collaborative artist tag to the lead artist."""
    name = raw.replace("\x00", "; ").strip().strip("-–—,;/ ")   # ID3 multi-value
    if not name or normalize_key(name) in PLACEHOLDER_KEYS:
        return None
    if normalize_key(name) in keep:
        return name

    stripped = FEATURING_RE.split(name, maxsplit=1)[0].strip(" ([{-,;/")
    if stripped and normalize_key(stripped):
        name = stripped
    if normalize_key(name) in keep:
        return name

    regexes = [HARD_SPLIT_RE]
    if split_ampersand:
        regexes.append(SOFT_SPLIT_WITH_X_RE if split_x else SOFT_SPLIT_RE)
    for regex in regexes:
        parts = [p.strip() for p in regex.split(name) if p and p.strip()]
        if len(parts) > 1:
            # A separator followed by an article is ambiguous.  After a
            # one-word head it is usually still one name ("Tyler, The
            # Creator"); after a longer head the article begins a second act.
            if (regex is HARD_SPLIT_RE and ARTICLE_RE.match(parts[1])
                    and len(parts[0].split()) == 1):
                continue
            name = parts[0]

    name = name.strip(" ([{-,;/&+")
    return name if normalize_key(name) else None


def artist_from_filename(stem: str, registry: dict[str, str],
                         dash_fallback: bool = True) -> tuple[str | None, str]:
    """Guess an artist for a file whose tags are empty.

    First looks for an artist the library already knows about anywhere in the
    name ("Song Title   Artist Name"), which also settles whether the stem reads
    "Artist - Title" or "Title - Artist".  Only then falls back to splitting on
    a dash.  Returns (artist, how) where how is 'library', 'filename' or ''.
    """
    text = stem.replace("_", " ")

    padded = f" {normalize_key(text)} "
    best = None
    for key in registry:
        if len(key) >= 4 and f" {key} " in padded:
            if best is None or len(key) > len(best):
                best = key
    if best:
        return registry[best], "library"

    if not dash_fallback:
        return None, ""
    trimmed = LEADING_TRACK_RE.sub("", text)
    match = FILENAME_ARTIST_RE.match(trimmed)
    if match:
        guess = primary_artist(match.group(1))
        if guess and len(normalize_key(guess)) >= 3:
            return guess, "filename"
    return None, ""


# --------------------------------------------------------------------------- #
# tag reading
# --------------------------------------------------------------------------- #

ID3_FRAMES = {
    "artist": "TPE1", "albumartist": "TPE2", "album": "TALB",
    "title": "TIT2", "tracknumber": "TRCK", "discnumber": "TPOS", "date": "TDRC",
}
ASF_KEYS = {
    "artist": "Author", "albumartist": "WM/AlbumArtist", "album": "WM/AlbumTitle",
    "title": "Title", "tracknumber": "WM/TrackNumber", "discnumber": "WM/PartOfSet",
    "date": "WM/Year",
}
TAG_FIELDS = ("artist", "albumartist", "album", "title", "tracknumber", "discnumber", "date")


def _first(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def read_tags(audio) -> dict[str, str | None]:
    """Pull the TAG_FIELDS values out of any mutagen file object."""
    tags = getattr(audio, "tags", None)
    found: dict[str, str | None] = dict.fromkeys(TAG_FIELDS)
    if tags is None:
        return found

    lowered = {}
    try:
        for key in tags.keys():
            lowered.setdefault(str(key).lower(), key)
    except Exception:
        lowered = {}

    for name in TAG_FIELDS:
        for candidate in (name, name.replace("number", ""), f"wm/{name}"):
            key = lowered.get(candidate)
            if key is not None:
                try:
                    found[name] = _first(tags[key])
                except Exception:
                    pass
                if found[name]:
                    break

    # Raw fallbacks for containers whose keys aren't plain words.
    for name, frame in ID3_FRAMES.items():
        if not found[name]:
            try:
                found[name] = _first(tags.get(frame) and tags[frame].text)
            except Exception:
                pass
    for name, key in ASF_KEYS.items():
        if not found[name]:
            try:
                found[name] = _first(tags.get(key))
            except Exception:
                pass
    return found


def parse_number(value: str | None) -> int | None:
    if not value:
        return None
    match = re.match(r"\s*(\d+)", str(value))
    return int(match.group(1)) if match else None


def parse_year(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"(1[89]\d\d|20\d\d)", str(value))
    return match.group(1) if match else None


def clean_value(value: str | None) -> str | None:
    """Drop placeholder junk like 'Unknown Artist' or 'track01'."""
    if not value:
        return None
    text = value.replace("\x00", " ").strip()
    return None if normalize_key(text) in PLACEHOLDER_KEYS else text or None


# --------------------------------------------------------------------------- #
# content fingerprinting
# --------------------------------------------------------------------------- #

def _mp3_audio_span(handle, size: int) -> tuple[int, int]:
    """Byte range of the actual MPEG frames, skipping ID3v2/ID3v1/APEv2."""
    start, end = 0, size
    handle.seek(0)
    header = handle.read(10)
    if header[:3] == b"ID3" and len(header) == 10:
        tag_size = 0
        for byte in header[6:10]:
            tag_size = (tag_size << 7) | (byte & 0x7F)
        start = 10 + tag_size + (10 if header[5] & 0x10 else 0)

    for _ in range(3):  # APEv2 and ID3v1 can both be present, in either order
        if end - start >= 128:
            handle.seek(end - 128)
            if handle.read(3) == b"TAG":
                end -= 128
                continue
        if end - start >= 32:
            handle.seek(end - 32)
            footer = handle.read(32)
            if footer[:8] == b"APETAGEX":
                tag_size = int.from_bytes(footer[12:16], "little")
                flags = int.from_bytes(footer[16:20], "little")
                end -= tag_size + (32 if flags & 0x80000000 else 0)
                continue
        break
    return start, max(start, end)


def _flac_audio_span(handle, size: int) -> tuple[int, int]:
    """Byte range after the FLAC metadata blocks."""
    handle.seek(0)
    if handle.read(4) != b"fLaC":
        return 0, size
    position = 4
    while position < size:
        handle.seek(position)
        header = handle.read(4)
        if len(header) < 4:
            break
        length = int.from_bytes(header[1:4], "big")
        position += 4 + length
        if header[0] & 0x80:  # last-metadata-block flag
            break
    return min(position, size), size


def fingerprint(path: Path) -> str:
    """SHA-256 of the audio payload, skipping the tag regions the parsers know.

    Two copies of the same song with different tags produce the same digest.
    Containers with no span parser here fall back to hashing the whole file, as
    does --exact-dupes.
    """
    digest = hashlib.sha256()
    size = path.stat().st_size
    with path.open("rb") as handle:
        suffix = path.suffix.lower()
        start, end = 0, size
        if CONFIG.audio_only_hash:
            try:
                if suffix == ".mp3":
                    start, end = _mp3_audio_span(handle, size)
                elif suffix == ".flac":
                    start, end = _flac_audio_span(handle, size)
            except Exception:
                start, end = 0, size

        handle.seek(start)
        remaining = end - start
        while remaining > 0:
            block = handle.read(min(CHUNK, remaining))
            if not block:
                break
            digest.update(block)
            remaining -= len(block)
    return digest.hexdigest()


def safe_fingerprint(path: Path) -> str | None:
    try:
        return fingerprint(path)
    except OSError:
        return None


# --------------------------------------------------------------------------- #
# scanning
# --------------------------------------------------------------------------- #

@dataclass
class Track:
    path: Path
    size: int
    artist: str | None = None
    artist_raw: str | None = None
    artist_source: str = "none"      # tag | tag-split | library | filename | none
    album: str | None = None
    title: str | None = None
    year: str | None = None
    track_no: int | None = None
    disc_no: int | None = None
    tag_count: int = 0
    digest: str = ""
    artist_key: str = ""
    album_key: str = ""


def find_audio_files(source: Path, skip: Path | None, options=None) -> list[Path]:
    extensions = getattr(options, "extensions", None) or AUDIO_EXTENSIONS
    excludes = getattr(options, "exclude", None) or []
    min_bytes = getattr(options, "min_bytes", 0)
    follow = getattr(options, "follow_symlinks", False)

    files: list[Path] = []
    for root, dirnames, filenames in os.walk(source, followlinks=follow):
        root_path = Path(root)
        dirnames[:] = [
            d for d in dirnames
            if not (skip is not None and (root_path / d).resolve() == skip)
            and not any(fnmatch.fnmatch(d, pattern) for pattern in excludes)
        ]
        dirnames.sort()
        for name in sorted(filenames):
            if Path(name).suffix.lower() not in extensions:
                continue
            if any(fnmatch.fnmatch(name, pattern) for pattern in excludes):
                continue
            full = root_path / name
            if min_bytes:
                try:
                    if full.stat().st_size < min_bytes:
                        continue
                except OSError:
                    continue
            files.append(full)
    return files


def scan_file(path: Path, options) -> tuple[Track | None, str | None]:
    try:
        size = path.stat().st_size
    except OSError as err:
        return None, f"{path}: {err}"
    if size == 0:
        return None, f"{path}: empty file"

    track = Track(path=path, size=size)
    try:
        audio = mutagen.File(path, easy=True)
    except Exception:
        audio = None
    if audio is None:
        try:  # some formats only load without the "easy" wrappers
            audio = mutagen.File(path)
        except Exception:
            audio = None

    if audio is not None:
        tags = read_tags(audio)
        try:
            track.tag_count = len(audio.tags or {})
        except Exception:
            track.tag_count = 0
        if options.prefer_artist_tag:
            raw = clean_value(tags["artist"]) or clean_value(tags["albumartist"])
        else:
            raw = clean_value(tags["albumartist"]) or clean_value(tags["artist"])
        track.artist_raw = raw
        if raw:
            track.artist = primary_artist(
                raw, split_ampersand=options.split_ampersand,
                keep=options.keep_names, split_x=options.split_x,
            )
            if track.artist:
                track.artist_source = "tag"
        track.album = clean_value(tags["album"])
        track.title = clean_value(tags["title"])
        track.year = parse_year(tags["date"])
        track.track_no = parse_number(tags["tracknumber"])
        track.disc_no = parse_number(tags["discnumber"])

    try:
        track.digest = fingerprint(path)
    except OSError as err:
        return None, f"{path}: {err}"

    track.artist_key = normalize_key(track.artist) if track.artist else ""
    track.album_key = normalize_key(track.album) if track.album else ""
    return track, None


# --------------------------------------------------------------------------- #
# second-pass artist resolution
# --------------------------------------------------------------------------- #

def resolve_artists(tracks: list[Track], options) -> Counter[str]:
    """Use the library's own artist list to settle the ambiguous cases.

    Two things can't be decided from a single file in isolation:

      * "A & B" is a collaboration in one library and a band name in another.
        Whether to split it depends on whether A or B also stands alone here.
      * A file with no tags at all may still name its artist in the filename.
        Matching against the known artists identifies which half of
        "Title - Artist" is the artist.

    Both need the whole collection in view, so they happen here rather than in
    scan_file.  Returns a count of how each track's artist was decided.
    """
    stats: Counter[str] = Counter()

    # Registry of unambiguous artists: named by a tag, and not themselves in
    # the "X & Y" shape whose reading is the open question.
    registry: dict[str, str] = {}
    for track in tracks:
        if track.artist and not (track.artist_raw and has_soft_separator(track.artist_raw)):
            registry.setdefault(track.artist_key, track.artist)

    if options.smart_split:
        for track in tracks:
            if not track.artist or not track.artist_raw:
                continue
            if not has_soft_separator(track.artist_raw):
                continue
            if normalize_key(track.artist_raw) in options.keep_names:
                continue
            sides = [p.strip() for p in SOFT_SPLIT_RE.split(track.artist_raw) if p.strip()]
            if len(sides) < 2:
                continue
            # Split only when *some* side also appears on its own elsewhere in
            # the library, which is the evidence that the tag names two acts.
            # If neither half is known, the separator belongs to the name.
            if not any(normalize_key(side) in registry for side in sides):
                continue
            head = primary_artist(
                track.artist_raw, split_ampersand=True,
                keep=options.keep_names, split_x=options.split_x,
            )
            if not head:
                continue
            key = normalize_key(head)          # always keep the first-listed name
            if key != track.artist_key:
                track.artist = registry.get(key, head)
                track.artist_key = key
                track.artist_source = "tag-split"

    if options.filename_guess != "off":
        for track in tracks:
            if track.artist:
                continue
            guess, how = artist_from_filename(
                track.path.stem, registry, dash_fallback=options.filename_guess == "full")
            if guess:
                track.artist = guess
                track.artist_key = normalize_key(guess)
                track.artist_source = how

    for track in tracks:                       # user-supplied --alias mappings
        target = options.aliases.get(track.artist_key)
        if target:
            track.artist = target
            track.artist_key = normalize_key(target)

    for track in tracks:
        stats[track.artist_source] += 1
    return stats


# --------------------------------------------------------------------------- #
# planning
# --------------------------------------------------------------------------- #

def build_name_maps(tracks: list[Track]) -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    """Decide one canonical spelling per artist, and per album within an artist."""
    artist_variants: dict[str, Counter[str]] = defaultdict(Counter)
    album_variants: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for track in tracks:
        if track.artist_key:
            artist_variants[track.artist_key][track.artist] += 1
        if track.album_key:
            album_variants[(track.artist_key, track.album_key)][track.album] += 1

    artists = {key: choose_display_name(v) for key, v in artist_variants.items()}
    albums = {key: choose_display_name(v) for key, v in album_variants.items()}
    return artists, albums


def similar_artists(artists: dict[str, str], counts: Counter[str]) -> list[tuple[str, str]]:
    """Artist folders where one name is contained in the other.

    Containment is a hint, not proof: a short name and a longer one built from
    it are often one artist and just as often two, and nothing in the tags says
    which.  Pairs are reported for a human to judge, never merged - see --alias.
    """
    pairs = []
    keys = sorted(artists)
    for short in keys:
        for long in keys:
            if short == long or len(short) < 4:
                continue
            if long.startswith(short + " ") or long.endswith(" " + short):
                pairs.append((short, long))
    pairs.sort(key=lambda p: -(counts[p[0]] + counts[p[1]]))
    return pairs


KEEP_RULES = {
    "tags":     lambda t: (-t.tag_count, -t.size, len(str(t.path)), str(t.path)),
    "largest":  lambda t: (-t.size, -t.tag_count, str(t.path)),
    "smallest": lambda t: (t.size, -t.tag_count, str(t.path)),
    "first":    lambda t: (str(t.path),),
}


def build_filename(track: Track, options, artist_display: str | None = None) -> str:
    suffix = track.path.suffix.lower()
    if options.keep_filenames or not track.title:
        return sanitize(track.path.stem, fallback="Untitled",
                        max_length=options.max_name_length) + suffix

    parts = []
    if track.track_no and not options.no_track_numbers:
        number = f"{track.track_no:02d}"
        if track.disc_no and track.disc_no > 1:
            number = f"{track.disc_no}-{number}"
        parts.append(number)
    parts.append(track.title)
    artist = artist_display or track.artist
    if options.artist_in_filename and artist:
        parts.insert(len(parts) - 1, artist)   # after the track number, before the title
    return sanitize(" - ".join(parts), fallback=track.path.stem,
                    max_length=options.max_name_length) + suffix


def destination_for(track: Track, artists, albums, options) -> Path:
    display = artists.get(track.artist_key) if track.artist_key else None
    name = build_filename(track, options, display)
    if options.layout == "flat":
        return options.destination / name

    if not track.artist_key:
        return options.destination / options.others_name / name
    artist = sanitize(display, fallback=options.others_name,
                      max_length=options.max_name_length)
    if options.layout == "artist":
        return options.destination / artist / name

    album = albums.get((track.artist_key, track.album_key)) if track.album_key else None
    if not album:
        if options.singles_in_artist_root:
            return options.destination / artist / name
        album = options.unknown_album
    elif options.layout == "artist/year-album" and track.year:
        album = f"{track.year} - {album}"
    album = sanitize(album, fallback=options.unknown_album, max_length=options.max_name_length)
    return options.destination / artist / album / name


def unique_path(target: Path, taken: set[Path]) -> Path:
    """Add ' (2)', ' (3)' ... until the name is free on disk and in this run."""
    candidate = target
    counter = 2
    while candidate in taken or candidate.exists():
        candidate = target.with_name(f"{target.stem} ({counter}){target.suffix}")
        counter += 1
    taken.add(candidate)
    return candidate


# --------------------------------------------------------------------------- #
# command line
# --------------------------------------------------------------------------- #

def human(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def parse_args(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(
        description="Organize a music library into Artist/Album folders.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  %(prog)s ~/Music ~/Sorted --dry-run        preview without touching anything
  %(prog)s ~/Music ~/Sorted --move           move instead of copy
  %(prog)s ~/Music ~/Sorted --hardlink       no extra disk space used
  %(prog)s ~/Music ~/Sorted --layout artist/year-album
  %(prog)s ~/Music ~/Sorted --report plan.csv --dry-run

Run with no arguments to be prompted for the two directories.""",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("source", nargs="?", help="folder to read music from (searched recursively)")
    parser.add_argument("destination", nargs="?", help="folder to build the library in")

    how = parser.add_argument_group("what to do with the files")
    mode = how.add_mutually_exclusive_group()
    mode.add_argument("--move", action="store_true", help="move files instead of copying")
    mode.add_argument("--hardlink", action="store_true",
                      help="hard-link instead of copying (no extra space, same filesystem only)")
    mode.add_argument("--symlink", action="store_true", help="symlink instead of copying")
    how.add_argument("-n", "--dry-run", action="store_true",
                     help="show what would happen, change nothing")
    how.add_argument("--on-conflict", choices=("rename", "skip", "overwrite"), default="rename",
                     help="when the target name is taken (default: rename to 'name (2)')")
    how.add_argument("-y", "--yes", action="store_true",
                     help="don't ask for confirmation before moving/overwriting")

    shape = parser.add_argument_group("folder and file naming")
    shape.add_argument("--layout", default="artist/album",
                       choices=("artist/album", "artist/year-album", "artist", "flat"),
                       help="folder structure to build (default: artist/album)")
    shape.add_argument("--others-name", default="Others", metavar="NAME",
                       help="folder for tracks with no usable artist (default: Others)")
    shape.add_argument("--unknown-album", default="Unknown Album", metavar="NAME",
                       help="folder for tracks with no album tag (default: Unknown Album)")
    shape.add_argument("--singles-in-artist-root", action="store_true",
                       help="put album-less tracks straight in the artist folder")
    shape.add_argument("--no-track-numbers", action="store_true",
                       help="don't prefix filenames with the track number")
    shape.add_argument("--artist-in-filename", action="store_true",
                       help="include the artist in the filename")
    shape.add_argument("--keep-filenames", action="store_true",
                       help="keep original filenames, only sort into folders")
    shape.add_argument("--max-name-length", type=int, default=120, metavar="N",
                       help="truncate any folder/file name to N characters (default: 120)")

    pick = parser.add_argument_group("which files to consider")
    pick.add_argument("--ext", metavar="LIST",
                      help="only these extensions, comma separated (e.g. mp3,flac)")
    pick.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                      help="skip files/folders matching this glob (repeatable)")
    pick.add_argument("--min-size", type=float, default=0, metavar="MB",
                      help="skip files smaller than this many MB (e.g. 0.5)")
    pick.add_argument("--follow-symlinks", action="store_true",
                      help="follow symlinked directories while scanning")

    names = parser.add_argument_group("how artist names are interpreted")
    names.add_argument("--split-ampersand", action="store_true",
                       help="always split 'A & B' and keep A, even when B is unknown")
    names.add_argument("--split-x", action="store_true",
                       help="with --split-ampersand, also split 'A x B'")
    names.add_argument("--no-smart-split", dest="smart_split", action="store_false",
                       help="don't split 'A & B' even when A is a known artist here")
    names.add_argument("--filename-guess", choices=("off", "library", "full"), default="full",
                       help="for untagged files: 'library' only trusts names already in your "
                            "collection, 'full' also parses 'Artist - Title' (default: full)")
    names.add_argument("--no-filename-guess", dest="filename_guess",
                       action="store_const", const="off",
                       help="same as --filename-guess off")
    names.add_argument("--keep-name", action="append", default=[], metavar="NAME",
                       help="never split this artist name (repeatable)")
    names.add_argument("--keep-names-file", metavar="FILE",
                       help="file with one never-split artist name per line")
    names.add_argument("--alias", action="append", default=[], metavar="FROM=TO",
                       help="file one artist under another, e.g. --alias 'Name=Full Name' "
                            "(repeatable)")
    names.add_argument("--aliases-file", metavar="FILE",
                       help="file with one FROM=TO alias per line")
    names.add_argument("--prefer-artist-tag", action="store_true",
                       help="trust the artist tag over albumartist")
    names.add_argument("--keep-the", dest="strip_the", action="store_false",
                       help="treat a leading 'The' as significant, keeping it a separate folder")
    names.add_argument("--no-recase", dest="recase", action="store_false",
                       help="never re-capitalize names, use them exactly as tagged")

    dupes = parser.add_argument_group("duplicate handling")
    dupes.add_argument("--no-dedupe", action="store_true",
                       help="copy duplicates too instead of skipping them")
    dupes.add_argument("--duplicates-dir", metavar="DIR",
                       help="put duplicates here instead of leaving them behind")
    dupes.add_argument("--exact-dupes", action="store_true",
                       help="compare whole files, not just audio (differing tags = different)")
    dupes.add_argument("--keep", choices=tuple(KEEP_RULES), default="tags",
                       help="which copy of a duplicate to keep (default: tags, the best-tagged)")
    dupes.add_argument("--no-library-check", dest="library_check", action="store_false",
                       help="don't skip tracks already present in the destination")

    out = parser.add_argument_group("output")
    out.add_argument("-q", "--quiet", action="store_true", help="only print the summary")
    out.add_argument("-v", "--verbose", action="store_true",
                     help="show how each artist name was decided")
    out.add_argument("--report", metavar="FILE", help="write the full plan to a CSV file")
    out.add_argument("--workers", type=int, default=min(8, (os.cpu_count() or 4) + 4),
                     metavar="N", help="parallel readers while scanning")

    options = parser.parse_args(argv)

    if not options.source:
        options.source = input("locate your music directory: ").strip().strip('"')
    if not options.destination:
        options.destination = input("locate your destination directory: ").strip().strip('"')

    options.source = Path(options.source).expanduser().resolve()
    options.destination = Path(options.destination).expanduser().resolve()

    keep_raw = list(options.keep_name)
    if options.keep_names_file:
        try:
            keep_raw += Path(options.keep_names_file).expanduser().read_text(
                encoding="utf-8").splitlines()
        except OSError as err:
            sys.exit(f"Cannot read --keep-names-file: {err}")
    options.keep_names = KNOWN_SINGLE_ACTS | {
        normalize_key(n) for n in keep_raw if n.strip() and not n.startswith("#")
    }

    alias_lines = list(options.alias)
    if options.aliases_file:
        try:
            alias_lines += Path(options.aliases_file).expanduser().read_text(
                encoding="utf-8").splitlines()
        except OSError as err:
            sys.exit(f"Cannot read --aliases-file: {err}")
    options.aliases = {}
    for line in alias_lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            sys.exit(f"Alias needs the form FROM=TO, got: {line!r}")
        source_name, target = (part.strip() for part in line.split("=", 1))
        if not source_name or not target:
            sys.exit(f"Alias needs the form FROM=TO, got: {line!r}")
        options.aliases[normalize_key(source_name)] = target

    options.extensions = AUDIO_EXTENSIONS
    if options.ext:
        options.extensions = {
            "." + e.strip().lstrip(".").lower() for e in options.ext.split(",") if e.strip()
        }
    options.min_bytes = int(options.min_size * 1024 * 1024)
    if options.duplicates_dir:
        options.duplicates_dir = Path(options.duplicates_dir).expanduser().resolve()

    CONFIG.strip_leading_the = options.strip_the
    CONFIG.recase = options.recase
    CONFIG.audio_only_hash = not options.exact_dupes
    return options


def confirm(options, message: str) -> bool:
    if options.dry_run or options.yes or not sys.stdin.isatty():
        return True
    return input(f"{message} [y/N] ").strip().lower() in ("y", "yes")


def transfer(track: Track, target: Path, options) -> None:
    if target.exists() and options.on_conflict == "overwrite":
        target.unlink()
    if options.move:
        shutil.move(str(track.path), str(target))
    elif options.hardlink:
        os.link(track.path, target)
    elif options.symlink:
        target.symlink_to(track.path)
    else:
        shutil.copy2(track.path, target)


def write_report(path: Path, rows: list[tuple[Track, Path, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["status", "artist", "artist_from", "album", "title",
                         "source", "destination", "bytes", "sha256"])
        for track, target, status in rows:
            writer.writerow([
                status, track.artist or "", track.artist_source, track.album or "",
                track.title or "", track.path,
                target if target else "", track.size, track.digest,
            ])


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    options = parse_args(argv)

    if not options.source.is_dir():
        sys.exit(f"Source directory not found: {options.source}")
    if options.destination == options.source:
        sys.exit("Source and destination must be different directories.")
    if options.source in options.destination.parents and not options.dry_run:
        print(f"Note: destination is inside the source; {options.destination.name} "
              "will be skipped while scanning.")

    say = (lambda *a, **k: None) if options.quiet else print
    progress = not options.quiet and sys.stdout.isatty()

    say(f"Scanning {options.source} ...")
    files = find_audio_files(options.source, options.destination, options)
    if not files:
        sys.exit("No audio files found.")
    say(f"Found {len(files)} audio file(s). Reading tags and hashing audio ...")

    # Anything already in the library, so repeat runs only add what is new.
    already_present: set[str] = set()
    if options.library_check and not options.no_dedupe and options.destination.is_dir():
        existing = find_audio_files(options.destination, None, options)
        if existing:
            say(f"Checking {len(existing)} file(s) already in {options.destination.name} ...")
            with ThreadPoolExecutor(max_workers=max(1, options.workers)) as pool:
                for digest in pool.map(safe_fingerprint, existing):
                    if digest:
                        already_present.add(digest)

    tracks: list[Track] = []
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, options.workers)) as pool:
        for done, (track, error) in enumerate(
            pool.map(lambda p: scan_file(p, options), files), start=1
        ):
            if track is not None:
                tracks.append(track)
            if error:
                errors.append(error)
            if progress and done % 100 == 0:
                print(f"  {done}/{len(files)}", end="\r", flush=True)
    if progress:
        print(" " * 40, end="\r")

    if not tracks:
        sys.exit("No readable audio files.")

    sources = resolve_artists(tracks, options)

    # de-duplicate on audio content
    duplicates: list[tuple[Track, Track]] = []
    skipped_existing = 0
    if options.no_dedupe:
        keepers = tracks
    else:
        by_digest: dict[str, list[Track]] = defaultdict(list)
        for track in tracks:
            by_digest[track.digest].append(track)
        keepers = []
        for digest, copies in by_digest.items():
            if digest in already_present:
                skipped_existing += len(copies)
                continue
            copies.sort(key=KEEP_RULES[options.keep])
            keepers.append(copies[0])
            duplicates.extend((extra, copies[0]) for extra in copies[1:])

    if not keepers:
        print(f"Nothing to do - all {len(tracks)} track(s) are already in {options.destination}.")
        return 0

    artists, albums = build_name_maps(keepers)

    say(f"{len(keepers)} unique track(s) across {len(artists)} artist(s)"
        + (f", {len(duplicates)} duplicate(s)" if duplicates else "") + ".")

    if options.verbose:
        say("\nHow artist names were decided:")
        labels = {
            "tag": "straight from the tags",
            "tag-split": "split off a collaboration (left side is a known artist here)",
            "library": "untagged, matched a known artist in the filename",
            "filename": "untagged, parsed 'Artist - Title' from the filename",
            "none": "no artist found -> " + options.others_name,
        }
        for source, count in sources.most_common():
            say(f"  {count:5}  {labels.get(source, source)}")
        say("")

    # plan
    taken: set[Path] = set()
    keepers.sort(key=lambda t: (
        artists.get(t.artist_key, "￿" + options.others_name).lower(),
        (albums.get((t.artist_key, t.album_key)) or options.unknown_album).lower(),
        t.disc_no or 0, t.track_no or 0, t.path.name.lower(),
    ))

    plan: list[tuple[Track, Path]] = []
    conflicts_skipped = 0
    for track in keepers:
        target = destination_for(track, artists, albums, options)
        if target.exists() or target in taken:
            if options.on_conflict == "skip":
                conflicts_skipped += 1
                continue
            if options.on_conflict == "rename":
                target = unique_path(target, taken)
        taken.add(target)
        plan.append((track, target))

    if options.duplicates_dir and duplicates:
        dup_plan = [
            (dup, unique_path(options.duplicates_dir / dup.path.name, taken))
            for dup, _ in duplicates
        ]
    else:
        dup_plan = []

    if options.dry_run:
        verb = "Would move" if options.move else "Would copy"
    elif options.move:
        verb = "Moved"
    elif options.hardlink:
        verb = "Linked"
    elif options.symlink:
        verb = "Symlinked"
    else:
        verb = "Copied"

    if options.move and not confirm(
        options, f"\nMove {len(plan)} file(s) out of {options.source}?"
    ):
        return 1
    if options.on_conflict == "overwrite" and not confirm(
        options, "Overwrite existing files in the destination?"
    ):
        return 1

    # execute
    moved = 0
    bytes_done = 0
    current_folder = None
    report_rows: list[tuple[Track, Path, str]] = []
    for track, target in plan + dup_plan:
        folder = target.parent
        if folder != current_folder:
            current_folder = folder
            try:
                say(f"\n{folder.relative_to(options.destination.parent)}/")
            except ValueError:
                say(f"\n{folder}/")
        say(f"  {target.name}")
        if options.dry_run:
            moved += 1
            bytes_done += track.size
            report_rows.append((track, target, "planned"))
            continue
        try:
            folder.mkdir(parents=True, exist_ok=True)
            transfer(track, target, options)
            moved += 1
            bytes_done += track.size
            report_rows.append((track, target, "ok"))
        except Exception as err:
            errors.append(f"{track.path}: {err}")
            report_rows.append((track, target, f"error: {err}"))
            say(f"    ! {err}")

    if options.report:
        for dup, _ in duplicates:
            if not any(dup is t for t, _, _ in report_rows):
                report_rows.append((dup, None, "duplicate"))
        try:
            write_report(Path(options.report).expanduser(), report_rows)
            print(f"\nReport written to {options.report}")
        except OSError as err:
            errors.append(f"report: {err}")

    others = sum(1 for t in keepers if not t.artist_key)
    guessed = sources["library"] + sources["filename"]

    print("\n" + "-" * 60)
    print(f"{verb:>12}: {moved} file(s), {human(bytes_done)}")
    print(f"{'Artists':>12}: {len(artists)}")
    if guessed:
        print(f"{'Guessed':>12}: {guessed} artist(s) recovered from filenames")
    if sources["tag-split"]:
        print(f"{'Split':>12}: {sources['tag-split']} collaboration(s) filed under the lead artist")
    if skipped_existing:
        print(f"{'Already in':>12}: {skipped_existing} track(s) skipped, already in the library")
    if others:
        print(f"{options.others_name:>12}: {others} track(s) with no artist")
    if conflicts_skipped:
        print(f"{'Conflicts':>12}: {conflicts_skipped} skipped (name already taken)")
    if duplicates:
        where = f"copied to {options.duplicates_dir}" if dup_plan else "left in place"
        print(f"{'Duplicates':>12}: {len(duplicates)} ({where})")
    if not options.quiet:
        counts = Counter(t.artist_key for t in keepers if t.artist_key)
        pairs = similar_artists(artists, counts)
        if pairs:
            print(f"{'Similar':>12}: {len(pairs)} artist folder(s) may be the same person:")
            for short, long in pairs[:6]:
                print(f"              {artists[short]!r} ({counts[short]}) vs "
                      f"{artists[long]!r} ({counts[long]})")
            if len(pairs) > 6:
                print(f"              ... and {len(pairs) - 6} more")
            print("              if any pair is one artist, merge it next run with:")
            print(f"              --alias '{artists[pairs[0][0]]}={artists[pairs[0][1]]}'")
    if errors:
        print(f"{'Errors':>12}: {len(errors)}")
        for line in errors[:15]:
            print(f"              {line}")
        if len(errors) > 15:
            print(f"              ... and {len(errors) - 15} more")
    if options.dry_run:
        print("\nDry run - nothing was written. Re-run without --dry-run to apply.")
    return 1 if errors and not moved else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit("\nInterrupted.")
