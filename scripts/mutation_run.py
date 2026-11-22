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
import datetime
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mutation_report as mr
import mutation_settings as ms
import mutation_state as st

SETTINGS = Path(__file__).resolve().parent / "mutation.json"
CHILDREN_PLUGIN = Path(__file__).resolve().parent / "mutation_children.py"
PLUGIN_COPY = "_mutation_children_plugin"
"""The plugin's name in mutmut's working directory: not mutation_children, since infrastructure's
own copy of that is in the source mutmut mutates, and a mutated copy would load in its place."""
PEAKS = "_mutation_children_peaks.log"
"""Where each process the plugin loads in records its memory peaks (#366, design D3)."""


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


# pytest options a mutation run can't honour from mutmut's copy: the guard's tag plugin finds its
# declarations from the repository's root, so it registers no scope markers, and strict markers
# then refuse every tagged test (trial of troupe, 2026-11-18; quality-scope design D5).
UNHONOURED = ("--strict-markers",)
UNHONOURED_PLUGINS = ("guard_pytest",)


def own_addopts(checkout: Path) -> str:
    """The repository's own pytest `addopts`, from its root pyproject.toml, without those a
    mutation run can't honour. With none, `-ra`."""
    path = checkout / "pyproject.toml"
    if not path.is_file():
        return "-ra"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise RunError(f"{path} isn't valid TOML: {error}") from error
    addopts = data.get("tool", {}).get("pytest", {}).get("ini_options", {}).get("addopts")
    if addopts is None:
        return "-ra"
    if isinstance(addopts, str):
        args = shlex.split(addopts)
    elif isinstance(addopts, list) and all(isinstance(arg, str) for arg in addopts):
        args = list(addopts)
    else:
        raise RunError(
            f"pyproject.toml's addopts is {addopts!r}; it must be a string or a list of strings"
        )
    kept: list[str] = []
    rest = iter(args)
    for arg in rest:
        if arg in UNHONOURED:
            continue
        if arg == "-p":
            plugin = next(rest, "")
            if plugin not in UNHONOURED_PLUGINS:
                kept += [arg, plugin]
            continue
        if arg.startswith("-p") and arg[2:] in UNHONOURED_PLUGINS:
            continue
        kept.append(arg)
    return shlex.join(kept)


def link_checkout_entries(checkout: Path, unit: ms.Unit, made: list[Path]) -> None:
    """For a package's unit, link into each directory from the package's own up to, not
    including, the checkout every entry of the directory above it, adding each link to `made` as
    it's made, so a failure partway still leaves every one for the caller to remove.

    Inside mutmut's copy a test file is one directory deeper (<package>/mutants/tests), so a test
    counting directories up from its own file lands one level lower than it means to: on the
    package's directory when it means packages/ (a sibling package, as troupe-store-text's
    test_processes.py finds troupe's tests; #343), on packages/ when it means the checkout
    (quality-scope design D5). With the links, it still finds what it reads: packages/packages and
    <package>/<package> included. .git isn't linked: git would take that directory for a
    repository of its own.
    """
    package = checkout / Path(unit.source).parent
    for level in [package, *package.parents]:
        if level == checkout or checkout not in level.parents:
            break
        for entry in sorted(level.parent.iterdir()):
            link = level / entry.name
            if entry.name == ".git" or link.exists() or link.is_symlink():
                continue
            link.symlink_to(Path("..") / entry.name, target_is_directory=entry.is_dir())
            made.append(link)


def mutmut_config(workdir: Path, checkout: Path, unit: ms.Unit, *, children: int) -> str:
    """mutmut's setup.cfg for a unit, with paths from its working directory."""

    def local(path: str) -> str:
        return os.path.relpath(checkout / path, workdir)

    tests = local(unit.tests)
    also_copy = [local(path) for path in unit.also_copy] + [
        f"{PLUGIN_COPY}.py",
        f"{PLUGIN_COPY}.json",
    ]
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
    else:
        # A package's tests find its own files (a plugin's tools/ and fixtures/) by counting up
        # from their own file, which inside mutmut's copy is under mutants/: copy them beside the
        # source, as the root unit copies the checkout's (#337; mutation-resources design D3).
        # Hidden entries (caches, .venv) and build output aren't the package's files.
        own = {"src", tests.split("/")[0], "mutants", "setup.cfg", "__pycache__",
               "node_modules", "dist", "build", f"{PLUGIN_COPY}.py"}  # fmt: skip
        also_copy += sorted(
            p.name
            for p in workdir.iterdir()
            if p.name not in own
            and not p.is_symlink()  # a sibling package linked in by link_checkout_entries (#343)
            and not p.name.startswith(".")
            and not p.name.endswith(".egg-info")
            and p.name not in also_copy
        )

    def listed(values: Sequence[str]) -> str:
        return "".join(f"\n    {value}" for value in values)

    lines = [
        "[mutmut]",
        "source_paths=src/",
        f"pytest_add_cli_args_test_selection={tests}",
        "pytest_add_cli_args="
        + listed(
            [
                "-o",
                f"addopts={own_addopts(checkout)}",
                "-p",
                PLUGIN_COPY,
                *deselected(workdir, checkout, unit),
            ]
        ),
        f"max_children={children}",
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


LARGEST_MUTANTS = 5


def megabytes(kilobytes: int) -> int:
    return (kilobytes + 512) // 1024


def memory_lines(unit: str, text: str | None) -> list[str]:
    """A unit's recorded peaks as `memory:` log lines: mutmut's own largest (where its stats and
    clean passes run, and every mutant's process starts from), then the largest mutant processes
    by peak virtual size, then the count. A malformed line is skipped and counted (#366, D3)."""
    own: list[tuple[int, int]] = []
    mutants: list[tuple[int, int, str]] = []
    malformed = 0
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
            malformed += 1
            continue
        name, peak, resident = parts[0], int(parts[1]), int(parts[2])
        if name == "mutmut":
            own.append((peak, resident))
        else:
            mutants.append((peak, resident, name))
    if not own and not mutants:
        return [f"memory: {unit} no peaks recorded"]
    lines = []
    if own:
        peak = megabytes(max(p for p, _ in own))
        resident = megabytes(max(r for _, r in own))
        lines.append(f"memory: {unit} mutmut VmPeak={peak} MB VmHWM={resident} MB")
    largest = sorted(mutants, key=lambda m: (-m[0], m[2]))[:LARGEST_MUTANTS]
    for peak, resident, name in largest:
        sizes = f"VmPeak={megabytes(peak)} MB VmHWM={megabytes(resident)} MB"
        lines.append(f"memory: {unit} mutant {name} {sizes}")
    skipped = f" ({malformed} malformed lines skipped)" if malformed else ""
    lines.append(f"memory: {unit} {len(own) + len(mutants)} processes recorded{skipped}")
    return lines


def peaks_summary(text: str) -> list[str]:
    """A peaks file's `memory:` lines, unit by unit, split at the `unit <name>` lines the run
    writes before each unit; lines before any unit go under `?`, and a unit with none says no
    peaks were recorded (#371, design D2)."""
    sections: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        if line.startswith("unit "):
            sections.append((line.removeprefix("unit ").strip(), []))
        elif line.strip():
            if not sections:
                sections.append(("?", []))
            sections[-1][1].append(line)
    if not sections:
        return ["memory: no peaks recorded"]
    # A unit with no lines (a run killed early in it) says so, which also says where it ended.
    return [out for name, lines in sections for out in memory_lines(name, "\n".join(lines))]


@dataclass
class StateRun:
    """The scheduled run's kept mutmut state (#378, mutation-incremental design D2, D3)."""

    directory: Path
    mutmut: str
    run_id: str
    commit: str
    today: datetime.date
    full_refresh_days: int
    full_refresh: bool
    previously_saved: frozenset[str]
    records: list[st.UnitState] = field(default_factory=list)


def run_mutmut(
    checkout: Path,
    unit: ms.Unit,
    names: Sequence[str],
    deadline: float,
    run: Run,
    *,
    children: int,
    memory_mb: int | None,
    state: StateRun | None = None,
) -> dict[str, mr.Module]:
    """One unit's modules, with paths as in the checkout. `names` limits it to those globs,
    `children` is how many mutants run at once (the settings' max_children), and `memory_mb` caps
    each mutant's test process (the settings' mutant_memory_mb; None for no cap, #366)."""
    workdir = mutmut_workdir(checkout, unit)
    if (workdir / "setup.cfg").exists():
        if workdir == checkout:
            (checkout / "src").unlink()
        raise RunError(
            f"{workdir / 'setup.cfg'} exists, and mutmut reads its configuration from there: "
            "this run writes its own, so it won't overwrite one the repository holds"
        )
    plugin = workdir / f"{PLUGIN_COPY}.py"
    plugin_config = workdir / f"{PLUGIN_COPY}.json"
    # In CI the workflow names the peaks file in out/, which the job uploads, and the step's exit
    # trap prints the summary from it: an OOM kill of this run would take a summary printed here
    # down with it (#371, mutation-peaks design D1). A local run keeps its own, in the workdir.
    named = os.environ.get("PEAKS")
    peaks = Path(named) if named else workdir / PEAKS
    links: list[Path] = []
    record: st.UnitState | None = None
    try:
        if workdir != checkout:
            link_checkout_entries(checkout, unit, links)
        shutil.copy2(CHILDREN_PLUGIN, plugin)
        # Beside the plugin, which mutmut copies into mutants/ with it (also_copy); the peaks file
        # is named absolutely, so every process records into the one file (design D2, D3).
        plugin_config.write_text(
            json.dumps({"mutant_memory_mb": memory_mb, "peaks": str(peaks)}), encoding="utf-8"
        )
        if named:
            peaks.parent.mkdir(parents=True, exist_ok=True)
            with peaks.open("a", encoding="utf-8") as marker:
                marker.write(f"unit {unit.name}\n")
        else:
            peaks.unlink(missing_ok=True)
        (workdir / "setup.cfg").write_text(
            mutmut_config(workdir, checkout, unit, children=children), encoding="utf-8"
        )
        shutil.rmtree(workdir / "mutants", ignore_errors=True)
        if workdir == checkout:
            # In mutmut's copy, the source's own name leads to the mutated source, so code that
            # puts <root>/scripts on sys.path (check.py) imports the mutants, not the original
            # (trial, 2026-11-18: every mutant read as untested until this).
            (workdir / "mutants").mkdir()
            (workdir / "mutants" / unit.source.rstrip("/")).symlink_to(
                "src", target_is_directory=True
            )
        if state is not None:
            (workdir / "mutants").mkdir(exist_ok=True)
            record = st.restore(
                state.directory,
                unit,
                workdir / "mutants",
                mutmut=state.mutmut,
                today=state.today,
                full_refresh_days=state.full_refresh_days,
                full_refresh=state.full_refresh,
                previously_saved=unit.name in state.previously_saved,
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
            crashed = tuple(
                replace(crash, path=source + crash.path.removeprefix("src"))
                for crash in module.crashed_mutants
            )
            # A whole run the budget stopped leaves its unrun mutants without a code, so from_mutmut
            # already reports their modules as not finished. A run limited to named functions
            # leaves every other mutant unrun on purpose: it finished unless the budget stopped it.
            finished = code != -1 if names else module.finished
            mapped[name] = replace(
                module, survivors=survivors, crashed_mutants=crashed, finished=finished
            )
        return mapped
    finally:
        if state is not None and record is not None:
            # Finished or not: what a run that stops completed is the next run's to keep (D2).
            mutants = workdir / "mutants"
            record.non_python_changes = st.non_python_changes(checkout, mutants / st.STATS)
            st.save(
                state.directory,
                unit,
                mutants,
                record,
                mutmut=state.mutmut,
                run_id=state.run_id,
                commit=state.commit,
                today=state.today,
            )
            state.records.append(record)
        if workdir == checkout:
            (checkout / "src").unlink()
        for link in links:
            link.unlink()
        plugin.unlink(missing_ok=True)
        plugin_config.unlink(missing_ok=True)
        if not named:
            # Finished or not: a run that stops is when the peaks matter most.
            recorded = (
                peaks.read_text(encoding="utf-8", errors="replace") if peaks.exists() else None
            )
            for line in memory_lines(unit.name, recorded):
                print(line, flush=True)
            peaks.unlink(missing_ok=True)


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
        crashed = []
        for mutant in entry.get("mutants", []):
            status = STRYKER_STATUS.get(str(mutant.get("status")))
            if status is None:  # Pending: not run within the budget
                finished = False
                continue
            counts[status] += 1
            if status not in ("survived", "crashed"):
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
            change = f"-{original}\n+{mutated}"
            if status == "survived":
                survivors.append(mr.Survivor(name, path, line, change))
            else:  # a RuntimeError, which Stryker reports without an exit code (#361)
                crashed.append(mr.Crashed(name, path, line, change, None))
        modules[path] = mr.Module(
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
    *,
    unit: str | None = None,
    state: StateRun | None = None,
) -> dict[str, mr.Module]:
    """`unit` limits a run to one unit, run whole, so mutmut resumes: module globs would make it
    re-run every match instead (#378)."""
    minutes = settings.pr_budget_minutes if only is not None else settings.budget_minutes
    deadline = time.monotonic() + minutes * 60
    modules: dict[str, mr.Module] = {}
    units = list(repository.units)
    if unit is not None:
        units = [u for u in units if u.name == unit]
        if not units:
            names = [u.name for u in repository.units]
            raise RunError(f"{repository.name} has no unit {unit!r}; its units are {names}")
    if repository.tool == "mutmut":
        for unit_ in units:
            names = list(only.get(unit_.name, [])) if only is not None else []
            if only is not None and not names:
                continue
            if time.monotonic() >= deadline:
                break  # a unit not reached has no modules in the report, so none is judged
            modules.update(
                run_mutmut(
                    checkout,
                    unit_,
                    names,
                    deadline,
                    run,
                    children=settings.max_children,
                    memory_mb=settings.mutant_memory_mb,
                    state=state,
                )
            )
    else:
        mutate = list(only.get("stryker", [])) if only is not None else []
        if only is None or mutate:
            modules.update(
                run_stryker(checkout, repository, mutate, deadline, settings.tools["stryker"], run)
            )
    return modules


def subcommand(given: Sequence[str]) -> int | None:
    """The workflow's helper commands, or None for a mutation run."""
    if given[:1] == ["peaks"] and len(given) == 2:
        # The step's exit trap: never fails, so the summary can't change how the step ends.
        path = Path(given[1])
        text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
        for line in peaks_summary(text):
            print(line, flush=True)
        return 0
    if given[:1] == ["state-merge"] and len(given) == 4:
        # Before the save: units this run ran from its state, the rest from the newest entry (D1a).
        record_path = Path(given[3])
        record = json.loads(record_path.read_text(encoding="utf-8"))
        st.merge(Path(given[1]), Path(given[2]), ran=sorted(record.get("units", {})))
        # Every unit the saved entry holds, so the next run notices any of them gone (#380).
        record["kept"] = sorted((st.read_manifest(Path(given[2])) or {}).get("units", {}))
        record_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        return 0
    if given[:1] == ["state-harvest"] and len(given) == 5:
        harvest(given[1], Path(given[2]), Path(given[3]), Path(given[4]))
        return 0
    return None


def harvest(repository: str, checkout: Path, state: Path, record_path: Path) -> None:
    """After a run killed outright (no `finally` ran, no record), keep the results mutmut had
    written to each unit's .meta files, and record that it did (#380's review)."""
    settings = ms.load_settings(SETTINGS.read_text(encoding="utf-8"))
    manifest = st.read_manifest(state) or {}
    today = datetime.datetime.now(datetime.UTC).date()
    try:
        commit = head(checkout)
    except RunError:
        commit = ""
    records = []
    for unit in settings.repositories[repository].units:
        source = checkout / unit.source
        mutants = (source.parent if source.name == "src" else checkout) / "mutants"
        if not mutants.is_dir():
            continue
        record = st.UnitState(unit.name)
        record.discarded.append(
            "the run was killed before it saved its state: the results it had finished were kept"
        )
        since = manifest.get("units", {}).get(unit.name, {}).get("filled_since")
        # A refresh discarded the old state but rewrites the manifest only when it saves: a killed
        # refresh is a fresh fill, not the stale date, or the next run discards it again (#380).
        try:
            age = (today - datetime.date.fromisoformat(str(since))).days
        except ValueError:
            age = settings.full_refresh_days + 1
        refresh = os.environ.get("MUTATION_FULL_REFRESH") == "true"
        record.filled_since = None if refresh or age > settings.full_refresh_days else since
        st.save(
            state,
            unit,
            mutants,
            record,
            mutmut=settings.tools["mutmut"],
            run_id=os.environ.get("MUTATION_RUN_ID", "local"),
            commit=commit,
            today=today,
        )
        records.append(record)
    record_path.parent.mkdir(parents=True, exist_ok=True)
    body = {"version": 1, "repository": repository, "units": {r.name: r.record() for r in records}}
    record_path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")


def finish_state(state: StateRun, repository: str, out: Path) -> int:
    """Write the run's state record beside its report, and fail visibly (3) when a unit's kept
    state was lost or didn't fit, the report being written already (#378, design D3)."""
    record = {
        "version": 1,
        "repository": repository,
        "units": {unit.name: unit.record() for unit in state.records},
    }
    (out.parent / f"state-{repository}.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8"
    )
    failures = [
        f"mutation_run: {unit.name}: {reason}"
        for unit in state.records
        if unit.lost or unit.unfit
        for reason in unit.discarded
    ]
    for failure in failures:
        print(failure, file=sys.stderr)
    return 3 if failures else 0


def main(argv: Sequence[str] | None = None, run: Run = run_command) -> int:
    given = list(sys.argv[1:] if argv is None else argv)
    helper = subcommand(given)
    if helper is not None:
        return helper
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("repository")
    parser.add_argument("checkout", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--previous", default=None)
    parser.add_argument("--only", default=None)
    parser.add_argument("--unit", default=None)
    args = parser.parse_args(argv)
    state: StateRun | None = None
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
        commit = head(checkout)
        state = state_run(settings, commit) if only is None else None
        modules = collect(
            repository, checkout, settings, only, run, unit=args.unit or None, state=state
        )
        report = mr.Report(args.repository, commit, None, modules)
        report = mr.attribute(
            report, checkout, args.previous, log=lambda line: print(f"mutation_run: {line}")
        )
    except (RunError, ms.SettingsError, mr.ReportError) as error:
        print(f"mutation_run: {error}", file=sys.stderr)
        if state is not None:
            # The units saved before the failure are kept: record them, so the save runs (#380).
            args.out.parent.mkdir(parents=True, exist_ok=True)
            finish_state(state, args.repository, args.out)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(mr.dump_report(report), encoding="utf-8")
    print(f"mutation_run: {len(modules)} modules from {args.repository}, written to {args.out}")
    return 0 if state is None else finish_state(state, args.repository, args.out)


def state_run(settings: ms.Settings, commit: str) -> StateRun | None:
    """The kept-state context from the workflow's environment, or None outside it (a local run,
    or the pull request run, which keeps no state)."""
    directory = os.environ.get("MUTATION_STATE")
    if not directory:
        return None
    saved: set[str] = set()
    previous = os.environ.get("MUTATION_PREVIOUS_STATE")
    if previous and Path(previous).is_file():
        record = json.loads(Path(previous).read_text(encoding="utf-8"))
        # The units its saved entry kept, which a single-unit run's own units don't cover (#380).
        saved = set(record.get("kept", []))
        saved |= {name for name, unit in record.get("units", {}).items() if unit.get("saved")}
    return StateRun(
        directory=Path(directory),
        mutmut=settings.tools["mutmut"],
        run_id=os.environ.get("MUTATION_RUN_ID", "local"),
        commit=commit,
        today=datetime.datetime.now(datetime.UTC).date(),
        full_refresh_days=settings.full_refresh_days,
        full_refresh=os.environ.get("MUTATION_FULL_REFRESH") == "true",
        previously_saved=frozenset(saved),
    )


if __name__ == "__main__":
    sys.exit(main())
