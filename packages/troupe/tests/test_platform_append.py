"""Durable appends (platform/files.py append_bytes; event-store design D4)."""

import tempfile
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from troupe.platform.files import append_bytes


def test_appending_creates_the_file_and_returns_its_size_before(tmp_path: Path) -> None:
    target = tmp_path / "segment.jsonl"
    assert append_bytes(target, b"one\n") == 0
    assert append_bytes(target, b"two\n") == 4
    assert target.read_bytes() == b"one\ntwo\n"


@given(st.lists(st.binary(max_size=200), max_size=10))
def test_appends_are_kept_byte_for_byte_with_line_feeds_untranslated(chunks: list[bytes]) -> None:
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / "segment.jsonl"
        for chunk in [b"a\nb\r\nc\n", *chunks]:
            append_bytes(target, chunk)
        assert target.read_bytes() == b"a\nb\r\nc\n" + b"".join(chunks)
