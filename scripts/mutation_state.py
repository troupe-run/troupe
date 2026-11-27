"""mutmut's state, kept between scheduled runs so each resumes where the last stopped (#378,
mutation-incremental design D1a-D4).

mutmut 3.8.1 saves each result in `mutants/<path>.meta`, one file per source file, as its mutant
finishes, and keeps a function's results while that function's code is unchanged. A run given no
mutant names skips every stored result. So only the `.meta` files and `mutmut-stats.json` need
keeping (the mutated sources are regenerated on every fresh checkout). The workflow keeps them in
GitHub's cache, one entry per repository: `state/<unit>/` for each unit, and `state/manifest.json`.

mutmut never re-tests a kept result for a test change: a new test only gets a stats run, an edited
one isn't noticed. So the manifest keeps a fingerprint of each unit's tests, and the results a
test change could change are cleared before the run and after it (#418,
mutation-retest-changed-tests design D1-D6).

Every way that state can be lost, stale or damaged is named, and it fails the run visibly where
state was expected; a first fill, or a refresh on purpose, doesn't. Standard library only, like
mutation_run.py, which imports it and is delivered with it.
"""

import ast
import datetime
import fnmatch
import hashlib
import json
import os
import shutil
import subprocess
from collections.abc import Callable, Collection
from dataclasses import dataclass, field, fields
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
    unreached: bool = False  # its selected tests reach none of its code (#399)
    lost: bool = False
    """State the previous run saved couldn't be restored: evicted or lost."""
    unfit: bool = False
    """Restored state didn't fit (another mutmut version, moved sources) or couldn't be read."""
    refreshed: bool = False
    saved: bool = False
    non_python_changes: list[str] = field(default_factory=list)
    tests_changed: list[str] = field(default_factory=list)
    """Files under the unit's tests changed since its state was saved (#418, design D1)."""
    tests_unrecorded: bool = False
    """The restored state had no fingerprint of the unit's tests: every test counted as changed."""
    cleared_for_tests: int = 0
    """Kept results cleared, before or after the run, because a test change could change them."""
    retested: bool = False
    """mutmut ran a second time for the results cleared after its first run (design D4)."""
    left_for_next_run: int = 0
    """Results cleared after the run with no budget or clean exit left to test them: the next run
    tests them."""
    restored_results: dict[str, int] = field(default_factory=dict, repr=False)
    tests_fingerprint: dict[str, str] | None = field(default=None, repr=False)
    """What the save records: the tests the kept results stand for (design D1, D4)."""
    tests_fingerprint_now: dict[str, str] | None = field(default=None, repr=False)
    kept_tests: dict[str, frozenset[str]] = field(default_factory=dict, repr=False)
    kept_hashes: dict[str, str] = field(default_factory=dict, repr=False)
    decided: dict[str, int] = field(default_factory=dict, repr=False)
    pending: frozenset[str] = field(default=frozenset(), repr=False)

    def record(self) -> dict[str, Any]:
        hidden = {f.name for f in fields(self) if not f.repr} | {"name"}
        return {k: v for k, v in vars(self).items() if k not in hidden}

    def settle(self, *, completed: bool) -> None:
        """After the run: the kept results now stand for the checkout's tests, if mutmut got past
        collecting what its tests reach. Otherwise the save keeps the old fingerprint, and the
        next run looks at the same changes again (design D4)."""
        if completed:
            self.tests_fingerprint = self.tests_fingerprint_now


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
    tests: Path,
    local_tests: str,
) -> UnitState:
    """Copy `unit`'s kept state into `mutants/` (cleared already), after checking it fits, and
    clear the results a change to its tests could change (#418, design D3).

    `previously_saved` is whether the previous run's record says it saved this unit's state: if
    so and none is here, the state is gone, which a first fill isn't. `tests` is the unit's
    tests in the checkout, and `local_tests` the same directory as mutmut's node ids name it."""
    record = UnitState(unit.name)
    now = fingerprint(tests)
    record.tests_fingerprint_now = now
    # Until a fit state is restored there are no kept results: what this run tests stands for now.
    record.tests_fingerprint = now
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
    old = entry.get("tests_fingerprint")
    if isinstance(old, dict):
        record.tests_fingerprint = {str(k): str(v) for k, v in old.items()}
        record.tests_changed = changed_files(record.tests_fingerprint, now)
        removed = {path for path in record.tests_changed if path not in now}
        named = (
            named_test_files(tests, record.tests_changed, removed=removed)
            if record.tests_changed
            else set()
        )
    else:
        record.tests_fingerprint = None
        record.tests_unrecorded = True
        named = None
    clear_for_tests(mutants, record, named, local_tests)
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
    entry: dict[str, Any] = {
        "source": unit.source,
        "tests": unit.tests,
        "select": unit.select,
        "filled_since": record.filled_since or today.isoformat(),
        "saved_by": run_id,
        "commit": commit,
    }
    if record.tests_fingerprint is not None:
        entry["tests_fingerprint"] = record.tests_fingerprint
    manifest.setdefault("units", {})[unit.name] = entry
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


# Tests that changed since the state was saved, and the results they could change (#418,
# mutation-retest-changed-tests design D1-D5). mutmut 3.8.1 keeps a result while its function's
# code is unchanged, and only collects what new tests reach: it never re-tests a result for them.

TEST_FILES = ("test_*.py", "*_test.py")  # pytest's default python_files
FUNCTION = "__mutmut_"  # a mutant's key is its function's mangled name, this, and a number


def fingerprint(tests: Path) -> dict[str, str]:
    """Every file under a unit's tests, by its path relative to them, with a hash of its content.
    Caches aren't the tests'. A unit with no tests directory has an empty fingerprint."""
    printed: dict[str, str] = {}
    if not tests.is_dir():
        return printed
    for root, dirs, files in os.walk(tests):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(files):
            if name.endswith(".pyc"):
                continue
            path = Path(root) / name
            relative = path.relative_to(tests).as_posix()
            printed[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return printed


def changed_files(old: dict[str, str], new: dict[str, str]) -> list[str]:
    """The paths added, edited or removed between two fingerprints."""
    return sorted(path for path in old.keys() | new.keys() if old.get(path) != new.get(path))


def is_test_file(relative: str) -> bool:
    name = relative.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(name, pattern) for pattern in TEST_FILES)


def module_names(relative: str) -> set[str]:
    """The names a file under the tests can be imported by: every dotted tail of its path, since
    the tests import helpers from whichever directory pytest put on the path."""
    parts = relative.removesuffix(".py").split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return {".".join(parts[i:]) for i in range(len(parts)) if parts[i:]}


def imported(relative: str, text: str) -> set[str]:
    """The module names a Python file imports, each with its submodule for `from x import y`.
    A file that doesn't parse imports nothing we can see."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return set()
    package = relative.split("/")[:-1]
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                up = package[: len(package) - node.level + 1] if node.level > 1 else package
                base = ".".join([*up, *([base] if base else [])])
            if base:
                names.add(base)
            names |= {f"{base}.{alias.name}" if base else alias.name for alias in node.names}
    return names


def named_test_files(
    tests: Path, changed: list[str], *, removed: Collection[str]
) -> set[str] | None:
    """The test files (relative to `tests`) whose tests a change could change, or None for every
    test file: a changed test file names itself, a changed helper every test file that imports it
    directly or through other helpers, a changed conftest.py every test file under its directory,
    and a changed file that isn't Python every test file (design D2). `removed` holds the changed
    paths no longer in the checkout."""
    if any(not path.endswith(".py") for path in changed):
        return None
    files = {
        path: (tests / path).read_text(encoding="utf-8", errors="replace")
        for path in fingerprint(tests)
        if path.endswith(".py")
    }
    imports = {path: imported(path, text) for path, text in files.items()}
    affected = set(changed)
    while True:
        names = set().union(*(module_names(path) for path in affected))
        more = {path for path, wanted in imports.items() if path not in affected and wanted & names}
        if not more:
            break
        affected |= more
    for path in changed:
        if path.rsplit("/", 1)[-1] == "conftest.py":
            directory = path.rsplit("/", 1)[0] + "/" if "/" in path else ""
            affected |= {other for other in files if other.startswith(directory)}
    return {path for path in affected if is_test_file(path) and (path in files or path in removed)}


def test_file_of(node_id: str, local_tests: str) -> str | None:
    """The file a node id's test is in, relative to the unit's tests; None for one outside them."""
    path = node_id.split("::", 1)[0]
    prefix = local_tests.rstrip("/") + "/"
    return path.removeprefix(prefix) if path.startswith(prefix) else None


def function_of(key: str) -> str:
    return key.rsplit(FUNCTION, 1)[0]


def read_stats(mutants: Path) -> dict[str, Any] | None:
    try:
        data = json.loads((mutants / STATS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(
        data.get("tests_by_mangled_function_name"), dict
    ):
        return None
    return data


def tests_by_function(data: dict[str, Any] | None) -> dict[str, frozenset[str]]:
    if data is None:
        return {}
    return {
        str(function): frozenset(str(test) for test in tests)
        for function, tests in data["tests_by_mangled_function_name"].items()
    }


def meta_files(mutants: Path) -> list[Path]:
    return [mutants / path for path in kept_files(mutants) if path.suffix == ".meta"]


def current_results(mutants: Path) -> dict[str, int | None]:
    found: dict[str, int | None] = {}
    for path in meta_files(mutants):
        try:
            codes = json.loads(path.read_text(encoding="utf-8"))["exit_code_by_key"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if isinstance(codes, dict):
            found.update(codes)
    return found


def clear_results(mutants: Path, record: UnitState, clear: Callable[[str], bool]) -> int:
    """Set every decided result whose key `clear` accepts to null, as mutmut does for a changed
    function, so mutmut tests it again; it's no longer carried. The count cleared."""
    count = 0
    for path in meta_files(mutants):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            codes = data["exit_code_by_key"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if not isinstance(codes, dict):
            continue
        hit = [key for key, code in codes.items() if code is not None and clear(key)]
        for key in hit:
            codes[key] = None
            record.restored_results.pop(key, None)
        if hit:
            path.write_text(json.dumps(data, indent=4), encoding="utf-8")
            count += len(hit)
    return count


def clear_for_tests(
    mutants: Path, record: UnitState, named: set[str] | None, local_tests: str
) -> None:
    """Before the run (design D3): every result of a function a named test reached is cleared, and
    the named tests are dropped from mutmut's stats, so mutmut collects what they reach now. Then
    note what the run starts from, for clear_gained."""
    data = read_stats(mutants)
    by_function = tests_by_function(data)
    if data is not None and named != set():
        everything = set().union(*by_function.values()) | set(data.get("duration_by_test", {}))
        dropped = {
            test for test in everything if named is None or test_file_of(test, local_tests) in named
        }
        reached = {function for function, tests in by_function.items() if tests & dropped}
        record.cleared_for_tests += clear_results(
            mutants, record, lambda key: function_of(key) in reached
        )
        if dropped:
            data["tests_by_mangled_function_name"] = {
                function: sorted(tests - dropped) for function, tests in by_function.items()
            }
            durations = data.get("duration_by_test", {})
            data["duration_by_test"] = {t: d for t, d in durations.items() if t not in dropped}
            (mutants / STATS).write_text(json.dumps(data, indent=4), encoding="utf-8")
            by_function = tests_by_function(data)
    record.kept_tests = by_function
    hashes = (data or {}).get("function_hashes", {})
    record.kept_hashes = dict(hashes) if isinstance(hashes, dict) else {}
    now = current_results(mutants)
    record.decided = {key: code for key, code in now.items() if code is not None}
    record.pending = frozenset(key for key, code in now.items() if code is None)


def clear_gained(mutants: Path, record: UnitState) -> tuple[int, bool]:
    """After mutmut's run (design D4): a function that gained a test, whose code didn't change,
    has the results it carried from before the run cleared. Returns how many were cleared, and
    whether mutmut tested anything, which it does only after collecting what its tests reach."""
    now = current_results(mutants)
    progressed = any(now.get(key) is not None for key in record.pending)
    data = read_stats(mutants)
    hashes = (data or {}).get("function_hashes", {})
    hashes = hashes if isinstance(hashes, dict) else {}
    gained = set()
    for function, tests in tests_by_function(data).items():
        if not tests - record.kept_tests.get(function, frozenset()):
            continue
        if function in record.kept_hashes and hashes.get(function) != record.kept_hashes[function]:
            continue  # mutmut re-tested its results with every test it now knows
        gained.add(function)

    def carried(key: str) -> bool:
        return (
            function_of(key) in gained
            and key in record.decided
            and now.get(key) == record.decided[key]
        )

    cleared = clear_results(mutants, record, carried)
    record.cleared_for_tests += cleared
    return cleared, progressed
