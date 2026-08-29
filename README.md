# Music Organizer

Sort a messy music folder into `Artist/Album/` — merging inconsistent name spellings,
filing collaborations under the lead artist, and removing duplicates by comparing the
**audio itself** rather than the tags.

[![CI](https://github.com/pcxzs/music-organizer/actions/workflows/ci.yml/badge.svg)](https://github.com/pcxzs/music-organizer/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

```
before/                                   after/
├── 01 - Nova Kane - Low Tide.flac        ├── Nova Kane/
├── nova kane - Overtime.flac             │   └── Night Signals/
├── NOVA KANE - Second Wind.flac          │       ├── 01 - Low Tide.flac
├── Night Drive   Rex Miller.mp3          │       ├── 02 - Overtime.flac
├── Vera Cole – Paper Boats.mp3           │       └── 03 - Second Wind.flac
├── Renée Adair, Rex Miller - Dusk.mp3    ├── Rex Miller/
└── zz_7fQ2b91k.mp3                       │   └── Unknown Album/
                                          │       └── Night Drive.mp3
                                          ├── Vera Cole/ ...
                                          ├── Renée Adair/ ...
                                          └── Others/
                                              └── zz_7fQ2b91k.mp3
```

## Install

```bash
git clone https://github.com/pcxzs/music-organizer.git
cd music-organizer
pip install -r requirements.txt
```

Or install it as a command:

```bash
pip install .          # gives you `music-organizer`
```

The only dependency is [mutagen](https://mutagen.readthedocs.io/). On distributions
where the system Python is externally managed and pip refuses to install into it, use a
virtualenv or the distribution's own package (`python-mutagen`, `python3-mutagen`).

## Usage

```bash
python MusicOrganizer.py ~/Music ~/MusicSorted --dry-run   # preview, changes nothing
python MusicOrganizer.py ~/Music ~/MusicSorted             # copy into place
```

Run it with no arguments and it prompts for the two folders. **It copies by default** —
your source library is never modified unless you pass `--move`.

Re-running is safe and cheap: the destination is fingerprinted first, so a second run
only adds genuinely new tracks. Point it at a downloads folder as often as you like.

## What it handles

**Inconsistent spellings.** `Nova Kane`, `nova kane` and `NOVA KANE` land in one folder.
Names are folded to a comparison key — case, accents, punctuation and a leading "The" are
ignored — so `Renée`/`Renee` and `The Wildfires`/`Wildfires` merge too. The folder name is
then voted on across every spelling seen, preferring properly capitalized ones. Short
all-caps names like `MGMT`, `ABBA` and `AC/DC` are recognized as acronyms and left alone.

**Collaborations.** `Artist A feat. Artist B` and `Artist A, Artist B` file under the
first artist. Names that merely look like collaborations survive intact, because the
splitter requires whitespace around a slash (`AC/DC`), refuses to split a one-word name
before an article (`Tyler, The Creator`), and carries a list of known single acts.

`&` is the hard case: it joins two artists on a collaboration about as often as it joins
two words inside one band's name (`Simon & Garfunkel`, `Iron & Wine`), and no fixed rule
gets both. So the tool builds a registry of the artists your library demonstrably
contains, and splits `A & B` only when one of the two sides also appears on its own
somewhere in the collection. A duo whose halves are never seen alone stays whole.

**Untagged files.** Files with no artist tag are still often named after one. The same
registry recovers them, and matching against it also settles whether a filename reads
`Artist - Title` or `Title - Artist` — otherwise a plain dash split would file half the
library under its song titles. `--filename-guess library` restricts recovery to names the
registry already contains; `off` disables it.

**Duplicates.** The fingerprint is a SHA-256 of the *audio payload*: ID3v2/ID3v1/APEv2
headers are parsed off MP3s and metadata blocks off FLACs first. The same song tagged two
different ways still hashes identically. The best-tagged copy is kept; see `--keep`.

**Formats.** mp3, flac, m4a, ogg, opus, wma, wav, aiff, ape, wv, mpc and more — anything
mutagen reads, with raw ID3/ASF fallbacks for containers its "easy" interface skips.

## Options

Run `--help` for the full grouped listing. The ones worth knowing:

### What to do with the files
| Switch | Effect |
| --- | --- |
| `--move` | Move instead of copy (asks first; `--yes` skips) |
| `--hardlink` / `--symlink` | Organize without using extra disk space |
| `-n`, `--dry-run` | Print the plan, change nothing |
| `--on-conflict {rename,skip,overwrite}` | When the target name is taken (default `rename`) |

### Folder and file naming
| Switch | Effect |
| --- | --- |
| `--layout {artist/album,artist/year-album,artist,flat}` | Folder structure |
| `--others-name NAME` | Folder for unidentifiable tracks (default `Others`) |
| `--unknown-album NAME` | Folder for tracks with no album (default `Unknown Album`) |
| `--singles-in-artist-root` | Put album-less tracks straight in the artist folder |
| `--no-track-numbers` | Don't prefix filenames with the track number |
| `--artist-in-filename` | Include the artist in the filename |
| `--keep-filenames` | Keep original filenames, only sort into folders |
| `--max-name-length N` | Truncate names (default 120) |

### Which files
| Switch | Effect |
| --- | --- |
| `--ext mp3,flac` | Only these extensions |
| `--exclude GLOB` | Skip matching files/folders (repeatable) |
| `--min-size MB` | Skip files below this size |
| `--follow-symlinks` | Follow symlinked directories |

### Artist names
| Switch | Effect |
| --- | --- |
| `--filename-guess {off,library,full}` | How hard to guess artists from filenames (default `full`) |
| `--split-ampersand` | Always split `A & B`, even when B is unknown |
| `--split-x` | With the above, also split `A x B` |
| `--no-smart-split` | Never split `A & B` |
| `--keep-name NAME` / `--keep-names-file F` | Never split these names |
| `--alias "FROM=TO"` / `--aliases-file F` | File one artist under another |
| `--prefer-artist-tag` | Trust `artist` over `albumartist` |
| `--keep-the` | Treat a leading `The` as significant, keeping it a separate folder |
| `--no-recase` | Use names exactly as tagged |

### Duplicates
| Switch | Effect |
| --- | --- |
| `--no-dedupe` | Copy duplicates too |
| `--duplicates-dir DIR` | Collect duplicates instead of leaving them behind |
| `--exact-dupes` | Compare whole files, so different tags count as different |
| `--keep {tags,largest,smallest,first}` | Which copy survives (default `tags`) |
| `--no-library-check` | Don't skip tracks already in the destination |

### Output
| Switch | Effect |
| --- | --- |
| `-q`, `--quiet` / `-v`, `--verbose` | Less / more detail |
| `--report FILE` | Write the full plan to CSV |
| `--workers N` | Parallel readers while scanning |

## Recipes

```bash
# Conservative first pass: never invent an artist that isn't already in your library
python MusicOrganizer.py ~/Music ~/Sorted --filename-guess library

# Audit before committing: full plan as a spreadsheet, nothing written
python MusicOrganizer.py ~/Music ~/Sorted --dry-run --report plan.csv

# A browsable view of a library you don't want to duplicate on disk
python MusicOrganizer.py ~/Music ~/ByArtist --hardlink --layout artist

# Merge two spellings the tool flagged as possibly-the-same
python MusicOrganizer.py ~/Music ~/Sorted --alias "Nova=Nova Kane"

# Pull duplicates aside for review instead of ignoring them
python MusicOrganizer.py ~/Music ~/Sorted --duplicates-dir ~/Dupes
```

## Limitations

- **Re-encodes aren't caught.** A 320 kbps and a 192 kbps copy of one song have different
  audio bytes and count as two tracks. Real acoustic fingerprinting (Chromaprint/AcoustID)
  would be needed, which is a much heavier dependency.
- **Guessing from filenames can be wrong.** `Rain_Sounds_-_8_Hours.mp3` becomes an artist
  called "Rain Sounds". Use `--filename-guess library` to only trust names already in your
  collection, or `off` to disable it.
- **Similar folder names are reported, never merged.** A short name and a longer one built
  from it are often one artist and just as often two, and nothing in the tags says which.
  The tool lists the candidate pairs and leaves the call to you — see `--alias`.
- **Tags are read, never written.** This tool does not fix your metadata.

## Development

```bash
pip install -r requirements-dev.txt
pytest -q          # 136 tests, no network or media files required
ruff check .
```

Tests build container structures byte-by-byte rather than shipping audio fixtures, so the
suite runs in well under a second and needs no encoder installed.

## License

MIT — see [LICENSE](LICENSE).
