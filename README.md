# Music Organizer

Sort a messy music folder into `Artist/Album/` — merging inconsistent name spellings,
filing collaborations under the lead artist, and removing duplicates by comparing the
**audio itself** rather than the tags.

[![CI](https://github.com/USERNAME/music-organizer/actions/workflows/ci.yml/badge.svg)](https://github.com/USERNAME/music-organizer/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

```
before/                              after/
├── 01 - Billie Eilish - Therefore    ├── Billie Eilish/
├── 24K Magic   Bruno Mars.mp3        │   └── Happier Than Ever/
├── gracie abrams - Amelie.flac       │       └── 03 - Therefore I Am.flac
├── GRACIE ABRAMS - Difficult.flac    ├── Bruno Mars/
├── Halsey – Not Afraid Anymore.mp3   │   └── Unknown Album/
├── Beyoncé, JAY-Z - Apeshit.mp3      │       └── 24K Magic.mp3
└── au_uu_SzH34yR2.mp3                ├── Gracie Abrams/
                                      │   └── Good Riddance/
                                      │       ├── 05 - Amelie.flac
                                      │       └── 07 - Difficult.flac
                                      ├── Halsey/ ...
                                      ├── Beyoncé/ ...
                                      └── Others/
                                          └── au_uu_SzH34yR2.mp3
```

## Install

```bash
git clone https://github.com/USERNAME/music-organizer.git
cd music-organizer
pip install -r requirements.txt
```

Or install it as a command:

```bash
pip install .          # gives you `music-organizer`
```

The only dependency is [mutagen](https://mutagen.readthedocs.io/). On Arch/Manjaro,
where pip is externally managed, use `sudo pacman -S python-mutagen`.

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

**Inconsistent spellings.** `Gracie Abrams`, `gracie abrams` and `GRACIE ABRAMS` land in
one folder. Names are folded to a comparison key — case, accents, punctuation and a
leading "The" are ignored — so `Beyoncé`/`Beyonce` and `The Beatles`/`Beatles` merge too.
The folder name is then voted on across every spelling seen, preferring properly
capitalized ones. Short all-caps names like `MGMT`, `SZA` and `AC/DC` are recognized as
acronyms and left alone.

**Collaborations.** `Adele feat. Someone` and `Beyoncé, JAY-Z` file under the first
artist. Names that merely look like collaborations survive intact, because the splitter
requires whitespace around a slash (`AC/DC`), refuses to split a one-word name before an
article (`Tyler, The Creator`), and carries a list of known single acts.

`&` is the hard case — `Billie Eilish & Khalid` should split but `Milk & Bone` should
not, and no fixed rule gets both. So the tool builds a registry of artists your library
demonstrably contains and splits only when one side is someone it already knows. On a
1,639-file test library this split 9 collaborations correctly and left `Milk & Bone`,
`Drum & Lace`, `Colin & Caroline` and `Hillsong Young & Free` untouched.

**Untagged files.** Files with no artist tag are still often named after one. The same
registry recovers them, and knowing the artist also settles whether a name is
`Artist - Title` or `Title - Artist`. On that test library this rescued 17 of 32 files
that would otherwise have been dumped in `Others`.

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
| `--keep-the` | Keep `The Beatles` and `Beatles` separate |
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
python MusicOrganizer.py ~/Music ~/Sorted --alias "Zhavia=Zhavia Ward"

# Pull duplicates aside for review instead of ignoring them
python MusicOrganizer.py ~/Music ~/Sorted --duplicates-dir ~/Dupes
```

## Limitations

- **Re-encodes aren't caught.** A 320 kbps and a 192 kbps copy of one song have different
  audio bytes and count as two tracks. Real acoustic fingerprinting (Chromaprint/AcoustID)
  would be needed, which is a much heavier dependency.
- **Guessing from filenames can be wrong.** `Your_Phone_Ringing_-_Funny_Asian.mp3` becomes
  an artist called "Your Phone Ringing". Use `--filename-guess library` to only trust
  names already in your collection, or `off` to disable it.
- **Similar folder names are reported, never merged.** `Zhavia`/`Zhavia Ward` is probably
  one artist; `Adele`/`Adele Roberts` is definitely two. The tool lists candidates and
  leaves the call to you — see `--alias`.
- **Tags are read, never written.** This tool does not fix your metadata.

## Development

```bash
pip install -r requirements-dev.txt
pytest -q          # 138 tests, no network or media files required
ruff check .
```

Tests build container structures byte-by-byte rather than shipping audio fixtures, so the
suite runs in well under a second and needs no encoder installed.

## License

MIT — see [LICENSE](LICENSE).
