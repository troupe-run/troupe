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
import base64
import json
import os
import re
import shlex
import shutil
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
    "schema-commit-type",
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
OPENSPEC_RULE = "openspec-strict"
"""Fails the GitHub check when a spec or active change in scope fails OpenSpec's strict validation.
Checked only on GitHub, where no override is consumed, so it isn't overridable
(guard-strict-openspec design D5, D7)."""
RULES = (*OVERRIDABLE_RULES, TAMPER_RULE, OPENSPEC_RULE)

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
SCHEMA_PATHS = ("protocol/schemas/",)
"""Where a change must release: troupe's protocol schemas, which release on their own and whose
version troupe records (troupe-run/troupe#140). A repository without them is never refused for
this (protocol-schema-commit-types design D1, #122)."""
OPENSPEC_ALL_PATHS = frozenset({"scripts/guard.py", ".github/workflows/guard.yml"})
"""Paths whose change puts every spec and active change in openspec-strict's scope: they decide how
the validation runs and which OpenSpec version runs it (guard-strict-openspec design D3)."""
OPENSPEC_TIMEOUT_SECONDS = 60.0
"""How long OpenSpec's validation may run before openspec-strict fails, well inside the guard
job's 5 minutes (guard-strict-openspec design D2)."""
OPENSPEC_PIN = ".github/workflows/guard.yml"
"""Where the OpenSpec version the check installs is pinned, as OPENSPEC_VERSION (design D6)."""
GUARD_DIR = "troupe-guard"
CHECK_TIMEOUT_SECONDS = 600.0
"""How long the pre-commit check may run before the commit is refused. The default lives here
only; pass a different value to commit_checks to override it."""
COMMIT_TYPES = (
    "feat", "fix", "docs", "build", "ci", "test", "refactor", "perf", "style", "chore", "revert",
)  # fmt: skip
COMMIT_PATTERN = re.compile(rf"^({'|'.join(COMMIT_TYPES)})(\([a-z0-9][a-z0-9-]*\))?!?: \S")
RELEASING_TYPES = ("feat", "fix", "perf", "revert")
"""The types release-please releases for, besides a breaking change of any type: the visible
sections of DEFAULT_CHANGELOG_SECTIONS in its src/util/filter-commits.ts, which troupe doesn't
override (protocol-schema-commit-types design D2)."""
BREAKING_FOOTER = re.compile(r"^BREAKING[ -]CHANGE:", re.MULTILINE)
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
    if COMMIT_PATTERN.match(_conventional_subject(message)):
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


def _conventional_subject(message: str) -> str:
    """The first line a commit-message rule judges: comments dropped, and the subject a fixup,
    squash or amend names in place of the fixup's own."""
    lines = [line for line in message.splitlines() if not line.startswith("#")]
    target = next((line for line in lines if line.strip()), "")
    while target.startswith(AUTOSQUASH_PREFIXES):
        # git writes "fixup! <subject of the commit being fixed>": that subject must conform too.
        target = target.split(" ", 1)[1]
    return target


def schema_files(paths: Iterable[str]) -> list[str]:
    """The paths under SCHEMA_PATHS, sorted."""
    return sorted({path for path in paths if path.startswith(SCHEMA_PATHS)})


def schema_commit_type(message: str, paths: Iterable[str]) -> Decision:
    """Refuse a schema change under a type that releases nothing (#122; design D2, D6). A message
    that isn't a Conventional Commit has no type to judge: that is commit-message's refusal."""
    schemas = schema_files(paths)
    match = COMMIT_PATTERN.match(_conventional_subject(message))
    if not schemas or match is None:
        return ALLOW
    kind = match.group(1)
    # The match ends with the subject's first character, so the header is what comes before it.
    header = match.group(0)[:-1]
    breaking = header.endswith("!: ") or BREAKING_FOOTER.search(message) is not None
    if kind in RELEASING_TYPES or breaking:
        return ALLOW
    listed = ", ".join(schemas[:5]) + (f" and {len(schemas) - 5} more" if len(schemas) > 5 else "")
    return Decision(
        "schema-commit-type",
        f"this commit changes protocol schemas ({listed}) under type '{kind}', which releases "
        "nothing, so troupe would ship them under the old protocol version.",
        f"Use a type that releases: {', '.join(RELEASING_TYPES)}, e.g. 'fix(protocol): <what "
        "changed>'. A breaking change of any type is allowed too ('!' before the colon, or a "
        "BREAKING CHANGE: footer). If the rest of the work shouldn't release, commit the schema "
        "change on its own.",
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

# Reading a shell command (spec: development-workflow, "The rules reach every command a shell line
# runs"; read-nested-commands design D1-D4). The reader returns every simple command a Bash
# command would run: each outer command, then the commands nested in it. An outer command keeps
# each substitution's text in its word, so pr-closes-issue still sees a --body built by the shell.

HEREDOC_OPERATOR = re.compile(r"(?<!<)<<(?!<)(-?)[ \t]*((?:[\w-]|\\[\w-]|'[^'\n]*'|\"[^\"\n]*\")+)")
HEREDOC_MARK = "\x01"
SPAN_MARK = "\x02"
MARKED = re.compile(f"([{HEREDOC_MARK}{SPAN_MARK}])(\\d+)[{HEREDOC_MARK}{SPAN_MARK}]")
OPERATORS = ("&&", "||", "|&", ";", "|", "&", "\n", "(", ")")
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\[[^\]]*\])?\+?=")
ARRAY_START = re.compile(r"(?:^|\s)[A-Za-z_][A-Za-z0-9_]*(?:\[[^\]]*\])?\+?=$")
REDIRECTION = re.compile(r"^\d*(?:>>?|<>?|&>>?|>&|<&|>\|)(.*)$")
RESERVED_WORDS = frozenset({"!", "{", "}", "if", "then", "elif", "else", "while", "until", "do"})
MAX_DEPTH = 16
COMMAND_START = re.compile(r"^\s*$|(?:^|[\s;])(?:if|while|until|then|do|else|elif|!|\{|time)\s*$")
CASE_STATEMENT = re.compile(r"(?:^|[;&|(\n{]|\b(?:then|do|else))\s*case\s")

SHELL_WRAPPERS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "command": (frozenset({"-p"}), frozenset()),
    "builtin": (frozenset(), frozenset()),
    "exec": (frozenset({"-c", "-l"}), frozenset({"-a"})),
    "env": (
        frozenset({"-i", "-", "--ignore-environment"}),
        frozenset({"-u", "--unset", "-C", "--chdir"}),
    ),
    "nice": (frozenset(), frozenset({"-n", "--adjustment"})),
    "nohup": (frozenset(), frozenset()),
    "noglob": (frozenset(), frozenset()),
    "nocorrect": (frozenset(), frozenset()),
    # The shell's time keyword takes -p; /usr/bin/time (BSD and GNU) takes the rest.
    "time": (
        frozenset({"-p", "-l", "-a", "-h", "-v", "--verbose", "--portability", "--append"}),
        frozenset({"-o", "--output", "-f", "--format"}),
    ),
    "timeout": (
        frozenset({"--foreground", "--preserve-status", "-v", "--verbose"}),
        frozenset({"-s", "--signal", "-k", "--kill-after"}),
    ),
}  # fmt: skip
"""Programs that run the rest of their words as a command, as written (design D3): each maps to the
options it accepts without a value, and those that take one. `command -v`/`-V` only print, so they
are data. An option not listed here makes the command unreadable, so a wrong guess about a
wrapper's options can't skip past a git or gh word. `timeout` takes a duration after its options."""
SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ksh"})
"""Shells whose -c string, or stdin heredoc, is read as commands (design D3)."""
DATA_PROGRAMS = frozenset(
    {"echo", "printf", "which", "type", "whereis", "man", "grep", "egrep", "fgrep", "rg",
     "for", "select", "case", "done", "fi", "esac"}
)  # fmt: skip
"""Programs that never run a word they're given, so a git or gh word among their arguments only
names it (design D3, from the 2026-10-19 survey of agents' commands). A program earns a place here
only if no option of it runs one of its words. `command -v` and `command -V` are data too."""


@dataclass(frozen=True)
class _Heredoc:
    operator: str
    """As it reads once quotes are removed, such as `<<EOF` or `<<-EOF`."""
    raw: str
    """As written, such as `<<'EOF'`."""
    quoted: bool
    body: str


@dataclass
class ShellReading:
    """Every simple command a shell command would run, and what couldn't be read (design D1, D5)."""

    commands: list[list[str]]
    unreadable: list[str]


class _ShellReader:
    def __init__(self) -> None:
        self.heredocs: list[_Heredoc] = []
        self.spans: list[str] = []
        self.reading = ShellReading([], [])

    # Heredocs (design D4): bodies come out first, so they're never read as shell words.

    def take_heredocs(self, text: str) -> str:
        out: list[str] = []
        lines = text.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i]
            found: list[re.Match[str]] = []

            def mark(match: re.Match[str], found: list[re.Match[str]] = found) -> str:
                raw_word = match.group(2)
                word = re.sub(r"[\\'\"]", "", raw_word)
                if not re.fullmatch(r"[A-Za-z_][\w-]*", word):
                    return match.group(0)
                index = len(self.heredocs) + len(found)
                found.append(match)
                return f"{HEREDOC_MARK}{index}{HEREDOC_MARK}"

            out.append(HEREDOC_OPERATOR.sub(mark, line))
            i += 1
            for match in found:
                word = re.sub(r"[\\'\"]", "", match.group(2))
                quoted = word != match.group(2)
                body: list[str] = []
                while i < len(lines) and lines[i].strip() != word:
                    body.append(lines[i])
                    i += 1
                i += 1  # the delimiter line itself
                operator = f"<<{match.group(1)}{word}"
                self.heredocs.append(_Heredoc(operator, match.group(0), quoted, "\n".join(body)))
        return "\n".join(out)

    def _unmark(self, text: str, raw: bool) -> str:
        def restore(match: re.Match[str]) -> str:
            index = int(match.group(2))
            if match.group(1) == SPAN_MARK:
                return self.spans[index]
            heredoc = self.heredocs[index]
            return heredoc.raw if raw else heredoc.operator

        return MARKED.sub(restore, text)

    # Finding where nested text ends (design D2).

    @staticmethod
    def _backtick_end(text: str, start: int) -> int:
        i = start
        while i < len(text):
            if text[i] == "\\":
                i += 1
            elif text[i] == "`":
                return i + 1
            i += 1
        raise ValueError("an unclosed backtick")

    @classmethod
    def _closing(cls, text: str, start: int, opener: str = "(", depth: int = 1) -> int:
        """The index just after the bracket that closes the one before `start`."""
        closer = ")" if opener == "(" else "}"
        quote: str | None = None
        i = start
        while i < len(text):
            char = text[i]
            if quote == "'":
                if char == "'":
                    quote = None
            elif char == "\\":
                i += 1
            elif quote == '"':
                if char == '"':
                    quote = None
                elif text.startswith("$(", i):
                    i = cls._closing(text, i + 2) - 1
                elif char == "`":
                    i = cls._backtick_end(text, i + 1) - 1
            elif char in "'\"":
                quote = char
            elif char == "`":
                i = cls._backtick_end(text, i + 1) - 1
            elif opener == "{" and text.startswith("$(", i):
                i = cls._closing(text, i + 2) - 1
            elif char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
                if depth == 0:
                    return i + 1
            i += 1
        raise ValueError(f"an unclosed {'$(...)' if opener == '(' else '${...}'}")

    def _span(
        self, text: str, i: int, quote: str | None, word: str
    ) -> tuple[int, list[str]] | None:
        """If a substitution or other nested text starts at `i`, its end and the commands in it."""
        if text.startswith("$((", i):
            end = self._closing(text, i + 3, depth=2)
            return end, self.heredoc_substitutions(text[i + 3 : end - 2])
        if text.startswith("$(", i):
            end = self._closing(text, i + 2)
            return end, [text[i + 2 : end - 1]]
        if text.startswith("${", i):
            end = self._closing(text, i + 2, "{")
            return end, self.substitutions(text[i + 2 : end - 1])
        if text[i] == "`":
            end = self._backtick_end(text, i + 1)
            inner = re.sub(r"\\([`\\$])", r"\1", text[i + 1 : end - 1])
            return end, [inner]
        if quote is not None:
            return None
        if text.startswith("((", i) and COMMAND_START.search(word):  # an arithmetic command
            end = self._closing(text, i + 2, depth=2)
            return end, self.heredoc_substitutions(text[i + 2 : end - 2])
        if text[i] in "<>" and text.startswith("(", i + 1):
            end = self._closing(text, i + 2)
            return end, [text[i + 2 : end - 1]]
        if text.startswith("=(", i) and (not word or word[-1].isspace()):  # zsh's =(...)
            end = self._closing(text, i + 2)
            return end, [text[i + 2 : end - 1]]
        if text[i] == "(" and ARRAY_START.search(word):
            end = self._closing(text, i + 1)
            return end, self.substitutions(text[i + 1 : end - 1])
        return None

    # Splitting into simple commands (design D3's operators).

    def split(self, text: str) -> list[tuple[str, list[str]]]:
        """Each simple command's text, with nested text marked, and the commands nested in it."""
        pieces: list[tuple[str, list[str]]] = []
        current: list[str] = []
        nested: list[str] = []
        quote: str | None = None
        i = 0
        while i < len(text):
            char = text[i]
            if quote == "'":
                current.append(char)
                if char == "'":
                    quote = None
                i += 1
                continue
            if char == "\\" and i + 1 < len(text):
                current.append(text[i : i + 2])
                i += 2
                continue
            span = self._span(text, i, quote, "".join(current))
            if span is not None:
                end, inner = span
                self.spans.append(self._unmark(text[i:end], raw=True))
                current.append(f"{SPAN_MARK}{len(self.spans) - 1}{SPAN_MARK}")
                nested.extend(inner)
                i = end
                continue
            if quote == '"':
                current.append(char)
                if char == '"':
                    quote = None
                i += 1
                continue
            if char in "'\"":
                quote = char
                current.append(char)
                i += 1
                continue
            operator = next((op for op in OPERATORS if text.startswith(op, i)), None)
            redirects = operator == "&" and (
                (i > 0 and text[i - 1] in "<>") or text.startswith(">", i + 1)
            )
            if operator is None or redirects:
                current.append(char)
                i += 1
                continue
            pieces.append(("".join(current), nested))
            current, nested = [], []
            i += len(operator)
        if quote:
            raise ValueError("unbalanced quotes")
        pieces.append(("".join(current), nested))
        return pieces

    def words(self, piece: str) -> tuple[list[str], list[_Heredoc]]:
        marked = shlex.split(piece, posix=True)
        heredocs = [
            self.heredocs[int(m.group(2))]
            for word in marked
            for m in MARKED.finditer(word)
            if m.group(1) == HEREDOC_MARK
        ]
        return [self._unmark(word, raw=False) for word in marked], heredocs

    def substitutions(self, text: str) -> list[str]:
        """The commands substituted in text that isn't itself a command (arithmetic, ${...})."""
        return [inner for _, nested in self.split(text) for inner in nested]

    @staticmethod
    def heredoc_substitutions(body: str) -> list[str]:
        """The commands substituted in an unquoted heredoc's body, or in arithmetic: text where
        quotes are literal and only $(...), backticks and ${...} hold commands."""
        return _ShellReader._expand(body)[0]

    @staticmethod
    def _expand(body: str) -> tuple[list[str], str]:
        """`heredoc_substitutions`, and the body as the shell passes it on: each expansion is a
        word whose value isn't known, and the expansion's escapes are gone."""
        found: list[str] = []
        out: list[str] = []
        i = 0
        while i < len(body):
            if body[i] == "\\" and i + 1 < len(body):
                out.append(body[i + 1] if body[i + 1] in "`\\$" else body[i : i + 2])
                i += 2
                continue
            if body.startswith("$((", i):
                end = _ShellReader._closing(body, i + 3, depth=2)
                found.extend(_ShellReader._expand(body[i + 3 : end - 2])[0])
            elif body.startswith("$(", i):
                end = _ShellReader._closing(body, i + 2)
                found.append(body[i + 2 : end - 1])
            elif body.startswith("${", i):
                end = _ShellReader._closing(body, i + 2, "{")
                found.extend(_ShellReader._expand(body[i + 2 : end - 1])[0])
            elif body[i] == "`":
                end = _ShellReader._backtick_end(body, i + 1)
                found.append(re.sub(r"\\([`\\$])", r"\1", body[i + 1 : end - 1]))
            else:
                out.append(body[i])
                i += 1
                continue
            out.append("_")
            i = end
        return found, "".join(out)

    # Reading (design D1).

    def read(self, text: str, depth: int = 0) -> None:
        if depth > MAX_DEPTH:
            self.reading.unreadable.append(f"commands nested more than {MAX_DEPTH} deep")
            return
        for piece, nested in self.split(self.take_heredocs(text)):
            words, heredocs = self.words(piece)
            scripts = self.command(words, heredocs, depth) if words else False
            for heredoc in heredocs:
                if not heredoc.quoted and not scripts:
                    for inner in self.heredoc_substitutions(heredoc.body):
                        self.nested(inner, depth)
            for inner in nested:
                self.nested(inner, depth)

    def nested(self, text: str, depth: int) -> None:
        if CASE_STATEMENT.search(text):
            self.reading.unreadable.append("a case statement inside a substitution")
            return
        self.read(text, depth + 1)

    def command(self, words: list[str], heredocs: list[_Heredoc], depth: int) -> bool:
        """Emit one simple command, after what comes before its program (design D3). True if a
        shell ran its heredocs as its script, which reads their substitutions too."""
        assignments: list[str] = []
        i = 0
        while i < len(words):
            word = words[i]
            if ASSIGNMENT.match(word):
                assignments.append(word)
            elif (redirection := REDIRECTION.match(word)) is not None:
                if not redirection.group(1):
                    i += 1  # the operator's target is the next word
            elif word in RESERVED_WORDS:
                pass
            elif word == "function":
                i += 1  # its name
            else:
                name = Path(word).name.lower().removesuffix(".exe")
                if name not in SHELL_WRAPPERS:
                    break
                skipped = self._wrapper_options(name, words, i + 1, assignments)
                if skipped is None:
                    self.reading.commands.append([*assignments, *words[i:]])
                    return False
                i = skipped
                continue
            i += 1
        rest = words[i:]
        if not rest:
            return False
        self.reading.commands.append([*assignments, *rest])
        name = Path(rest[0]).name.lower().removesuffix(".exe")
        if "$" in rest[0] or "`" in rest[0]:
            self.reading.unreadable.append(f"its program is the expansion {rest[0]}")
        elif name == "alias" and any("=" in word for word in rest[1:]):
            self.reading.unreadable.append("it defines an alias")
        elif name == "eval":
            self.read(" ".join(rest[1:]), depth + 1)
        elif name in SHELLS:
            return self._shell(rest, heredocs, depth)
        elif name not in ("git", "gh") and not _is_data(rest):
            self._git_or_gh_given_to(name, rest[1:])
        return False

    def _git_or_gh_given_to(self, program: str, args: Sequence[str]) -> None:
        """A program the guard can't follow that's given git or gh may run it (design D5)."""
        named = next((word for word in args if _names_git_or_gh(word)), None)
        if named is not None:
            self.reading.unreadable.append(f"{named} is given to {program}, which may run it")

    def _wrapper_options(
        self, name: str, words: list[str], i: int, assignments: list[str]
    ) -> int | None:
        """The index of the wrapped command's first word, or None if the wrapper runs nothing.
        An option the wrapper's entry doesn't list makes the command unreadable."""
        flags, valued = SHELL_WRAPPERS[name]
        while i < len(words):
            if not words[i].startswith("-") or (words[i] == "-" and name != "env"):
                break
            option, _, _ = words[i].partition("=")
            if words[i] == "--":
                i += 1
                break
            if name == "command" and words[i] in ("-v", "-V"):
                return None
            if words[i] in flags:
                i += 1
            elif option in valued:
                i += 1 if "=" in words[i] else 2
            elif name == "nice" and re.fullmatch(r"-n?\d+", words[i]):
                i += 1
            else:
                self.reading.unreadable.append(
                    f"an option of {name} the guard doesn't know ({words[i]})"
                )
                return None
        if name == "env":
            while i < len(words) and ASSIGNMENT.match(words[i]):
                assignments.append(words[i])
                i += 1
        if name == "timeout" and i < len(words):
            i += 1  # the duration
        return i

    def _shell(self, words: list[str], heredocs: list[_Heredoc], depth: int) -> bool:
        """A shell's -c string, or the heredoc it reads as its script (design D3). True if it
        reads its heredocs as its script."""
        # Redirections and here-strings first, each with its target when that's a separate word.
        here_string = False
        rest: list[str] = []
        i = 1
        while i < len(words):
            word = words[i]
            redirection = REDIRECTION.match(word)
            if word.startswith("<<<"):
                here_string = True
                i += 1 if word != "<<<" else 2
            elif redirection is not None:
                i += 1 if redirection.group(1) else 2
            else:
                rest.append(word)
                i += 1
        command_string = stdin = False
        i = 0
        while i < len(rest):
            word = rest[i]
            if word == "--":
                i += 1
                break
            if word in ("-o", "+o"):
                i += 2
                continue
            if word.startswith("--"):
                i += 1
                continue
            if not word.startswith(("-", "+")) or word in ("-", "+"):
                break
            command_string = command_string or "c" in word[1:]
            stdin = stdin or "s" in word[1:]
            i += 1
        operands = rest[i:]
        if command_string:
            if operands:
                self.read(operands[0], depth + 1)
                self._git_or_gh_given_to(words[0], operands[1:])
            return False
        if operands and not stdin:
            # A script file: what it runs isn't in the command (a non-goal).
            self._git_or_gh_given_to(words[0], operands)
            return False
        if heredocs:
            # An unquoted body is expanded before the shell reads it: what it substitutes runs
            # first, and the script holds only the results, whose text isn't known.
            for heredoc in heredocs:
                if heredoc.quoted:
                    self.read(heredoc.body, depth + 1)
                    continue
                substituted, script = self._expand(heredoc.body)
                for inner in substituted:
                    self.nested(inner, depth)
                self.read(script, depth + 1)
            return True
        if here_string:
            self.reading.unreadable.append(f"{words[0]} reading its commands from a here-string")
        else:
            self.reading.unreadable.append(f"{words[0]} reading its commands from a pipe")
        return False


def _names_git_or_gh(word: str) -> bool:
    return Path(word).name.lower().removesuffix(".exe") in ("git", "gh")


def _is_data(words: Sequence[str]) -> bool:
    """True for a command whose words only name things (DATA_PROGRAMS, `command -v`)."""
    name = Path(words[0]).name.lower().removesuffix(".exe")
    return name in DATA_PROGRAMS or (name == "command" and words[1:2] in (["-v"], ["-V"]))


# PowerShell, read with its own rules (read-nested-commands design D7). A statement runs a program
# only when it starts with a bare word or a call operator (& or .); one that starts with a
# variable, a string, a number or a bracket is an expression, though what it substitutes runs.

POWERSHELL_OPERATORS = ("&&", "||", ";", "|", "\n")
POWERSHELL_ASSIGNMENTS = frozenset({"=", "+=", "-=", "*=", "/=", "%=", "??="})
POWERSHELL_EXPRESSION_START = tuple("$'\"([@0123456789-{")
POWERSHELL_DATA_PROGRAMS = frozenset(
    {"write-output", "echo", "write-host", "get-command", "gcm", "select-string", "sls",
     "if", "elseif", "else", "foreach", "for", "while", "do", "until", "switch", "try", "catch",
     "finally", "function", "filter", "param", "return", "throw", "trap"}
)  # fmt: skip
"""Like DATA_PROGRAMS, for PowerShell: commands and keywords that never run a word they're given.
A keyword's conditions and blocks are read as commands of their own."""
POWERSHELL_STRING_COMMANDS = frozenset({"invoke-expression", "iex"})
POWERSHELL_SHELLS = frozenset({"pwsh", "powershell"})
POWERSHELL_VALUE_OPTIONS = frozenset(
    {"-executionpolicy", "-ex", "-ep", "-windowstyle", "-w", "-workingdirectory", "-wd",
     "-inputformat", "-if", "-outputformat", "-of", "-o", "-configurationname", "-config",
     "-custompipename", "-settingsfile", "-settings"}
)  # fmt: skip


@dataclass
class _Token:
    text: str
    """With quotes and escapes removed, and nested text restored as written."""
    raw: str
    """As written."""


class _PowerShellReader:
    def __init__(self, reading: ShellReading) -> None:
        self.reading = reading
        self.spans: list[str] = []

    @staticmethod
    def _closing(text: str, start: int, opener: str) -> int:
        """The index just after the bracket that closes the one before `start`."""
        closer = {"(": ")", "{": "}"}[opener]
        depth = 1
        quote: str | None = None
        i = start
        while i < len(text):
            char = text[i]
            if char == "`":
                i += 2
                continue
            if quote:
                if char == quote:
                    quote = None
            elif char in "'\"":
                quote = char
            elif char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
                if depth == 0:
                    return i + 1
            i += 1
        raise ValueError(f"an unclosed {opener}")

    @classmethod
    def expandable(cls, text: str) -> list[str]:
        """The commands in $(...) in text PowerShell expands: a "..." string or @"..."@."""
        found: list[str] = []
        i = 0
        while i < len(text):
            if text[i] == "`":
                i += 2
            elif text.startswith("$(", i):
                end = cls._closing(text, i + 2, "(")
                found.append(text[i + 2 : end - 1])
                i = end
            else:
                i += 1
        return found

    def split(self, text: str) -> list[tuple[list[_Token], list[str]]]:
        """Each statement's tokens, and the commands nested in it."""
        statements: list[tuple[list[_Token], list[str]]] = []
        tokens: list[_Token] = []
        nested: list[str] = []
        word: list[str] = []
        raw: list[str] = []
        started = False

        def end_word() -> None:
            nonlocal word, raw, started
            if started:
                tokens.append(_Token("".join(word), "".join(raw)))
            word, raw, started = [], [], False

        def end_statement() -> None:
            nonlocal tokens, nested
            end_word()
            statements.append((tokens, nested))
            tokens, nested = [], []

        def span(end: int, start: int, inner: list[str]) -> None:
            nonlocal started
            self.spans.append(text[start:end])
            word.append(text[start:end])
            raw.append(text[start:end])
            nested.extend(inner)
            started = True

        i = 0
        while i < len(text):
            char = text[i]
            if char == "`":  # an escape, or a line continuation
                if i + 1 < len(text) and text[i + 1] != "\n":
                    word.append(text[i + 1])
                    raw.append(text[i : i + 2])
                    started = True
                i += 2
                continue
            if not started and char == "#":
                newline = text.find("\n", i)
                i = len(text) if newline < 0 else newline
                continue
            if not started and text.startswith("<#", i):
                close = text.find("#>", i + 2)
                i = len(text) if close < 0 else close + 2
                continue
            here = re.match(r"@(['\"])[ \t]*\r?\n", text[i:]) if not started else None
            if here is not None:
                closer = "\n" + here.group(1) + "@"
                close = text.find(closer, i)
                if close < 0:
                    raise ValueError("an unclosed here-string")
                body = text[i + here.end() : close]
                span(close + len(closer), i, self.expandable(body) if here.group(1) == '"' else [])
                i = close + len(closer)
                continue
            if char == "'":
                close = i + 1
                while True:
                    close = text.find("'", close)
                    if close < 0:
                        raise ValueError("unbalanced quotes")
                    if text.startswith("''", close):
                        close += 2
                        continue
                    break
                word.append(text[i + 1 : close].replace("''", "'"))
                raw.append(text[i : close + 1])
                started = True
                i = close + 1
                continue
            if char == '"':
                j = i + 1
                content: list[str] = []
                while j < len(text) and text[j] != '"':
                    if text[j] == "`" and j + 1 < len(text):
                        content.append(text[j + 1])
                        j += 2
                    elif text.startswith("$(", j):
                        end = self._closing(text, j + 2, "(")
                        nested.append(text[j + 2 : end - 1])
                        content.append(text[j:end])
                        j = end
                    else:
                        content.append(text[j])
                        j += 1
                if j >= len(text):
                    raise ValueError("unbalanced quotes")
                word.append("".join(content))
                raw.append(text[i : j + 1])
                started = True
                i = j + 1
                continue
            opener = next((o for o in ("$(", "@(", "@{", "(", "{") if text.startswith(o, i)), None)
            if opener is not None:
                end = self._closing(text, i + len(opener), opener[-1])
                span(end, i, [text[i + len(opener) : end - 1]])
                i = end
                continue
            operator = next((op for op in POWERSHELL_OPERATORS if text.startswith(op, i)), None)
            if operator is not None:
                end_statement()
                i += len(operator)
                continue
            if char == "&" and not started:
                # A call operator before a command, or a background job at the end.
                end_word()
                rest = text[i + 1 :].lstrip(" \t")
                if not rest or rest[0] in ";\n|":
                    end_statement()
                else:
                    tokens.append(_Token("&", "&"))
                i += 1
                continue
            if char.isspace():
                end_word()
                i += 1
                continue
            word.append(char)
            raw.append(char)
            started = True
            i += 1
        end_statement()
        return statements

    def read(self, text: str, depth: int = 0) -> None:
        if depth > MAX_DEPTH:
            self.reading.unreadable.append(f"commands nested more than {MAX_DEPTH} deep")
            return
        for tokens, nested in self.split(text):
            self.statement(tokens, depth)
            for inner in nested:
                self.read(inner, depth + 1)

    def statement(self, tokens: list[_Token], depth: int) -> None:
        while (
            len(tokens) > 1
            and tokens[0].raw.startswith("$")
            and tokens[1].raw in POWERSHELL_ASSIGNMENTS
        ):
            tokens = tokens[2:]  # an assignment: what's on the right may be a command
        if not tokens:
            return
        if tokens[0].raw in ("&", "."):
            if len(tokens) < 2 or tokens[1].raw.startswith("{"):
                return  # a script block, read with the nested commands
            target = tokens[1]
            if target.raw.startswith(("$", "(", "@")):
                self.reading.commands.append([t.text for t in tokens[1:]])
                self.reading.unreadable.append(f"its program is the expression {target.raw}")
                return
            tokens = tokens[1:]
        elif tokens[0].raw.startswith(POWERSHELL_EXPRESSION_START):
            return  # an expression; what it substitutes is read with the nested commands
        words = [t.text for t in tokens]
        self.reading.commands.append(words)
        name = Path(words[0].replace("\\", "/")).name.lower().removesuffix(".exe")
        args = words[1:]
        if name in POWERSHELL_STRING_COMMANDS:
            strings = [w for w in args if w.lower() != "-command"]
            self.read(" ".join(strings), depth + 1)
        elif name in POWERSHELL_SHELLS:
            self._powershell(name, args, depth)
        elif name == "cmd":
            self._cmd(args, depth)
        elif name not in ("git", "gh") and name not in POWERSHELL_DATA_PROGRAMS:
            named = next((w for w in args if _names_git_or_gh(w.replace("\\", "/"))), None)
            if named is not None:
                self.reading.unreadable.append(f"{named} is given to {name}, which may run it")

    def _powershell(self, name: str, args: list[str], depth: int) -> None:
        """pwsh's or powershell's -Command or -EncodedCommand, read as PowerShell."""
        i = 0
        while i < len(args):
            option = args[i].lower()
            if option in ("-command", "-c"):
                if args[i + 1 : i + 2] == ["-"]:
                    break
                self.read(" ".join(args[i + 1 :]), depth + 1)
                return
            if option in ("-encodedcommand", "-ec", "-e", "-enc"):
                try:
                    decoded = base64.b64decode(args[i + 1], validate=True).decode("utf-16-le")
                except (IndexError, ValueError):
                    self.reading.unreadable.append(f"{name} -EncodedCommand that doesn't decode")
                    return
                self.read(decoded, depth + 1)
                return
            if option in ("-file", "-f"):
                return  # a script file: what it runs isn't in the command (a non-goal)
            if option in POWERSHELL_VALUE_OPTIONS:
                i += 2
                continue
            if not option.startswith("-"):
                self.read(" ".join(args[i:]), depth + 1)  # a command with no -Command
                return
            i += 1
        self.reading.unreadable.append(f"{name} reading its commands from a pipe")

    def _cmd(self, args: list[str], depth: int) -> None:
        """cmd /c or /k: the rest is a cmd command line, split on & && || | outside quotes."""
        for i, arg in enumerate(args):
            if arg.lower() in ("/c", "/k"):
                line = " ".join(args[i + 1 :])
                break
        else:
            return
        pieces: list[str] = []
        current: list[str] = []
        quoted = False
        j = 0
        while j < len(line):
            char = line[j]
            if char == "^" and j + 1 < len(line):
                current.append(line[j + 1])
                j += 2
                continue
            if char == '"':
                quoted = not quoted
            elif not quoted and char in "&|":
                pieces.append("".join(current))
                current = []
                j += 2 if line.startswith(char * 2, j) else 1
                continue
            current.append(char)
            j += 1
        pieces.append("".join(current))
        for piece in pieces:
            words = [w.replace('"', "") for w in re.findall(r'(?:[^\s"]|"[^"]*")+', piece)]
            if words:
                self.statement([_Token(w, w) for w in words], depth + 1)


def read_shell(command: str, tool: str = "Bash") -> ShellReading:
    """Every simple command `command` would run, outer ones first, read by the rules of the tool's
    shell. Raises ValueError when the text can't be split at all (unbalanced quotes, or a
    substitution with no end)."""
    if tool == "PowerShell":
        reading = ShellReading([], [])
        _PowerShellReader(reading).read(command)
        return reading
    reader = _ShellReader()
    reader.read(command)
    return reader.reading


def commands_run(command: str, tool: str = "Bash") -> list[list[str]]:
    return read_shell(command, tool).commands


def strip_heredocs(command: str) -> str:
    """Drop heredoc bodies: they are data (often commit messages), not shell words."""
    reader = _ShellReader()
    return reader._unmark(reader.take_heredocs(command), raw=True)


def split_command(command: str) -> list[list[str]]:
    """Split a shell command into its outer simple commands, each as a list of words.

    Raises ValueError when the text can't be parsed (for example, unbalanced quotes).
    """
    reader = _ShellReader()
    pieces = reader.split(reader.take_heredocs(command))
    return [words for piece, _ in pieces if (words := reader.words(piece)[0])]


def _program(words: Sequence[str]) -> tuple[str, list[str]]:
    """The program name and its arguments, after any leading VAR=value assignments."""
    index = 0
    while index < len(words) and ASSIGNMENT.match(words[index]):
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


def shell_decisions(command: str, cwd: Path, tool: str = "Bash") -> list[Decision]:
    """Every rule's decision on every git and gh command a shell command would run, nested ones
    included (read-nested-commands design D1)."""
    text = strip_heredocs(command)
    try:
        reading = read_shell(command, tool)
    except ValueError as error:
        if GUARD_DIR in text.lower() or re.search(r"guard\.py\S*\s+override\b", text.lower()):
            return [TAMPER]
        # The whole command, heredoc bodies included: a shell may run one as its script.
        if not re.search(r"\b(git|gh)\b", command):
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
    for words in reading.commands:
        tamper = guard_tamper(words)
        if tamper.refused:
            return [tamper]
        decisions.append(skip_hooks(words))
        if gh_help_request(words):
            continue  # it only prints help, whatever the command would be refused for
        decisions.append(pr_closes_issue(words, cwd))
        decisions.append(gh_decision(words, cwd))
    if reading.unreadable and re.search(r"\b(git|gh)\b", command):
        decisions.append(
            Decision(
                "command-unparseable",
                "this command runs git or gh where the guardrails can't read it "
                f"({reading.unreadable[0]}).",
                "Run the git or gh command on its own, as a separate Bash command, not through "
                "another program, a variable or a pipe into a shell.",
            )
        )
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


def schema_commit_types(root: Path, commits: Iterable[str]) -> Decision:
    """The schema-commit-type rule over many commits, each judged on its own changes, so a commit
    amended, reworded or made with --no-verify is still caught (design D5)."""
    bad: list[str] = []
    for sha in commits:
        message = git(root, "log", "-1", "--format=%B", sha)
        # --root so a repository's first commit lists its files; --no-renames so a move lists both.
        paths = git(
            root, "diff-tree", "--no-commit-id", "--name-only", "--no-renames", "-r", "--root", sha
        ).splitlines()
        if schema_commit_type(message, paths).refused:
            first = next((line for line in message.splitlines() if line.strip()), "")
            bad.append(f"{sha[:7]} '{first}' ({', '.join(schema_files(paths)[:5])})")
    if not bad:
        return ALLOW
    listed = "; ".join(bad[:5]) + (f"; and {len(bad) - 5} more" if len(bad) > 5 else "")
    return Decision(
        "schema-commit-type",
        f"{len(bad)} commit(s) change protocol schemas under a type that releases nothing: "
        f"{listed}.",
        f"Reword each to a type that releases ({', '.join(RELEASING_TYPES)}), or mark it "
        "breaking: git commit --amend for the last commit, or git rebase with reword for earlier "
        "ones. If the rest of a commit's work shouldn't release, split the schema change out.",
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
    decisions = [nonconforming_commits(root, commits), schema_commit_types(root, commits)]
    if title is not None:
        decisions.append(pr_title(title))
    if branch and branch != "main" and not reserved_release_branch(branch, repository):
        decisions.append(commit_branch_change(root, branch))
    changed = changed_paths(root, commits)

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


def changed_paths(root: Path, commits: Iterable[str]) -> list[str]:
    """Every path the commits change, in order, repeats included."""
    changed: list[str] = []
    for sha in commits:
        changed += git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", sha).splitlines()
    return changed


# --- strict OpenSpec validation on GitHub (guard-strict-openspec) -----------------------------


@dataclass(frozen=True)
class OpenSpecScope:
    """What openspec-strict judges: everything, or the main specs and active changes named."""

    everything: bool = False
    specs: frozenset[str] = frozenset()
    changes: frozenset[str] = frozenset()

    @property
    def empty(self) -> bool:
        return not (self.everything or self.specs or self.changes)

    def covers(self, kind: str, name: str) -> bool:
        if self.everything:
            return True
        return name in (self.specs if kind == "spec" else self.changes)


def openspec_scope(
    paths: Iterable[str], branch: str | None, pull_request: bool, exists: Callable[[str], bool]
) -> OpenSpecScope:
    """A push to main is judged in full, and so is a range that changes the guard; anything else
    on what it touches: the main specs it changes, and the active changes it changes that still
    exist (design D3). ``exists`` says whether a repository path is a directory at the head."""
    paths = list(paths)
    if (branch == "main" and not pull_request) or any(p in OPENSPEC_ALL_PATHS for p in paths):
        return OpenSpecScope(everything=True)
    specs: set[str] = set()
    changes: set[str] = set()
    for path in paths:
        parts = path.split("/")
        if len(parts) < 4 or parts[0] != "openspec":
            continue
        if parts[1] == "specs":
            specs.add(parts[2])
        elif parts[1] == "changes" and parts[2] != "archive":
            changes.add(parts[2])
    return OpenSpecScope(
        specs=frozenset(s for s in specs if exists(f"openspec/specs/{s}")),
        changes=frozenset(c for c in changes if exists(f"openspec/changes/{c}")),
    )


@dataclass(frozen=True)
class OpenSpecRun:
    """What one run of OpenSpec's strict validation printed, and the version that printed it."""

    status: int
    stdout: str
    stderr: str
    version: str


class OpenSpecUnavailableError(Exception):
    """OpenSpec's validation couldn't be run at all: the CLI is missing, or it ran too long."""

    def __init__(self, problem: str, fix: str) -> None:
        super().__init__(problem)
        self.problem = problem
        self.fix = fix


class UnreadableOpenSpecReportError(Exception):
    """OpenSpec ran, but what it printed isn't a report the guard can read (design D2)."""


@dataclass(frozen=True)
class OpenSpecIssue:
    level: str
    path: str
    message: str


@dataclass(frozen=True)
class OpenSpecItem:
    kind: str
    name: str
    valid: bool
    issues: tuple[OpenSpecIssue, ...]


def _report_item(entry: object) -> OpenSpecItem:
    if not isinstance(entry, dict):
        raise UnreadableOpenSpecReportError("an item isn't an object")
    name, kind, valid, issues = (entry.get(k) for k in ("id", "type", "valid", "issues"))
    if not isinstance(name, str) or kind not in ("spec", "change") or not isinstance(valid, bool):
        raise UnreadableOpenSpecReportError(
            f"an item has no string id, a type of 'spec' or 'change', and a boolean valid: {entry}"
        )
    if not isinstance(issues, list):
        raise UnreadableOpenSpecReportError(f"item {name} has no issues list")
    read: list[OpenSpecIssue] = []
    for issue in issues:
        fields = (
            [issue.get(k) for k in ("level", "path", "message")] if isinstance(issue, dict) else []
        )
        if len(fields) != 3 or not all(isinstance(f, str) for f in fields):
            raise UnreadableOpenSpecReportError(
                f"an issue of item {name} has no string level, path and message: {issue}"
            )
        read.append(OpenSpecIssue(*(str(f) for f in fields)))
    return OpenSpecItem(str(kind), name, valid, tuple(read))


def read_openspec_report(run: OpenSpecRun) -> list[OpenSpecItem]:
    """The items of a run's JSON report. Its exit status is only cross-checked: a failure with
    no failing item, or success with one, is unreadable, not a pass (design D2)."""
    try:
        report = json.loads(run.stdout)
    except json.JSONDecodeError as error:
        raise UnreadableOpenSpecReportError(f"its output isn't JSON ({error})") from None
    entries = report.get("items") if isinstance(report, dict) else None
    if not isinstance(entries, list):
        raise UnreadableOpenSpecReportError("its output has no items list")
    items = [_report_item(entry) for entry in entries]
    failing = any(not item.valid for item in items)
    if failing != (run.status != 0):
        raise UnreadableOpenSpecReportError(
            f"it exited {run.status} but reported "
            f"{'a failing item' if failing else 'no failing item'}"
        )
    return items


REQUIREMENT_INDEX = re.compile(r"^requirements\[(\d+)\]$")
REQUIREMENT_HEADING = re.compile(r"^### Requirement:\s*(.+?)\s*$", re.MULTILINE)


def requirement_name(root: Path, spec: str, index: int) -> str | None:
    """The name of a main spec's requirement OpenSpec counts as ``index``: the index-th
    '### Requirement:' heading, from 0 (design D4). None when there's no such file or heading."""
    try:
        text = (root / "openspec" / "specs" / spec / "spec.md").read_text(encoding="utf-8")
    except OSError:
        return None
    names = REQUIREMENT_HEADING.findall(text)
    return names[index] if index < len(names) else None


def _issue_text(root: Path, item: OpenSpecItem, issue: OpenSpecIssue) -> str:
    where = issue.path
    match = REQUIREMENT_INDEX.match(issue.path)
    if item.kind == "spec" and match:
        name = requirement_name(root, item.name, int(match.group(1)))
        if name is not None:
            where = f'requirement "{name}" ({issue.path})'
    elif item.kind == "change" and issue.path.endswith(".md"):
        where = f"openspec/changes/{item.name}/specs/{issue.path}"
    return f"{where}: [{issue.level.lower()}] {issue.message}"


def openspec_refusal(root: Path, items: Iterable[OpenSpecItem], version: str) -> Decision:
    """One refusal listing every failing item, each issue naming its requirement (design D5)."""
    failing = [item for item in items if not item.valid]
    if not failing:
        return ALLOW
    listed = "; ".join(
        f"{item.kind} {item.name}: "
        + ("; ".join(_issue_text(root, item, i) for i in item.issues) or "no issue given")
        for item in failing
    )
    target = f"{failing[0].name} --type {failing[0].kind}" if len(failing) == 1 else "--all"
    return Decision(
        OPENSPEC_RULE,
        f"{len(failing)} item(s) fail OpenSpec's strict validation: {listed}.",
        f"Run `openspec validate {target} --strict` with OpenSpec {version} and fix what it "
        "reports. For a long requirement, move examples into scenarios, or split it.",
    )


def run_openspec(root: Path) -> OpenSpecRun:
    """OpenSpec's strict validation of every main spec and active change, with its telemetry
    off. shutil.which finds npm's openspec.cmd on Windows too (design D1, D2)."""
    executable = shutil.which("openspec")
    if executable is None:
        raise OpenSpecUnavailableError(
            "the OpenSpec CLI wasn't found on PATH.",
            f"Install it before the guard runs, at the version {OPENSPEC_PIN} pins "
            "(OPENSPEC_VERSION).",
        )
    env = {**os.environ, "OPENSPEC_TELEMETRY": "0", "DO_NOT_TRACK": "1"}

    def call(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [executable, *args],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env=env,
            timeout=OPENSPEC_TIMEOUT_SECONDS,
        )

    try:
        version = call("--version")
        result = call("validate", "--all", "--strict", "--json", "--no-interactive")
    except subprocess.TimeoutExpired:
        raise OpenSpecUnavailableError(
            f"OpenSpec's validation ran for more than {OPENSPEC_TIMEOUT_SECONDS:g} seconds.",
            "Re-run the check. If it times out again, run the validation locally to see why.",
        ) from None
    shown = version.stdout.strip() if version.returncode == 0 else ""
    return OpenSpecRun(result.returncode, result.stdout, result.stderr, shown or "(unknown)")


def openspec_strict(
    root: Path,
    scope: OpenSpecScope,
    run: Callable[[Path], OpenSpecRun] = run_openspec,
    notes: list[str] | None = None,
) -> Decision:
    """The openspec-strict rule. With no openspec/ root or nothing in scope, OpenSpec isn't run;
    otherwise a run that can't be had or read fails, and never passes (design D2). ``notes``
    gets one line saying what was judged, so a passing run's log shows it."""
    said = notes if notes is not None else []
    if not (root / "openspec").is_dir():
        said.append("guard: openspec-strict: no openspec/ root, so OpenSpec wasn't run.")
        return ALLOW
    if scope.empty:
        said.append(
            "guard: openspec-strict: no spec or active change in scope, so OpenSpec wasn't run."
        )
        return ALLOW
    try:
        result = run(root)
    except OpenSpecUnavailableError as error:
        return Decision(OPENSPEC_RULE, error.problem, error.fix)
    try:
        items = read_openspec_report(result)
    except UnreadableOpenSpecReportError as error:
        stderr = result.stderr.strip()[-500:] or "(empty)"
        return Decision(
            OPENSPEC_RULE,
            f"couldn't read OpenSpec {result.version}'s result: {error}. It exited "
            f"{result.status}; its error output ends: {stderr}",
            "Re-run the check. If it fails again, run the same validation locally with that "
            "version; if OpenSpec's report has changed shape, the guard's reading of it needs "
            "changing in troupe-run/infrastructure.",
        )
    judged = [item for item in items if scope.covers(item.kind, item.name)]
    which = "every spec and active change" if scope.everything else "what the range touches"
    said.append(
        f"guard: openspec-strict: OpenSpec {result.version} validated {len(judged)} of "
        f"{len(items)} item(s), {which}."
    )
    return openspec_refusal(root, judged, result.version)


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
        commits = commits_in_range(root, remote_sha, local_sha)
        decisions = [nonconforming_commits(root, commits), schema_commit_types(root, commits)]
        refusal = first_refusal(root, decisions, f"push {local_ref}")
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
    # After the git-level rules, and outside run_ci, which needs no OpenSpec (design D1).
    scope = openspec_scope(
        changed_paths(root, commits_in_range(root, base, head)),
        branch,
        title is not None,
        lambda path: (root / path).is_dir(),
    )
    notes: list[str] = []
    strict = openspec_strict(root, scope, notes=notes)
    for note in notes:
        print(note)
    if strict.refused:
        refusals.append(strict)
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


def committing_paths(root: Path) -> list[str]:
    """The paths the commit being made changes. During `git commit -a` or `git commit <path>`, git
    names the index it commits in GIT_INDEX_FILE, sometimes relative to the root; every other git
    call here strips it (design D4)."""
    env = _git_env()
    index = os.environ.get("GIT_INDEX_FILE")
    if index:
        env["GIT_INDEX_FILE"] = str(root / index)
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--no-renames"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return result.stdout.splitlines()


def run_commit_msg(root: Path, message_file: Path) -> int:
    message = message_file.read_text(encoding="utf-8")
    first = next((line for line in message.splitlines() if line.strip()), "")

    def checks() -> Iterable[Decision]:
        yield commit_message(message)
        yield schema_commit_type(message, committing_paths(root))

    refusal = first_refusal(root, checks(), f"commit message: {first}")
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
        decisions = shell_decisions(command, cwd, tool)
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
