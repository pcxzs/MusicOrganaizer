"""Duplicate detection: the hash must cover the audio and ignore the tags.

Real encoders aren't available in CI, so these build byte-exact container
structures by hand - which is what the span parsers actually read.
"""
import pytest

import MusicOrganizer as org


def syncsafe(size):
    return bytes((size >> shift) & 0x7F for shift in (21, 14, 7, 0))


def write_mp3(path, payload, id3v2_size=100, id3v1=False, apev2=False):
    data = b"ID3\x03\x00\x00" + syncsafe(id3v2_size) + b"\xAA" * id3v2_size + payload
    if apev2:
        body = b"\xCC" * 40
        data += body + b"APETAGEX" + b"\x00" * 4 + (len(body) + 32).to_bytes(4, "little") \
            + b"\x00" * 4 + b"\x00" * 12
    if id3v1:
        data += b"TAG" + b"\xBB" * 125
    path.write_bytes(data)
    return path


def write_flac(path, payload, block_sizes=(34,)):
    data = b"fLaC"
    for index, size in enumerate(block_sizes):
        last = 0x80 if index == len(block_sizes) - 1 else 0x00
        data += bytes([last | index]) + size.to_bytes(3, "big") + b"\xAA" * size
    path.write_bytes(data + payload)
    return path


AUDIO = b"the actual audio frames" * 100


def test_mp3_hash_ignores_tag_size(tmp_path):
    a = write_mp3(tmp_path / "a.mp3", AUDIO, id3v2_size=50)
    b = write_mp3(tmp_path / "b.mp3", AUDIO, id3v2_size=4000)
    assert a.stat().st_size != b.stat().st_size
    assert org.fingerprint(a) == org.fingerprint(b)


def test_mp3_hash_ignores_trailing_tags(tmp_path):
    a = write_mp3(tmp_path / "a.mp3", AUDIO)
    b = write_mp3(tmp_path / "b.mp3", AUDIO, id3v1=True)
    c = write_mp3(tmp_path / "c.mp3", AUDIO, id3v1=True, apev2=True)
    assert org.fingerprint(a) == org.fingerprint(b) == org.fingerprint(c)


def test_mp3_hash_detects_different_audio(tmp_path):
    a = write_mp3(tmp_path / "a.mp3", AUDIO)
    b = write_mp3(tmp_path / "b.mp3", AUDIO + b"extra")
    assert org.fingerprint(a) != org.fingerprint(b)


def test_flac_hash_ignores_metadata_blocks(tmp_path):
    a = write_flac(tmp_path / "a.flac", AUDIO, block_sizes=(34,))
    b = write_flac(tmp_path / "b.flac", AUDIO, block_sizes=(34, 500, 1200))
    assert a.stat().st_size != b.stat().st_size
    assert org.fingerprint(a) == org.fingerprint(b)


def test_flac_hash_detects_different_audio(tmp_path):
    a = write_flac(tmp_path / "a.flac", AUDIO)
    b = write_flac(tmp_path / "b.flac", AUDIO + b"x")
    assert org.fingerprint(a) != org.fingerprint(b)


def test_exact_dupes_compares_whole_file(tmp_path):
    a = write_mp3(tmp_path / "a.mp3", AUDIO, id3v2_size=50)
    b = write_mp3(tmp_path / "b.mp3", AUDIO, id3v2_size=4000)
    org.CONFIG.audio_only_hash = False
    assert org.fingerprint(a) != org.fingerprint(b)


def test_unknown_format_falls_back_to_whole_file(tmp_path):
    a = tmp_path / "a.ogg"
    b = tmp_path / "b.ogg"
    a.write_bytes(AUDIO)
    b.write_bytes(AUDIO)
    assert org.fingerprint(a) == org.fingerprint(b)


def test_truncated_files_do_not_raise(tmp_path):
    for name, blob in [("t.mp3", b"ID3"), ("t.flac", b"fLaC\x80"), ("t.ogg", b"")]:
        (tmp_path / name).write_bytes(blob)
        org.fingerprint(tmp_path / name)   # must not raise


def test_safe_fingerprint_returns_none_for_missing(tmp_path):
    assert org.safe_fingerprint(tmp_path / "nope.mp3") is None


@pytest.mark.parametrize("rule", list(org.KEEP_RULES))
def test_keep_rules_are_total_orders(rule):
    from conftest import make_track
    tracks = [make_track("A", name="a.mp3", size=10, tag_count=1),
              make_track("A", name="b.mp3", size=20, tag_count=5)]
    assert sorted(tracks, key=org.KEEP_RULES[rule])
