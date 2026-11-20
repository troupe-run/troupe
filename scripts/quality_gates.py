# Source: troupe-run/infrastructure. Change it there; copies in other repositories are delivered.
"""The quality gates every governed repository's check runs (spec: quality-gates; its design).

Usage:
    quality_gates.py complexity [--base REV] [--lizard PATH]
    quality_gates.py size [--base REV]
    quality_gates.py coverage (--coveragepy REPORT.json | --vitest coverage-summary.json)
    quality_gates.py audit [--base REV] [--pip-audit PATH] [--uv PATH] [--npm PATH]
    quality_gates.py report --repository OWNER/NAME [--github-output PATH] [--gh PATH] ...

Each gate reads its thresholds from quality-gates.toml at the repository's root (design D2),
strictly: an unknown key, a wrong type or a missing file is an error, never a skipped gate.
Standard library only, like the guard: the measuring tools (lizard, pip-audit, npm) run as
processes.

Exit codes: 0 the gate passed, 1 it failed, 2 it couldn't judge (config, git, a tool or the
network), which also fails the check.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_NAME = "quality-gates.toml"

LANGUAGES: Mapping[str, tuple[str, ...]] = {
    "python": (".py",),
    "javascript": (".js", ".mjs", ".cjs", ".jsx"),
    "typescript": (".ts", ".mts", ".cts", ".tsx"),
}
"""The languages the complexity gate can measure, and the extensions lizard reads as each."""

SEVERITIES = ("low", "moderate", "high", "critical")
"""Advisory severities, as GitHub's advisory database and npm name them. An advisory whose severity
can't be found is `unknown`, which always blocks (design D7)."""

LOCK_FILES = ("uv.lock", "package-lock.json")
"""The lock files the audit knows how to read."""


class GateError(Exception):
    """The gate couldn't judge: a bad config, a missing base, a tool or the network failing."""


# --- Config (design D2) ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Package:
    name: str
    paths: tuple[str, ...]
    baseline: float | None


@dataclass(frozen=True)
class CoverageConfig:
    floor: float
    tolerance: float
    packages: tuple[Package, ...]


@dataclass(frozen=True)
class ComplexityConfig:
    block_above: int
    languages: tuple[str, ...]
    exclude: tuple[str, ...] = ()


@dataclass(frozen=True)
class SizeConfig:
    block_above: int
    warn_above: int
    exclude: tuple[str, ...] = ()
    allow: Mapping[str, int] = field(default_factory=dict)
    """Each declared file's own ceiling in bytes, above `block_above` (gate-files design D6)."""


@dataclass(frozen=True)
class AuditConfig:
    lock_files: tuple[str, ...]
    block: tuple[str, ...]


@dataclass(frozen=True)
class Config:
    coverage: CoverageConfig | None
    """None when the repository measures no coverage: only those infrastructure's list names for
    coverage and mutation testing declare it (#332)."""
    complexity: ComplexityConfig
    audit: AuditConfig
    mutation: Mapping[str, object] = field(default_factory=dict)
    """#325's table, passed through raw: its own script validates it."""
    size: SizeConfig | None = None
    """None until the repository declares [size]: optional until every governed repository has it
    (gate-files design D7)."""


class _Reader:
    """Reads one table strictly, naming the full key in every error."""

    def __init__(self, table: Mapping[str, object], where: str) -> None:
        self.table = table
        self.where = where

    def _key(self, key: str) -> str:
        return f"{self.where}.{key}" if self.where else key

    def keys(self, required: Iterable[str], optional: Iterable[str] = ()) -> None:
        allowed = [*required, *optional]
        unknown = sorted(set(self.table) - set(allowed))
        if unknown:
            raise GateError(
                f"{CONFIG_NAME}: unknown key `{self._key(unknown[0])}`. "
                f"`[{self.where or 'top level'}]` takes: {', '.join(allowed)}."
            )
        missing = [key for key in required if key not in self.table]
        if missing:
            raise GateError(f"{CONFIG_NAME}: `{self._key(missing[0])}` is required.")

    def number(self, key: str, low: float, high: float | None = None) -> float:
        value = self.table[key]
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise GateError(f"{CONFIG_NAME}: `{self._key(key)}` must be a number, not {value!r}.")
        if value < low or (high is not None and value > high):
            span = f"from {low:g} to {high:g}" if high is not None else f"{low:g} or more"
            raise GateError(f"{CONFIG_NAME}: `{self._key(key)}` must be {span}, not {value!r}.")
        return float(value)

    def integer(self, key: str, low: int) -> int:
        value = self.table[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < low:
            raise GateError(
                f"{CONFIG_NAME}: `{self._key(key)}` must be a whole number, {low} or more, "
                f"not {value!r}."
            )
        return value

    def strings(self, key: str, choices: Sequence[str] | None = None) -> tuple[str, ...]:
        value = self.table.get(key, [])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise GateError(f"{CONFIG_NAME}: `{self._key(key)}` must be a list of strings.")
        for item in value:
            if choices is not None and item not in choices:
                raise GateError(
                    f"{CONFIG_NAME}: `{self._key(key)}` can't hold {item!r}. "
                    f"Valid: {', '.join(choices)}."
                )
        return tuple(value)

    def table_at(self, key: str) -> _Reader:
        value = self.table[key]
        if not isinstance(value, dict):
            raise GateError(f"{CONFIG_NAME}: `{self._key(key)}` must be a table.")
        return _Reader(value, self._key(key))


def _packages(reader: _Reader) -> tuple[Package, ...]:
    packages: list[Package] = []
    for name in reader.table:
        table = reader.table_at(name)
        table.keys(["paths"], ["baseline"])
        paths = tuple(path.strip("/") for path in table.strings("paths"))
        if not paths:
            raise GateError(f"{CONFIG_NAME}: `{table.where}.paths` needs at least one path.")
        baseline = table.number("baseline", 0, 100) if "baseline" in table.table else None
        packages.append(Package(name, paths, baseline))
    claimed: dict[str, str] = {}
    for package in packages:
        for path in package.paths:
            for other, owner in claimed.items():
                if _under(path, other) or _under(other, path):
                    raise GateError(
                        f"{CONFIG_NAME}: packages `{owner}` and `{package.name}` overlap "
                        f"(`{other}` and `{path}`). Each source file belongs to one package."
                    )
            claimed[path] = package.name
    return tuple(packages)


def parse_config(text: str) -> Config:
    """The config, from the text of quality-gates.toml."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise GateError(f"{CONFIG_NAME} isn't valid TOML: {error}.") from error
    top = _Reader(data, "")
    top.keys(["version", "complexity", "audit"], ["coverage", "mutation", "size"])
    if data["version"] != 1:
        raise GateError(f"{CONFIG_NAME}: `version` must be 1, not {data['version']!r}.")

    coverage = None
    if "coverage" in data:
        cov = top.table_at("coverage")
        cov.keys(["floor", "tolerance", "packages"])
        coverage = CoverageConfig(
            floor=cov.number("floor", 0, 100),
            tolerance=cov.number("tolerance", 0, 100),
            packages=_packages(cov.table_at("packages")),
        )

    cx = top.table_at("complexity")
    cx.keys(["block_above", "languages"], ["exclude"])
    languages = cx.strings("languages", tuple(LANGUAGES))
    if not languages:
        raise GateError(f"{CONFIG_NAME}: `complexity.languages` needs at least one language.")
    complexity = ComplexityConfig(cx.integer("block_above", 1), languages, cx.strings("exclude"))

    au = top.table_at("audit")
    au.keys(["lock_files", "block"])
    lock_files = au.strings("lock_files")
    for lock in lock_files:
        if Path(lock).name not in LOCK_FILES:
            raise GateError(
                f"{CONFIG_NAME}: `audit.lock_files` can't hold {lock!r}: the audit reads "
                f"{' and '.join(LOCK_FILES)}."
            )
    block = au.strings("block", SEVERITIES)
    if not block:
        raise GateError(f"{CONFIG_NAME}: `audit.block` needs at least one severity.")
    audit = AuditConfig(lock_files, block)

    mutation = top.table_at("mutation").table if "mutation" in data else {}
    size = _size_config(top.table_at("size")) if "size" in data else None
    return Config(coverage, complexity, audit, mutation, size)


def _size_config(reader: _Reader) -> SizeConfig:
    reader.keys(["block_above", "warn_above"], ["exclude", "allow"])
    block_above = reader.integer("block_above", 1)
    warn_above = reader.integer("warn_above", 1)
    if warn_above > block_above:
        raise GateError(
            f"{CONFIG_NAME}: `size.warn_above` ({warn_above}) must be at or below "
            f"`size.block_above` ({block_above})."
        )
    allow: dict[str, int] = {}
    if "allow" in reader.table:
        entries = reader.table_at("allow")
        for path in entries.table:
            ceiling = entries.integer(path, 1)
            if ceiling <= block_above:
                raise GateError(
                    f"{CONFIG_NAME}: `size.allow.{path}` is {ceiling}, but a ceiling must be above "
                    f"`size.block_above` ({block_above}). Fix: remove the entry, since the file "
                    "needs no allowance."
                )
            allow[path] = ceiling
    return SizeConfig(block_above, warn_above, reader.strings("exclude"), allow)


def read_config(root: Path) -> Config:
    """The repository's config; a missing file is an error, never a skipped gate."""
    path = root / CONFIG_NAME
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise GateError(
            f"{CONFIG_NAME} is missing at {root}. Fix: add it, declaring [complexity] and "
            "[audit], and [coverage] if the repository measures it (docs/development-workflow.md)."
        ) from None
    return parse_config(text)


# --- Paths ----------------------------------------------------------------------------------------


def _under(path: str, prefix: str) -> bool:
    """Whether `path` is `prefix` or inside it, by whole path segments."""
    return path == prefix or path.startswith(prefix.rstrip("/") + "/")


def glob_pattern(pattern: str) -> re.Pattern[str]:
    """A glob as a regex: `**/` spans any number of directories, `*` and `?` stay inside one."""
    out = ""
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(out + r"\Z")


def excluded(path: str, patterns: Sequence[str]) -> bool:
    return any(glob_pattern(pattern).match(path) for pattern in patterns)


DELIVERY_LIST = ".github/guard-delivery.json"
"""The files infrastructure delivers to this repository (spec: guard-delivery). They're measured at
their source, so every gate leaves them out here (#333)."""


def delivered_paths(root: Path) -> frozenset[str]:
    """The repository-relative paths the delivered list names. No list means nothing is delivered,
    as in infrastructure, their source; a list that can't be read is an error, never "nothing"."""
    path = root / DELIVERY_LIST
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return frozenset()
    except (OSError, UnicodeDecodeError) as error:
        raise GateError(f"couldn't read {DELIVERY_LIST}: {error}.") from error
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise GateError(f"{DELIVERY_LIST} isn't valid JSON: {error}.") from error
    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(files, list) or not all(isinstance(item, str) for item in files):
        raise GateError(
            f"{DELIVERY_LIST} must be an object whose `files` is a list of paths. It's written by "
            "infrastructure's delivery: fix it there, never by hand."
        )
    return frozenset(files)


# --- Git ------------------------------------------------------------------------------------------


def _process(
    command: Sequence[str], cwd: Path, body: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Run a tool, capturing its UTF-8 output. With no body, its stdin is empty rather than the
    caller's. A tool that can't be started is the gate unable to judge, not a crash."""
    try:
        return subprocess.run(
            list(command),
            cwd=cwd,
            input=body,
            stdin=subprocess.DEVNULL if body is None else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as error:
        raise GateError(f"couldn't run {command[0]}: {error}.") from error


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _process(["git", *args], root)


def resolve_base(root: Path, base: str | None) -> str:
    """The commit the diff gates judge against: the one named, or where the work left main."""
    if base is not None:
        found = _git(root, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}")
        if found.returncode != 0:
            raise GateError(
                f"the base {base!r} isn't a commit here. Fix: fetch it "
                f"(`git fetch origin {base}`), or pass a commit this clone has."
            )
        return found.stdout.strip()
    merged = _git(root, "merge-base", "HEAD", "origin/main")
    if merged.returncode != 0:
        raise GateError(
            "the complexity and audit gates compare with origin/main, which this clone doesn't "
            "have. Fix: run `git fetch origin main`."
        )
    return merged.stdout.strip()


HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)


Lines = frozenset[int] | None
"""A changed file's new or edited line numbers, or None when the whole file is new to git."""


def changed_lines(root: Path, base: str) -> dict[str, Lines]:
    """Each file the work changes since `base` (staged, unstaged and untracked), with its new or
    edited line numbers. Deleted files aren't listed: nothing in them can be measured. No file is
    opened here: an untracked file is new throughout, so its lines are None, not counted."""
    diff = _git(root, "diff", "-U0", "--no-renames", "--no-ext-diff", "--no-color", base, "--")
    if diff.returncode != 0:
        raise GateError(f"git diff from {base} failed: {diff.stderr.strip()}")
    changed: dict[str, Lines] = {}
    for section in re.split(r"^diff --git ", diff.stdout, flags=re.MULTILINE)[1:]:
        target = re.search(r"^\+\+\+ b/(.+)$", section, re.MULTILINE)
        if target is None:
            continue  # deleted, or binary
        lines: set[int] = set()
        for start, length in HUNK.findall(section):
            count = int(length) if length else 1
            lines.update(range(int(start), int(start) + count))
        changed[target.group(1)] = frozenset(lines)
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
    for path in filter(None, untracked.stdout.split("\0")):
        changed[path] = None
    return changed


# --- Complexity (design D6) -----------------------------------------------------------------------


@dataclass(frozen=True)
class Function:
    path: str
    name: str
    long_name: str
    start: int
    end: int
    complexity: int


@dataclass(frozen=True)
class ComplexityProblem:
    function: Function
    before: int | None
    limit: int

    def text(self) -> str:
        where = f"{self.function.path}:{self.function.start} {self.function.name}"
        if self.before is None:
            return (
                f"{where}: a new function with complexity {self.function.complexity}, "
                f"above the limit of {self.limit}"
            )
        return (
            f"{where}: complexity rose from {self.before} to {self.function.complexity}, "
            f"above the limit of {self.limit}"
        )


def measured_path(path: str, config: ComplexityConfig) -> bool:
    extensions = [ext for language in config.languages for ext in LANGUAGES[language]]
    return path.endswith(tuple(extensions)) and not excluded(path, config.exclude)


def lizard_functions(lizard: str, tree: Path, paths: Sequence[str]) -> list[Function]:
    """Every function lizard finds in `paths` under `tree`. Each path is given as ./<path>, so a
    file named like an option (`--exclude=*.py`) is read as a file, never as an option that hides
    the others (#359 review)."""
    if not paths:
        return []
    result = _process([lizard, "--csv", *(f"./{path}" for path in paths)], tree)
    if result.returncode != 0:
        raise GateError(f"lizard failed (exit {result.returncode}): {result.stderr.strip()}")
    functions = []
    for row in csv.reader(io.StringIO(result.stdout)):
        # NLOC, CCN, tokens, parameters, length, location, file, name, long name, start, end
        path = Path(row[6]).as_posix()
        functions.append(Function(path, row[7], row[8], int(row[9]), int(row[10]), int(row[1])))
    return functions


def _base_copies(root: Path, base: str, paths: Sequence[str], into: Path) -> list[str]:
    """Write each path's content at `base` under `into`; the paths that existed there."""
    present = []
    for path in paths:
        shown = _git(root, "show", f"{base}:{path}")
        if shown.returncode != 0:
            continue  # new since the base
        target = into / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(shown.stdout, encoding="utf-8")
        present.append(path)
    return present


def complexity_problems(
    root: Path, base: str, config: ComplexityConfig, lizard: str
) -> list[ComplexityProblem]:
    """Each function the work adds or edits that is above the limit, and new or more complex.
    Delivered files are measured at their source, not here (#333)."""
    delivered = delivered_paths(root)
    changes = {
        path: lines
        for path, lines in changed_lines(root, base).items()
        if measured_path(path, config) and path not in delivered and (root / path).is_file()
    }
    paths = sorted(changes)
    with tempfile.TemporaryDirectory() as scratch:
        before_paths = _base_copies(root, base, paths, Path(scratch))
        before: dict[tuple[str, str], int] = {}
        for function in lizard_functions(lizard, Path(scratch), before_paths):
            key = (function.path, function.long_name)
            before[key] = max(before.get(key, 0), function.complexity)
    problems = []
    for function in lizard_functions(lizard, root, paths):
        # Only functions the work edits (spec). A function the diff doesn't touch can't be more
        # complex than at the base, so this also keeps the rule's answer the same; #320 counts the
        # changed functions themselves.
        span = set(range(function.start, function.end + 1))
        lines = changes[function.path]
        if function.complexity <= config.block_above or (lines is not None and not span & lines):
            continue
        old = before.get((function.path, function.long_name))
        if old is None or function.complexity > old:
            problems.append(ComplexityProblem(function, old, config.block_above))
    return problems


# --- Size (gate-files design D4) ------------------------------------------------------------------


@dataclass(frozen=True)
class SizeResult:
    notes: list[str]
    problems: list[str]


def _text_size(data: bytes) -> int | None:
    """A text file's size in bytes, with each CRLF counted as LF, so a Windows checkout measures
    what Linux and macOS do; None when it's binary: a NUL byte, or not UTF-8."""
    if b"\0" in data:
        return None
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return len(data.replace(b"\r\n", b"\n"))


def _size_at(root: Path, base: str, path: str) -> int | None:
    """The file's size at the base, measured as in the working tree; None when it's new since."""
    shown = subprocess.run(
        ["git", "show", f"{base}:{path}"], cwd=root, capture_output=True, check=False
    )
    return _text_size(shown.stdout) if shown.returncode == 0 else None


def _stale_allowances(root: Path, config: SizeConfig) -> list[str]:
    """Each [size.allow] entry whose file is gone or now fits: the list only shrinks."""
    problems = []
    for path in sorted(config.allow):
        target = root / path
        size = _text_size(target.read_bytes()) if target.is_file() else 0
        if not target.is_file() or size is None:
            what = "isn't measured, being binary" if target.is_file() else "doesn't exist"
            problems.append(f"`size.allow` names {path}, which {what}. Fix: remove its entry.")
        elif size <= config.block_above:
            problems.append(
                f"{path} is {size:,} bytes, within the limit of "
                f"{config.block_above:,}, so it needs no allowance. Fix: remove its entry from "
                "`size.allow`."
            )
    return problems


def _size_problem(path: str, before: int | None, size: int, limit: int, declared: bool) -> str:
    what = f"its ceiling of {limit:,} in `size.allow`" if declared else f"the limit of {limit:,}"
    if before is None:
        return f"{path}: a new file of {size:,} bytes, above {what}"
    return f"{path}: grew from {before:,} to {size:,} bytes, above {what}"


def size_result(root: Path, base: str, config: SizeConfig) -> SizeResult:
    """Each file the work adds or changes that is above its limit and new or larger, and each one
    above the warning. Delivered, excluded and binary files aren't measured."""
    delivered = delivered_paths(root)
    notes: list[str] = []
    problems = _stale_allowances(root, config)
    for path in sorted(changed_lines(root, base)):
        target = root / path
        if path in delivered or excluded(path, config.exclude) or not target.is_file():
            continue
        size = _text_size(target.read_bytes())
        if size is None:
            continue
        limit = config.allow.get(path, config.block_above)
        before = _size_at(root, base, path)
        if size > limit and (before is None or size > before):
            problems.append(_size_problem(path, before, size, limit, path in config.allow))
        elif size > config.warn_above:
            notes.append(
                f"{path} is {size:,} bytes, above the warning at {config.warn_above:,} "
                "(more than one Read for a review)"
            )
    return SizeResult(notes, problems)


# --- Coverage (design D3, D4) ---------------------------------------------------------------------


@dataclass(frozen=True)
class Counts:
    covered: int
    total: int

    def __add__(self, other: Counts) -> Counts:
        return Counts(self.covered + other.covered, self.total + other.total)

    @property
    def percent(self) -> float | None:
        return 100 * self.covered / self.total if self.total else None


def _relative(path: str, root: Path) -> str:
    """A report's path relative to the root, with forward slashes. Reports name files absolutely or
    relatively, with either separator (Vitest on Windows writes C:\\... or C:/...), so this works
    on the text; names compare case-insensitively on Windows."""
    text = path.replace("\\", "/")
    prefix = root.as_posix().replace("\\", "/").rstrip("/") + "/"
    windows = sys.platform == "win32"
    if (text.lower() if windows else text).startswith(prefix.lower() if windows else prefix):
        return text[len(prefix) :]
    return text


def coveragepy_counts(report: Mapping[str, object], root: Path) -> dict[str, Counts]:
    """Statements and branches per file, from `coverage json` run with branch coverage."""
    files = report.get("files")
    if not isinstance(files, dict):
        raise GateError("the coverage.py report has no `files`: is it `coverage json` output?")
    counts = {}
    for path, entry in files.items():
        summary = entry["summary"]
        if "num_branches" not in summary:
            raise GateError("the coverage.py report has no branch counts: run with branch = true.")
        counts[_relative(path, root)] = Counts(
            summary["covered_lines"] + summary["covered_branches"],
            summary["num_statements"] + summary["num_branches"],
        )
    return counts


def vitest_counts(summary: Mapping[str, object], root: Path) -> dict[str, Counts]:
    """Statements and branches per file, from Vitest's `json-summary` coverage reporter."""
    counts = {}
    for path, entry in summary.items():
        if path == "total":
            continue
        if not isinstance(entry, dict) or "branches" not in entry:
            raise GateError(f"the Vitest summary's entry for {path} has no branch counts.")
        statements, branches = entry["statements"], entry["branches"]
        counts[_relative(path, root)] = Counts(
            statements["covered"] + branches["covered"], statements["total"] + branches["total"]
        )
    return counts


@dataclass(frozen=True)
class CoverageResult:
    lines: list[str]
    problems: list[str]


def _format(value: float) -> str:
    return f"{value:.1f}%"


def _package_line(
    package: Package, counts: Counts, config: CoverageConfig
) -> tuple[str, str | None]:
    measured = counts.percent
    if measured is None:
        return f"{package.name}: nothing to measure", None
    if package.baseline is None:
        line = f"{package.name}: {_format(measured)} (no baseline; floor {_format(config.floor)})"
        if measured < config.floor:
            return line, (
                f"{package.name} measures {_format(measured)}, below the floor of "
                f"{_format(config.floor)} for a package with no baseline"
            )
        return line, None
    baseline = package.baseline
    difference = f"{measured - baseline:+.1f}"
    line = f"{package.name}: {_format(measured)} (baseline {_format(baseline)}, {difference})"
    if measured < baseline - config.tolerance - 1e-9:
        return line, (
            f"{package.name} measures {_format(measured)}, {baseline - measured:.1f} below its "
            f"baseline of {_format(baseline)} (tolerance {config.tolerance:g})"
        )
    raised = int(measured * 10) / 10
    if raised > baseline:
        line += f"; its baseline could be raised to {raised:.1f}"
    return line, None


def coverage_result(files: Mapping[str, Counts], config: CoverageConfig) -> CoverageResult:
    """Each package's coverage against its baseline or the floor, and every file in no package."""
    totals = {package.name: Counts(0, 0) for package in config.packages}
    problems = []
    for path, counts in sorted(files.items()):
        owner = next(
            (p for p in config.packages if any(_under(path, prefix) for prefix in p.paths)), None
        )
        if owner is None:
            problems.append(
                f"{path} is in no package. Fix: add it to a package's paths in {CONFIG_NAME}."
            )
            continue
        totals[owner.name] += counts
    lines = []
    for package in config.packages:
        line, problem = _package_line(package, totals[package.name], config)
        lines.append(line)
        if problem is not None:
            problems.append(problem)
    return CoverageResult(lines, problems)


# --- Command line ---------------------------------------------------------------------------------


def _tool(name: str, given: str | None) -> str:
    """A tool named on the command line, beside this interpreter, or on the PATH."""
    if given is not None:
        return given
    found = shutil.which(name, path=str(Path(sys.executable).parent)) or shutil.which(name)
    if found is None:
        raise GateError(f"{name} isn't installed. Fix: run `uv sync`.")
    return found


def _complexity(args: argparse.Namespace, root: Path, config: Config) -> int:
    base = resolve_base(root, args.base)
    lizard = _tool("lizard", args.lizard)
    problems = complexity_problems(root, base, config.complexity, lizard)
    for problem in problems:
        print(f"complexity: {problem.text()}")
    if problems:
        print(
            "complexity: split the function, or move its branches into named helpers "
            f"(the limit is [complexity] block_above in {CONFIG_NAME})."
        )
        return 1
    print(f"complexity: no new or edited function above {config.complexity.block_above}")
    return 0


def _size(args: argparse.Namespace, root: Path, config: Config) -> int:
    if config.size is None:
        print(f"size: not declared in this repository (no [size] in {CONFIG_NAME})")
        return 0
    result = size_result(root, resolve_base(root, args.base), config.size)
    for note in result.notes:
        print(f"size: note {note}")
    for problem in result.problems:
        print(f"size: FAIL {problem}")
    if result.problems:
        print(
            "size: split the file so a review can read it in one or two goes, or declare it with "
            f"a ceiling in [size.allow] (the limits are [size] in {CONFIG_NAME})."
        )
        return 1
    print(f"size: no added or grown file above {config.size.block_above:,} bytes")
    return 0


def _coverage(args: argparse.Namespace, root: Path, config: Config) -> int:
    if config.coverage is None:
        print(f"coverage: not measured in this repository (no [coverage] in {CONFIG_NAME})")
        return 0
    report_path = Path(args.coveragepy or args.vitest)
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GateError(f"couldn't read the coverage report {report_path}: {error}.") from error
    files = coveragepy_counts(report, root) if args.coveragepy else vitest_counts(report, root)
    delivered = delivered_paths(root)
    measured = {path: counts for path, counts in files.items() if path not in delivered}
    result = coverage_result(measured, config.coverage)
    for line in result.lines:
        print(f"coverage: {line}")
    for problem in result.problems:
        print(f"coverage: FAIL {problem}")
    return 1 if result.problems else 0


def main(argv: Sequence[str] | None = None, root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    gates = parser.add_subparsers(dest="gate", required=True)
    complexity = gates.add_parser("complexity")
    complexity.add_argument("--base")
    complexity.add_argument("--lizard")
    size = gates.add_parser("size")
    size.add_argument("--base")
    coverage = gates.add_parser("coverage")
    reports = coverage.add_mutually_exclusive_group(required=True)
    reports.add_argument("--coveragepy")
    reports.add_argument("--vitest")
    audit = gates.add_parser("audit")
    audit.add_argument("--base")
    audit.add_argument("--uv")
    audit.add_argument("--pip-audit")
    audit.add_argument("--npm")
    report = gates.add_parser("report")
    report.add_argument("--repository", required=True, help="owner/name, where the issue lives")
    report.add_argument("--github-output", help="where to write issue-url= when an issue opens")
    report.add_argument("--gh")
    report.add_argument("--uv")
    report.add_argument("--pip-audit")
    report.add_argument("--npm")
    args = parser.parse_args(argv)
    root = root or Path.cwd()
    # Imported here: quality_audit imports this module for the config and errors it shares.
    import quality_audit

    run = {
        "complexity": _complexity,
        "size": _size,
        "coverage": _coverage,
        "audit": quality_audit.audit_command,
        "report": quality_audit.report_command,
    }[args.gate]
    try:
        return run(args, root, read_config(root))
    except GateError as error:
        print(f"{args.gate}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    # Run as the module, not as __main__: quality_audit imports `quality_gates`, and two copies
    # would have two GateErrors, so main couldn't catch the audit's.
    import quality_gates

    sys.exit(quality_gates.main())
