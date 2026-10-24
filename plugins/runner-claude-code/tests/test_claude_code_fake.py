"""The stand-in claude writes each fixture's native lines byte for byte (task 7.1)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from claude_harness import FIXTURES, recording, wait_for_record
from fake_claude import install

NAMES = sorted(path.name for path in FIXTURES.iterdir() if path.is_dir())


@pytest.mark.parametrize("name", NAMES)
def test_the_stand_in_writes_a_fixtures_native_lines_byte_for_byte(
    name: str, tmp_path: Path
) -> None:
    shim = install(tmp_path / "bin")
    record = tmp_path / "record.json"
    env = {
        **os.environ,
        "FAKE_CLAUDE_FIXTURE": str(FIXTURES / name / "recording.jsonl"),
        "FAKE_CLAUDE_RECORD": str(record),
    }
    done = subprocess.run(
        [str(shim), "-p", "--setting-sources", ""],
        input=b"say hi",
        capture_output=True,
        env=env,
        cwd=tmp_path,
        check=False,
        timeout=60,
    )
    native = [line["transcript"] for line in recording(name) if "transcript" in line]
    assert done.stdout == b"".join(line.encode("utf-8") + b"\n" for line in native)
    seen = json.loads(record.read_text(encoding="utf-8"))
    assert seen["argv"] == ["-p", "--setting-sources", ""]
    assert seen["stdin"] == "say hi"
    assert done.returncode == 0


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no SIGTERM to send")
def test_the_stand_in_exits_143_on_sigterm_as_claude_code_does(tmp_path: Path) -> None:
    import signal

    shim = install(tmp_path / "bin")
    record = tmp_path / "record.json"
    env = {**os.environ, "FAKE_CLAUDE_HANG": "1", "FAKE_CLAUDE_RECORD": str(record)}
    process = subprocess.Popen([str(shim)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env)
    assert process.stdin is not None
    process.stdin.close()
    assert wait_for_record(record, "argv")["pid"] == process.pid
    process.send_signal(signal.SIGTERM)
    assert process.wait(timeout=30) == 143
