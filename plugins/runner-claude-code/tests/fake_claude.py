"""A stand-in for ``claude`` that the tests put first on the runner's PATH (design D12).

It records what it was given, then writes native lines as Claude Code would. Standard library
only, so core's tests can install it by path too. Set in its environment (the runner passes its
own environment on):

- ``FAKE_CLAUDE_RECORD``: where to write, as JSON, its argv, standard input, working directory,
  environment, pid, and what the files named by ``--append-system-prompt-file`` and ``--settings``
  hold. The pid is written first, before standard input is read, so a test can
  find the process while it runs.
- ``FAKE_CLAUDE_FIXTURE``: a fixture's ``recording.jsonl``, whose native lines it writes, or a
  ``.txt`` file whose lines it writes as they are.
- ``FAKE_CLAUDE_STDERR``: text to write to standard error.
- ``FAKE_CLAUDE_HANG``: ``1`` to wait, after writing its lines, until it is stopped.
- ``FAKE_CLAUDE_EXIT``: the exit code, 0 by default.

It exits 143 on SIGTERM without writing anything more, as the real CLI does.
"""

import json
import os
import signal
import sys
import time
from pathlib import Path


def install(bin_dir: Path) -> Path:
    """Put a ``claude`` that runs this stand-in in ``bin_dir``, and return it: an executable
    script on POSIX, which execs Python so the pid is Claude Code's, and ``claude.cmd`` on
    Windows."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    here = Path(__file__).resolve()
    if sys.platform == "win32":
        shim = bin_dir / "claude.cmd"
        shim.write_text(f'@"{sys.executable}" "{here}" %*\r\n', encoding="utf-8")
    else:
        shim = bin_dir / "claude"
        shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{here}" "$@"\n', encoding="utf-8")
        shim.chmod(0o755)
    return shim


def _write_record(path: str, record: dict[str, object]) -> None:
    """Replace the record at once, so a test never reads half of it."""
    partial = Path(f"{path}.partial")
    partial.write_text(json.dumps(record), encoding="utf-8")
    for _ in range(200):
        try:
            os.replace(partial, path)
            return
        except PermissionError:  # Windows: a test is reading the record at this moment
            time.sleep(0.01)
    os.replace(partial, path)


def _lines(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".txt":
        return text.splitlines()
    entries = [json.loads(line) for line in text.splitlines()]
    return [entry["transcript"] for entry in entries if "transcript" in entry]


def _named_files(argv: list[str]) -> dict[str, str]:
    """What the files the runner names on the command line hold, by flag, read while it runs."""
    files: dict[str, str] = {}
    for flag in ("--append-system-prompt-file", "--settings"):
        if flag in argv:
            files[flag] = Path(argv[argv.index(flag) + 1]).read_text(encoding="utf-8")
    return files


def main() -> None:
    signal.signal(signal.SIGTERM, lambda *_: os._exit(143))
    record_path = os.environ.get("FAKE_CLAUDE_RECORD")
    record: dict[str, object] = {"pid": os.getpid()}
    if record_path:
        _write_record(record_path, record)
    stdin = sys.stdin.buffer.read()
    record.update(
        {
            "argv": sys.argv[1:],
            "stdin": stdin.decode("utf-8", errors="replace"),
            "cwd": os.getcwd(),
            "env": dict(os.environ),
            "files": _named_files(sys.argv[1:]),
        }
    )
    if record_path:
        _write_record(record_path, record)
    if stderr := os.environ.get("FAKE_CLAUDE_STDERR"):
        sys.stderr.write(stderr)
        sys.stderr.flush()
    if fixture := os.environ.get("FAKE_CLAUDE_FIXTURE"):
        out = sys.stdout.buffer
        for line in _lines(Path(fixture)):
            out.write(line.encode("utf-8") + b"\n")
            out.flush()
    if os.environ.get("FAKE_CLAUDE_HANG") == "1":
        while True:
            time.sleep(0.05)
    sys.exit(int(os.environ.get("FAKE_CLAUDE_EXIT", "0")))


if __name__ == "__main__":
    main()
