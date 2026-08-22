"""End-to-end runs of main() against a temporary library."""
import csv

import pytest
from test_fingerprint import AUDIO, write_mp3

import MusicOrganizer as org


@pytest.fixture
def library(tmp_path):
    src = tmp_path / "src"
    (src / "nested").mkdir(parents=True)
    write_mp3(src / "one.mp3", AUDIO, id3v2_size=999)          # the better-tagged copy
    write_mp3(src / "two.mp3", AUDIO * 2)
    write_mp3(src / "nested" / "copy-of-one.mp3", AUDIO, id3v2_size=10)   # same audio, fewer tags
    (src / "cover.jpg").write_bytes(b"not audio")
    return src, tmp_path / "dst"


def run(*argv):
    return org.main([str(a) for a in argv])


def audio_files(root):
    return sorted(p.name for p in root.rglob("*.mp3"))


def test_copies_and_dedupes(library, capsys):
    src, dst = library
    assert run(src, dst) == 0
    assert audio_files(dst) == ["one.mp3", "two.mp3"]        # the retagged copy is a duplicate
    assert "Duplicates" in capsys.readouterr().out
    assert (src / "one.mp3").exists()                        # copy leaves the source alone


def test_non_audio_is_ignored(library):
    src, dst = library
    run(src, dst)
    assert not list(dst.rglob("*.jpg"))


def test_dry_run_writes_nothing(library):
    src, dst = library
    assert run(src, dst, "--dry-run") == 0
    assert not dst.exists()


def test_rerun_is_a_no_op(library, capsys):
    src, dst = library
    run(src, dst)
    before = {p: p.stat().st_mtime_ns for p in dst.rglob("*")}
    run(src, dst)
    assert {p: p.stat().st_mtime_ns for p in dst.rglob("*")} == before
    assert "already in" in capsys.readouterr().out.lower()


def test_move_empties_the_source(library):
    src, dst = library
    run(src, dst, "--move", "--yes")
    assert not (src / "one.mp3").exists()
    assert (src / "nested" / "copy-of-one.mp3").exists()   # duplicates are left behind


def test_duplicates_dir(library):
    src, dst = library
    run(src, dst, "--duplicates-dir", str(dst / "_Dupes"))
    assert audio_files(dst / "_Dupes") == ["copy-of-one.mp3"]


def test_no_dedupe_keeps_everything(library):
    src, dst = library
    run(src, dst, "--no-dedupe")
    assert len(audio_files(dst)) == 3


def test_hardlink_shares_an_inode(library):
    src, dst = library
    run(src, dst, "--hardlink")
    assert (dst / "Others" / "one.mp3").stat().st_ino == (src / "one.mp3").stat().st_ino


def test_symlink_points_back(library):
    src, dst = library
    run(src, dst, "--symlink")
    assert (dst / "Others" / "one.mp3").resolve() == (src / "one.mp3").resolve()


def test_on_conflict_skip(library, capsys):
    src, dst = library
    run(src, dst)
    run(src, dst, "--no-library-check", "--on-conflict", "skip")
    assert "Conflicts" in capsys.readouterr().out
    assert audio_files(dst) == ["one.mp3", "two.mp3"]


def test_report_lists_every_track(library, tmp_path):
    src, dst = library
    report = tmp_path / "plan.csv"
    run(src, dst, "--report", str(report))
    rows = list(csv.DictReader(report.open()))
    assert {r["status"] for r in rows} == {"ok", "duplicate"}
    assert len(rows) == 3


def test_ext_filter(library):
    src, dst = library
    with pytest.raises(SystemExit):          # nothing matches, so there is no work
        run(src, dst, "--ext", "flac")
    assert not dst.exists()


def test_exclude_glob(library):
    src, dst = library
    run(src, dst, "--exclude", "nested", "--exclude", "two.mp3")
    assert audio_files(dst) == ["one.mp3"]


def test_min_size(library):
    src, dst = library
    with pytest.raises(SystemExit):          # 10 MB - everything here is tiny
        run(src, dst, "--min-size", "10")
    assert not dst.exists()


def test_empty_and_corrupt_files_are_reported_not_fatal(library, capsys):
    src, dst = library
    (src / "empty.mp3").write_bytes(b"")
    (src / "junk.mp3").write_bytes(b"\x00\x01\x02")
    assert run(src, dst) == 0
    assert "empty file" in capsys.readouterr().out


def test_source_must_exist(tmp_path):
    with pytest.raises(SystemExit):
        run(tmp_path / "missing", tmp_path / "dst")


def test_source_and_destination_must_differ(library):
    src, _ = library
    with pytest.raises(SystemExit):
        run(src, src)


def test_destination_inside_source_is_skipped(library):
    src, _ = library
    run(src, src / "sorted")
    assert (src / "sorted").exists()
    run(src, src / "sorted")              # must not re-ingest its own output
    assert len(audio_files(src / "sorted")) == 2
