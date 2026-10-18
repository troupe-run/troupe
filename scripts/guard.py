# Source: troupe-run/infrastructure. Change it there; copies in other repositories are delivered.
"""Workflow guardrails for every repository the org builds in (spec: development-workflow).

Every rule is a pure function from facts to a Decision. Thin entry points gather the facts, apply
the rules, honour a person-granted override, and refuse or allow:

    guard.py pre-commit              git hook (.githooks/pre-commit)
    guard.py commit-msg FILE         git hook (.githooks/commit-msg)
    guard.py claude-pre-tool-use     Claude Code PreToolUse hook (.claude/settings.json)
    guard.py claude-session-start    Claude Code SessionStart hook
    guard.py pre-push                git hook (.githooks/pre-push)
    guard.py ci                      the same rules on GitHub, for a push or pull request
    guard.py check-scope             CI: what changed paths (stdin) need from scripts/check.py
    guard.py override RULE --reason  a person grants one override, from their own terminal

Standard library only, so it runs under `uv run --no-project` without installing anything.
These guardrails stop honest shortcuts; they are not a security boundary (design D1).

The rules are documented in troupe-run/infrastructure (docs/development-workflow.md). "Design D<n>"
refers to troupe's archived workflow-guardrails change, which holds the reasoning behind each rule.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar, TextIO

# Rule ids, as named in refusals, overrides and the rules doc (design D7).
OVERRIDABLE_RULES = (
    "commit-on-main",
    "commit-branch-change",
    "commit-message",
    "commit-checks",
    "archive-incomplete",
    "edit-branch-change",
    "pr-closes-issue",
    "skip-hooks",
    "command-unparseable",
    "delivered-file",
    "owner-only",
    "gh-allow-list",
)
TAMPER_RULE = "guard-tamper"
"""Refuses an agent's attempt to grant itself an override. Never overridable."""
RULES = (*OVERRIDABLE_RULES, TAMPER_RULE)

HOOKS_PATH = ".githooks"
SOURCE_REPOSITORY = "troupe-run/infrastructure"
"""Where the guard's files are maintained and delivered from (spec: guard-delivery)."""
DELIVERY_LIST = ".github/guard-delivery.json"
"""Present only in a repository that receives the guard: the files delivered to it."""
DELIVERY_AUTHOR_EMAIL = "340938853+troupe-run-infrastructure[bot]@users.noreply.github.com"
"""The infrastructure App's bot account, which makes every delivery commit."""
RELEASE_BRANCH_PREFIX = "release-please--"
RELEASE_REPOSITORIES = frozenset({"troupe-run/troupe"})
"""Where a ruleset lets only the release App create or update release-please--* branches
(tofu/release.tf). There, GitHub enforces who writes such a branch, so its name is proof; anywhere
else, a fork included, anyone can use the name (open-release-exemption design D1;
drop-forgery-resistance design D1)."""
GUARD_DIR = "troupe-guard"
CHECK_TIMEOUT_SECONDS = 600.0
"""How long the pre-commit check may run before the commit is refused. The default lives here
only; pass a different value to commit_checks to override it."""
COMMIT_TYPES = (
    "feat", "fix", "docs", "build", "ci", "test", "refactor", "perf", "style", "chore", "revert",
)  # fmt: skip
COMMIT_PATTERN = re.compile(rf"^({'|'.join(COMMIT_TYPES)})(\([a-z0-9][a-z0-9-]*\))?!?: \S")
AUTOSQUASH_PREFIXES = ("fixup! ", "squash! ", "amend! ")
CLOSING = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?):?\s+"
    r"(?:#\d+|[\w.-]+/[\w.-]+#\d+|https://github\.com/[\w.-]+/[\w.-]+/issues/\d+)",
    re.IGNORECASE,
)
SHELL_EXPANSION = re.compile(r"\$[A-Za-z_{(]|`")
"""A $NAME, ${...}, $(...) or backtick: text the shell replaces before gh sees it."""
UNTICKED = re.compile(r"^\s*- \[(?![xX]\])[^\]]*\]\s*(.*)$", re.MULTILINE)
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
SHELL_TOOLS = ("Bash", "PowerShell")


@dataclass(frozen=True)
class Decision:
    """Allow (rule is None), or refuse with the rule id, the problem and the fix."""

    rule: str | None = None
    problem: str = ""
    fix: str = ""

    @property
    def refused(self) -> bool:
        return self.rule is not None

    def text(self) -> str:
        return f"guard: {self.rule}: {self.problem}\n  fix: {self.fix}"


ALLOW = Decision()


# --- facts ---------------------------------------------------------------------------------


REPOSITORY_LOCATION_VARIABLES = frozenset(
    {
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_PREFIX",
        "GIT_COMMON_DIR",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_NAMESPACE",
    }
)
"""Set by git while a hook runs. They pin git to that repository, so nested git calls (such as
the tests' temporary repositories) must not inherit them. Other GIT_* settings are the user's."""


def _git_env() -> dict[str, str]:
    """The environment without the hook-time repository-location variables."""
    return {k: v for k, v in os.environ.items() if k not in REPOSITORY_LOCATION_VARIABLES}


def git(root: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=False, env=_git_env()
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def repo_root(start: Path) -> Path | None:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=start,
        capture_output=True,
        text=True,
        check=False,
        env=_git_env(),
    )
    return Path(result.stdout.strip()) if result.returncode == 0 else None


def current_branch(root: Path) -> str | None:
    """The checked-out branch, read from the rebase state while a rebase has HEAD detached."""
    branch = git(root, "rev-parse", "--abbrev-ref", "HEAD", check=False)
    if branch and branch != "HEAD":
        return branch
    git_dir = Path(git(root, "rev-parse", "--absolute-git-dir"))
    for state in ("rebase-merge", "rebase-apply"):
        head_name = git_dir / state / "head-name"
        if head_name.is_file():
            return head_name.read_text(encoding="utf-8").strip().removeprefix("refs/heads/")
    return None


def matching_change(root: Path, branch: str | None) -> Path | None:
    """The OpenSpec change named like ``branch``: active, or archived on that branch (design D3)."""
    if not branch or branch == "main" or branch == "archive":
        return None
    changes = root / "openspec" / "changes"
    active = changes / branch
    if active.is_dir():
        return active
    archived = re.compile(rf"^\d{{4}}-\d{{2}}-\d{{2}}-{re.escape(branch)}$")
    archive = changes / "archive"
    if archive.is_dir():
        for candidate in sorted(archive.iterdir()):
            if candidate.is_dir() and archived.match(candidate.name):
                return candidate
    return None


# --- git-level rules -------------------------------------------------------------------------


def commit_on_main(branch: str | None) -> Decision:
    if branch == "main":
        return Decision(
            "commit-on-main",
            "commits aren't made on main; work reaches main through a pull request.",
            "Create a branch named after the OpenSpec change: git switch -c <change-name>",
        )
    return ALLOW


def commit_branch_change(root: Path, branch: str | None) -> Decision:
    if branch is None:
        return Decision(
            "commit-branch-change",
            "HEAD is detached, so this commit belongs to no change.",
            "Switch to the change's branch: git switch <change-name>",
        )
    if branch != "main" and matching_change(root, branch) is None:
        return Decision(
            "commit-branch-change",
            f"branch '{branch}' has no matching OpenSpec change "
            f"(openspec/changes/{branch}/, active or archived).",
            f"Propose the change (/opsx:propose {branch}), or switch to the branch of the change "
            "this work belongs to.",
        )
    return ALLOW


def commit_message(message: str) -> Decision:
    lines = [line for line in message.splitlines() if not line.startswith("#")]
    first = next((line for line in lines if line.strip()), "")
    target = first
    while target.startswith(AUTOSQUASH_PREFIXES):
        # git writes "fixup! <subject of the commit being fixed>": that subject must conform too.
        target = target.split(" ", 1)[1]
    if COMMIT_PATTERN.match(target):
        return ALLOW
    example = "feat(cli): add --version"
    if first.startswith('Revert "'):
        fix = "Write it as a Conventional Commit: revert: <what is reverted> (git revert --edit)."
    elif first.startswith("Merge "):
        fix = "History stays linear: rebase onto the target instead of merging (git rebase main)."
    else:
        fix = (
            f"Start the first line with a type, an optional (scope) and ': ', e.g. '{example}'. "
            f"Types: {', '.join(COMMIT_TYPES)}."
        )
    return Decision("commit-message", f"'{first}' isn't a Conventional Commit.", fix)


def pr_title(title: str) -> Decision:
    """The commit-message rule over a pull request's title: if squash merging is ever turned on,
    the title becomes the commit message on main (release-please-prs design D3)."""
    if not commit_message(title).refused:
        return ALLOW
    return Decision(
        "commit-message",
        f"pull request title '{title}' isn't a Conventional Commit.",
        "Edit the title (gh pr edit <n> --title 'feat(cli): add --version', or on GitHub) to "
        f"start with a type, an optional (scope) and ': '. Types: {', '.join(COMMIT_TYPES)}.",
    )


def unticked_archived_tasks(
    staged: Iterable[str], read_staged: Callable[[str], str | None]
) -> Decision:
    """Refuse when a staged archived change still has an unticked task (design D7)."""
    archived = re.compile(r"^openspec/changes/archive/([^/]+)/")
    seen: set[str] = set()
    for path in staged:
        match = archived.match(path)
        if match is None or match.group(1) in seen:
            continue
        name = match.group(1)
        seen.add(name)
        tasks = read_staged(f"openspec/changes/archive/{name}/tasks.md")
        if tasks is None:
            continue
        unticked = UNTICKED.search(tasks)
        if unticked is not None:
            return Decision(
                "archive-incomplete",
                f"archived change '{name}' has an unticked task: {unticked.group(1).strip()[:120]}",
                "Finish and tick every task before archiving, or move the change back out of "
                "openspec/changes/archive/.",
            )
    return ALLOW


def delivered_paths(read: Callable[[str], str | None]) -> frozenset[str]:
    """The files delivered to this repository, from its delivered list (empty in the source)."""
    text = read(DELIVERY_LIST)
    if text is None:
        return frozenset()
    try:
        files = json.loads(text).get("files", [])
    except (ValueError, AttributeError):
        # A list that can't be read still protects itself.
        return frozenset({DELIVERY_LIST})
    return frozenset(str(path) for path in files if isinstance(path, str)) | {DELIVERY_LIST}


def _delivered_refusal(paths: Iterable[str], problem: str) -> Decision:
    listed = ", ".join(sorted(paths)[:5])
    return Decision(
        "delivered-file",
        f"{problem}: {listed}. Delivered files are changed only at their source.",
        f"Change the file in {SOURCE_REPOSITORY}, and deliver it from there.",
    )


def delivered_file_staged(staged: Iterable[str], delivered: frozenset[str]) -> Decision:
    """Refuse a commit that changes a delivered file (spec: guard-delivery)."""
    touched = [path for path in staged if path in delivered]
    if not touched:
        return ALLOW
    return _delivered_refusal(touched, "this commit changes delivered files")


CHECK_PATHS = "scripts/check-paths.toml"
"""Each repository's own declaration of what a change to its paths needs from scripts/check.py:
nothing (skip), named scopes, or, for a path it doesn't name, the full check. Not delivered
(commit-check-paths design D1)."""
SCOPE_NAME = re.compile(r"[a-z][a-z0-9_]*\Z")
"""A valid tag in any test runner: a Python attribute, a word in `pytest -m`, a JS identifier."""
RESERVED_SCOPES = frozenset({"none", "full"})
"""check-scope's other answers, so no scope may be called by them (design D6)."""
SCOPE_KEYS = frozenset({"paths", "tests"})
"""What a `[scopes.<name>]` table may hold; `[skip]` holds only `paths`."""
CHECK_PATHS_FIX = (
    f"Fix {CHECK_PATHS}: `version = 1`, then `[skip]` and `[scopes.<name>]` tables, each holding "
    "`paths`, a list of exact paths or `dir/**`, with no path both skipped and in a scope. A scope "
    "may also hold `tests`, a list of the test directories it runs, each `dir/**`. Or delete it to "
    "run the full check on every commit."
)


class CheckPathsError(ValueError):
    """The declaration is present but malformed: an error, never treated as absent (design D5)."""

    def __init__(self, problem: str, fix: str = CHECK_PATHS_FIX) -> None:
        super().__init__(problem)
        self.problem = problem
        self.fix = fix

    def decision(self) -> Decision:
        return Decision("commit-checks", f"{CHECK_PATHS} is malformed: {self.problem}", self.fix)


@dataclass(frozen=True)
class CheckPaths:
    """A parsed declaration: the skipped entries, and each scope's entries, in file order."""

    skip: tuple[str, ...]
    scopes: tuple[tuple[str, tuple[str, ...]], ...]
    tests: tuple[tuple[str, tuple[str, ...]], ...] = ()
    """Each scope that declares `tests`, with its test directories, in file order. Kept apart from
    `scopes`, whose `(name, paths)` shape every check.py reads (scope-test-directories D3)."""


@dataclass(frozen=True)
class Scope:
    """What a change needs: the full check, or the named scopes (none at all means skip)."""

    full: bool
    names: tuple[str, ...] = ()
    matched: tuple[str, ...] = ()
    """The declared entries the paths matched, as written, for the announcement."""

    @property
    def label(self) -> str:
        return "full" if self.full else ",".join(self.names) or "none"

    @property
    def args(self) -> tuple[str, ...]:
        return tuple(word for name in self.names for word in ("--scope", name))


FULL_CHECK = Scope(full=True)


def _check_paths_entry(entry: object, where: str) -> str:
    """An exact relative path, or a directory written `dir/**` (design D2)."""
    if not isinstance(entry, str):
        raise CheckPathsError(f"{where} is not a string.")
    base = entry.removesuffix("/**")
    problem = None
    if not base or base == "**":
        problem = "is empty" if not entry else "covers every path"
    elif "\\" in base:
        problem = "uses a backslash; write paths with `/`"
    elif any(char in base for char in "*?["):
        problem = "uses a wildcard other than a trailing `/**`"
    elif base.startswith("/"):
        problem = "is absolute; write it relative to the repository root"
    elif any(segment in ("", ".", "..") for segment in base.split("/")):
        problem = "has an empty, `.` or `..` segment"
    if problem is not None:
        raise CheckPathsError(f"{where} `{entry}` {problem}.")
    return entry


def _check_paths_group(
    table: object, where: str, keys: frozenset[str] = frozenset({"paths"})
) -> tuple[str, ...]:
    if not isinstance(table, dict):
        raise CheckPathsError(f"{where} is not a table.")
    unknown = sorted(set(table) - keys)
    if unknown:
        read = " and ".join(f"`{key}`" for key in sorted(keys))
        verb = "is" if len(keys) == 1 else "are"
        raise CheckPathsError(
            f"{where} has an unknown key `{unknown[0]}`; only {read} {verb} read."
        )
    if "paths" not in table:
        raise CheckPathsError(f"{where}.paths is missing.")
    paths = table["paths"]
    if not isinstance(paths, list):
        raise CheckPathsError(f"{where}.paths is not a list.")
    return tuple(
        _check_paths_entry(entry, f"{where}.paths[{index}]") for index, entry in enumerate(paths)
    )


def _check_paths_tests(table: dict[str, object], where: str) -> tuple[str, ...] | None:
    """A scope's test directories, each `dir/**` (scope-test-directories design D2), or None."""
    if "tests" not in table:
        return None
    tests = table["tests"]
    if not isinstance(tests, list):
        raise CheckPathsError(f"{where}.tests is not a list.")
    if not tests:
        raise CheckPathsError(f"{where}.tests is empty; leave `tests` out instead.")
    entries = []
    for index, entry in enumerate(tests):
        place = f"{where}.tests[{index}]"
        entry = _check_paths_entry(entry, place)
        if not entry.endswith("/**"):
            raise CheckPathsError(
                f"{place} `{entry}` is a file; `tests` names directories, written `dir/**`. Tag a "
                "single test file with a marker in it instead."
            )
        entries.append(entry)
    return tuple(entries)


def _entries_overlap(first: str, second: str) -> bool:
    """Whether some path matches both entries. Exact for the two forms D2 allows."""
    first_dir, second_dir = first.endswith("/**"), second.endswith("/**")
    if first_dir and second_dir:
        return first[:-2].startswith(second[:-2]) or second[:-2].startswith(first[:-2])
    if first_dir:
        return second.startswith(first[:-2])
    if second_dir:
        return first.startswith(second[:-2])
    return first == second


def check_paths(text: str) -> CheckPaths:
    """Parse and validate a declaration, or raise CheckPathsError naming what's wrong."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise CheckPathsError(f"it isn't valid TOML ({error}).") from None
    unknown = sorted(set(data) - {"version", "skip", "scopes"})
    if unknown:
        raise CheckPathsError(
            f"unknown key `{unknown[0]}`; only `version`, `skip` and `scopes` are read."
        )
    version = data.get("version")
    if type(version) is not int or version != 1:
        raise CheckPathsError(f"`version` must be 1, not {version!r}.")
    skip = _check_paths_group(data["skip"], "skip") if "skip" in data else ()
    scopes_table = data.get("scopes", {})
    if not isinstance(scopes_table, dict):
        raise CheckPathsError("scopes is not a table of `[scopes.<name>]` tables.")
    scopes = []
    tests = []
    for name, table in scopes_table.items():
        if not SCOPE_NAME.match(name) or name in RESERVED_SCOPES:
            raise CheckPathsError(
                f"scope name `{name}` must match [a-z][a-z0-9_]* and not be `none` or `full`."
            )
        scopes.append((name, _check_paths_group(table, f"scopes.{name}", SCOPE_KEYS)))
        directories = _check_paths_tests(table, f"scopes.{name}")
        if directories is not None:
            tests.append((name, directories))
    # Scopes may overlap one another (a path then runs each), but not the skip list (design D2).
    for name, entries in scopes:
        for entry in entries:
            for skipped in skip:
                if _entries_overlap(skipped, entry):
                    raise CheckPathsError(
                        f"`{skipped}` in skip overlaps `{entry}` in scopes.{name}: a path can't "
                        "be both unread and read by a scope's tests.",
                        f"Take the path out of skip or out of scopes.{name}, in {CHECK_PATHS}.",
                    )
    return CheckPaths(skip=skip, scopes=tuple(scopes), tests=tuple(tests))


def _matches(entry: str, path: str) -> bool:
    return path.startswith(entry[:-2]) if entry.endswith("/**") else path == entry


def check_scope(paths: Iterable[str], declaration: CheckPaths | None) -> Scope:
    """What a change to these paths needs from scripts/check.py (design D4).

    The full check, unless there's a declaration, at least one path, the declaration isn't among
    them, and every path is skipped or in a scope. Then every scope any path is in, sorted (none
    means skip): scopes may overlap, and a path in two runs both.
    """
    changed = [path for path in paths if path]
    if declaration is None or not changed or CHECK_PATHS in changed:
        return FULL_CHECK
    groups = [(None, entry) for entry in declaration.skip] + [
        (name, entry) for name, entries in declaration.scopes for entry in entries
    ]
    names: set[str] = set()
    matched: set[str] = set()
    for path in changed:
        found = [(name, entry) for name, entry in groups if _matches(entry, path)]
        if not found:
            return FULL_CHECK
        for name, entry in found:
            matched.add(entry)
            if name is not None:
                names.add(name)
    return Scope(full=False, names=tuple(sorted(names)), matched=tuple(sorted(matched)))


def marker_expression(names: Iterable[str]) -> str:
    """pytest's `-m` expression selecting the tests tagged with any of these scopes (design D8)."""
    return " or ".join(names)


@dataclass(frozen=True)
class TestReads:
    """What one test read, from any test runner: its id, its tags, and the repository-relative
    POSIX paths it opened (design D9). A runner's adapter collects it; tag_violations judges it."""

    __test__: ClassVar[bool] = False  # not a pytest test class, despite the name

    test: str
    tags: frozenset[str]
    reads: frozenset[str]


def tag_violations(test: TestReads, declaration: CheckPaths) -> list[str]:
    """Each read the test's tags don't cover: a skipped path, or a scope's path without its tag.

    Paths in no group are fine: the full check covers them (design D9).
    """
    found = []
    for path in sorted(test.reads):
        skipped = next((entry for entry in declaration.skip if _matches(entry, path)), None)
        if skipped is not None:
            found.append(
                f"{test.test} reads {path}, but {CHECK_PATHS} skips `{skipped}`, so a change to it "
                "would run no test. Take it out of skip (and into a scope), or don't read it."
            )
            continue
        needed = sorted(
            {name for name, entries in declaration.scopes for e in entries if _matches(e, path)}
        )
        missing = [name for name in needed if name not in test.tags]
        if missing:
            tags = " and ".join(f"`{name}`" for name in missing)
            found.append(
                f"{test.test} reads {path}, which {CHECK_PATHS} puts in scope {tags}, so a change "
                f"to it wouldn't run this test. Tag the test {tags} (pytest: @pytest.mark.<name>)."
            )
    return found


def directory_tags(path: str, declaration: CheckPaths) -> frozenset[str]:
    """The scopes whose `tests` directories hold this test file, a repository-relative POSIX path.

    A runner's adapter adds them to the test's own tags, before it selects by tag, so a scope
    selects whole suites and tag_violations counts them like any other tag (scope-test-directories
    design D4).
    """
    return frozenset(
        name for name, entries in declaration.tests if any(_matches(e, path) for e in entries)
    )


@dataclass(frozen=True)
class UnmatchedTests:
    """A scope's `tests` entry that no collected test is under."""

    scope: str
    index: int
    entry: str

    @property
    def place(self) -> str:
        return f"scopes.{self.scope}.tests[{self.index}]"

    @property
    def message(self) -> str:
        return (
            f"{CHECK_PATHS}: scope `{self.scope}` runs the tests under `{self.entry}` "
            f"({self.place}), but no collected test is there, so `--scope {self.scope}` would "
            "quietly stop running them. Correct the entry if the directory moved, or take it out."
        )


def _under_root(path: str, root: str) -> bool:
    """Whether a repository-relative path is the root or under it ("" is the repository)."""
    return root == "" or path == root or path.startswith(root + "/")


def unmatched_tests(
    test_files: Iterable[str], roots: Iterable[str], declaration: CheckPaths
) -> list[UnmatchedTests]:
    """Each `tests` entry inside the run's roots that none of the collected test files is under.

    The roots are what the run was asked to collect, as repository-relative POSIX paths ("" for
    the repository). An entry outside every root isn't checked, so running one file or one suite
    never fails for another (scope-test-directories design D6).
    """
    files = list(test_files)
    run_roots = list(roots)
    found = []
    for name, entries in declaration.tests:
        for index, entry in enumerate(entries):
            directory = entry.removesuffix("/**")
            if not any(_under_root(directory, root) for root in run_roots):
                continue
            if not any(_matches(entry, path) for path in files):
                found.append(UnmatchedTests(scope=name, index=index, entry=entry))
    return found


def read_working_tree(root: Path) -> Callable[[str], str | None]:
    def read(path: str) -> str | None:
        target = root / path
        return target.read_text(encoding="utf-8") if target.is_file() else None

    return read


class ReadStaged:
    """Reads a file's staged contents (None when it isn't staged or doesn't exist)."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def __call__(self, path: str) -> str | None:
        result = subprocess.run(
            ["git", "show", f":{path}"],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=False,
            env=_git_env(),
        )
        return result.stdout if result.returncode == 0 else None


def _stop_process_tree(process: subprocess.Popen[str]) -> None:
    """Stop the check and everything it started (uv, python, pytest's children)."""
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True, check=False
        )
    else:
        os.killpg(process.pid, signal.SIGKILL)


def commit_checks(
    root: Path,
    *,
    timeout: float = CHECK_TIMEOUT_SECONDS,
    progress: TextIO | None = None,
) -> Decision:
    """Refuse unless the tracked work equals what's staged and scripts/check.py passes (D4).

    What runs is what the staged paths need, by the repository's check-paths declaration:
    nothing, `check.py --scope <name>...`, or the full check (commit-check-paths design D4, D8).
    The check never runs silently: it is announced, its output is streamed to ``progress``
    (stderr by default) as it runs, and it is stopped after ``timeout`` seconds.
    """
    out = sys.stderr if progress is None else progress
    unstaged = git(root, "diff", "--name-only")
    if unstaged:
        files = ", ".join(unstaged.splitlines()[:5])
        return Decision(
            "commit-checks",
            f"tracked files have unstaged changes ({files}), so the check wouldn't test what's "
            "being committed.",
            "Stage them (git add) or set them aside (git stash --keep-index), then commit again.",
        )
    staged = git(root, "diff", "--cached", "--name-only", "--no-renames").splitlines()
    text = ReadStaged(root)(CHECK_PATHS)
    try:
        scope = check_scope(staged, None if text is None else check_paths(text))
    except CheckPathsError as error:
        return error.decision()
    if not scope.full:
        *rest, last = scope.matched
        listed = f"{', '.join(rest)} and {last}" if rest else last
        verb = "are" if rest else "is"
        if not scope.names:
            print(
                f"guard: only {listed} {verb} staged; the check is skipped ({CHECK_PATHS}).",
                file=out,
                flush=True,
            )
            return ALLOW
        command = " ".join(("scripts/check.py", *scope.args))
        print(
            f"guard: only {listed} {verb} staged; running {command} instead of the full check "
            f"({CHECK_PATHS}; gives up after {timeout:.0f}s)...",
            file=out,
            flush=True,
        )
    else:
        command = "scripts/check.py"
        print(
            f"guard: running scripts/check.py, the same check CI runs (gives up after "
            f"{timeout:.0f}s)...",
            file=out,
            flush=True,
        )
    check = root / "scripts" / "check.py"
    started = time.monotonic()
    process = subprocess.Popen(
        ["uv", "run", "--quiet", str(check), *scope.args],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=_git_env(),
        start_new_session=sys.platform != "win32",
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    timed_out = threading.Event()

    def give_up() -> None:
        timed_out.set()
        _stop_process_tree(process)

    timer = threading.Timer(timeout, give_up)
    timer.start()
    output: list[str] = []
    try:
        for line in process.stdout or ():
            output.append(line)
            print(f"  | {line}", end="", file=out, flush=True)
        process.wait()
    finally:
        timer.cancel()
    elapsed = time.monotonic() - started
    if timed_out.is_set():
        return Decision(
            "commit-checks",
            f"the check was still running after {timeout:.0f}s, so it was stopped.",
            f"Run `uv run {command}` on its own to see what is slow or stuck, then commit again.",
        )
    if process.returncode != 0:
        failed = re.search(r"^check: (.+?) failed", "".join(output), re.MULTILINE)
        gate = failed.group(1) if failed else "a"
        return Decision(
            "commit-checks",
            f"the {gate} gate failed.",
            f"Run `uv run {command}`, fix what it reports, then commit again.",
        )
    what = "the check" if scope.full else command
    print(f"guard: {what} passed in {elapsed:.0f}s.", file=out, flush=True)
    return ALLOW


# --- Claude Code rules -----------------------------------------------------------------------

HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][\w-]*)\1")
OPERATORS = ("&&", "||", ";", "|", "&", "\n")


def strip_heredocs(command: str) -> str:
    """Drop heredoc bodies: they are data (often commit messages), not shell words."""
    out: list[str] = []
    lines = command.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        delimiters = [m.group(2) for m in HEREDOC.finditer(line)]
        i += 1
        for delimiter in delimiters:
            while i < len(lines) and lines[i].strip() != delimiter:
                i += 1
            i += 1  # the delimiter line itself
    return "\n".join(out)


def split_command(command: str) -> list[list[str]]:
    """Split a shell command into its simple commands, each as a list of words.

    Raises ValueError when the text can't be parsed (for example, unbalanced quotes).
    """
    text = strip_heredocs(command)
    segments: list[str] = []
    current: list[str] = []
    quote: str | None = None
    i = 0
    while i < len(text):
        char = text[i]
        if quote:
            current.append(char)
            if char == "\\" and quote == '"' and i + 1 < len(text):
                current.append(text[i + 1])
                i += 1
            elif char == quote:
                quote = None
        elif char in "'\"":
            quote = char
            current.append(char)
        elif char == "\\" and i + 1 < len(text):
            current.append(text[i : i + 2])
            i += 1
        else:
            operator = next((op for op in OPERATORS if text.startswith(op, i)), None)
            if operator is None:
                current.append(char)
            else:
                segments.append("".join(current))
                current = []
                i += len(operator) - 1
        i += 1
    if quote:
        raise ValueError("unbalanced quotes")
    segments.append("".join(current))
    return [words for segment in segments if (words := shlex.split(segment, posix=True))]


def _program(words: Sequence[str]) -> tuple[str, list[str]]:
    """The program name and its arguments, after any leading VAR=value assignments."""
    index = 0
    while index < len(words) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[index]):
        index += 1
    if index >= len(words):
        return "", []
    name = Path(words[index]).name.lower().removesuffix(".exe")
    return name, list(words[index + 1 :])


def _git_subcommand(args: list[str]) -> tuple[list[str], str | None, list[str]]:
    """Split git's arguments into its global options, the subcommand and the rest."""
    globals_: list[str] = []
    index = 0
    while index < len(args) and args[index].startswith("-"):
        globals_.append(args[index])
        if args[index] in ("-c", "-C", "--git-dir", "--work-tree") and index + 1 < len(args):
            globals_.append(args[index + 1])
            index += 1
        index += 1
    if index >= len(args):
        return globals_, None, []
    return globals_, args[index], args[index + 1 :]


def _sets_hooks_path_elsewhere(setting: str) -> bool:
    key, _, value = setting.partition("=")
    return key.strip().lower() == "core.hookspath" and value.strip() != HOOKS_PATH


def skip_hooks(words: Sequence[str]) -> Decision:
    program, args = _program(words)
    if program != "git":
        return ALLOW
    globals_, sub, rest = _git_subcommand(args)
    refused = Decision(
        "skip-hooks",
        "this would skip or disable the repository's git hooks.",
        "Fix what the hook reports instead. If a skip is really needed, ask the owner to grant "
        "an override.",
    )
    for index, option in enumerate(globals_):
        setting = globals_[index + 1] if index + 1 < len(globals_) else ""
        if option == "-c" and _sets_hooks_path_elsewhere(setting):
            return refused
    if "--no-verify" in rest:
        return refused
    if sub == "commit":
        value_flags = set("mFCct")
        skip_next = False
        for word in rest:
            if skip_next:
                skip_next = False
                continue
            if word == "--":
                break
            if word.startswith("-") and not word.startswith("--"):
                for position, flag in enumerate(word[1:]):
                    if flag == "n":
                        return refused
                    if flag in value_flags:
                        skip_next = position == len(word) - 2
                        break
            elif word in (
                "--message",
                "--file",
                "--reuse-message",
                "--reedit-message",
                "--template",
            ):
                skip_next = True
    if sub == "config":
        lowered = [word.lower() for word in rest]
        if "core.hookspath" in lowered:
            position = lowered.index("core.hookspath")
            value = rest[position + 1] if position + 1 < len(rest) else None
            removing = any(word in ("--unset", "--unset-all", "--remove-section") for word in rest)
            reading = value is None and not removing
            if removing or (not reading and value != HOOKS_PATH):
                return refused
    return ALLOW


REPO_PART = re.compile(r"[\w.-]+")
REPO_URL = re.compile(r"(?:https|ssh)://(?:[^@/]+@)?([^@/:]+)(?::\d+)?/(.+)")
REPO_SCP = re.compile(r"[^@/:]+@([^@/:]+):(.+)")
GH_PR_CREATE_VALUE_FLAGS = frozenset(
    {
        "-a", "--assignee", "--attach", "-B", "--base", "-b", "--body", "-F", "--body-file", "-H",
        "--head", "-l", "--label", "-m", "--milestone", "-p", "--project", "-R", "--repo",
        "--recover", "-r", "--reviewer", "-T", "--template", "-t", "--title",
    }
)  # fmt: skip
"""gh pr create's flags that take the next word as their value, so it isn't read as a flag.
From gh 2.102.0's pkg/cmd/pr/create/create.go, and -R/--repo from pkg/cmdutil/repo_override.go."""
GH_PR_CREATE_BOOLEAN_SHORT_FLAGS = frozenset({"-d", "-e", "-f", "-w"})
"""gh pr create's short flags that take no value: --draft, --editor, --fill and --web."""


def normalise_repository(name: str) -> tuple[str, str, str] | None:
    """A repository name or remote URL as (host, owner, name), lower-cased; None if unrecognised.

    Accepts what gh accepts for --repo (OWNER/REPO, HOST/OWNER/REPO, an https:// URL) and the
    SSH forms a remote may use (git@HOST:OWNER/REPO, ssh://git@HOST/OWNER/REPO). A trailing
    .git and / are dropped, and a name without a host means github.com (design decision 3).
    """
    text = name.strip().lower().rstrip("/").removesuffix(".git")
    host: str | None = None
    if match := REPO_URL.fullmatch(text) or REPO_SCP.fullmatch(text):
        host, text = match.group(1), match.group(2)
    parts = text.split("/")
    if host is None and len(parts) == 3:
        host, parts = parts[0], parts[1:]
    if len(parts) != 2 or not all(
        REPO_PART.fullmatch(part) and part not in (".", "..")
        for part in (*parts, *([] if host is None else [host]))
    ):
        return None
    return (host or "github.com", parts[0], parts[1])


def remote_urls(cwd: Path) -> list[str]:
    """The fetch and push URLs of every remote of the repository at cwd; empty if there's none."""
    try:
        listing = git(cwd, "remote", "-v", check=False)
    except OSError:
        return []
    return [fields[1] for line in listing.splitlines() if len(fields := line.split()) >= 2]


def pr_create_flags(args: Sequence[str]) -> list[tuple[str, str | None]]:
    """gh pr create's flags as gh (pflag) reads them, in order, as (flag, value): a long flag by
    its long name, a short one as -x, and None for a flag given no value. Positional words are left
    out, and -- ends the flags (refuse-substituted-pr-body design D3).

    A long flag's value follows = or, for a flag that takes one, is the next word whatever it looks
    like. A word starting with one - is short flags, read letter by letter: a boolean letter is
    taken and the next one read; a letter that takes a value takes the rest of the word (dropping
    one = when more follows) or, when nothing follows, the next word. An unknown letter ends the
    word: gh refuses the command, so it creates nothing."""
    flags: list[tuple[str, str | None]] = []
    index = 0
    while index < len(args):
        word = args[index]
        index += 1
        if word == "--":
            break
        if word.startswith("--"):
            name, equals, inline = word.partition("=")
            if equals:
                flags.append((name, inline))
            elif name in GH_PR_CREATE_VALUE_FLAGS:
                flags.append((name, args[index] if index < len(args) else None))
                index += 1
            else:
                flags.append((name, None))
            continue
        letters = word[1:] if word.startswith("-") else ""
        while letters:
            flag, letters = f"-{letters[0]}", letters[1:]
            after_equals = letters[1:] if letters[:1] == "=" and letters[1:] else None
            if flag in GH_PR_CREATE_VALUE_FLAGS:
                if letters:
                    flags.append((flag, letters if after_equals is None else after_equals))
                else:
                    flags.append((flag, args[index] if index < len(args) else None))
                    index += 1
                break
            if flag not in GH_PR_CREATE_BOOLEAN_SHORT_FLAGS:
                break
            if after_equals is not None:
                flags.append((flag, after_equals))
                break
            flags.append((flag, None))
    return flags


def pr_target(words: Sequence[str], args: Sequence[str]) -> str | None:
    """The repository a gh pr create names, in gh's order: -R/--repo, then GH_REPO set for the
    command, then GH_REPO in the environment. None when it names none (design decision 1)."""
    target: str | None = None
    for flag, value in pr_create_flags(args):
        if flag in ("-R", "--repo"):
            target = value or ""
    if target is not None:
        return target
    for word in words:
        variable, equals, value = word.partition("=")
        if not equals or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", variable):
            break
        if variable == "GH_REPO":
            target = value
    return target if target is not None else os.environ.get("GH_REPO")


def targets_this_repository(target: str | None, remotes: Iterable[str]) -> bool:
    """Whether a PR's target is this repository. A target that isn't named or can't be read, or
    a clone with no readable remote, counts as this repository (design decisions 2 and 4)."""
    if target is None:
        return True
    named = normalise_repository(target)
    ours = {repository for url in remotes if (repository := normalise_repository(url))}
    return named is None or not ours or named in ours


def pr_closes_issue(words: Sequence[str], cwd: Path) -> Decision:
    program, args = _program(words)
    if program != "gh" or args[:2] != ["pr", "create"]:
        return ALLOW
    rest = args[2:]
    target = pr_target(words, rest)
    if not targets_this_repository(target, remote_urls(cwd) if target is not None else ()):
        return ALLOW
    body: str | None = None
    problem = "the pull request's description doesn't close an issue."
    fix = "Add a line like 'Closes #22' to the description (--body or --body-file)."
    for name, value in pr_create_flags(rest):
        if name in ("-f", "--fill", "--fill-first", "--fill-verbose"):
            body = None
            problem = "--fill writes the description from commits, so it can't be checked."
            fix = "Pass the description with --body or --body-file, including 'Closes #<issue>'."
            break
        if name in ("-b", "--body"):
            body = value or ""
        elif name in ("-F", "--body-file"):
            path = "-" if value is None else value
            if path == "-":
                body = None
                problem = "a description read from stdin can't be checked before it's sent."
                fix = "Write the description to a file and pass it with --body-file."
                break
            file = Path(path) if Path(path).is_absolute() else cwd / path
            if file.is_file():
                body = file.read_text(encoding="utf-8")
            else:
                body = None
                problem = f"the body file '{path}' doesn't exist when the command starts."
                fix = (
                    "Write the file in an earlier, separate command, and name it with a literal "
                    "path: shell variables aren't expanded before the check."
                )
                break
    if body is None and problem.startswith("the pull request's"):
        problem = "the pull request has no description, so it closes no issue."
    if body is not None and CLOSING.search(body):
        return ALLOW
    if body is not None and SHELL_EXPANSION.search(body):
        # Quoting is gone by now, so literal '$HOME' gets this message too: the fix still works
        # (refuse-substituted-pr-body design D1, D2).
        problem = (
            "a description built by the shell ($VAR, $(...) or backticks) can't be checked "
            "before it's sent."
        )
        fix = (
            "Write the description to a file in an earlier, separate command, and pass it with "
            "--body-file and a literal path, including 'Closes #<issue>'."
        )
    return Decision("pr-closes-issue", problem, fix)


# The gh allow-list (spec: development-workflow, "Agents don't act as the owner" and "Agents' gh
# commands are allow-listed"; refuse-admin-merge design D1-D5). Every gh command in a session is
# classified against this table. Its evidence is a survey of the gh commands agents ran in 13
# earlier sessions (design D4). To allow something new, add it here, by pull request.

GH_READS = frozenset(
    {
        ("pr", "view"), ("pr", "list"), ("pr", "checks"), ("pr", "diff"), ("pr", "status"),
        ("issue", "view"), ("issue", "list"), ("issue", "status"),
        ("run", "list"), ("run", "view"), ("run", "watch"), ("run", "download"),
        ("repo", "view"), ("repo", "list"), ("repo", "clone"),
        ("label", "list"),
        ("project", "view"), ("project", "list"), ("project", "item-list"),
        ("project", "field-list"),
        ("workflow", "list"), ("workflow", "view"),
        ("release", "list"), ("release", "view"),
        ("secret", "list"), ("variable", "list"),
        ("ruleset", "list"), ("ruleset", "view"), ("ruleset", "check"),
        ("auth", "status"),
    }
)  # fmt: skip
GH_WORKFLOW_WRITES = frozenset(
    {
        ("pr", "create"), ("pr", "edit"), ("pr", "ready"), ("pr", "close"), ("pr", "reopen"),
        ("pr", "comment"), ("pr", "checkout"), ("pr", "merge"),
        ("issue", "create"), ("issue", "comment"), ("issue", "edit"), ("issue", "close"),
        ("issue", "reopen"),
        ("project", "item-add"), ("project", "item-edit"), ("project", "item-archive"),
        ("workflow", "run"), ("run", "rerun"), ("run", "cancel"),
    }
)  # fmt: skip
# What the hook grants, so it runs without a prompt or auto mode's check (guard-grants-gh
# design D1). A grant skips auto mode's classifier entirely, so this is narrower than the
# allow-list: merging, checking out, starting or stopping runs, and reads that write local files
# anywhere keep Claude Code's own check, and so does gh api.
GH_NOT_GRANTED = frozenset(
    {("pr", "merge"), ("pr", "checkout"), ("workflow", "run"), ("run", "rerun"), ("run", "cancel"),
     ("run", "download"), ("repo", "clone")}
)  # fmt: skip
GH_GRANTED = (GH_READS | GH_WORKFLOW_WRITES) - GH_NOT_GRANTED
GH_OWNER_ONLY = {
    ("secret", "set"): "admin", ("secret", "delete"): "admin",
    ("variable", "set"): "admin", ("variable", "delete"): "admin",
    ("repo", "create"): "admin", ("repo", "edit"): "admin", ("repo", "rename"): "admin",
    ("repo", "archive"): "admin", ("repo", "unarchive"): "admin", ("repo", "delete"): "admin",
    ("repo", "transfer"): "admin",
    ("issue", "transfer"): "admin", ("issue", "delete"): "admin",
    ("label", "create"): "admin", ("label", "edit"): "admin", ("label", "delete"): "admin",
    ("label", "clone"): "admin",
    ("project", "create"): "admin", ("project", "delete"): "admin", ("project", "edit"): "admin",
    ("project", "close"): "admin", ("project", "copy"): "admin", ("project", "link"): "admin",
    ("project", "unlink"): "admin", ("project", "mark-template"): "admin",
    ("project", "field-create"): "admin", ("project", "field-delete"): "admin",
    ("auth", "token"): "credentials", ("auth", "login"): "credentials",
    ("auth", "logout"): "credentials", ("auth", "refresh"): "credentials",
    ("auth", "switch"): "credentials", ("auth", "setup-git"): "credentials",
}  # fmt: skip

_SEG = r"[^/]+"
_REPO = rf"repos/{_SEG}/{_SEG}"
_WRITES = frozenset({"POST", "PUT", "PATCH", "DELETE"})
GH_API_WORKFLOW_WRITES = tuple(
    (re.compile(pattern), frozenset(methods))
    for pattern, methods in (
        (rf"{_REPO}/issues/{_SEG}/comments", {"POST"}),
        (rf"{_REPO}/issues/{_SEG}/labels(/{_SEG})?", {"POST", "DELETE"}),
        (rf"{_REPO}/issues/{_SEG}/sub_issues", {"POST"}),
        (rf"{_REPO}/issues/{_SEG}/sub_issue", {"DELETE"}),
        (rf"{_REPO}/issues/{_SEG}", {"PATCH"}),
        (rf"{_REPO}/pulls/{_SEG}/comments", {"POST"}),
        (rf"{_REPO}/pulls/{_SEG}/reviews", {"POST"}),
    )
)
GH_API_OWNER_ONLY = tuple(
    (re.compile(pattern), group)
    for pattern, group in (
        (rf"{_REPO}/pulls/{_SEG}/merge", "merge"),
        (rf"{_REPO}/actions/runs/{_SEG}/pending_deployments", "deployment"),
        (rf"({_REPO}|orgs/{_SEG})/rulesets(/.*)?", "gates"),
        (rf"{_REPO}/branches/.+/protection(/.*)?", "gates"),
        (rf"{_REPO}/environments(/.*)?", "gates"),
        (rf"{_REPO}", "admin"),
        (
            rf"{_REPO}/(pages|labels|collaborators|private-vulnerability-reporting|hooks)(/.*)?",
            "admin",
        ),
        (rf"orgs/{_SEG}", "admin"),
        (rf"orgs/{_SEG}/(issue-types|members|teams)(/.*)?", "admin"),
        (r".*/(secrets|variables)(/.*)?", "admin"),
    )
)
# Every everyday write has one way to do it, its gh command, so no GraphQL mutation is allowed
# (guard-issue-mutations design D1). Add one here only for a write gh can't do.
GH_MUTATIONS_ALLOWED: frozenset[str] = frozenset()
# The gh command that does what a refused mutation does, named in its refusal's fix (design D2).
# Only commands the guard allows; a mutation whose gh command is refused or owner-only has no entry.
# Each name was checked against GitHub's GraphQL schema on 2026-10-13.
GH_MUTATION_EQUIVALENTS: dict[str, tuple[str, ...]] = {
    "updateIssue": ("gh issue edit <n>", "gh issue close <n>", "gh issue reopen <n>"),
    "updateIssueIssueType": ("gh issue edit <n> --type <name>",),
    "addBlockedBy": ("gh issue edit <n> --add-blocked-by <m>",),
    "removeBlockedBy": ("gh issue edit <n> --remove-blocked-by <m>",),
    "addSubIssue": ("gh issue edit <n> --add-sub-issue <m>",),
    "removeSubIssue": ("gh issue edit <n> --remove-sub-issue <m>",),
    "addComment": ("gh issue comment <n>", "gh pr comment <n>"),
    "addProjectV2ItemById": ("gh project item-add <number> --owner <org> --url <url>",),
    "updateProjectV2ItemFieldValue": (
        "gh project item-edit --id <item> --field-id <field> --project-id <project> --text <value>",
    ),
    "addLabelsToLabelable": (
        "gh issue edit <n> --add-label <name>", "gh pr edit <n> --add-label <name>",
    ),
    "removeLabelsFromLabelable": (
        "gh issue edit <n> --remove-label <name>", "gh pr edit <n> --remove-label <name>",
    ),
    "addAssigneesToAssignable": (
        "gh issue edit <n> --add-assignee <login>", "gh pr edit <n> --add-assignee <login>",
    ),
    "removeAssigneesFromAssignable": (
        "gh issue edit <n> --remove-assignee <login>", "gh pr edit <n> --remove-assignee <login>",
    ),
    "closeIssue": ("gh issue close <n>",),
    "reopenIssue": ("gh issue reopen <n>",),
    "createIssue": ("gh issue create --title <title> --body-file <file>",),
    "closePullRequest": ("gh pr close <n>",),
    "reopenPullRequest": ("gh pr reopen <n>",),
    "markPullRequestReadyForReview": ("gh pr ready <n>",),
    "convertPullRequestToDraft": ("gh pr ready <n> --undo",),
    "updatePullRequest": ("gh pr edit <n>",),
    "createPullRequest": ("gh pr create --title <title> --body-file <file>",),
}  # fmt: skip
GH_MUTATIONS_OWNER_ONLY = {
    "mergePullRequest": "merge",
    "approveDeployments": "deployment", "rejectDeployments": "deployment",
    "createRepositoryRuleset": "gates", "updateRepositoryRuleset": "gates",
    "deleteRepositoryRuleset": "gates",
    "createBranchProtectionRule": "gates", "updateBranchProtectionRule": "gates",
    "deleteBranchProtectionRule": "gates",
    "updateProjectV2Field": "admin",
}  # fmt: skip

# Throwaway repositories (design D2): any write by an agent, but only infra-probe-* may be deleted,
# and archiving, unarchiving or deleting the others' records is the owner's.
THROWAWAY_OWNER = "troupe-run"
THROWAWAY_DELETABLE = ("infra-probe-",)
THROWAWAY_KEPT = ("spike-", "bakeoff-")
# gh's own command groups that act on one repository, so a throwaway target can exempt them.
# Anything else (an extension, an alias) is never exempt: what it does can't be known here.
GH_REPO_GROUPS = frozenset(
    {"api", "pr", "issue", "release", "repo", "run", "workflow", "secret", "variable", "label",
     "ruleset", "cache"}
)  # fmt: skip

GH_API_VALUE_FLAGS = frozenset(
    {"-X", "--method", "-f", "--raw-field", "-F", "--field", "-H", "--header", "--input", "-q",
     "--jq", "-t", "--template", "--hostname", "--cache", "-p", "--preview"}
)  # fmt: skip
GH_REPO_VALUE_FLAGS = GH_PR_CREATE_VALUE_FLAGS | GH_API_VALUE_FLAGS

OWNER_ONLY_MESSAGES = {
    "merge": (
        "only the owner merges past a pull request's rules.",
        "Ask the owner to merge it, or fix what blocks it.",
    ),
    "deployment": (
        "only the owner approves or rejects a deployment.",
        "Tell the owner the run is waiting, with its link.",
    ),
    "gates": (
        "only the owner changes a ruleset, branch protection or an environment.",
        "Change it in troupe-run/infrastructure through a pull request, or ask the owner.",
    ),
    "admin": (
        "only the owner changes the org's or a repository's administration.",
        "Change it in troupe-run/infrastructure through a pull request, or ask the owner.",
    ),
    "credentials": (
        "agents don't handle the login's credentials.",
        "Use gh itself; if something needs the token, ask the owner.",
    ),
}
NOT_LISTED_FIX = (
    "Ask the owner, or add it to the list in troupe-run/infrastructure (scripts/guard.py). "
    "A read with fields needs -X GET."
)


def _flag_value(rest: Sequence[str], index: int, word: str) -> tuple[str, bool]:
    """The value of the flag at rest[index], and whether it used the next word."""
    _, equals, inline = word.partition("=")
    if equals:
        return inline, False
    return (rest[index + 1] if index + 1 < len(rest) else ""), True


def _gh_repository(words: Sequence[str], call_args: Sequence[str]) -> str | None:
    """The repository a gh command names: -R/--repo, else GH_REPO set for the command (D2)."""
    index = 0
    while index < len(call_args):
        word = call_args[index]
        name = word.partition("=")[0]
        if name in ("-R", "--repo"):
            return _flag_value(call_args, index, word)[0]
        if word.startswith("-R") and len(word) > 2 and "=" not in word:
            return word[2:]
        if word in GH_REPO_VALUE_FLAGS:
            index += 1
        index += 1
    for word in words:
        variable, equals, value = word.partition("=")
        if not equals or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", variable):
            break
        if variable == "GH_REPO":
            return value
    return None


def _positionals(rest: Sequence[str], value_flags: frozenset[str]) -> list[str]:
    out: list[str] = []
    index = 0
    while index < len(rest):
        word = rest[index]
        if word.startswith("-"):
            if "=" not in word and word in value_flags:
                index += 1
        else:
            out.append(word)
        index += 1
    return out


def throwaway_kind(repository: str | None) -> str | None:
    """'deletable' for troupe-run/infra-probe-*, 'kept' for troupe-run/spike-* and bakeoff-*."""
    named = normalise_repository(repository) if repository else None
    if named is None or named[0] != "github.com" or named[1] != THROWAWAY_OWNER:
        return None
    if named[2].startswith(THROWAWAY_DELETABLE):
        return "deletable"
    if named[2].startswith(THROWAWAY_KEPT):
        return "kept"
    return None


def _api_fields(rest: Sequence[str]) -> list[tuple[str, bool]]:
    """Each -f/-F/--raw-field/--field value as (key=value, typed): -F and --field read @files."""
    fields: list[tuple[str, bool]] = []
    for index, word in enumerate(rest):
        if word in ("-f", "-F", "--raw-field", "--field"):
            value = rest[index + 1] if index + 1 < len(rest) else ""
            fields.append((value, word in ("-F", "--field")))
        elif word.startswith(("--raw-field=", "--field=")):
            fields.append((word.partition("=")[2], word.startswith("--field=")))
        elif re.fullmatch(r"-[fF].+", word):
            fields.append((word[2:], word[1] == "F"))
    return fields


def _api_method(rest: Sequence[str]) -> str:
    """gh's rule: -X/--method if given, else POST when it sends fields or --input, else GET."""
    for index, word in enumerate(rest):
        name = word.partition("=")[0]
        if name in ("-X", "--method"):
            return _flag_value(rest, index, word)[0].upper()
        if word.startswith("-X") and len(word) > 2:
            return word[2:].upper()
    sends_input = any(word.partition("=")[0] == "--input" for word in rest)
    return "POST" if _api_fields(rest) or sends_input else "GET"


def _api_endpoint(rest: Sequence[str]) -> str:
    positionals = _positionals(rest, GH_API_VALUE_FLAGS)
    endpoint = positionals[0] if positionals else ""
    endpoint = re.sub(r"^https?://api\.github\.com/", "", endpoint, flags=re.IGNORECASE)
    return endpoint.lstrip("/").split("?", 1)[0].rstrip("/").lower()


def _graphql_queries(rest: Sequence[str], cwd: Path) -> list[str] | None:
    """Every GraphQL query a gh api graphql command sends; None if one can't be read first."""
    queries: list[str] = []
    for value, typed in _api_fields(rest):
        key, _, content = value.partition("=")
        if key != "query":
            continue
        if typed and content.startswith("@"):
            text = _read_named(content[1:], cwd)
            if text is None:
                return None
            queries.append(text)
        else:
            queries.append(content)
    for index, word in enumerate(rest):
        if word.partition("=")[0] != "--input":
            continue
        text = _read_named(_flag_value(rest, index, word)[0], cwd)
        if text is None:
            return None
        try:
            body = json.loads(text)
        except ValueError:
            return None
        query = body.get("query") if isinstance(body, dict) else None
        if not isinstance(query, str):
            return None
        queries.append(query)
    return queries or None


def _read_named(path: str, cwd: Path) -> str | None:
    if path in ("", "-"):
        return None
    file = Path(path) if Path(path).is_absolute() else cwd / path
    try:
        return file.read_text(encoding="utf-8")
    except OSError:
        return None


def graphql_mutations(query: str) -> list[str] | None:
    """The top-level fields of every mutation in a GraphQL document; [] when it has none.

    A small scanner, not a parser: strings and comments are skipped, and a field at depth one of a
    `mutation` operation is a mutation. Returns None if the braces don't balance.
    """
    pieces = re.findall(r'"""(?:.|\n)*?"""|"(?:\\.|[^"\\])*"|#[^\n]*|[A-Za-z_]\w*|[{}()]|:', query)
    mutations: list[str] = []
    depth = 0
    parens = 0
    in_mutation = False
    pending: str | None = None
    for piece in pieces:
        if piece.startswith(('"', "#")):
            continue
        if piece == "(":
            parens += 1
        elif piece == ")":
            parens -= 1
        elif parens:
            continue
        elif piece == "{":
            if depth == 0 and pending is not None:
                in_mutation = pending == "mutation"
            elif depth == 0:
                in_mutation = False
            depth += 1
            pending = None
        elif piece == "}":
            depth -= 1
            if depth < 0:
                return None
        elif depth == 0 and piece in ("query", "mutation", "subscription", "fragment"):
            pending = piece
        elif depth == 1 and in_mutation and piece != ":":
            mutations.append(piece)
    if depth != 0 or parens != 0:
        return None
    # An alias (`alias: field`) names two pieces; the field is the second, so keep both: an alias
    # that matches a listed name can't hide an unlisted field after it.
    return mutations


def _owner_only(group: str) -> Decision:
    problem, fix = OWNER_ONLY_MESSAGES[group]
    return Decision("owner-only", problem, fix)


def _not_listed(what: str) -> Decision:
    return Decision("gh-allow-list", f"{what} isn't on the guard's gh allow-list.", NOT_LISTED_FIX)


def _not_listed_mutations(names: Sequence[str]) -> Decision:
    """Refuse unlisted GraphQL mutations by name, with the gh command for each that has one."""
    unique = list(dict.fromkeys(names))
    if len(unique) == 1:
        problem = f"GraphQL mutation {unique[0]} isn't on the guard's gh allow-list."
    else:
        problem = f"GraphQL mutations {', '.join(unique)} aren't on the guard's gh allow-list."
    hints = [
        f"For {name}, run {' or '.join(GH_MUTATION_EQUIVALENTS[name])}, which the guard allows."
        for name in unique
        if name in GH_MUTATION_EQUIVALENTS
    ]
    fix = "Ask the owner, or add it to the list in troupe-run/infrastructure (scripts/guard.py)."
    return Decision("gh-allow-list", problem, " ".join([*hints, fix]))


def _classify_api(rest: Sequence[str], cwd: Path) -> tuple[str, str | None, str | None, list[str]]:
    """('allow' | 'owner' | 'unlisted' | 'unreadable', owner group, repository, the unlisted
    GraphQL mutations) for a gh api call."""
    endpoint = _api_endpoint(rest)
    method = _api_method(rest)
    repo_match = re.match(rf"repos/({_SEG}/{_SEG})", endpoint)
    repository = repo_match.group(1) if repo_match else None
    if endpoint == "graphql":
        queries = _graphql_queries(rest, cwd)
        if queries is None:
            return "unreadable", None, None, []
        names: list[str] = []
        for query in queries:
            found = graphql_mutations(query)
            if found is None:
                return "unreadable", None, None, []
            names.extend(found)
        for name in names:
            if name in GH_MUTATIONS_OWNER_ONLY:
                return "owner", GH_MUTATIONS_OWNER_ONLY[name], None, []
        unlisted = [name for name in names if name not in GH_MUTATIONS_ALLOWED]
        if not unlisted:
            return "allow", None, None, []
        return "unlisted", None, None, unlisted
    if method in ("GET", "HEAD"):
        return "allow", None, repository, []
    for pattern, group in GH_API_OWNER_ONLY:
        if pattern.fullmatch(endpoint) and method in _WRITES:
            return "owner", group, repository, []
    for pattern, methods in GH_API_WORKFLOW_WRITES:
        if pattern.fullmatch(endpoint) and method in methods:
            return "allow", None, repository, []
    return "unlisted", None, repository, []


def gh_decision(words: Sequence[str], cwd: Path) -> Decision:
    """Classify one gh command against the allow-list: owner-only first, then gh-allow-list."""
    program, args = _program(words)
    if program != "gh":
        return ALLOW
    leading = 0
    while leading < len(args) and args[leading].startswith("-"):
        if args[leading] in ("--version", "-h", "--help"):
            return ALLOW
        leading += 1
    if leading >= len(args):
        return ALLOW
    group = args[leading]
    call_args = args[leading + 1 :]
    if group == "help":
        return ALLOW
    if group == "search":
        return ALLOW
    if group == "api":
        verdict, owner_group, repository, mutations = _classify_api(call_args, cwd)
        repository = repository or _gh_repository(words, call_args)
        kind = throwaway_kind(repository)
        if verdict == "allow":
            return ALLOW
        if verdict == "unreadable":
            return Decision(
                "gh-allow-list",
                "a GraphQL query read from stdin, from a file that doesn't exist yet, or that "
                "doesn't parse can't be checked.",
                "Pass the query with -f query=..., or write it to a file in an earlier command.",
            )
        if kind is not None:
            endpoint = _api_endpoint(call_args)
            repo_itself = re.fullmatch(_REPO, endpoint) is not None
            if not (kind == "kept" and repo_itself and _api_method(call_args) in _WRITES):
                return ALLOW
        if verdict == "owner" and owner_group is not None:
            return _owner_only(owner_group)
        if mutations:
            return _not_listed_mutations(mutations)
        return _not_listed(f"gh api {_api_method(call_args)} {_api_endpoint(call_args) or '?'}")
    sub = call_args[0] if call_args and not call_args[0].startswith("-") else None
    rest = call_args[1:] if sub is not None else call_args
    key = (group, sub or "")
    if key == ("auth", "status") and any(
        word in ("-t", "--show-token") or word.startswith("--show-token=") for word in rest
    ):
        return _owner_only("credentials")
    if key == ("pr", "merge") and any(
        word == "--admin"
        or (word.startswith("--admin=") and word[8:].lower() not in ("false", "0"))
        for word in rest
    ):
        return ALLOW if throwaway_kind(_gh_repository(words, rest)) else _owner_only("merge")
    if key in GH_READS or key in GH_WORKFLOW_WRITES:
        return ALLOW
    repository = _gh_repository(words, rest)
    if group == "repo" and sub in ("create", "delete", "archive", "unarchive", "edit", "rename"):
        positional = _positionals(rest, GH_REPO_VALUE_FLAGS)
        if positional and sub != "rename":
            repository = positional[0]
    kind = throwaway_kind(repository)
    if kind is not None and group in GH_REPO_GROUPS:
        keeps_record = group == "repo" and sub in ("delete", "archive", "unarchive", "rename")
        if not (kind == "kept" and keeps_record):
            return ALLOW
    if key in GH_OWNER_ONLY:
        return _owner_only(GH_OWNER_ONLY[key])
    return _not_listed(f"gh {group}{' ' + sub if sub else ''}")


# Help requests (spec: development-workflow, "Agents' gh commands are allow-listed";
# refuse-substituted-pr-body design D4).

GH_BUILTIN_GROUPS = frozenset(
    {
        "agent-task", "alias", "api", "attestation", "auth", "browse", "cache", "codespace",
        "completion", "config", "copilot", "discussion", "extension", "gist", "gpg-key", "issue",
        "label", "licenses", "org", "pr", "preview", "project", "release", "repo", "ruleset", "run",
        "search", "secret", "skill", "ssh-key", "status", "variable", "workflow",
    }
)  # fmt: skip
"""gh's own command groups, from gh 2.102.0's `gh help` (CORE, GITHUB ACTIONS and ADDITIONAL
COMMANDS). ALIAS COMMANDS are left out: `co` is an alias, and an alias or extension runs its own
code with --help. When updating this for a new gh, check each new command for DisableFlagParsing:
one that hands its arguments to another program belongs in GH_HELP_FORWARDED."""
GH_HELP_FORWARDED = frozenset({("extension", "exec")})
"""Built-in commands that pass --help on to another program rather than printing help:
`gh extension exec <name>` runs the extension (gh 2.102.0, pkg/cmd/extension/command.go)."""
HELP_FLAGS = ("--help", "-h")


def gh_help_request(words: Sequence[str]) -> bool:
    """True for `gh <built-in group> [<word> ...] --help|-h`: no word before the help flag is a
    flag, so none can take it as a value, and gh prints help and runs nothing. A command that only
    mentions --help, or a group that isn't gh's own, is judged as the command it is."""
    program, args = _program(words)
    if program != "gh" or len(args) < 2 or args[-1] not in HELP_FLAGS:
        return False
    named = args[:-1]
    if any(word.startswith("-") for word in named) or named[0] not in GH_BUILTIN_GROUPS:
        return False
    return tuple(named[:2]) not in GH_HELP_FORWARDED


TAMPER = Decision(
    TAMPER_RULE,
    "agents can't grant themselves an override or touch the override files.",
    "Ask the owner. Only a person, in their own terminal, can grant an override.",
)


def guard_tamper(words: Sequence[str]) -> Decision:
    """Refuse a command that runs the override, or names a path in the override directory.

    Works on parsed words, so a commit message that merely mentions the override command (one
    quoted word containing spaces) isn't mistaken for running it.
    """
    for index, word in enumerate(words):
        runs_override = word.lower().endswith("guard.py") and words[index + 1 : index + 2] == [
            "override"
        ]
        names_override_path = GUARD_DIR in word.lower() and not re.search(r"\s", word)
        if runs_override or names_override_path:
            return TAMPER
    return ALLOW


def shell_decisions(command: str, cwd: Path) -> list[Decision]:
    text = strip_heredocs(command)
    try:
        simple_commands = split_command(command)
    except ValueError as error:
        if GUARD_DIR in text.lower() or re.search(r"guard\.py\S*\s+override\b", text.lower()):
            return [TAMPER]
        if not re.search(r"\b(git|gh)\b", text):
            return [ALLOW]
        return [
            Decision(
                "command-unparseable",
                f"this git or gh command couldn't be parsed ({error}), so the guardrails can't "
                "check it.",
                "Simplify the command: one git or gh step at a time, with balanced quotes.",
            )
        ]
    decisions: list[Decision] = []
    for words in simple_commands:
        tamper = guard_tamper(words)
        if tamper.refused:
            return [tamper]
        decisions.append(skip_hooks(words))
        if gh_help_request(words):
            continue  # it only prints help, whatever the command would be refused for
        decisions.append(pr_closes_issue(words, cwd))
        decisions.append(gh_decision(words, cwd))
    return decisions or [ALLOW]


# --- grants (guard-grants-gh design D2) ------------------------------------------------------

# Outside quotes, any of these makes a command more than one plain gh command: chaining,
# substitution, variables, redirection, globs, history, comments, escapes, subshells.
UNQUOTED_SHELL_SYNTAX = frozenset("$`\\<>|&;(){}*?[]~!#\n")
# Inside double quotes, these still expand.
DOUBLE_QUOTED_SHELL_SYNTAX = frozenset("$`")
# The flags of granted commands that read a local file and send its contents to GitHub. When gh
# is updated, look for new ones: a StringVarP whose help names a `file`, or attachments.AddFlag
# (refuse-substituted-pr-body design D6).
GH_FILE_FLAGS = ("--body-file", "-F", "--input", "--attach")


def _plain_shell_text(command: str) -> bool:
    """True if the command has no shell syntax beyond words and quotes (design D2)."""
    quote: str | None = None
    for char in command:
        if quote == "'":
            if char == "'":
                quote = None
        elif quote == '"':
            if char == '"':
                quote = None
            elif char in DOUBLE_QUOTED_SHELL_SYNTAX:
                return False
        elif char in "'\"":
            quote = char
        elif char in UNQUOTED_SHELL_SYNTAX:
            return False
    return quote is None


def _files_read(words: Sequence[str]) -> list[str] | None:
    """The local files a gh command's file flags name; None if one can't be known."""
    files: list[str] = []
    for index, word in enumerate(words):
        name, equals, inline = word.partition("=")
        if name not in GH_FILE_FLAGS:
            continue
        value = inline if equals else (words[index + 1] if index + 1 < len(words) else "")
        if value in ("", "-"):
            return None
        files.extend(_attachment_readings(value) if name == "--attach" else [value])
    return files


def _attachment_readings(value: str) -> list[str]:
    """Every file gh might read for `--attach <value>`: the whole value, or the part before any
    '#' but a leading one, whichever exists when gh runs (gh 2.102.0, internal/attachments)."""
    return [value, *(value[:index] for index, char in enumerate(value) if char == "#" and index)]


def _within(path: Path, *roots: Path) -> bool:
    resolved = path.resolve()
    return any(resolved.is_relative_to(root.resolve()) for root in roots)


def grantable(command: str, cwd: Path, root: Path) -> bool:
    """True if the hook may grant this Bash command: exactly one plain gh command in GH_GRANTED,
    refused by no rule, reading files only inside the repository or the temp directory (design D2).
    Anything unusual is no grant, and Claude Code decides as it would without the guard."""
    if not _plain_shell_text(command):
        return False
    try:
        words = shlex.split(command, posix=True)
    except ValueError:
        return False
    if len(words) < 3 or words[0] != "gh" or words[1].startswith("-") or words[2].startswith("-"):
        return False
    if (words[1], words[2]) not in GH_GRANTED:
        return False
    if any(decision.refused for decision in shell_decisions(command, cwd)):
        return False
    files = _files_read(words[3:])
    if files is None:
        return False
    temp = Path(tempfile.gettempdir())
    return all(_within(Path(f) if Path(f).is_absolute() else cwd / f, root, temp) for f in files)


def guard_is_reviewed(root: Path, running: Path = Path(__file__)) -> bool:
    """True if the running guard is byte-identical to scripts/guard.py on origin/main, so a guard
    edited on a branch can refuse but never grant (design D3). Any doubt is False."""
    try:
        here = git(root, "hash-object", "--", str(running))
        reviewed = git(root, "rev-parse", "--verify", "--quiet", "origin/main:scripts/guard.py")
    except (RuntimeError, OSError):
        return False
    return bool(here) and here == reviewed


def edit_decision(root: Path, file_path: str, branch: str | None) -> Decision:
    target = Path(file_path)
    target = target if target.is_absolute() else root / target
    resolved = target.resolve()
    real_root = root.resolve()
    if not resolved.is_relative_to(real_root):
        return ALLOW
    if ".git" in resolved.relative_to(real_root).parts:
        return Decision(
            TAMPER_RULE,
            "files under .git/ aren't edited directly; it holds the override files.",
            "Use git commands for repository state. Ask the owner for an override.",
        )
    relative = resolved.relative_to(real_root).as_posix()
    if relative in delivered_paths(read_working_tree(root)):
        return _delivered_refusal([relative], "this file is delivered")
    if matching_change(root, branch) is None:
        where = "main" if branch == "main" else f"branch '{branch}'"
        return Decision(
            "edit-branch-change",
            f"edits need an OpenSpec change matching the branch, and {where} has none.",
            "Create or switch to the branch named after the change (git switch -c <change-name> "
            "after /opsx:propose <change-name>).",
        )
    return ALLOW


# --- overrides -------------------------------------------------------------------------------


def _guard_dir(root: Path) -> Path:
    common = Path(git(root, "rev-parse", "--git-common-dir"))
    return (common if common.is_absolute() else root / common) / GUARD_DIR


def grant_override(root: Path, rule: str, reason: str) -> Path:
    if rule not in OVERRIDABLE_RULES:
        known = ", ".join(OVERRIDABLE_RULES)
        raise SystemExit(f"guard: '{rule}' isn't an overridable rule. Rules: {known}")
    if not reason.strip():
        raise SystemExit("guard: an override needs a reason.")
    granted_by = git(root, "config", "user.email", check=False)
    if not granted_by:
        raise SystemExit(
            "guard: no git user.email is set, so the override can't say who granted it."
        )
    directory = _guard_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    record = {
        "rule": rule,
        "reason": reason.strip(),
        "granted_by": granted_by,
        "granted_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    path = directory / "override.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def consume_override(root: Path, decision: Decision, action: str) -> bool:
    """Use a pending override for this refusal, if there is one. Returns True when allowed."""
    if decision.rule not in OVERRIDABLE_RULES:
        return False
    directory = _guard_dir(root)
    pending = directory / "override.json"
    if not pending.is_file():
        return False
    record = json.loads(pending.read_text(encoding="utf-8"))
    if record.get("rule") != decision.rule:
        return False
    pending.unlink()
    record["used_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    record["allowed"] = action
    with (directory / "overrides.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps(record) + "\n")
    return True


def first_refusal(root: Path, decisions: Iterable[Decision], action: str) -> Decision | None:
    for decision in decisions:
        if decision.refused and not consume_override(root, decision, action):
            return decision
    return None


# --- checking a range of commits (pre-push and CI) -------------------------------------------


def _is_null(sha: str) -> bool:
    return set(sha) == {"0"}


def commits_in_range(root: Path, base: str | None, head: str) -> list[str]:
    """Commits reachable from ``head`` but not ``base``. With no usable base, everything not on
    any remote-tracking branch (a branch being pushed for the first time)."""
    if base and not _is_null(base):
        result = subprocess.run(
            ["git", "rev-list", f"{base}..{head}"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            env=_git_env(),
        )
        if result.returncode == 0:
            return result.stdout.split()
    return git(root, "rev-list", head, "--not", "--remotes").split()


def nonconforming_commits(root: Path, commits: Iterable[str]) -> Decision:
    """The commit-message rule over many commits, naming each one that fails."""
    bad: list[str] = []
    for sha in commits:
        message = git(root, "log", "-1", "--format=%B", sha)
        if commit_message(message).refused:
            first = next((line for line in message.splitlines() if line.strip()), "")
            bad.append(f"{sha[:7]} '{first}'")
    if not bad:
        return ALLOW
    listed = "; ".join(bad[:5]) + (f"; and {len(bad) - 5} more" if len(bad) > 5 else "")
    return Decision(
        "commit-message",
        f"{len(bad)} commit(s) aren't Conventional Commits: {listed}.",
        "Reword them before they're shared: git commit --amend for the last commit, or git rebase "
        "with --exec / reword for earlier ones. Expected form: 'feat(cli): add --version'.",
    )


def delivered_changes_by_others(
    root: Path, commits: Iterable[str], delivered: frozenset[str]
) -> Decision:
    """The delivered-file rule over many commits: only the App's deliveries may change them."""
    bad: list[str] = []
    for sha in commits:
        if git(root, "log", "-1", "--format=%ae", sha) == DELIVERY_AUTHOR_EMAIL:
            continue
        changed = git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", sha).splitlines()
        touched = sorted(path for path in changed if path in delivered)
        if touched:
            bad.append(f"{sha[:7]} ({', '.join(touched)})")
    if not bad:
        return ALLOW
    return _delivered_refusal(bad, "commits not made by the delivery change delivered files")


def reserved_release_branch(branch: str | None, repository: str | None) -> bool:
    """A release-please branch in a repository where GitHub lets only the release App create or
    update it. The name is the whole test: who authored the commits isn't asked, because a pusher
    writes that, and GitHub sees the owner and their agents as one identity (#47;
    drop-forgery-resistance design D1). With no repository named, nothing is exempt."""
    return repository in RELEASE_REPOSITORIES and (branch or "").startswith(RELEASE_BRANCH_PREFIX)


def run_ci(
    root: Path,
    base: str | None,
    head: str,
    branch: str | None,
    title: str | None = None,
    repository: str | None = None,
) -> list[Decision]:
    """The git-level rules, re-checked on GitHub for a push or a pull request (design D11), and a
    pull request's title when there is one. The repository is the one the branch lives in, which
    decides whether a release branch's name exempts it from the branch rule (open-release-exemption
    design D2; drop-forgery-resistance design D1, #47)."""
    commits = commits_in_range(root, base, head)
    decisions = [nonconforming_commits(root, commits)]
    if title is not None:
        decisions.append(pr_title(title))
    if branch and branch != "main" and not reserved_release_branch(branch, repository):
        decisions.append(commit_branch_change(root, branch))
    changed: list[str] = []
    for sha in commits:
        changed += git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", sha).splitlines()

    def read_at_head(path: str) -> str | None:
        result = subprocess.run(
            ["git", "show", f"{head}:{path}"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            env=_git_env(),
        )
        return result.stdout if result.returncode == 0 else None

    decisions.append(unticked_archived_tasks(changed, read_at_head))

    def read_at_base(path: str) -> str | None:
        return read_at_head(path) if base is None else _show(root, base, path)

    # The list at the base as well as the head, so a range can't remove its own protection.
    delivered = delivered_paths(read_at_head) | delivered_paths(read_at_base)
    if delivered:
        decisions.append(delivered_changes_by_others(root, commits, delivered))
    return [decision for decision in decisions if decision.refused]


def _show(root: Path, revision: str, path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{revision}:{path}"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        env=_git_env(),
    )
    return result.stdout if result.returncode == 0 else None


# --- entry points ----------------------------------------------------------------------------


def run_pre_push(root: Path, refs: Iterable[str]) -> int:
    """git pre-push hook: stdin lines are '<local ref> <local sha> <remote ref> <remote sha>'."""
    for line in refs:
        parts = line.split()
        if len(parts) != 4:
            continue
        local_ref, local_sha, _, remote_sha = parts
        if _is_null(local_sha):
            continue  # deleting a remote branch sends no commits
        decision = nonconforming_commits(root, commits_in_range(root, remote_sha, local_sha))
        refusal = first_refusal(root, [decision], f"push {local_ref}")
        if refusal is not None:
            print(refusal.text(), file=sys.stderr)
            return 1
    return 0


class UnreadableTitleError(Exception):
    """A pull_request event whose payload has no string title: malformed input, not "no title"."""


class UnreadableHeadRepositoryError(Exception):
    """A pull_request event whose head repository is present but isn't an object with a string
    full_name: malformed input, not "no repository" (open-release-exemption design D2)."""


def _head_repository(pull_request: dict[str, object]) -> str | None:
    """The repository a pull request's branch lives in: a fork's name for a fork. None when the
    payload names none, as for a deleted fork, whose head.repo is null."""
    head = pull_request.get("head")
    repo = head.get("repo") if isinstance(head, dict) else None
    if repo is None:
        return None
    full_name = repo.get("full_name") if isinstance(repo, dict) else None
    if not isinstance(full_name, str):
        raise UnreadableHeadRepositoryError(
            os.environ.get("GITHUB_EVENT_PATH", "no GITHUB_EVENT_PATH")
        )
    return full_name


def _event_payload() -> dict[str, object]:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if event_path and Path(event_path).is_file():
        payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    return {}


def github_ci_inputs(
    root: Path,
) -> tuple[str | None, str, str | None, str | None, str | None]:
    """The range, branch, pull request title and the branch's repository for this GitHub Actions
    run (design D11; release-please-prs design D3; open-release-exemption design D2). A push has
    no title, and its repository is the run's; a pull request's is its head repository."""
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    payload = _event_payload()
    head = git(root, "rev-parse", "HEAD")
    if event == "pull_request":
        pull_request = payload.get("pull_request")
        title = pull_request.get("title") if isinstance(pull_request, dict) else None
        if not isinstance(title, str):
            raise UnreadableTitleError(os.environ.get("GITHUB_EVENT_PATH", "no GITHUB_EVENT_PATH"))
        base_branch = os.environ.get("GITHUB_BASE_REF", "main")
        base = git(root, "merge-base", f"origin/{base_branch}", head, check=False) or None
        repository = _head_repository(pull_request) if isinstance(pull_request, dict) else None
        return base, head, os.environ.get("GITHUB_HEAD_REF"), title, repository
    before = payload.get("before")
    branch = os.environ.get("GITHUB_REF_NAME")
    if not isinstance(before, str) or not before or _is_null(before):
        before = git(root, "merge-base", "origin/main", head, check=False) or None
    return before, head, branch, None, os.environ.get("GITHUB_REPOSITORY") or None


def run_ci_entry(
    root: Path,
    base: str | None,
    head: str | None,
    branch: str | None,
    title: str | None = None,
    repository: str | None = None,
) -> int:
    if head is None:
        try:
            base, head, branch, title, repository = github_ci_inputs(root)
        except UnreadableTitleError as error:
            refusal = Decision(
                "commit-message",
                f"couldn't read the pull request's title from the event payload ({error}).",
                "Re-run the check. If it fails again, the event payload is malformed: tell the "
                "owner, with the run's URL.",
            )
            print(refusal.text(), file=sys.stderr)
            return 1
        except UnreadableHeadRepositoryError as error:
            refusal = Decision(
                "commit-branch-change",
                "couldn't read the pull request's head repository from the event payload "
                f"({error}).",
                "Re-run the check. If it fails again, the event payload is malformed: tell the "
                "owner, with the run's URL.",
            )
            print(refusal.text(), file=sys.stderr)
            return 1
    refusals = run_ci(root, base, head, branch, title, repository)
    for refusal in refusals:
        print(refusal.text(), file=sys.stderr)
    if not refusals:
        print(f"guard: every rule passes for {branch or 'this range'}.")
    return 1 if refusals else 0


def run_pre_commit(root: Path) -> int:
    branch = current_branch(root)
    staged = git(root, "diff", "--cached", "--name-only").splitlines()

    def checks() -> Iterable[Decision]:
        yield commit_on_main(branch)
        yield commit_branch_change(root, branch)
        yield unticked_archived_tasks(staged, ReadStaged(root))
        # The list as committed as well as staged, so a commit can't remove its own protection.
        delivered = delivered_paths(ReadStaged(root)) | delivered_paths(
            lambda path: _show(root, "HEAD", path)
        )
        yield delivered_file_staged(staged, delivered)
        yield commit_checks(root)

    refusal = first_refusal(root, checks(), f"commit on {branch}")
    if refusal is not None:
        print(refusal.text(), file=sys.stderr)
        return 1
    return 0


def run_check_scope(root: Path, paths: Iterable[str], stdout: TextIO | None = None) -> int:
    """CI's entry to the commit hook's decision: `scope=` and `check-args=` for $GITHUB_OUTPUT.

    Reads the declaration from the working tree, which CI has checked out at the head. No paths
    means the full check; a malformed declaration fails and answers nothing (design D6).
    """
    out = sys.stdout if stdout is None else stdout
    text = read_working_tree(root)(CHECK_PATHS)
    try:
        scope = check_scope(paths, None if text is None else check_paths(text))
    except CheckPathsError as error:
        print(error.decision().text(), file=sys.stderr)
        return 1
    print(f"scope={scope.label}\ncheck-args={' '.join(scope.args)}", file=out)
    return 0


def run_commit_msg(root: Path, message_file: Path) -> int:
    message = message_file.read_text(encoding="utf-8")
    first = next((line for line in message.splitlines() if line.strip()), "")
    refusal = first_refusal(root, [commit_message(message)], f"commit message: {first}")
    if refusal is not None:
        print(refusal.text(), file=sys.stderr)
        return 1
    return 0


def run_claude_pre_tool_use(payload: dict[str, object], stdout: TextIO | None = None) -> int:
    out = sys.stdout if stdout is None else stdout
    tool = str(payload.get("tool_name", ""))
    tool_input = payload.get("tool_input")
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    cwd = Path(str(payload.get("cwd") or os.getcwd()))
    root = repo_root(cwd) if cwd.is_dir() else None
    if root is None:
        return 0
    decisions: list[Decision]
    action: str
    if tool in EDIT_TOOLS:
        file_path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
        if not file_path:
            return 0
        decisions = [edit_decision(root, file_path, current_branch(root))]
        action = f"{tool} {file_path}"
    elif tool in SHELL_TOOLS:
        command = str(tool_input.get("command", ""))
        decisions = shell_decisions(command, cwd)
        action = f"{tool}: {command[:200]}"
    else:
        return 0
    refusal = first_refusal(root, decisions, action)
    if refusal is not None:
        deny = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": refusal.text(),
            }
        }
        print(json.dumps(deny), file=out)
        return 0
    # A grant comes only after every refusal, never for an override-excused command (grantable
    # re-reads the rules), and only from the reviewed guard (design D4).
    command = str(tool_input.get("command", ""))
    if tool == "Bash" and grantable(command, cwd, root) and guard_is_reviewed(root):
        words = shlex.split(command, posix=True)
        allow = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "permissionDecisionReason": (
                    f"guard: gh {words[1]} {words[2]} is on the guard's allow-list (granted)."
                ),
            }
        }
        print(json.dumps(allow), file=out)
    return 0


WORKFLOW_SUMMARY = (
    "This repository's workflow is enforced by guardrails ("
    f"https://github.com/{SOURCE_REPOSITORY}/blob/main/docs/development-workflow.md): "
    "issue -> OpenSpec change (/opsx:propose) on a branch named after the change -> "
    "/opsx:apply -> PR that closes the issue -> archive on the branch -> merge -> comment on and "
    "close the issue. Conventional Commits; scripts/check.py passes before every commit. "
    "When a guardrail refuses, follow its fix; don't work around it. Only the owner can grant "
    "an override."
)


def activate_hooks(root: Path) -> str | None:
    """Turn the repository's git hooks on if they aren't; return a notice when it changed them, or
    when git would skip one of them.

    The one place hook activation lives: the session-start hook and scripts/check.py both call it.
    """
    notices = []
    configured = git(root, "config", "--get", "core.hooksPath", check=False)
    if configured != HOOKS_PATH:
        git(root, "config", "core.hooksPath", HOOKS_PATH)
        notices.append(
            f"Activated the repository's git hooks (core.hooksPath was "
            f"{configured or 'unset'}; now {HOOKS_PATH})."
        )
    notices += skipped_hook_notices(root)
    return " ".join(notices) or None


def skipped_hook_notices(root: Path) -> list[str]:
    """A notice for each hook git skips because it isn't executable (spec: development-workflow).

    Only a notice: refusing would block a repository whose fix is made elsewhere, and changing the
    mode here would leave a change in the clone. Git for Windows has no executable bit; it runs a
    hook that starts with #!, so there is nothing to report there (executable-hooks design D6).
    """
    hooks = root / HOOKS_PATH
    if os.name == "nt" or not hooks.is_dir():
        return []
    delivered = delivered_paths(read_working_tree(root))
    notices = []
    for hook in sorted(hooks.iterdir()):
        if not hook.is_file() or os.access(hook, os.X_OK):
            continue
        path = f"{HOOKS_PATH}/{hook.name}"
        if path in delivered:
            fix = (
                f"It's delivered from {SOURCE_REPOSITORY}, where the next plan sets its mode; "
                "don't change it here."
            )
        else:
            fix = f"Make it executable: git update-index --chmod=+x {path}, then commit."
        notices.append(f"Git skips {path}: it isn't executable. {fix}")
    return notices


def run_claude_session_start(root: Path, stdout: TextIO | None = None) -> int:
    out = sys.stdout if stdout is None else stdout
    notes: list[str] = []
    activated = activate_hooks(root)
    if activated is not None:
        notes.append(activated)
    branch = current_branch(root)
    change = matching_change(root, branch)
    if change is not None:
        notes.append(
            f"Branch '{branch}' matches the OpenSpec change "
            f"{change.relative_to(root).as_posix()}: edits and commits are allowed."
        )
    else:
        notes.append(
            f"Branch '{branch}' has no matching OpenSpec change: edits and commits will be "
            "refused until you switch to, or create, the change's branch."
        )
    context = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": " ".join([WORKFLOW_SUMMARY, *notes]),
        }
    }
    print(json.dumps(context), file=out)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="guard.py", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="entry", required=True, metavar="ENTRY")
    sub.add_parser("pre-commit", help="git pre-commit hook")
    message = sub.add_parser("commit-msg", help="git commit-msg hook")
    message.add_argument("message_file")
    sub.add_parser("claude-pre-tool-use", help="Claude Code PreToolUse hook (JSON on stdin)")
    sub.add_parser("claude-session-start", help="Claude Code SessionStart hook")
    push = sub.add_parser("pre-push", help="git pre-push hook (refs on stdin)")
    push.add_argument("remote", nargs="?", help="passed by git; not needed")
    push.add_argument("url", nargs="?", help="passed by git; not needed")
    ci = sub.add_parser("ci", help="re-check a push or pull request on GitHub")
    ci.add_argument("--base", help="exclusive start of the range (default: from GitHub)")
    ci.add_argument("--head", help="end of the range (default: from GitHub)")
    ci.add_argument("--branch", help="branch the range belongs to (default: from GitHub)")
    ci.add_argument("--title", help="a pull request's title to check (default: from GitHub)")
    ci.add_argument(
        "--repository",
        help="owner/name of the repository the branch lives in (default: from GitHub)",
    )
    sub.add_parser(
        "check-scope", help="what changed paths (stdin) need from scripts/check.py, for CI"
    )
    grant = sub.add_parser("override", help="grant one override (a person, in a terminal)")
    grant.add_argument("rule", choices=OVERRIDABLE_RULES)
    grant.add_argument("--reason", required=True)
    args = parser.parse_args(argv)

    if args.entry == "claude-pre-tool-use":
        return run_claude_pre_tool_use(json.loads(sys.stdin.read() or "{}"))
    start = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    root = repo_root(start)
    if root is None:
        print("guard: not inside a git repository.", file=sys.stderr)
        return 1
    if args.entry == "pre-commit":
        return run_pre_commit(root)
    if args.entry == "commit-msg":
        return run_commit_msg(root, Path(args.message_file))
    if args.entry == "claude-session-start":
        sys.stdin.read()
        return run_claude_session_start(root)
    if args.entry == "pre-push":
        return run_pre_push(root, sys.stdin.read().splitlines())
    if args.entry == "ci":
        return run_ci_entry(root, args.base, args.head, args.branch, args.title, args.repository)
    if args.entry == "check-scope":
        return run_check_scope(root, sys.stdin.read().splitlines())
    path = grant_override(root, args.rule, args.reason)
    print(f"guard: override granted for '{args.rule}' (one action). Recorded in {path.parent}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
