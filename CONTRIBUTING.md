# Contributing

Bug reports and pull requests are welcome.

## Getting set up

```bash
pip install -r requirements-dev.txt
pytest -q
ruff check .
```

## The most useful contribution

Artist names that get filed wrong. The splitting rules are heuristics tuned against real
libraries, and every library is messy in its own way. If you find a name that lands in the
wrong folder:

1. Add it to the parametrized cases in `tests/test_names.py` with the folder you expected.
2. Run `pytest -q` and watch it fail.
3. Fix the rule, or — if the name is genuinely a one-off — add it to
   `KNOWN_SINGLE_ACTS_RAW` in `MusicOrganizer.py`.

Entries in that set are written naturally (`"Earth, Wind & Fire"`); they are folded
through `normalize_key()` at import, so you don't need to match its output format.

## Guidelines

- No new runtime dependencies. mutagen is the only one, and that's worth keeping.
- Tests must not require network access, an audio encoder, or committed media files.
  `tests/test_fingerprint.py` shows how to build container structures by hand.
- Anything that writes to disk needs a `--dry-run` path that doesn't.
- Keep lines under 100 characters.
