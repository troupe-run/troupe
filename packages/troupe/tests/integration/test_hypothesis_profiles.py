"""The project's hypothesis profiles (hypothesis_profiles.py, loaded for every test path).

Its tests that stay in their own process are in unit/test_hypothesis_profiles_unit.py."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

TESTS_ROOT = next(p for p in Path(__file__).resolve().parents if p.name == "tests")
"""This suite's tests directory, found by name so the file can sit at any depth under it."""

ROOT = TESTS_ROOT.parents[2]
SLOW = """\
import time
from hypothesis import Phase, given, settings, strategies as st

@settings(max_examples=3, phases=[Phase.generate])
@given(st.integers())
def test_slow(number):
    time.sleep(0.3)
"""

RECORD_DIRS = """\
import os
import pytest

def pytest_collectstart(collector):
    if isinstance(collector, pytest.Dir):
        with open(os.environ["RECORDED_DIRS"], "a", encoding="utf-8") as recorded:
            recorded.write(str(collector.path) + "\\n")
"""
"""A plugin for the child run that writes down every directory it collects."""


def run_slow(
    tmp_path: Path, config: Path, *plugins: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """A 300 ms example, run with pytest's configuration from ``config``.

    The child collects only ``tmp_path`` (``--confcutdir``). Without it, when the repository and the
    temp directory are on different drives, no directory above the test is above the repository, so
    pytest collects every one from the drive's root down, and on Windows stats each entry beside
    them, other tests' temp directories included. One removed in between failed the run (#226).
    """
    test = tmp_path / "test_slow.py"
    test.write_text(SLOW, encoding="utf-8")
    return subprocess.run(
        [
            # Without the kinds plugin: the example sits in tmp_path, in neither kind's directory.
            *[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
            *["-p", "no:kinds_pytest"],
            *["--rootdir", str(config.parent), "-c", str(config), "-o", "testpaths="],
            *["--confcutdir", str(tmp_path)],
            *[arg for plugin in plugins for arg in ("-p", plugin)],
            *["--hypothesis-profile=default", str(test)],
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
        cwd=ROOT,
        env={**os.environ, "HYPOTHESIS_STORAGE_DIRECTORY": str(tmp_path / "db"), **(env or {})},
    )


def test_a_slow_example_passes_under_the_profile_the_flake_hunt_asks_for(tmp_path: Path) -> None:
    completed = run_slow(tmp_path, ROOT / "pyproject.toml")
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_the_slow_examples_run_collects_no_directory_outside_its_own(tmp_path: Path) -> None:
    # Directories above or beside tmp_path belong to other tests, which create and remove theirs
    # while this runs (#226).
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    (plugin / "record_dirs.py").write_text(RECORD_DIRS, encoding="utf-8")
    recorded = tmp_path / "dirs.txt"
    path = os.pathsep.join(filter(None, [str(plugin), os.environ.get("PYTHONPATH")]))
    completed = run_slow(
        tmp_path,
        ROOT / "pyproject.toml",
        "record_dirs",
        env={"PYTHONPATH": path, "RECORDED_DIRS": str(recorded)},
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    collected = [Path(line) for line in recorded.read_text(encoding="utf-8").splitlines()]
    assert collected, "the child run collected no directory, so this checks nothing"
    assert [d for d in collected if not d.is_relative_to(tmp_path)] == []


def test_without_the_plugin_the_same_example_fails_on_hypothesiss_deadline(tmp_path: Path) -> None:
    # The control: hypothesis's own default profile, with no project configuration, fails it.
    bare = tmp_path / "pytest.ini"
    bare.write_text("[pytest]\n", encoding="utf-8")
    completed = run_slow(tmp_path, bare)
    assert completed.returncode == 1
    assert "DeadlineExceeded" in completed.stdout


FOUND = """\
import os
from hypothesis import Phase, given, settings, strategies as st

REPLAY = [Phase.reuse] if os.environ.get("REPLAY_ONLY") else list(Phase)

@settings(phases=REPLAY)
@given(st.integers())
def test_found(number):
    assert number < 1000
"""
"""A property that fails for a value hypothesis finds at once. Told to replay only, it runs just the
examples saved in the database, so it fails only if the earlier run's failure is there."""


def fake_repository(tmp_path: Path) -> Path:
    """A repository laid out like this one: the profiles plugin at its place in
    packages/troupe/tests, loaded by the root's configuration, and the property beside it."""
    repo = tmp_path / "repo"
    tests = repo / "packages" / "troupe" / "tests"
    tests.mkdir(parents=True)
    (tests / "hypothesis_profiles.py").write_bytes(
        (TESTS_ROOT / "hypothesis_profiles.py").read_bytes()
    )
    (tests / "test_found.py").write_text(FOUND, encoding="utf-8")
    (repo / "pytest.ini").write_text(
        "[pytest]\npythonpath = packages/troupe/tests\naddopts = -p hypothesis_profiles\n",
        encoding="utf-8",
    )
    return repo


def run_found(
    repo: Path, cwd: Path, *, replay_only: bool, storage: Path | None = None
) -> subprocess.CompletedProcess[str]:
    """The property, run by pytest started in ``cwd``, as a developer or ``scripts/check.py``
    starts it."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"HYPOTHESIS_STORAGE_DIRECTORY", "CI", "REPLAY_ONLY"}
    }
    if replay_only:
        env["REPLAY_ONLY"] = "1"
    if storage is not None:
        env["HYPOTHESIS_STORAGE_DIRECTORY"] = str(storage)
    return subprocess.run(
        [
            *[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
            *["--rootdir", str(repo), "-c", str(repo / "pytest.ini"), "--confcutdir", str(repo)],
            *[
                "--hypothesis-profile=default",
                str(repo / "packages" / "troupe" / "tests" / "test_found.py"),
            ],
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
        cwd=cwd,
        env=env,
    )


def replayed_the_failure(completed: subprocess.CompletedProcess[str]) -> bool:
    """Whether a replay-only run failed on the saved example, not on anything else."""
    return completed.returncode == 1 and "number=1000" in completed.stdout


def test_a_failure_saved_from_a_package_directory_fails_a_run_from_the_root(tmp_path: Path) -> None:
    # #537: the full check runs from the root, and missed a failure found from packages/troupe
    # (#532).
    repo = fake_repository(tmp_path)
    found = run_found(repo, repo / "packages" / "troupe", replay_only=False)
    assert found.returncode == 1, found.stdout + found.stderr
    replayed = run_found(repo, repo, replay_only=True)
    assert replayed_the_failure(replayed), (
        "the root's run didn't replay the saved failure:\n" + replayed.stdout
    )


def test_a_failure_saved_from_the_root_fails_a_run_from_a_package_directory(tmp_path: Path) -> None:
    repo = fake_repository(tmp_path)
    found = run_found(repo, repo, replay_only=False)
    assert found.returncode == 1, found.stdout + found.stderr
    replayed = run_found(repo, repo / "packages" / "troupe", replay_only=True)
    assert replayed_the_failure(replayed), (
        "the package's run didn't replay the saved failure:\n" + replayed.stdout
    )


def test_a_storage_directory_from_the_environment_keeps_the_examples_out_of_the_repository(
    tmp_path: Path,
) -> None:
    # The flake hunt gives each round a private database this way (spec: flake-hunt).
    repo = fake_repository(tmp_path)
    private = tmp_path / "private"
    found = run_found(repo, repo / "packages" / "troupe", replay_only=False, storage=private)
    assert found.returncode == 1, found.stdout + found.stderr
    assert any((private / "examples").iterdir())
    assert not (repo / ".hypothesis").exists()
    assert not (repo / "packages" / "troupe" / ".hypothesis").exists()
    assert replayed_the_failure(run_found(repo, repo, replay_only=True, storage=private))


UNIT_TEST = "test_hypothesis_profiles_unit.py"
PACKAGE = Path("packages") / "troupe"


def checkout_under_another_directory(tmp_path: Path) -> Path:
    """A checkout at ``tmp_path/target``, as the nightly mutation run checks troupe out: the root's
    pytest configuration loading the plugin, the plugin and its unit test at their places, and the
    package's own pyproject.toml, which holds no pytest configuration."""
    repo = tmp_path / "target"
    (repo / PACKAGE / "tests" / "unit").mkdir(parents=True)
    (repo / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\npythonpath = ["packages/troupe/tests"]\n'
        'addopts = "-p hypothesis_profiles"\n',
        encoding="utf-8",
    )
    (repo / PACKAGE / "pyproject.toml").write_text('[project]\nname = "troupe"\n', encoding="utf-8")
    for name in ("hypothesis_profiles.py", f"unit/{UNIT_TEST}"):
        (repo / PACKAGE / "tests" / name).write_bytes((TESTS_ROOT / name).read_bytes())
    return repo


def mutmut_copy(repo: Path) -> Path:
    """The package's tests and files as mutmut copies them, to ``packages/troupe/mutants``, with
    the entries of each directory above linked in, as infrastructure's mutation_run.py
    (link_checkout_entries) links them: the root's pyproject.toml into packages/ among them (#543).
    Returns the directory mutmut runs the tests from."""
    package = repo / PACKAGE
    mutants = package / "mutants"
    mutants.mkdir()
    shutil.copytree(package / "tests", mutants / "tests")
    shutil.copy2(package / "pyproject.toml", mutants / "pyproject.toml")
    for level in (package, package.parent):
        for entry in sorted(level.parent.iterdir()):
            link = level / entry.name
            if entry.name != ".git" and not (link.exists() or link.is_symlink()):
                link.symlink_to(Path("..") / entry.name, target_is_directory=entry.is_dir())
    return mutants


def can_symlink(directory: Path) -> bool:
    try:
        (directory / "probe-link").symlink_to("probe-target")
    except OSError:
        return False  # Windows without Developer Mode or the privilege
    (directory / "probe-link").unlink()
    return True


@pytest.mark.parametrize("layout", ["root", "package", "mutmut copy"])
def test_the_database_and_its_test_agree_in_a_checkout_under_another_directory(
    tmp_path: Path, layout: str
) -> None:
    # #543: under the nightly mutation run's layout the unit test took packages/ for the root.
    repo = checkout_under_another_directory(tmp_path)
    test = Path("tests") / "unit" / UNIT_TEST
    extra: list[str] = []
    if layout == "root":
        cwd, test = repo, PACKAGE / test
    elif layout == "package":
        cwd = repo / PACKAGE
    else:
        if not can_symlink(tmp_path):
            pytest.skip("this platform account can't make symbolic links")
        cwd = mutmut_copy(repo)
        extra = ["-o", "addopts=-p hypothesis_profiles"]  # as mutation_run.py's setup.cfg passes it
    completed = subprocess.run(
        [
            *[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *extra],
            *["--confcutdir", str(repo), "--hypothesis-profile=default"],
            *["-k", "test_every_run_shares_the_roots_example_database", str(test)],
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
        cwd=cwd,
        env={k: v for k, v in os.environ.items() if k != "HYPOTHESIS_STORAGE_DIRECTORY"},
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "1 passed" in completed.stdout, completed.stdout
