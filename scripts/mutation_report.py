"""One shape for a mutation run's results, whichever tool made them (spec: mutation-testing;
lint-mutation design D3, D7, D8).

A report is what the job that ran a repository's tests hands on. The job that writes issues reads it
as data, against a closed schema: an unknown or missing field is an error naming it.

    {"version": 1, "repository": "troupe", "commit": "<sha>", "previous_commit": "<sha>" | null,
     "modules": {"<module>": {"killed": n, "survived": n, "no_tests": n, "timeout": n,
                              "crashed": n, "skipped": n, "finished": true,
                              "survivors": [{"name": ..., "path": ..., "line": n, "change": ...,
                                             "commit": "<sha>" | null, "new": false}],
                              "crashed_mutants": [{"name": ..., "path": ..., "line": n,
                                                   "change": ..., "exit_code": n | null}]}}}

A module's score counts untested code against it: caught (killed, timed out or crashed) over
caught, survived and not covered by any test. Skipped mutants don't count.

Standard library only, Python 3.12+: it's delivered with the pull request report (design D9).
"""

import ast
import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from mutation_settings import SettingsError, closed, text, whole

VERSION = 2
"""2 added each module's crashed_mutants (#361)."""
SHA = re.compile(r"[0-9a-f]{40}")
COUNTS = ("killed", "survived", "no_tests", "timeout", "crashed", "skipped")


class ReportError(Exception):
    """A report isn't well formed."""


@dataclass(frozen=True)
class Survivor:
    name: str  # the tool's name for the mutant, which its own commands take
    path: str  # the file, relative to the repository's root
    line: int
    change: str  # the mutated line, as the tool shows it
    commit: str | None = None  # the commit that last changed the line (design D8)
    new: bool = False  # changed since the previous weekly run's tested commit (design D8)


@dataclass(frozen=True)
class Crashed:
    """A mutant whose tests died (by a signal, or the tool's runtime error), named so the owner can
    decide on an exclusion from it (#361)."""

    name: str
    path: str
    line: int
    change: str
    exit_code: int | None  # the tool's exit code for it; None where the tool gives none (Stryker)


@dataclass(frozen=True)
class Module:
    killed: int
    survived: int
    no_tests: int
    timeout: int
    crashed: int
    skipped: int
    finished: bool
    survivors: tuple[Survivor, ...]
    crashed_mutants: tuple[Crashed, ...] = ()

    @property
    def caught(self) -> int:
        return self.killed + self.timeout + self.crashed

    @property
    def counted(self) -> int:
        """The mutants the score is over: skipped ones don't count."""
        return self.caught + self.survived + self.no_tests

    @property
    def score(self) -> float:
        """Caught as a percentage of counted, to one decimal; 100 with nothing counted."""
        if self.counted == 0:
            return 100.0
        return round(100 * self.caught / self.counted, 1)


@dataclass(frozen=True)
class Report:
    repository: str
    commit: str
    previous_commit: str | None
    modules: dict[str, Module]


def sha(value: object, where: str, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise ReportError(f"{where} is {value!r}; it must be a full commit SHA")
    return value


def load_survivor(value: object, where: str) -> Survivor:
    fields = closed(value, {"name", "path", "line", "change", "commit", "new"}, where)
    new = fields["new"]
    if not isinstance(new, bool):
        raise ReportError(f"{where}.new is {new!r}; it must be true or false")
    return Survivor(
        name=text(fields["name"], f"{where}.name"),
        path=text(fields["path"], f"{where}.path"),
        line=whole(fields["line"], f"{where}.line", 1, 10_000_000),
        change=text(fields["change"], f"{where}.change"),
        commit=sha(fields["commit"], f"{where}.commit", optional=True),
        new=new,
    )


def load_crashed(value: object, where: str) -> Crashed:
    fields = closed(value, {"name", "path", "line", "change", "exit_code"}, where)
    code = fields["exit_code"]
    if code is not None and (isinstance(code, bool) or not isinstance(code, int)):
        raise ReportError(f"{where}.exit_code is {code!r}; it must be a whole number or null")
    return Crashed(
        name=text(fields["name"], f"{where}.name"),
        path=text(fields["path"], f"{where}.path"),
        line=whole(fields["line"], f"{where}.line", 1, 10_000_000),
        change=text(fields["change"], f"{where}.change"),
        exit_code=code,
    )


def load_module(value: object, where: str) -> Module:
    fields = closed(value, {*COUNTS, "finished", "survivors", "crashed_mutants"}, where)
    counts = {name: whole(fields[name], f"{where}.{name}", 0, 10_000_000) for name in COUNTS}
    finished = fields["finished"]
    if not isinstance(finished, bool):
        raise ReportError(f"{where}.finished is {finished!r}; it must be true or false")
    survivors = fields["survivors"]
    if not isinstance(survivors, list):
        raise ReportError(f"{where}.survivors must be a list")
    loaded = tuple(
        load_survivor(item, f"{where}.survivors[{n}]") for n, item in enumerate(survivors)
    )
    if len(loaded) != counts["survived"]:
        raise ReportError(
            f"{where} lists {len(loaded)} survivors but counts {counts['survived']} survived"
        )
    crashes = fields["crashed_mutants"]
    if not isinstance(crashes, list):
        raise ReportError(f"{where}.crashed_mutants must be a list")
    crashed = tuple(
        load_crashed(item, f"{where}.crashed_mutants[{n}]") for n, item in enumerate(crashes)
    )
    if len(crashed) != counts["crashed"]:
        raise ReportError(
            f"{where} lists {len(crashed)} crashed mutants but counts {counts['crashed']} crashed"
        )
    return Module(**counts, finished=finished, survivors=loaded, crashed_mutants=crashed)


def load_report(source: str, repository: str) -> Report:
    """The report for `repository`, or ReportError naming the repository and what's wrong."""
    try:
        try:
            loaded: Any = json.loads(source)
        except json.JSONDecodeError as error:
            raise ReportError(f"it isn't JSON: {error}") from None
        fields = closed(
            loaded, {"version", "repository", "commit", "previous_commit", "modules"}, "it"
        )
        if fields["version"] != VERSION:
            raise ReportError(f"its version is {fields['version']!r}; this reads version {VERSION}")
        if fields["repository"] != repository:
            raise ReportError(f"it's for {fields['repository']!r}")
        modules = fields["modules"]
        if not isinstance(modules, dict):
            raise ReportError("its modules isn't an object")
        return Report(
            repository=repository,
            commit=str(sha(fields["commit"], "commit")),
            previous_commit=sha(fields["previous_commit"], "previous_commit", optional=True),
            modules={
                str(name): load_module(value, f"modules.{name}") for name, value in modules.items()
            },
        )
    except (ReportError, SettingsError) as error:
        raise ReportError(f"{repository}'s report: {error}") from None


def dump_report(report: Report) -> str:
    """The report as JSON, in the shape load_report reads."""
    return json.dumps(
        {
            "version": VERSION,
            "repository": report.repository,
            "commit": report.commit,
            "previous_commit": report.previous_commit,
            "modules": {
                name: {
                    **{count: getattr(module, count) for count in COUNTS},
                    "finished": module.finished,
                    "survivors": [vars(survivor) for survivor in module.survivors],
                    "crashed_mutants": [vars(crash) for crash in module.crashed_mutants],
                }
                for name, module in sorted(report.modules.items())
            },
        },
        indent=2,
    )


# W: who added each survivor (design D8)


def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)


def last_changed(root: Path, commit: str, path: str, line: int) -> str:
    """The commit that last changed `line` of `path`, as of `commit`."""
    blamed = git(root, "blame", "--porcelain", "-L", f"{line},{line}", commit, "--", path)
    if blamed.returncode != 0 or not SHA.match(blamed.stdout[:40]):
        raise ReportError(
            f"git blame of {path}:{line} at {commit[:12]} failed: {blamed.stderr.strip()}"
        )
    return blamed.stdout[:40]


def attribute(report: Report, root: Path, previous: str | None) -> Report:
    """The report with each survivor's last commit, and `new` when that commit isn't in `previous`.

    `previous` is the commit the previous weekly run tested this repository at. Without one (the
    first run, or one whose report has expired), nothing is new.
    """
    modules = {}
    for name, module in report.modules.items():
        survivors = []
        for survivor in module.survivors:
            commit = last_changed(root, report.commit, survivor.path, survivor.line)
            new = (
                previous is not None
                and git(root, "merge-base", "--is-ancestor", commit, previous).returncode != 0
            )
            survivors.append(replace(survivor, commit=commit, new=new))
        modules[name] = replace(module, survivors=tuple(survivors))
    return replace(report, previous_commit=previous, modules=modules)


# mutmut's results (design D3)

STATUS_BY_EXIT_CODE = {
    1: "killed",
    3: "killed",  # pytest's internal error is a kill
    37: "killed",  # caught by the type check
    0: "survived",
    5: "no_tests",
    33: "no_tests",
    36: "timeout",
    24: "timeout",
    -24: "timeout",
    152: "timeout",
    255: "timeout",
    -11: "crashed",
    -9: "crashed",
    34: "skipped",
}
"""mutmut's exit codes (mutmut.stats.status_by_exit_code, 3.8.1) as the report's counts. Any
other code, suspicious or interrupted, counts as skipped; no code at all means not run yet."""

MUTANT = re.compile(r"(?P<module>.+)\.(?P<function>x(?:_|\u01c1)[^.]+?)__mutmut_\d+")
HUNK = re.compile(r"^@@ -(?P<start>\d+)")


def module_name(path: str, source: str) -> str:
    """`packages/troupe/src/troupe/store/events.py`, under `packages/troupe/src`, is
    `troupe.store.events`."""
    relative = Path(path).relative_to(source).with_suffix("")
    parts = [part for part in relative.parts if part != "__init__"]
    return ".".join(parts)


def function_start(tree: ast.Module, mangled: str) -> int | None:
    """The first line (its first decorator's, if any) of mutmut's `x_f`, or of `x<sep>C<sep>m`
    for a method, <sep> being U+01C1."""
    if mangled.startswith("x_"):
        wanted, scope = mangled[2:], tree.body
    else:
        _, owner, wanted = mangled.split("\u01c1")
        classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == owner]
        if not classes:
            return None
        scope = classes[0].body
    for node in scope:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == wanted:
            return min([node.lineno, *(d.lineno for d in node.decorator_list)])
    return None


def mutated_line(diff: str, start: int) -> tuple[int, str]:
    """The file line a mutant changes, and its change, from `mutmut show`'s diff, which counts
    lines from the function's first."""
    offset, removed, added, seen = 0, [], [], False
    for line in diff.splitlines():
        hunk = HUNK.match(line)
        if hunk:
            offset, seen = int(hunk["start"]), True
            continue
        if not seen or line.startswith(("---", "+++")):
            continue
        if line.startswith("-"):
            removed.append(line)
        elif line.startswith("+"):
            added.append(line)
        elif not removed:
            offset += 1
    if not seen:  # no hunk to count from: the function's own first line is the nearest known
        return start, ""
    change = "\n".join([*removed, *added])
    return start + offset - 1, change


def from_mutmut(
    root: Path, source: str, show: Callable[[str], str], skip: tuple[str, ...] = ()
) -> dict[str, Module]:
    """Each module's counts and survivors from mutmut's `mutants/` tree, for one unit's `source`.
    Paths starting with one in `skip` (the unit's tests, whose fixtures may hold mutmut's own
    files) aren't read."""
    modules: dict[str, Module] = {}
    for meta in sorted((root / "mutants" / source).rglob("*.py.meta")):
        path = str(meta.relative_to(root / "mutants")).removesuffix(".meta")
        if path.startswith(skip) or not (root / path).is_file():
            continue
        codes = json.loads(meta.read_text(encoding="utf-8"))["exit_code_by_key"]
        counts = dict.fromkeys(COUNTS, 0)
        finished = True
        survivors = []
        crashed = []
        tree = ast.parse((root / path).read_text(encoding="utf-8"))
        for name, code in sorted(codes.items()):
            if code is None:
                finished = False
                continue
            status = STATUS_BY_EXIT_CODE.get(code, "skipped")
            counts[status] += 1
            if status not in ("survived", "crashed"):
                continue
            match = MUTANT.fullmatch(name)
            start = function_start(tree, match["function"]) if match else None
            line, change = mutated_line(show(name), start or 1)
            if status == "survived":
                survivors.append(Survivor(name, path, line, change or name))
            else:
                crashed.append(Crashed(name, path, line, change or name, code))
        modules[module_name(path, source)] = Module(
            killed=counts["killed"],
            survived=counts["survived"],
            no_tests=counts["no_tests"],
            timeout=counts["timeout"],
            crashed=counts["crashed"],
            skipped=counts["skipped"],
            finished=finished,
            survivors=tuple(survivors),
            crashed_mutants=tuple(crashed),
        )
    return modules
