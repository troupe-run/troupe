"""troupe's git adapter for the VCS port (spec: vcs; event-store design D1, D4, D11).

Every git command runs through troupe.core.commands with GIT_ENVIRONMENT, so git sees its own
config, credentials and SSH agent, but never a hook's GIT_DIR or GIT_INDEX_FILE, and nothing else of
troupe's environment. Only local commands run (symbolic-ref, rev-parse, ls-files, ls-tree, config),
so git never starts a credential helper or ssh.
"""

import os
import shlex
from collections.abc import Hashable, Mapping, Sequence
from pathlib import Path

from troupe.core.commands import run_command
from troupe.core.errors import TroupeError
from troupe.platform.processes import Completed, EnvironmentPolicy, ProcessWaitCallback
from troupe_vcs_git import defaults

# Exit status 1 means "no answer" for these, not failure: an unborn or detached HEAD, a missing key.
_NO_ANSWER = 1


class GitAdapter:
    """The VCS port, read through git in the theatre's directory."""

    def __init__(
        self,
        theatre: Path,
        *,
        policy: EnvironmentPolicy = defaults.GIT_ENVIRONMENT,
        timeout: float = defaults.GIT_TIMEOUT_SECONDS,
        announce_after: float = defaults.GIT_ANNOUNCE_AFTER_SECONDS,
        max_output_bytes: int = defaults.GIT_MAX_OUTPUT_BYTES,
        source: Mapping[str, str] | None = None,
        on_wait: ProcessWaitCallback | None = None,
    ) -> None:
        self.theatre = theatre
        self.policy = policy
        self.timeout = timeout
        self.announce_after = announce_after
        self.max_output_bytes = max_output_bytes
        self.source = source
        self.on_wait = on_wait
        self.commands_run = 0
        """How many git commands this adapter has run, so callers can check their cost."""
        self._watched: tuple[Path, ...] | None = None

    @property
    def name(self) -> str:
        return "git"

    def git(self, *args: str, allow: Sequence[int] = (0,)) -> Completed:
        """Run ``git args`` in the theatre; any exit status outside ``allow`` is vcs.failed."""
        argv = ["git", *args]
        self.commands_run += 1
        completed = run_command(
            argv,
            cwd=self.theatre,
            policy=self.policy,
            timeout=self.timeout,
            max_output_bytes=self.max_output_bytes,
            announce_after=self.announce_after,
            source=self.source,
            on_wait=self.on_wait,
        )
        if completed.returncode not in allow:
            message = completed.stderr.decode("utf-8", "replace").strip() or "no message"
            raise TroupeError(
                "vcs.failed",
                problem=f"{shlex.join(argv)} failed with exit status {completed.returncode}: "
                f"{message}",
                fix="Check that the theatre is a git repository and that git works there, then try "
                "again.",
                path=str(self.theatre.absolute()),
                details={"command": shlex.join(argv), "exit_status": completed.returncode},
            )
        return completed

    def branch(self) -> str | None:
        completed = self.git("symbolic-ref", "--quiet", "--short", "HEAD", allow=(0, _NO_ANSWER))
        if completed.returncode == _NO_ANSWER:
            return None  # detached
        return completed.stdout.decode("utf-8").strip()

    def head(self) -> str | None:
        completed = self.git("rev-parse", "--verify", "--quiet", "HEAD", allow=(0, _NO_ANSWER))
        if completed.returncode == _NO_ANSWER:
            return None  # no commit yet
        return completed.stdout.decode("ascii").strip()

    def branch_token(self) -> Hashable:
        # HEAD moves on a switch; the index is rewritten on add, commit, switch, merge and reset;
        # the HEAD reflog grows whenever HEAD moves. Statting the three costs no command.
        if self._watched is None:
            out = self.git(
                "rev-parse", "--git-path", "HEAD", "--git-path", "index", "--git-path", "logs/HEAD"
            )
            self._watched = tuple(
                self.theatre / line for line in out.stdout.decode("utf-8").splitlines()
            )
        return tuple(_stat_token(path) for path in self._watched)

    def committed_under(self, directory: str) -> frozenset[str]:
        staged = self.git("ls-files", "-z", "--", directory)
        names = set(_nul_separated(staged.stdout))
        if self.head() is not None:
            in_head = self.git("ls-tree", "-r", "-z", "--name-only", "HEAD", "--", directory)
            names.update(_nul_separated(in_head.stdout))
        return frozenset(names)

    def configured_identities(self) -> tuple[str, ...]:
        completed = self.git(
            "config", "--get-all", "--show-scope", "-z", "user.email", allow=(0, _NO_ANSWER)
        )
        if completed.returncode == _NO_ANSWER:
            return ()
        fields = completed.stdout.decode("utf-8").split("\0")
        if fields and fields[-1] == "":
            fields.pop()  # the terminator after the last value; an empty value is kept as a field
        by_scope: dict[str, list[str]] = {}
        for scope, value in zip(fields[::2], fields[1::2], strict=True):
            by_scope.setdefault(scope, []).append(value)
        # git reads scopes from least to most specific, and a more specific scope overrides a less
        # specific one, so the last scope listed wins. Several values within that one scope are an
        # ambiguity git would settle silently (the last one); troupe refuses instead.
        winning = list(by_scope.values())[-1]
        values = [value for value in winning if value.strip()]
        return tuple(dict.fromkeys(values))


def _nul_separated(data: bytes) -> list[str]:
    return [item for item in data.decode("utf-8").split("\0") if item]


def _stat_token(path: Path) -> tuple[int, int, int] | None:
    try:
        info = os.stat(path)
    except FileNotFoundError:
        return None
    return (info.st_mtime_ns, info.st_size, info.st_ino)
