"""mutmut's state, kept between scheduled runs so each resumes where the last stopped (#378,
mutation-incremental design D1a-D4).

mutmut 3.8.1 saves each result in `mutants/<path>.meta`, one file per source file, as its mutant
finishes, and keeps a function's results while that function's code is unchanged. A run given no
mutant names skips every stored result. So only the `.meta` files and `mutmut-stats.json` need
keeping (the mutated sources are regenerated on every fresh checkout). The workflow keeps them in
GitHub's cache, one entry per repository: `state/<unit>/` for each unit, and `state/manifest.json`.

Every way that state can be lost, stale or damaged is named, and it fails the run visibly where
state was expected; a first fill, or a refresh on purpose, doesn't. Standard library only, like
mutation_run.py, which imports it and is delivered with it.
"""

import datetime
import fnmatch
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import mutation_settings as ms

MANIFEST = "manifest.json"
STATS = "mutmut-stats.json"

# mutmut 3.8.1's own list of files whose changes never affect tests (`_DEFAULT_INVALIDATION_EXCLUDE`
# in mutmut/__main__.py), so the run names the same non-Python changes mutmut warns about.
MUTMUT_EXCLUDE = (
    "*.md", "*.rst", "LICENSE*", "COPYING*", "NOTICE*", "AUTHORS*", "CHANGELOG*", "CHANGES*",
    ".gitignore", ".gitattributes", ".editorconfig", ".pre-commit-config.yaml", "docs/*", "doc/*",
)  # fmt: skip


@dataclass
class UnitState:
    """What a run did with one unit's kept state, for its record and the summary."""

    name: str
    restored_from: str | None = None
    """The run that saved the state restored, or None when none was."""
    filled_since: str | None = None
    carried: int = 0
    """Results restored that still stand after the run."""
    tested: int = 0
    """Results this run produced."""
    discarded: list[str] = field(default_factory=list)
    lost: bool = False
    """State the previous run saved couldn't be restored: evicted or lost."""
    unfit: bool = False
    """Restored state didn't fit (another mutmut version, moved sources) or couldn't be read."""
    refreshed: bool = False
    saved: bool = False
    non_python_changes: list[str] = field(default_factory=list)
    restored_results: dict[str, int] = field(default_factory=dict, repr=False)

    def record(self) -> dict[str, Any]:
        fields = {k: v for k, v in vars(self).items() if k not in ("name", "restored_results")}
        return fields


def results(path: Path) -> dict[str, int]:
    """A `.meta` file's stored results (mutmut's exit codes), without the mutants not yet run."""
    codes = json.loads(path.read_text(encoding="utf-8"))["exit_code_by_key"]
    if not isinstance(codes, dict):
        raise ValueError("exit_code_by_key isn't an object")
    return {key: code for key, code in codes.items() if code is not None}


def readable(path: Path) -> bool:
    try:
        if path.name == STATS:
            return isinstance(json.loads(path.read_text(encoding="utf-8")), dict)
        results(path)
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return True


def kept_files(directory: Path) -> list[Path]:
    """The files of a unit's state: its `.meta` files and mutmut's stats, as paths under it.
    Symlinks aren't followed: mutation_run links a unit's source inside `mutants/` (run_mutmut)."""
    found = []
    for root, _, files in os.walk(directory, followlinks=False):
        for name in files:
            path = Path(root) / name
            if not path.is_symlink() and (path.suffix == ".meta" or name == STATS):
                found.append(path.relative_to(directory))
    return sorted(found)


def read_manifest(state: Path) -> dict[str, Any] | None:
    try:
        manifest = json.loads((state / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return manifest if isinstance(manifest, dict) else None


def restore(
    state: Path,
    unit: ms.Unit,
    mutants: Path,
    *,
    mutmut: str,
    today: datetime.date,
    full_refresh_days: int,
    full_refresh: bool,
    previously_saved: bool,
) -> UnitState:
    """Copy `unit`'s kept state into `mutants/` (cleared already), after checking it fits.

    `previously_saved` is whether the previous run's record says it saved this unit's state: if
    so and none is here, the state is gone, which a first fill isn't."""
    record = UnitState(unit.name)
    manifest = read_manifest(state)
    entry = (manifest or {}).get("units", {}).get(unit.name)
    if manifest is None or not isinstance(entry, dict) or not (state / unit.name).is_dir():
        if previously_saved:
            record.lost = True
            record.discarded.append(
                "the state the previous run saved is gone (the cache entry was evicted or lost): "
                "filling afresh"
            )
        else:
            record.discarded.append("no state kept yet: a first fill")
        return record
    if manifest.get("mutmut") != mutmut:
        record.unfit = True
        record.discarded.append(
            f"state from mutmut {manifest.get('mutmut')}, not {mutmut}: discarded, filling afresh"
        )
        return record
    # A changed selection too: results an integration test killed would otherwise be carried as
    # killed once the run uses only unit tests (#394, mutation-unit-tests design D3).
    saved = (entry.get("source"), entry.get("tests"), entry.get("select"))
    if saved != (unit.source, unit.tests, unit.select):
        record.unfit = True
        record.discarded.append(
            "the settings moved the unit's sources, tests or test selection since its state was "
            "saved: discarded, filling afresh"
        )
        return record
    since = str(entry.get("filled_since", ""))
    try:
        age = (today - datetime.date.fromisoformat(since)).days
    except ValueError:
        age = full_refresh_days + 1
    if full_refresh or age > full_refresh_days:
        record.refreshed = True
        record.discarded.append(
            "a full refresh: the kept state is discarded on purpose, filling afresh"
            if full_refresh
            else f"a full refresh: the state was filled from {since}, over {full_refresh_days} "
            "days ago, filling afresh"
        )
        return record
    record.restored_from = str(entry.get("saved_by"))
    record.filled_since = since
    for relative in kept_files(state / unit.name):
        source = state / unit.name / relative
        if not readable(source):
            record.unfit = True
            what = "its mutants are tested again" if source.suffix == ".meta" else "re-collected"
            record.discarded.append(f"{relative} can't be read: {what}")
            continue
        (mutants / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, mutants / relative)
        if source.suffix == ".meta":
            record.restored_results.update(results(source))
    record.carried = len(record.restored_results)
    return record


def save(
    state: Path,
    unit: ms.Unit,
    mutants: Path,
    record: UnitState,
    *,
    mutmut: str,
    run_id: str,
    commit: str,
    today: datetime.date,
) -> None:
    """Write `unit`'s state back from `mutants/`, finished or not, and count what was carried and
    what this run tested."""
    target = state / unit.name
    shutil.rmtree(target, ignore_errors=True)
    final: dict[str, int] = {}
    for relative in kept_files(mutants) if mutants.is_dir() else []:
        if not readable(mutants / relative):
            continue
        (target / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(mutants / relative, target / relative)
        if relative.suffix == ".meta":
            final.update(results(mutants / relative))
    record.carried = sum(
        1 for key, code in record.restored_results.items() if final.get(key) == code
    )
    record.tested = len(final) - record.carried
    manifest = read_manifest(state) or {"version": 1, "units": {}}
    manifest["mutmut"] = mutmut
    manifest.setdefault("units", {})[unit.name] = {
        "source": unit.source,
        "tests": unit.tests,
        "select": unit.select,
        "filled_since": record.filled_since or today.isoformat(),
        "saved_by": run_id,
        "commit": commit,
    }
    state.mkdir(parents=True, exist_ok=True)
    (state / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    record.saved = True


def merge(mine: Path, newest: Path, ran: list[str]) -> None:
    """Into `newest` (the newest entry, restored again just before the save), put the units this
    run ran from `mine`, leaving every other unit as the newest entry has it, byte for byte: two
    overlapping runs then can't drop each other's progress on a unit only one of them ran (D1a)."""
    if not (newest / MANIFEST).exists():
        shutil.rmtree(newest, ignore_errors=True)
        shutil.copytree(mine, newest)
        return
    theirs = read_manifest(newest) or {"version": 1, "units": {}}
    ours = read_manifest(mine) or {"units": {}}
    for name in ran:
        shutil.rmtree(newest / name, ignore_errors=True)
        if (mine / name).is_dir():
            shutil.copytree(mine / name, newest / name)
        if name in ours.get("units", {}):
            theirs.setdefault("units", {})[name] = ours["units"][name]
    if "mutmut" in ours:
        theirs["mutmut"] = ours["mutmut"]
    (newest / MANIFEST).write_text(json.dumps(theirs, indent=2) + "\n", encoding="utf-8")


def non_python_changes(checkout: Path, stats: Path) -> list[str]:
    """Non-Python files changed since mutmut's last full stats run, minus mutmut's own exclusions:
    the files mutmut warns about and keeps cached results despite ("warn", owner 2026-11-22)."""
    try:
        commit = json.loads(stats.read_text(encoding="utf-8")).get("git_commit")
    except (OSError, ValueError, AttributeError):
        return []
    if not commit:
        return []
    changed = subprocess.run(
        ["git", "diff", "--name-only", str(commit), "--"],
        cwd=checkout,
        capture_output=True,
        text=True,
        check=False,
    )
    if changed.returncode != 0:
        return []
    return sorted(
        path
        for path in changed.stdout.splitlines()
        if path
        and not path.endswith(".py")
        and not any(fnmatch.fnmatch(path, pattern) for pattern in MUTMUT_EXCLUDE)
    )
