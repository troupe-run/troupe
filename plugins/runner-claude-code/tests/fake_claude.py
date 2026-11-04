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
- ``FAKE_CLAUDE_WAIT_MS``: how long to wait before writing its lines, so a cancel can arrive
  mid-run.
- ``FAKE_CLAUDE_WRITE``: ``path=content``, a file to write under its working directory, as an
  agent's tool would.
- ``FAKE_CLAUDE_HANG``: ``1`` to wait, after writing its lines, until it is stopped.
- ``FAKE_CLAUDE_EXIT``: the exit code, 0 by default.
- ``FAKE_CLAUDE_LEDGER``: a directory where it records itself before anything else, so a check can
  find a stand-in a test left running (reap-fake-claude design D2). It holds an exclusive lock on
  ``<pid>.lock`` there for as long as it runs, and writes ``<pid>.json`` with its pid, working
  directory and argv. The OS releases the lock when the process ends, however it ends, so a held
  lock means the stand-in is still running and the pid is still its own. ``install()`` writes the
  installing process's value into the shim, so it reaches the stand-in whatever environment the
  runner passes on. Before it has the lock, while it starts up, it's in the runner's process
  group or job, so it ends with the runner.

It exits 143 on SIGTERM without writing anything more, as the real CLI does.
"""

import contextlib
import json
import os
import shlex
import signal
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import IO

LEDGER = "FAKE_CLAUDE_LEDGER"

_held: IO[bytes] | None = None
"""The stand-in's own lock file, kept open (and so locked) until the process ends."""


def install(bin_dir: Path, settings: Mapping[str, str] | None = None) -> Path:
    """Put a ``claude`` that runs this stand-in in ``bin_dir``, and return it: an executable
    script on POSIX, which execs Python so the pid is Claude Code's, and ``claude.cmd`` on
    Windows. ``settings`` (``FAKE_CLAUDE_*`` variables) are set by the shim itself, for runs whose
    environment troupe chooses, such as perform's."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    here = Path(__file__).resolve()
    settings = dict(settings or {})
    if ledger := os.environ.get(LEDGER):
        settings.setdefault(LEDGER, ledger)
    if sys.platform == "win32":
        shim = bin_dir / "claude.cmd"
        lines = [f'@set "{name}={value}"' for name, value in settings.items()]
        # The base interpreter, not the venv's python.exe, a launcher that runs the real one as a
        # child in a job of its own: the recorded pid is then Claude Code's stand-in itself.
        lines.append(f'@"{getattr(sys, "_base_executable", sys.executable)}" "{here}" %*')
        shim.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    else:
        shim = bin_dir / "claude"
        lines = [
            "#!/bin/sh",
            *(f"export {name}={shlex.quote(value)}" for name, value in settings.items()),
        ]
        lines.append(f'exec "{sys.executable}" "{here}" "$@"')
        shim.write_text("\n".join(lines) + "\n", encoding="utf-8")
        shim.chmod(0o755)
    return shim


if sys.platform == "win32":
    import msvcrt

    def _try_lock(fd: int) -> bool:
        """Take an exclusive lock on the file's first byte without waiting: False if it's held."""
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def _unlock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

    _STOP = signal.SIGTERM  # os.kill on Windows terminates the process for any other signal

else:
    import fcntl

    def _try_lock(fd: int) -> bool:
        """Take an exclusive lock on the file without waiting: False if it's held."""
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)

    _STOP = signal.SIGKILL


def _register(ledger: Path) -> None:
    """Lock ``<pid>.lock`` in the ledger for the rest of this process's life, then describe this
    stand-in in ``<pid>.json``."""
    global _held
    pid = os.getpid()
    held = (ledger / f"{pid}.lock").open("a+b")
    if not _try_lock(held.fileno()):
        held.close()
        raise RuntimeError(f"the stand-in claude's ledger entry {pid}.lock is locked by another")
    _held = held
    _write_record(
        str(ledger / f"{pid}.json"), {"pid": pid, "cwd": os.getcwd(), "argv": sys.argv[1:]}
    )


def ledger_entries(ledger: Path) -> set[int]:
    """The pids of every stand-in recorded in ``ledger``, ended or not."""
    return {int(path.stem) for path in ledger.glob("*.lock") if path.stem.isdigit()}


def forget(ledger: Path, pid: int) -> None:
    """Remove a stand-in's entry once it's been checked, so a later process with its pid is new."""
    for suffix in (".lock", ".json"):
        with contextlib.suppress(OSError):  # gone already, or (Windows) still open
            (ledger / f"{pid}{suffix}").unlink()


def still_running(ledger: Path, pid: int) -> bool:
    """Whether the stand-in recorded as ``pid`` still holds its lock, so is still running.

    A pid the OS has since given to another process reads as ended: only the stand-in's own lock
    counts, never whether some process has the pid."""
    try:
        fd = os.open(ledger / f"{pid}.lock", os.O_RDWR)
    except FileNotFoundError:
        return False
    try:
        if _try_lock(fd):
            _unlock(fd)
            return False
        return True
    finally:
        os.close(fd)


def described(ledger: Path, pid: int) -> dict[str, object] | None:
    """What the stand-in recorded as ``pid`` wrote about itself, or None before it has."""
    try:
        record: dict[str, object] = json.loads((ledger / f"{pid}.json").read_text("utf-8"))
    except (OSError, ValueError):
        return None
    return record


def stop(pid: int) -> None:
    """Kill ``pid``. Call it only once ``still_running`` has said the pid is still the stand-in."""
    with contextlib.suppress(OSError):  # it ended in the meantime
        os.kill(pid, _STOP)


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
    if ledger := os.environ.get(LEDGER):
        _register(Path(ledger))
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
        sys.stderr.buffer.write(stderr.encode("utf-8"))  # bytes, so Windows adds no \r
        sys.stderr.flush()
    if write := os.environ.get("FAKE_CLAUDE_WRITE"):
        relative, _, content = write.partition("=")
        target = Path.cwd() / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    time.sleep(int(os.environ.get("FAKE_CLAUDE_WAIT_MS", "0")) / 1000)
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
