# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.9.0] - 2026-08-22

First public release.

### Added
- Sorts a library into `Artist/Album/<track> - <title>.<ext>`.
- Reads tags from mp3, flac, m4a, ogg, opus, wma, wav, aiff, ape, wv, mpc and other
  formats mutagen supports, with raw ID3/ASF fallbacks.
- Folds inconsistent artist spellings (case, accents, punctuation, leading "The") into a
  single folder and votes on the best spelling to use as its name.
- Files collaborations under the lead artist, with guards for names that only look like
  collaborations (`AC/DC`, `Tyler, The Creator`, `Crosby, Stills & Nash`).
- Splits `A & B` only when one side is an artist already present in the library.
- Recovers artists from filenames for untagged files, matched against the same registry.
- Detects duplicates by hashing the audio payload with tags stripped, so the same song
  tagged two different ways is recognized.
- Skips tracks already present in the destination, making re-runs safe and incremental.
- Copy, move, hardlink and symlink modes; `--dry-run`; CSV reporting.
- 40 command-line switches covering layout, file selection, name handling, duplicate
  policy and output.
