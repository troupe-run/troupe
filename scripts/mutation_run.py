"""Runs mutmut or Stryker over a repository and writes a mutation report (spec: mutation-testing;
lint-mutation design D3, D8, D9).

Usage: python scripts/mutation_run.py REPOSITORY CHECKOUT OUT [--previous SHA] [--only JSON]

REPOSITORY names an entry in scripts/mutation.json; CHECKOUT is a throwaway checkout of it, which
this changes (it writes mutmut's configuration and output there). OUT is the report to write
(scripts/mutation_report.py's shape). --previous is the commit the previous weekly run tested,
for attributing new survivors (design D8). --only limits the run to what a pull request changed:
a JSON object from mutation_pr.py's plan, {unit: [mutmut name globs or Stryker file:range]}
(design D9). The budget is the settings' budget_minutes, or pr_budget_minutes with --only; a run
that reaches it stops, and what didn't run is reported as not finished.

What a trial of mutmut 3.8.1 taught (design D3):
- mutmut names a module by its path from where it runs, stripping only `src/`, so it runs where
  `src` is the unit's source: a package's own directory in troupe, and in infrastructure the
  checkout's root with `src` linked to `scripts`.
- The tests run in mutmut's copy, `mutants/`, so what they read beside the source is copied in too
  (the unit's also_copy), and the repository's own pytest addopts, which load plugins that look
  for files from the repository's root, are cleared.

Standard library only, Python 3.12+: delivered with the pull request report (design D9).
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mutation_report as mr
import mutation_settings as ms

SETTINGS = Path(__file__).resolve().parent / "mutation.json"
CHILDREN_PLUGIN = Path(__file__).resolve().parent / "mutation_children.py"
PLUGIN_COPY = "_mutation_children_plugin"
"""The plugin's name in mutmut's working directory: not mutation_children, since infrastructure's
own copy of that is in the source mutmut mutates, and a mutated copy would load in its place."""
CHILDREN = 4
"""Parallel mutants: a hosted Linux runner has 4 CPUs."""


class RunError(Exception):
    """A tool couldn't run at all, as opposed to running and finding survivors."""


Run = Callable[[list[str], Path, float], int]
"""Runs a command in a directory, with a timeout in seconds: its exit code, or -1 on timeout."""


def run_command(command: list[str], cwd: Path, timeout: float) -> int:
    try:
        return subprocess.run(command, cwd=cwd, check=False, timeout=max(timeout, 1)).returncode
    except subprocess.TimeoutExpired:
        return -1


# mutmut


def mutmut_workdir(checkout: Path, unit: ms.Unit) -> Path:
    """Where mutmut runs for a unit: the directory whose `src` is the unit's source."""
    source = checkout / unit.source
    if source.name == "src":
        return source.parent
    link = checkout / "src"
    if link.exists() or link.is_symlink():
        raise RunError(f"{checkout} already has a src, so {unit.source} can't be linked there")
    link.symlink_to(unit.source, target_is_directory=True)
    return checkout


def mutmut_config(workdir: Path, checkout: Path, unit: ms.Unit) -> str:
    """mutmut's setup.cfg for a unit, with paths from its working directory."""

    def local(path: str) -> str:
        return os.path.relpath(checkout / path, workdir)

    tests = local(unit.tests)
    also_copy = [local(path) for path in unit.also_copy] + [f"{PLUGIN_COPY}.py"]
    do_not_mutate = []
    if workdir == checkout:
        # The source is linked as src, and its tests with it: they're run, never mutated. Every
        # other top-level entry is copied beside it, since the tests find the repository's files
        # from their own place (a hand-kept list missed .tflint.hcl in the trial).
        tests = "src/" + os.path.relpath(checkout / unit.tests, checkout / unit.source)
        do_not_mutate.append(f"{tests}/*")
        # The source's own name is linked to the mutated copy instead (run_mutmut): an unmutated
        # copy under it would shadow the mutants for code that imports through it, as check.py does.
        skipped = {
            unit.source.rstrip("/"),
            "src",
            ".git",
            ".venv",
            "mutants",
            "setup.cfg",
            "node_modules",
            f"{PLUGIN_COPY}.py",
        }
        also_copy += sorted(
            p.name for p in checkout.iterdir() if p.name not in skipped and p.name not in also_copy
        )

    def listed(values: Sequence[str]) -> str:
        return "".join(f"\n    {value}" for value in values)

    lines = [
        "[mutmut]",
        "source_paths=src/",
        f"pytest_add_cli_args_test_selection={tests}",
        "pytest_add_cli_args="
        + listed(["-o", "addopts=-ra", "-p", PLUGIN_COPY, *deselected(workdir, checkout, unit)]),
        f"max_children={CHILDREN}",
    ]
    if do_not_mutate:
        lines.append("do_not_mutate=" + listed(do_not_mutate))
    if also_copy:
        lines.append("also_copy=" + listed(also_copy))
    return "\n".join(lines) + "\n"


def deselected(workdir: Path, checkout: Path, unit: ms.Unit) -> list[str]:
    """pytest's --deselect for each test the settings say mutmut's hooks can't run, as its node
    id from mutmut's working directory (design D3)."""
    args = []
    for test, _ in unit.deselect:
        path, _, node = test.partition("::")
        if workdir == checkout:
            local = "src/" + os.path.relpath(checkout / path, checkout / unit.source)
        else:
            local = os.path.relpath(checkout / path, workdir)
        args += ["--deselect", f"{local}::{node}"]
    return args


def mutmut_bin() -> str:
    found = shutil.which("mutmut")
    if found is None:
        raise RunError("mutmut isn't on the PATH: install the version scripts/mutation.json names")
    return found


def run_mutmut(
    checkout: Path, unit: ms.Unit, names: Sequence[str], deadline: float, run: Run
) -> dict[str, mr.Module]:
    """One unit's modules, with paths as in the checkout. `names` limits it to those globs."""
    workdir = mutmut_workdir(checkout, unit)
    if (workdir / "setup.cfg").exists():
        if workdir == checkout:
            (checkout / "src").unlink()
        raise RunError(
            f"{workdir / 'setup.cfg'} exists, and mutmut reads its configuration from there: "
            "this run writes its own, so it won't overwrite one the repository holds"
        )
    plugin = workdir / f"{PLUGIN_COPY}.py"
    try:
        shutil.copy2(CHILDREN_PLUGIN, plugin)
        (workdir / "setup.cfg").write_text(mutmut_config(workdir, checkout, unit), encoding="utf-8")
        shutil.rmtree(workdir / "mutants", ignore_errors=True)
        if workdir == checkout:
            # In mutmut's copy, the source's own name leads to the mutated source, so code that
            # puts <root>/scripts on sys.path (check.py) imports the mutants, not the original
            # (trial, 2026-11-18: every mutant read as untested until this).
            (workdir / "mutants").mkdir()
            (workdir / "mutants" / unit.source.rstrip("/")).symlink_to(
                "src", target_is_directory=True
            )
        mutmut = mutmut_bin()
        code = run([mutmut, "run", *names], workdir, deadline - time.monotonic())
        if code not in (0, -1):
            # mutmut stops before mutating anything when the unit's tests fail in its copy: that's
            # a run that didn't happen, never a report of empty modules.
            raise RunError(f"mutmut failed for {unit.name} (exit {code}); its output says why")

        def show(name: str) -> str:
            done = subprocess.run(
                [mutmut, "show", name], cwd=workdir, capture_output=True, text=True, check=False
            )
            return done.stdout

        tests = os.path.relpath(checkout / unit.tests, checkout / unit.source)
        modules = mr.from_mutmut(workdir, "src", show, skip=(f"src/{tests}/",))
        source = unit.source.rstrip("/")
        mapped = {}
        for name, module in modules.items():
            survivors = tuple(
                replace(survivor, path=source + survivor.path.removeprefix("src"))
                for survivor in module.survivors
            )
            # A whole run the budget stopped leaves its unrun mutants without a code, so from_mutmut
            # already reports their modules as not finished. A run limited to named functions
            # leaves every other mutant unrun on purpose: it finished unless the budget stopped it.
            finished = code != -1 if names else module.finished
            mapped[name] = replace(module, survivors=survivors, finished=finished)
        return mapped
    finally:
        if workdir == checkout:
            (checkout / "src").unlink()
        plugin.unlink(missing_ok=True)


# Stryker

STRYKER_STATUS = {
    "Killed": "killed",
    "Survived": "survived",
    "NoCoverage": "no_tests",
    "Timeout": "timeout",
    "RuntimeError": "crashed",
    "CompileError": "skipped",  # an invalid mutant, which Stryker leaves out of its score too
    "Ignored": "skipped",
}


def from_stryker(report: Mapping[str, object]) -> dict[str, mr.Module]:
    """Each file's counts and survivors from Stryker's JSON report (the mutation testing
    report schema)."""
    files = report.get("files")
    if not isinstance(files, dict):
        raise RunError("Stryker's report has no files")
    modules = {}
    for path, entry in sorted(files.items()):
        lines = str(entry.get("source", "")).splitlines()
        counts = dict.fromkeys(mr.COUNTS, 0)
        finished = True
        survivors = []
        for mutant in entry.get("mutants", []):
            status = STRYKER_STATUS.get(str(mutant.get("status")))
            if status is None:  # Pending: not run within the budget
                finished = False
                continue
            counts[status] += 1
            if status != "survived":
                continue
            start = mutant["location"]["start"]
            end = mutant["location"]["end"]
            line = int(start["line"])
            original = lines[line - 1] if 0 < line <= len(lines) else ""
            if int(end["line"]) == line:
                mutated = (
                    original[: start["column"] - 1]
                    + str(mutant.get("replacement", ""))
                    + original[end["column"] - 1 :]
                )
            else:
                mutated = f"{mutant.get('mutatorName')}: {mutant.get('replacement', '')}"
            name = f"{mutant.get('mutatorName')}#{mutant.get('id')}"
            survivors.append(mr.Survivor(name, path, line, f"-{original}\n+{mutated}"))
        modules[path] = mr.Module(**counts, finished=finished, survivors=tuple(survivors))
    return modules


def stryker_commands(mutate: Sequence[str], version: str) -> list[list[str]]:
    """Install Stryker into the checkout, then run it (design D3; trial, 2026-11-18).

    - Installed into the project (`--no-save`: package.json and the lockfile are left alone), since
      Stryker run from npx's own cache can't find the project's typescript or vitest.
    - `--inPlace`: the checkout is throwaway, and Stryker's sandbox copy fails on the repository's
      symlinked skills.
    - One test runner: website's roadmap tests fetch into a shared git cache, and parallel
      runners collide on its lock.
    """
    return [
        [
            "npm",
            "install",
            "--no-save",
            "--no-audit",
            "--no-fund",
            f"@stryker-mutator/core@{version}",
            f"@stryker-mutator/vitest-runner@{version}",
        ],
        [
            "npx",
            "--no-install",
            "stryker",
            "run",
            "--inPlace",
            "--testRunner",
            "vitest",
            "--reporters",
            "json,html",
            "--concurrency",
            "1",
            "--mutate",
            ",".join(mutate),
        ],
    ]


def run_stryker(
    checkout: Path,
    repository: ms.Repository,
    mutate: Sequence[str],
    deadline: float,
    version: str,
    run: Run,
) -> dict[str, mr.Module]:
    out = checkout / "reports" / "mutation" / "mutation.json"
    out.unlink(missing_ok=True)
    install, stryker = stryker_commands(mutate or repository.mutate, version)
    installed = run(install, checkout, deadline - time.monotonic())
    if installed != 0:
        raise RunError(f"installing Stryker {version} failed (exit {installed})")
    code = run(stryker, checkout, deadline - time.monotonic())
    if not out.exists():
        raise RunError(f"Stryker wrote no report (exit {code})")
    modules = from_stryker(json.loads(out.read_text(encoding="utf-8")))
    if code == -1:
        modules = {name: replace(module, finished=False) for name, module in modules.items()}
    return modules


# The run


def head(checkout: Path) -> str:
    done = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=checkout, capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        raise RunError(f"{checkout} isn't a git checkout")
    return done.stdout.strip()


def collect(
    repository: ms.Repository,
    checkout: Path,
    settings: ms.Settings,
    only: Mapping[str, Sequence[str]] | None,
    run: Run,
) -> dict[str, mr.Module]:
    minutes = settings.pr_budget_minutes if only is not None else settings.budget_minutes
    deadline = time.monotonic() + minutes * 60
    modules: dict[str, mr.Module] = {}
    if repository.tool == "mutmut":
        for unit in repository.units:
            names = list(only.get(unit.name, [])) if only is not None else []
            if only is not None and not names:
                continue
            if time.monotonic() >= deadline:
                break  # a unit not reached has no modules in the report, so none is judged
            modules.update(run_mutmut(checkout, unit, names, deadline, run))
    else:
        mutate = list(only.get("stryker", [])) if only is not None else []
        if only is None or mutate:
            modules.update(
                run_stryker(checkout, repository, mutate, deadline, settings.tools["stryker"], run)
            )
    return modules


def main(argv: Sequence[str] | None = None, run: Run = run_command) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("repository")
    parser.add_argument("checkout", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--previous", default=None)
    parser.add_argument("--only", default=None)
    args = parser.parse_args(argv)
    try:
        settings = ms.load_settings(SETTINGS.read_text(encoding="utf-8"))
        if args.repository not in settings.repositories:
            raise RunError(f"{args.repository} isn't in {SETTINGS.name}")
        only = json.loads(args.only) if args.only else None
        if only is not None and not (
            isinstance(only, dict)
            and all(
                isinstance(v, list) and all(isinstance(x, str) for x in v) for v in only.values()
            )
        ):
            raise RunError("--only must be a JSON object of lists of strings")
        repository = settings.repositories[args.repository]
        checkout = args.checkout.resolve()
        modules = collect(repository, checkout, settings, only, run)
        report = mr.Report(args.repository, head(checkout), None, modules)
        report = mr.attribute(report, checkout, args.previous)
    except (RunError, ms.SettingsError, mr.ReportError) as error:
        print(f"mutation_run: {error}", file=sys.stderr)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(mr.dump_report(report), encoding="utf-8")
    print(f"mutation_run: {len(modules)} modules from {args.repository}, written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
