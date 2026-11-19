"""Run every quality gate, in order, stopping at the first failure.

Usage: uv run scripts/check.py [--scope NAME ...] [--base REV]

With --scope, every gate still runs, but the tests narrow to those marked with any of the scopes
declared in scripts/check-paths.toml. The guard passes scopes when a commit stages only paths
they cover (spec: quality-check; troupe-run/infrastructure commit-check-paths design D8).

The tests run in parallel, one pytest-xdist worker per CPU this process may use; set
PYTEST_XDIST_AUTO_NUM_WORKERS to change the count. Running pytest directly stays one process.

Every run measures the complexity of the functions the work adds or edits, and the size of the
files it adds or changes, since --base, or since where it left origin/main. Coverage and the
dependency audit run only on CI's coverage leg, which sets QUALITY_GATES_LEG=true; never locally
(troupe-run/infrastructure spec: quality-gates; owner, 2026-11-18). The measures are
scripts/quality_gates.py, delivered from troupe-run/infrastructure.

The same script runs locally and in CI on Linux, macOS and Windows, so the two can't
diverge. It is Python rather than shell for that reason.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIN = Path(sys.executable).parent
sys.path.insert(0, str(ROOT / "scripts"))
import guard  # noqa: E402  (scripts/guard.py reads the declaration and activates the hooks)


def tool(name: str) -> str:
    """Find a console script installed in the same environment as this interpreter."""
    found = shutil.which(name, path=str(BIN))
    if found is None:
        sys.exit(f"check: {name} is not installed in {BIN}. Fix: run `uv sync`.")
    return found


def requested_scopes(names: Sequence[str], declaration: guard.CheckPaths | None) -> tuple[str, ...]:
    """The scopes to run, sorted and once each; exits naming any the declaration doesn't list."""
    declared = {name for name, _ in declaration.scopes} if declaration is not None else set()
    unknown = sorted(set(names) - declared)
    if unknown:
        listed = ", ".join(f"`{name}`" for name in unknown)
        sys.exit(
            f"check: scope {listed} isn't declared in {guard.CHECK_PATHS}. Fix: declare it "
            "there, or run the check without --scope."
        )
    return tuple(sorted(set(names)))


PARALLEL = ["-n", "auto", "--dist", "worksteal"]
"""How the tests gate runs the suite: a worker per CPU, and an idle worker takes work from a busy
one, because a few tests wait for seconds while most take milliseconds (parallel-tests D1-D3)."""

DURATIONS = ["--durations=25"]
"""The tests gate prints its 25 slowest tests on every run, full or scoped, so a slowdown shows in
the log with its cause (spec: quality-check; shorten-slow-tests design D4)."""


LEG = "QUALITY_GATES_LEG"
"""Set to `true` by CI's coverage leg, under GitHub Actions only, to run coverage and the audit
(quality-gates design D3)."""

QUALITY_GATES = str(ROOT / "scripts" / "quality_gates.py")


def on_leg(env: Mapping[str, str]) -> bool:
    """Whether this run is CI's coverage leg. Set anywhere else, or to anything but `true`, the
    variable stops the check: it is not a way to measure coverage locally."""
    value = env.get(LEG, "")
    if value == "":
        return False
    if value != "true":
        sys.exit(
            f"check: {LEG}={value!r} isn't valid. Fix: unset it; CI's coverage leg sets it to true."
        )
    if env.get("GITHUB_ACTIONS") != "true":
        sys.exit(
            f"check: {LEG} is set, but this isn't GitHub Actions. Coverage and the dependency "
            f"audit run on CI's coverage leg only (quality-gates design D3). Fix: unset {LEG}."
        )
    return True


def coverage_report() -> Path:
    """Where the coverage leg's report goes: the runner's temporary directory."""
    folder = os.environ.get("RUNNER_TEMP", tempfile.gettempdir())
    return Path(folder) / "quality-gates-coverage.json"


def gates(
    scopes: tuple[str, ...] = (), base: str | None = None, leg: bool = False
) -> list[tuple[str, list[str]]]:
    pytest = [tool("pytest"), *PARALLEL, *DURATIONS]
    if scopes:
        pytest += ["-m", guard.marker_expression(scopes)]
    measure = leg and not scopes
    if measure:
        pytest += ["--cov", "--cov-report=", f"--cov-report=json:{coverage_report()}"]
    on_base = ["--base", base] if base else []
    steps = [
        ("ruff lint", [tool("ruff"), "check", "."]),
        ("ruff format", [tool("ruff"), "format", "--check", "."]),
        ("mypy --strict", [tool("mypy")]),
        ("import contracts", [tool("lint-imports")]),
        ("complexity", [sys.executable, QUALITY_GATES, "complexity", *on_base]),
        ("size", [sys.executable, QUALITY_GATES, "size", *on_base]),
        ("tests", pytest),
    ]
    if measure:
        report = str(coverage_report())
        steps.append(
            ("coverage", [sys.executable, QUALITY_GATES, "coverage", "--coveragepy", report])
        )
    elif leg:
        note = "print('coverage not measured: the tests were scoped')"
        steps.append(("coverage", [sys.executable, "-c", note]))
    if leg:
        steps.append(("audit", [sys.executable, QUALITY_GATES, "audit", *on_base]))
    return steps


def activate_git_hooks(root: Path) -> str | None:
    """Turn the repository's git hooks on by default (spec: development-workflow).

    Git never runs hooks from a fresh clone, so the project's own tooling turns them on. The
    logic lives in guard.py, next to the hooks it activates. The spec and the guard's source are in
    troupe-run/infrastructure, which delivers guard.py here.
    """
    if not (root / ".git").exists():
        return None  # not a git checkout (for example, an unpacked source archive)
    return guard.activate_hooks(root)


NO_TESTS_RAN = 5
"""pytest's exit code when it selected no tests, as `-m` does for a scope no test is tagged with."""


def run_gates(steps: list[tuple[str, list[str]]], cwd: Path, scopes: tuple[str, ...] = ()) -> int:
    for label, command in steps:
        print(f"==> {label}", flush=True)
        started = time.monotonic()
        result = subprocess.run(command, cwd=cwd, check=False)
        elapsed = time.monotonic() - started
        if scopes and label == "tests" and result.returncode == NO_TESTS_RAN:
            # Safe: guard_pytest fails any test that reads a scope's paths untagged, so no tagged
            # tests means no test reads them (commit-check-paths design D8).
            tags = " or ".join(f"`{name}`" for name in scopes)
            print(f"    no test is tagged {tags}, so there was nothing to test", flush=True)
            continue
        if result.returncode != 0:
            code = result.returncode
            print(f"check: {label} failed (exit {code}) after {elapsed:.1f}s", flush=True)
            return code
        print(f"    {label} passed in {elapsed:.1f}s", flush=True)
    print("check: all gates passed", flush=True)
    return 0


def main(argv: Sequence[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--scope", action="append", default=[], help="a declared scope")
    parser.add_argument("--base", help="the commit the complexity and audit gates compare with")
    args = parser.parse_args(argv)
    names = args.scope
    scopes: tuple[str, ...] = ()
    if names:
        text = guard.read_working_tree(root)(guard.CHECK_PATHS)
        try:
            declaration = None if text is None else guard.check_paths(text)
        except guard.CheckPathsError as error:
            sys.exit(f"check: {error.decision().text()}")
        scopes = requested_scopes(names, declaration)
    activated = activate_git_hooks(root)
    if activated is not None:
        print(f"check: {activated}", flush=True)
    return run_gates(gates(scopes, args.base, on_leg(os.environ)), root, scopes)


if __name__ == "__main__":
    sys.exit(main())
