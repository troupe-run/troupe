"""Mutation tests what a pull request changed, and reports what survives on its changed lines
(spec: mutation-testing; lint-mutation design D9).

Usage:
    python scripts/mutation_pr.py run BASE HEAD OUT    # mutate what changed; write its report
    python scripts/mutation_pr.py comment REPORT       # the comment's text, from a report

It runs in the repository the pull request is in, which names itself in GITHUB_REPOSITORY, and
reads that repository's targets from scripts/mutation.json. `run` is the job that runs the pull
request's code, with a read-only token; `comment` reads only the report it handed on, as data.

It never blocks: it reports. Only its own failure to run exits non-zero.

Standard library only, Python 3.12+: delivered with the guard's files (design D9).
"""

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mutation_report as mr
import mutation_settings as ms

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = ROOT / "scripts" / "mutation.json"
MARKER = "<!-- mutation-pr-report -->"
SEPARATOR = "\u01c1"
"""mutmut 3's separator between a class and its method in a mutant's name."""
SHOWN = 30
REPORT_VERSION = 1
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,(?P<count>\d+))? @@")


# What changed


def changed_lines(diff: str) -> dict[str, set[int]]:
    """Each file's added or changed lines, from `git diff --unified=0` (lines in the new file)."""
    changed: dict[str, set[int]] = {}
    path: str | None = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            target = line[4:]
            path = None if target == "/dev/null" else target.removeprefix("b/")
            continue
        hunk = HUNK.match(line)
        if hunk and path is not None:
            start, count = int(hunk["start"]), int(hunk["count"] or "1")
            changed.setdefault(path, set()).update(range(start, start + count))
    return {path: lines for path, lines in changed.items() if lines}


def mutmut_functions(source: str, lines: set[int]) -> set[str]:
    """mutmut's mangled names (`x_f`, or `x<sep>C<sep>m` for a method, <sep> being SEPARATOR) of
    the functions and methods the lines fall in."""
    found: set[str] = set()
    tree = ast.parse(source)

    def covers(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        first = min([node.lineno, *(d.lineno for d in node.decorator_list)])
        return any(first <= line <= (node.end_lineno or node.lineno) for line in lines)

    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and covers(node):
            found.add(f"x_{node.name}")
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef) and covers(item):
                    found.add(f"x{SEPARATOR}{node.name}{SEPARATOR}{item.name}")
    return found


def glob_regex(glob: str) -> re.Pattern[str]:
    """A path glob as Stryker reads it: `**/` is zero or more directories, `*` and `?` stay
    within one. fnmatch's `*` crosses `/`, and its `**/` needs at least one directory, so
    `src/index.ts` wouldn't match `src/**/*.ts`."""
    pattern = ""
    index = 0
    while index < len(glob):
        if glob.startswith("**/", index):
            pattern, index = pattern + "(?:.*/)?", index + 3
        elif glob.startswith("**", index):
            pattern, index = pattern + ".*", index + 2
        elif glob[index] == "*":
            pattern, index = pattern + "[^/]*", index + 1
        elif glob[index] == "?":
            pattern, index = pattern + "[^/]", index + 1
        else:
            pattern, index = pattern + re.escape(glob[index]), index + 1
    return re.compile(pattern)


def glob_match(path: str, glob: str) -> bool:
    return glob_regex(glob).fullmatch(path) is not None


@dataclass(frozen=True)
class Target:
    """What to mutate for one mutmut unit, or for Stryker."""

    unit: str  # the unit's name, or "stryker"
    globs: tuple[str, ...]  # mutmut name globs, or Stryker's file:start-end ranges
    lines: dict[str, list[int]]  # each file's changed lines, to filter survivors


def ranges(lines: set[int]) -> list[tuple[int, int]]:
    """Consecutive runs of line numbers."""
    runs: list[tuple[int, int]] = []
    for line in sorted(lines):
        if runs and line == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], line)
        else:
            runs.append((line, line))
    return runs


def plan(
    repository: ms.Repository, changed: Mapping[str, set[int]], read: Callable[[str], str]
) -> list[Target]:
    """The targets a pull request's changed lines call for, in the repository's own units."""
    targets = []
    if repository.tool == "mutmut":
        for unit in repository.units:
            globs: set[str] = set()
            lines: dict[str, list[int]] = {}
            for path, changed_here in sorted(changed.items()):
                if not path.endswith(".py") or not path.startswith(unit.source.rstrip("/") + "/"):
                    continue
                if path.startswith(unit.tests.rstrip("/") + "/"):
                    continue
                module = mr.module_name(path, unit.source)
                for function in mutmut_functions(read(path), changed_here):
                    globs.add(f"{module}.{function}__mutmut_*")
                lines[path] = sorted(changed_here)
            if globs:
                targets.append(Target(unit.name, tuple(sorted(globs)), lines))
    else:
        globs = set()
        lines = {}
        for path, changed_here in sorted(changed.items()):
            if any(glob_match(path, glob) for glob in repository.mutate):
                globs.update(f"{path}:{start}-{end}" for start, end in ranges(changed_here))
                lines[path] = sorted(changed_here)
        if globs:
            targets.append(Target("stryker", tuple(sorted(globs)), lines))
    return targets


# The report


def on_changed_lines(
    modules: Mapping[str, mr.Module], lines: Mapping[str, list[int]]
) -> list[mr.Survivor]:
    return [
        survivor
        for module in modules.values()
        for survivor in module.survivors
        if survivor.line in set(lines.get(survivor.path, ()))
    ]


def code(text: str) -> str:
    """Text for inside a code span: the report comes from the job that ran the pull request's own
    code, so a backtick can't end the span and let the rest render as Markdown."""
    return text.replace("`", "'")


def comment(report: Mapping[str, object]) -> str:
    """The pull request comment, from a report `run` wrote (read as data by load_pr_report)."""
    survivors = report["survivors"]
    timings = report["timings"]
    if not isinstance(survivors, list) or not isinstance(timings, dict):
        raise ms.SettingsError("the pull request report isn't one load_pr_report read")
    lines = [MARKER, "### Mutation testing of this pull request's changes", ""]
    if report["nothing"]:
        lines.append("No file this repository mutation tests changed, so nothing was mutated.")
    else:
        lines.append(
            f"{report['mutants']} mutants on changed code: {report['caught']} caught, "
            f"**{len(survivors)} surviving on changed lines**."
        )
        if not report["finished"]:
            lines.append("The run stopped at its budget, so some mutants weren't run.")
        if survivors:
            lines += ["", "No test fails when these changed lines are changed:", ""]
            for survivor in survivors[:SHOWN]:
                if not isinstance(survivor, dict):
                    raise ms.SettingsError("a survivor in the report isn't an object")
                change = code(str(survivor["change"]).replace("\n", " / "))
                lines.append(
                    f"- `{code(str(survivor['path']))}:{survivor['line']}` "
                    f"`{code(str(survivor['name']))}`: `{change}`"
                )
            if len(survivors) > SHOWN:
                lines.append(f"- and {len(survivors) - SHOWN} more, in the run's summary")
            lines += [
                "",
                "Add a test that fails for each, or exempt a line with the tool's own comment and "
                "a reason (`# pragma: no mutate`, "
                "`// Stryker disable next-line <mutator>: <reason>`).",
            ]
    lines += ["", "This is a report: it doesn't block the merge (lint-mutation design D9).", ""]
    lines.append(
        "Time: "
        + ", ".join(
            f"{step} {seconds:.0f}s"
            for step, seconds in timings.items()
            if isinstance(seconds, int | float)
        )
    )
    return "\n".join(lines) + "\n"


STEPS = {"plan", "mutation", "total"}
"""The steps a pull request report times."""

PR_REPORT_KEYS = {
    "version",
    "repository",
    "nothing",
    "finished",
    "mutants",
    "caught",
    "survivors",
    "timings",
}


def load_pr_report(source: str) -> dict[str, object]:
    """A pull request report, read against its closed schema (spec: the comment job reads data)."""
    loaded = json.loads(source)
    fields = ms.closed(loaded, PR_REPORT_KEYS, "the pull request report")
    if fields["version"] != REPORT_VERSION:
        raise ms.SettingsError(f"the pull request report's version is {fields['version']!r}")
    for key in ("nothing", "finished"):
        if not isinstance(fields[key], bool):
            raise ms.SettingsError(f"the pull request report's {key} isn't true or false")
    for key in ("mutants", "caught"):
        ms.whole(fields[key], f"the pull request report's {key}", 0, 10_000_000)
    if not isinstance(fields["survivors"], list):
        raise ms.SettingsError("the pull request report's survivors isn't a list")
    for index, survivor in enumerate(fields["survivors"]):
        mr.load_survivor(survivor, f"survivors[{index}]")
    timings = fields["timings"]
    if not isinstance(timings, dict) or not all(
        isinstance(value, int | float) and not isinstance(value, bool) for value in timings.values()
    ):
        raise ms.SettingsError("the pull request report's timings aren't seconds by step")
    for step in sorted(set(timings) - STEPS):
        # The report comes from the run of the pull request's own code: only known steps reach
        # the comment, so no key can carry Markdown into it.
        raise ms.SettingsError(
            f"the pull request report's timings name {step!r}, not one of {sorted(STEPS)}"
        )
    return fields


# The command


def git_diff(checkout: Path, base: str, head: str) -> str:
    done = subprocess.run(
        ["git", "diff", "--unified=0", "--no-color", "--no-renames", f"{base}...{head}"],
        cwd=checkout,
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise ms.SettingsError(f"git diff {base}...{head} failed: {done.stderr.strip()}")
    return done.stdout


def only_argument(targets: Sequence[Target]) -> dict[str, list[str]]:
    """What mutation_run.py's --only takes."""
    return {target.unit: list(target.globs) for target in targets}


def pr_report(
    repository: str,
    targets: Sequence[Target],
    report: mr.Report | None,
    timings: Mapping[str, float],
) -> dict[str, object]:
    """The pull request report: survivors on changed lines only."""
    lines: dict[str, list[int]] = {}
    for target in targets:
        for path, changed in target.lines.items():
            lines.setdefault(path, []).extend(changed)
    modules = report.modules if report is not None else {}
    survivors = on_changed_lines(modules, lines)
    return {
        "version": REPORT_VERSION,
        "repository": repository,
        "nothing": not targets,
        "finished": all(module.finished for module in modules.values()),
        "mutants": sum(module.counted for module in modules.values()),
        "caught": sum(module.caught for module in modules.values()),
        "survivors": [vars(survivor) for survivor in survivors],
        "timings": dict(timings),
    }


def run_mutation(command: list[str]) -> int:
    """Run mutation_run.py, its output streaming to the job's log."""
    return subprocess.run(command, check=False).returncode


def main(
    argv: Sequence[str] | None = None,
    env: Mapping[str, str] = os.environ,
    root: Path = ROOT,
    mutate: Callable[[list[str]], int] = run_mutation,
) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("base")
    run.add_argument("head")
    run.add_argument("out", type=Path)
    show = commands.add_parser("comment")
    show.add_argument("report", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "comment":
            fields = load_pr_report(args.report.read_text(encoding="utf-8"))
            print(comment(fields), end="")
            return 0
        settings = ms.load_settings(SETTINGS.read_text(encoding="utf-8"))
        name = env.get("GITHUB_REPOSITORY", "").removeprefix("troupe-run/")
        if name not in settings.repositories:
            raise ms.SettingsError(
                f"GITHUB_REPOSITORY names {name!r}, which mutation.json doesn't list"
            )
        started = time.monotonic()
        changed = changed_lines(git_diff(root, args.base, args.head))
        targets = plan(
            settings.repositories[name], changed, lambda p: (root / p).read_text(encoding="utf-8")
        )
        timings = {"plan": time.monotonic() - started}
        report = None
        if targets:
            out = args.out.with_suffix(".mutants.json")
            command = [
                sys.executable,
                str(root / "scripts" / "mutation_run.py"),
                name,
                str(root),
                str(out),
                "--only",
                json.dumps(only_argument(targets)),
            ]
            begun = time.monotonic()
            code = mutate(command)
            timings["mutation"] = time.monotonic() - begun
            if code != 0:
                raise ms.SettingsError(f"mutation_run.py failed (exit {code})")
            report = mr.load_report(out.read_text(encoding="utf-8"), name)
        timings["total"] = time.monotonic() - started
        fields = pr_report(name, targets, report, timings)
    except (ms.SettingsError, mr.ReportError) as error:
        print(f"mutation_pr: {error}", file=sys.stderr)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(fields, indent=2), encoding="utf-8")
    if summary := env.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(comment(fields))
    return 0


if __name__ == "__main__":
    sys.exit(main())
