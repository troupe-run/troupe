# Source: troupe-run/infrastructure. Change it there; copies in other repositories are delivered.
"""The quality gates every governed repository's check runs (spec: quality-gates; its design).

Usage:
    quality_gates.py complexity [--base REV] [--lizard PATH]
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
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

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
    top.keys(["version", "complexity", "audit"], ["coverage", "mutation"])
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
    return Config(coverage, complexity, audit, mutation)


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
    """Every function lizard finds in `paths` under `tree`."""
    if not paths:
        return []
    result = _process([lizard, "--csv", *paths], tree)
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
    """Each function the work adds or edits that is above the limit, and new or more complex."""
    changes = {
        path: lines
        for path, lines in changed_lines(root, base).items()
        if measured_path(path, config) and (root / path).is_file()
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


# --- Audit (design D7) ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Advisory:
    package: str
    version: str
    id: str
    severity: str
    """One of SEVERITIES, or `unknown`."""
    fixed_in: str | None
    """The version that fixes it, or None when there's no fix."""

    def text(self) -> str:
        fix = f"fixed in {self.fixed_in}" if self.fixed_in else "no fix yet"
        return f"{self.package} {self.version}: {self.id} ({self.severity}, {fix})"


def changed_lock_files(root: Path, base: str, lock_files: Sequence[str]) -> list[str]:
    """The configured lock files that differ between `base` and the work."""
    changed = []
    for lock in lock_files:
        diff = _git(root, "diff", "--quiet", base, "--", lock)
        if diff.returncode == 1:
            changed.append(lock)
        elif diff.returncode != 0:
            raise GateError(f"git diff of {lock} from {base} failed: {diff.stderr.strip()}")
        elif not (root / lock).exists():
            raise GateError(f"{CONFIG_NAME} names {lock}, which doesn't exist.")
    return changed


OSV_VULNS = "https://api.osv.dev/v1/vulns/"


def osv_record(advisory_id: str, timeout: float = 30) -> dict[str, object] | None:
    """An advisory's OSV record, or None when OSV doesn't have it. Unreachable is an error."""
    url = OSV_VULNS + urllib.parse.quote(advisory_id)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 (fixed https URL)
            record = json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise GateError(f"OSV answered {error.code} for {advisory_id}.") from error
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise GateError(f"couldn't read {advisory_id} from OSV ({url}): {error}.") from error
    return record if isinstance(record, dict) else None


def osv_severity(advisory_id: str, timeout: float = 30) -> str | None:
    """The severity GitHub's advisory database gives an advisory, through OSV, or None."""
    record = osv_record(advisory_id, timeout)
    specific = record.get("database_specific") if record else None
    severity = specific.get("severity") if isinstance(specific, dict) else None
    return severity.lower() if isinstance(severity, str) else None


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version))


def osv_fixed_version(record: Mapping[str, object], package: str) -> str | None:
    """The lowest version of `package` that OSV's record says fixes the advisory, or None.

    Only the vulnerable package's own patched releases count: npm's `fixAvailable` can name a
    downgrade of a package that depends on it, which isn't a fix (spec: quality-gates; #330)."""
    fixed = []
    affected = record.get("affected")
    for entry in affected if isinstance(affected, list) else []:
        if entry.get("package", {}).get("name") != package:
            continue
        for found in entry.get("ranges", []):
            fixed += [event["fixed"] for event in found.get("events", []) if "fixed" in event]
    return min(fixed, key=_version_key) if fixed else None


SeverityLookup = Callable[[str], str | None]
RecordLookup = Callable[[str], Mapping[str, object] | None]


def pip_audit_advisories(report: Mapping[str, object], severity: SeverityLookup) -> list[Advisory]:
    """Each advisory in pip-audit's JSON, once, with its severity read through its GitHub alias."""
    dependencies = report.get("dependencies")
    if not isinstance(dependencies, list):
        raise GateError("pip-audit's report has no `dependencies`: is it `-f json` output?")
    advisories: dict[tuple[str, str], Advisory] = {}
    for dependency in dependencies:
        for vuln in dependency.get("vulns", []):
            key = (dependency["name"], vuln["id"])
            if key in advisories:
                continue  # pip-audit lists some advisories twice
            ids = [vuln["id"], *vuln.get("aliases", [])]
            github = next((i for i in ids if i.startswith("GHSA-")), None)
            found = severity(github) if github else None
            fixes = vuln.get("fix_versions") or []
            advisories[key] = Advisory(
                dependency["name"],
                dependency["version"],
                github or vuln["id"],
                found if found in SEVERITIES else "unknown",
                fixes[0] if fixes else None,
            )
    return list(advisories.values())


def _npm_own_fix(entry: object, package: str) -> str | None:
    """npm's fix for an advisory OSV has no record of, only when it names the vulnerable package
    itself: a dependent's move, such as a downgrade, isn't a fix (owner, 2026-11-18; #330)."""
    fix = entry.get("fixAvailable") if isinstance(entry, dict) else None
    if isinstance(fix, dict) and fix.get("name") == package and isinstance(fix.get("version"), str):
        return str(fix["version"])
    return None


def npm_audit_advisories(
    report: Mapping[str, object], record: RecordLookup = osv_record
) -> list[Advisory]:
    """Each root advisory in `npm audit --json`, once, with npm's severity and OSV's fixed version.

    npm lists every package that depends on a vulnerable one too; the advisories themselves are
    the objects in each entry's `via`. Each one's fix is OSV's; npm's `fixAvailable` is read only
    when OSV has no record, and only when it names the vulnerable package itself, since it can be a
    downgrade of a dependent (#330)."""
    if "error" in report:
        raise GateError(f"npm audit failed: {report['error']}")
    vulnerabilities = report.get("vulnerabilities")
    if not isinstance(vulnerabilities, dict):
        raise GateError("npm audit's report has no `vulnerabilities`: is it `--json` output?")
    roots: dict[object, Mapping[str, object]] = {}
    for entry in vulnerabilities.values():
        for via in entry.get("via", []):
            if isinstance(via, dict):
                roots.setdefault(via.get("source", via.get("url")), via)
    advisories = []
    for via in sorted(roots.values(), key=lambda v: (str(v.get("name")), str(v.get("url")))):
        package = str(via.get("name"))
        advisory_id = str(via.get("url", "")).rstrip("/").rsplit("/", 1)[-1] or "npm advisory"
        found = record(advisory_id) if advisory_id.startswith("GHSA-") else None
        if found is not None:
            fixed_in = osv_fixed_version(found, package)
        else:
            fixed_in = _npm_own_fix(vulnerabilities.get(package), package)
        severity = via.get("severity")
        advisories.append(
            Advisory(
                package,
                str(via.get("range", "?")),
                advisory_id,
                severity if isinstance(severity, str) and severity in SEVERITIES else "unknown",
                fixed_in,
            )
        )
    return advisories


def blocking(advisories: Iterable[Advisory], config: AuditConfig) -> list[Advisory]:
    """The advisories that fail the gate: a blocked or unknown severity, with a fix."""
    return [
        advisory
        for advisory in advisories
        if advisory.fixed_in is not None
        and (advisory.severity in config.block or advisory.severity == "unknown")
    ]


def _run_json(command: Sequence[str], root: Path, what: str) -> dict[str, object]:
    """Run a tool that prints JSON (exit 1 can mean "found something"), and parse it."""
    result = _process(command, root)
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise GateError(
            f"{what} failed (exit {result.returncode}): {result.stderr.strip()[-2000:]}"
        ) from None
    if not isinstance(data, dict):
        raise GateError(f"{what} printed JSON that isn't an object.")
    return data


def audit_uv_lock(
    root: Path, uv: str, pip_audit: str, severity: SeverityLookup = osv_severity
) -> list[Advisory]:
    """Every advisory for what uv.lock pins, every group and workspace member included."""
    with tempfile.TemporaryDirectory() as scratch:
        requirements = Path(scratch) / "requirements.txt"
        exported = _process(
            [uv, "export", "--frozen", "--all-groups", "--all-packages", "--no-emit-workspace",
             "--no-hashes", "--no-header", "--quiet", "--output-file", str(requirements)],
            root,
        )  # fmt: skip
        if exported.returncode != 0:
            raise GateError(f"uv export failed: {exported.stderr.strip()}")
        report = _run_json(
            [pip_audit, "-r", str(requirements), "--no-deps", "--disable-pip", "-s", "osv",
             "-f", "json", "--progress-spinner", "off"],
            root, "pip-audit",
        )  # fmt: skip
    return pip_audit_advisories(report, severity)


def audit_package_lock(root: Path, npm: str) -> list[Advisory]:
    return npm_audit_advisories(
        _run_json([npm, "audit", "--package-lock-only", "--json"], root, "npm audit")
    )


# --- Weekly report (design D8) --------------------------------------------------------------------

REPORT_TITLE = "Dependency advisories"
REPORT_LABEL = "dependencies"


class IssueTracker(Protocol):
    """The one report issue: found among open issues by title and label."""

    def find_open(self) -> int | None: ...
    def create(self, body: str) -> str: ...
    def edit(self, number: int, body: str) -> None: ...
    def close(self, number: int, comment: str) -> None: ...


def report_body(
    advisories: Sequence[Advisory], config: AuditConfig, lock_files: Sequence[str]
) -> str:
    """The issue's body: every advisory, marking those that would block a pull request."""
    failing = blocking(advisories, config)
    rows = [
        f"| {a.package} | {a.version} | {a.id} | {a.severity} | {a.fixed_in or 'no fix yet'} | "
        f"{'yes' if a in failing else ''} |"
        for a in sorted(advisories, key=lambda a: (a.package, a.id))
    ]
    return "\n".join(
        [
            f"The weekly dependency audit found {len(advisories)} advisories in "
            f"{', '.join(f'`{lock}`' for lock in lock_files)} on `main` "
            "(spec: quality-gates). This issue is kept up to date by "
            "`.github/workflows/dependency-report.yml`: its list is replaced each week, and it's "
            "closed when the audit finds none.",
            "",
            "A pull request that changes a lock file fails on the advisories marked *blocks*.",
            "",
            "| Package | Version | Advisory | Severity | Fixed in | Blocks |",
            "|---|---|---|---|---|---|",
            *rows,
        ]
    )


def upkeep(
    advisories: Sequence[Advisory],
    config: AuditConfig,
    issues: IssueTracker,
    lock_files: Sequence[str],
) -> str | None:
    """Open, update or close the one report issue. Returns its URL when it was opened."""
    number = issues.find_open()
    if not advisories:
        if number is not None:
            issues.close(number, "The weekly dependency audit found no advisories.")
        return None
    body = report_body(advisories, config, lock_files)
    if number is None:
        return issues.create(body)
    issues.edit(number, body)
    return None


class GhIssues:
    """The report issue through the gh CLI, with the token the workflow gives it."""

    def __init__(self, gh: str, repository: str) -> None:
        self.gh = gh
        self.repository = repository

    def _run(self, *args: str, body: str | None = None) -> str:
        result = _process([self.gh, *args, "-R", self.repository], Path.cwd(), body)
        if result.returncode != 0:
            raise GateError(f"gh {args[0]} {args[1]} failed: {result.stderr.strip()}")
        return result.stdout

    def find_open(self) -> int | None:
        listed = json.loads(
            self._run(
                "issue", "list", "--state", "open", "--label", REPORT_LABEL,
                "--search", f'in:title "{REPORT_TITLE}"', "--json", "number,title",
            )
        )  # fmt: skip
        matches = sorted(i["number"] for i in listed if i["title"] == REPORT_TITLE)
        return matches[0] if matches else None

    def create(self, body: str) -> str:
        return self._run(
            "issue", "create", "--title", REPORT_TITLE, "--label", REPORT_LABEL,
            "--body-file", "-", body=body,
        ).strip()  # fmt: skip

    def edit(self, number: int, body: str) -> None:
        self._run("issue", "edit", str(number), "--body-file", "-", body=body)

    def close(self, number: int, comment: str) -> None:
        self._run("issue", "close", str(number), "--comment", comment)


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
    result = coverage_result(files, config.coverage)
    for line in result.lines:
        print(f"coverage: {line}")
    for problem in result.problems:
        print(f"coverage: FAIL {problem}")
    return 1 if result.problems else 0


def _audit_locks(args: argparse.Namespace, root: Path, locks: Sequence[str]) -> list[Advisory]:
    found: list[Advisory] = []
    for lock in locks:
        if Path(lock).name == "uv.lock":
            where = root / Path(lock).parent
            found += audit_uv_lock(where, _tool("uv", args.uv), _tool("pip-audit", args.pip_audit))
        else:
            found += audit_package_lock(root / Path(lock).parent, _tool("npm", args.npm))
    return found


def _audit(args: argparse.Namespace, root: Path, config: Config) -> int:
    base = resolve_base(root, args.base)
    changed = changed_lock_files(root, base, config.audit.lock_files)
    if not changed:
        print("audit: no lock file changed, so nothing to audit")
        return 0
    found = _audit_locks(args, root, changed)
    failing = blocking(found, config.audit)
    for advisory in found:
        mark = "FAIL" if advisory in failing else "note"
        print(f"audit: {mark} {advisory.text()}")
    if failing:
        print("audit: update each package above to its fixed version, or pin a fixed version.")
        return 1
    print(f"audit: {', '.join(changed)}: no {'/'.join(config.audit.block)} advisory with a fix")
    return 0


def _report(args: argparse.Namespace, root: Path, config: Config) -> int:
    for lock in config.audit.lock_files:
        if not (root / lock).exists():
            raise GateError(f"{CONFIG_NAME} names {lock}, which doesn't exist.")
    found = _audit_locks(args, root, config.audit.lock_files)
    issues = GhIssues(_tool("gh", args.gh), args.repository)
    opened = upkeep(found, config.audit, issues, config.audit.lock_files)
    print(f"report: {len(found)} advisories in {', '.join(config.audit.lock_files)}")
    if opened is not None and args.github_output:
        with Path(args.github_output).open("a", encoding="utf-8") as output:
            output.write(f"issue-url={opened}\n")
    return 0


def main(argv: Sequence[str] | None = None, root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    gates = parser.add_subparsers(dest="gate", required=True)
    complexity = gates.add_parser("complexity")
    complexity.add_argument("--base")
    complexity.add_argument("--lizard")
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
    run = {"complexity": _complexity, "coverage": _coverage, "audit": _audit, "report": _report}[
        args.gate
    ]
    try:
        return run(args, root, read_config(root))
    except GateError as error:
        print(f"{args.gate}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
