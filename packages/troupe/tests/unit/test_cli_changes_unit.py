"""Writing troupe diff's output to a byte stream passes the captured bytes through unchanged, adding
no newline and translating no line ending (spec: cli, run-workspaces; worktree-stage design D6).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_cli_changes.py."""

import io


def test_writing_the_diff_to_a_byte_stream_adds_and_translates_nothing() -> None:
    from troupe.cli.commands import _write_exactly

    raw = io.BytesIO()

    class Bytes(io.StringIO):
        buffer = raw

    stream = Bytes()
    _write_exactly(b"line\r\nno newline at the end \xe9", stream)
    assert raw.getvalue() == b"line\r\nno newline at the end \xe9"
    assert stream.getvalue() == ""
