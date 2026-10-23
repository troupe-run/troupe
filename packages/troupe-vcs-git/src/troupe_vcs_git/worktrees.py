"""The git adapter's worktree operations (spec: vcs, run-workspaces; worktree-stage design D2, D4,
D5, D6, D10).

A run's worktree is a ``git worktree``, detached at the base commit and made with
``--no-checkout``, so git writes no file and runs no post-checkout hook. troupe fills it: each file
that matches HEAD in the theatre is cloned from the theatre (its bytes are already what checkout
would write), the rest are checked out from the index, and then git compares every file with HEAD.
Each one it lists is checked out again from git's objects: a clone that caught a file mid-edit is
replaced by exactly what checkout writes. A file can still be listed after that, when the commit
holds it in a form git would normalise (CRLF in the repository under an eol attribute, say); git
lists it in every checkout, the theatre's too, so it isn't refused (found in CI on Windows).

The worktree's starting state is then written as a tree, the baseline (``add -A``, ``write-tree``),
and the diff is ``git diff --binary`` between the baseline and a tree written the same way from the
worktree's files when the run ends. Untracked files and any commits the actor made count, ignored
files don't, and a normalisation git would make to a file the actor never touched cancels out.
It is written to a file, never held in memory, with the person's diff settings that would change
it (renames, prefixes, external drivers, textconv, colour, relative) overridden. Applying it is
``git apply``: checked first, then applied unstaged, all or nothing.

These operations speak in paths relative to the repository's top level, which isn't the theatre
when the theatre is a subdirectory (``theatre_prefix``).
"""

import hashlib
import os
import re
import stat
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from troupe.core.errors import TroupeError
from troupe.core.vcs import Applicability, Captured, Clone, Filled, SharedState
from troupe.platform.files import remove_tree
from troupe.platform.processes import Completed

if TYPE_CHECKING:
    from troupe_vcs_git import GitAdapter

_DIFF_OPTIONS = (
    "--binary",
    "--no-color",
    "--no-renames",
    "--no-ext-diff",
    "--no-textconv",
    "--no-relative",
    "--src-prefix=a/",
    "--dst-prefix=b/",
    "--ignore-submodules=all",
)
"""Everything that pins the diff's form against the person's own diff configuration."""

_FAILED_PATCH = re.compile(r"^error: patch failed: (.+):\d+$")
_FAILED_PATH = re.compile(
    r"^error: (.+?): (patch does not apply|already exists in working directory|"
    r"No such file or directory|does not exist in (?:index|working tree)|wrong type|"
    r"does not match index)$"
)


def _nul_fields(data: bytes) -> list[str]:
    fields = data.decode("utf-8").split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    return fields


def _pathspec(leave_out: Sequence[str]) -> list[str]:
    return [".", *(f":(exclude){path}" for path in leave_out)]


class Worktrees:
    """The worktree operations, run through one adapter's git."""

    def __init__(self, adapter: "GitAdapter") -> None:
        self.adapter = adapter
        self._top: Path | None = None
        self._prefix: str | None = None

    def _git(
        self,
        cwd: Path,
        *args: str,
        allow: Sequence[int] = (0,),
        input: bytes | None = None,
    ) -> Completed:
        return self.adapter.git_in(
            cwd,
            *args,
            allow=allow,
            input=input,
            timeout=self.adapter.worktree_timeout,
            max_output_bytes=self.adapter.worktree_max_output_bytes,
        )

    def _layout(self) -> tuple[Path, str]:
        if self._top is None or self._prefix is None:
            out = self.adapter.git("rev-parse", "--show-toplevel", "--show-prefix").stdout
            top, *rest = out.decode("utf-8").splitlines()
            self._top = Path(top)
            self._prefix = rest[0] if rest else ""
        return self._top, self._prefix

    def theatre_prefix(self) -> str:
        return self._layout()[1]

    def differing_from_head(self) -> tuple[str, ...]:
        top, _ = self._layout()
        out = self._git(top, "status", "--porcelain=v2", "-z", "--untracked-files=normal").stdout
        fields = iter(_nul_fields(out))
        paths: list[str] = []
        for record in fields:
            kind = record[:1]
            if kind == "1":
                paths.append(record.split(" ", 8)[8])
            elif kind == "2":
                paths.append(record.split(" ", 9)[9])
                paths.append(next(fields))  # the path it was renamed or copied from
            elif kind == "u":
                paths.append(record.split(" ", 10)[10])
            elif kind == "?":
                paths.append(record[2:])
        return tuple(dict.fromkeys(paths))

    def add_worktree(self, path: Path, at: str) -> None:
        self._git(
            self.adapter.theatre, "worktree", "add", "--detach", "--no-checkout", str(path), at
        )

    def fill_worktree(self, path: Path, clone: Clone, skip: frozenset[str]) -> Filled:
        top, _ = self._layout()
        self._git(path, "read-tree", "HEAD")
        listed = self._git(path, "ls-tree", "-r", "-z", "--full-tree", "HEAD").stdout
        mechanisms: set[str] = set()
        to_check_out: list[str] = []
        cloned = 0
        for record in _nul_fields(listed):
            meta, _, name = record.partition("\t")
            if meta.split(" ")[1] != "blob":
                continue  # a submodule's gitlink: its contents aren't part of the worktree
            source = top.joinpath(*name.split("/"))
            if name in skip or not os.path.lexists(source):
                to_check_out.append(name)
                continue
            destination = path.joinpath(*name.split("/"))
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                mechanisms.add(clone(source, destination))
            except TroupeError:
                to_check_out.append(name)  # checked out instead, then verified like the rest
                continue
            cloned += 1
        self._check_out(path, to_check_out, force=False)
        self._check_out(path, self._differing(path), force=True)
        self._git(path, "add", "-A")
        baseline = self._git(path, "write-tree").stdout.decode("ascii").strip()
        return Filled(tuple(sorted(mechanisms)), cloned, len(to_check_out), baseline)

    def _check_out(self, path: Path, names: Iterable[str], *, force: bool) -> None:
        listed = b"".join(name.encode("utf-8") + b"\0" for name in names)
        if not listed:
            return
        args = ["checkout-index", "-z", "--stdin"] + (["-f"] if force else [])
        self._git(path, *args, input=listed)

    def _differing(self, path: Path) -> list[str]:
        self._git(path, "update-index", "-q", "--refresh", allow=(0, 1))
        return _nul_fields(self._git(path, "diff-files", "--name-only", "-z").stdout)

    def capture(self, path: Path, baseline: str, leave_out: tuple[str, ...], out: Path) -> Captured:
        self._git(path, "add", "-A")
        tree = self._git(path, "write-tree").stdout.decode("ascii").strip()
        spec = _pathspec(leave_out)
        self._git(path, "diff", *_DIFF_OPTIONS, f"--output={out}", baseline, tree, "--", *spec)
        if out.stat().st_size > self.adapter.diff_max_bytes:
            out.unlink()
            raise TroupeError(
                "workspace.diff-too-large",
                problem=f"The run's changes make a diff larger than "
                f"{self.adapter.diff_max_bytes} bytes, so they weren't captured.",
                fix="Look at the worktree to see what the run wrote, then discard it, or raise "
                "GIT_DIFF_MAX_BYTES.",
                path=str(path),
                details={"worktree": str(path), "limitBytes": self.adapter.diff_max_bytes},
            )
        status = _nul_fields(
            self._git(
                path,
                "diff",
                "--name-status",
                "-z",
                "--no-renames",
                "--ignore-submodules=all",
                baseline,
                tree,
                "--",
                *spec,
            ).stdout
        )
        added: list[str] = []
        modified: list[str] = []
        deleted: list[str] = []
        for letter, name in zip(status[::2], status[1::2], strict=True):
            {"A": added, "D": deleted}.get(letter, modified).append(name)
        left: list[str] = []
        if leave_out:
            left = _nul_fields(
                self._git(
                    path,
                    "diff",
                    "--name-only",
                    "-z",
                    "--no-renames",
                    baseline,
                    tree,
                    "--",
                    *leave_out,
                ).stdout
            )
        return Captured(tuple(added), tuple(modified), tuple(deleted), tuple(left))

    def check_apply(self, diff: Path) -> Applicability:
        if diff.stat().st_size == 0:
            return Applicability((), ())
        top, _ = self._layout()
        numstat = _nul_fields(self._git(top, "apply", "--numstat", "-z", str(diff)).stdout)
        files = tuple(record.split("\t", 2)[2] for record in numstat if record.count("\t") >= 2)
        checked = self._git(top, "apply", "--check", str(diff), allow=(0, 1))
        if checked.returncode == 0:
            return Applicability(files, ())
        failing = _failing(checked.stderr.decode("utf-8", "replace"))
        if not failing:
            raise self.adapter.failed(["git", "apply", "--check", str(diff)], checked)
        return Applicability(files, failing)

    def apply(self, diff: Path) -> tuple[str, ...]:
        applicability = self.check_apply(diff)
        if not applicability.applies:
            raise TroupeError(
                "vcs.failed",
                problem="git apply --check refused the diff, so nothing was applied: "
                + ", ".join(applicability.failing),
                fix="Check the files named, then try again.",
                path=str(diff),
                details={"command": f"git apply --check {diff}", "exitStatus": 1},
            )
        if applicability.files:
            top, _ = self._layout()
            self._git(top, "apply", str(diff))
        return applicability.files

    def remove_worktree(self, path: Path) -> None:
        theatre = self.adapter.theatre
        if path.exists():
            self._git(
                theatre, "worktree", "remove", "--force", "--force", str(path), allow=(0, 128)
            )
        if path.exists():  # not registered (made part-way), or holding something git won't remove
            remove_tree(path)
        self._git(theatre, "worktree", "prune")

    def shared_state(self) -> SharedState:
        adapter = self.adapter
        out = adapter.git("for-each-ref", "--format=%(objectname) %(refname)").stdout
        refs: dict[str, str] = {}
        for line in out.decode("utf-8").splitlines():
            if line:
                objectname, refname = line.split(" ", 1)
                refs[refname] = objectname
        refs["HEAD"] = f"{adapter.branch() or ''}:{adapter.head() or ''}"
        paths = (
            adapter.git(
                "rev-parse",
                "--git-common-dir",
                "--git-path",
                "config.worktree",
                "--git-path",
                "hooks",
            )
            .stdout.decode("utf-8")
            .splitlines()
        )
        common, worktree_config, hooks = (adapter.theatre / line for line in paths)
        config = {
            name: digest
            for name, file in (("config", common / "config"), ("config.worktree", worktree_config))
            if (digest := _digest(file)) is not None
        }
        return SharedState(refs=refs, config=config, hooks=_hooks(hooks))


def _failing(stderr: str) -> tuple[str, ...]:
    names: list[str] = []
    for line in stderr.splitlines():
        match = _FAILED_PATCH.match(line) or _FAILED_PATH.match(line)
        if match:
            names.append(match.group(1))
    return tuple(dict.fromkeys(names))


def _digest(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except (FileNotFoundError, NotADirectoryError):
        return None


def _hooks(directory: Path) -> dict[str, str]:
    try:
        entries = sorted(directory.iterdir())
    except (FileNotFoundError, NotADirectoryError):
        return {}
    hooks: dict[str, str] = {}
    for entry in entries:
        if not entry.is_file():
            continue
        executable = bool(entry.stat().st_mode & stat.S_IXUSR)
        digest = _digest(entry)
        if digest is not None:
            hooks[entry.name] = f"{digest}:{'x' if executable else '-'}"
    return hooks
