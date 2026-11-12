"""guard_pytest's tag rule holds when the tests run across pytest-xdist workers, as scripts/check.py
runs them (spec: quality-check; parallel-tests design D5). guard_pytest itself is maintained in
troupe-run/infrastructure; this checks the way troupe runs it."""

import os
from pathlib import Path

import pytest

pytest_plugins = ["pytester"]

SCRIPTS = Path(__file__).resolve().parents[1]

TESTS = """
from pathlib import Path

import pytest


def test_reads_the_docs_untagged():
    Path("docs/x.md").read_text(encoding="utf-8")


@pytest.mark.docs
def test_reads_the_docs_tagged():
    Path("docs/x.md").read_text(encoding="utf-8")


def test_reads_openspec():
    Path("openspec/changes/x.md").read_text(encoding="utf-8")


def test_reads_nothing():
    pass
"""


@pytest.fixture
def repository(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> pytest.Pytester:
    """A repository that declares a docs scope and skips openspec/, as troupe's does."""
    monkeypatch.setenv(
        "PYTHONPATH", os.pathsep.join([str(SCRIPTS), os.environ.get("PYTHONPATH", "")])
    )
    pytester.makeini("[pytest]\ntestpaths = tests\n")
    for relative, text in {
        "scripts/check-paths.toml": (
            'version = 1\n\n[skip]\npaths = ["openspec/**"]\n\n[scopes.docs]\npaths = ["docs/**"]\n'
        ),
        "docs/x.md": "# x\n",
        "openspec/changes/x.md": "# x\n",
        "tests/test_reads.py": TESTS,
    }.items():
        target = pytester.path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return pytester


@pytest.mark.parametrize("workers", [["-n", "2"], []], ids=["parallel", "one-process"])
def test_an_untagged_docs_read_and_an_openspec_read_fail_at_teardown_however_the_run_is_split(
    repository: pytest.Pytester, workers: list[str]
) -> None:
    result = repository.runpytest_subprocess(
        "-p", "guard_pytest", "--strict-markers", "-p", "no:cacheprovider", "-rE", *workers
    )

    if workers:  # the run really was split
        result.stdout.fnmatch_lines(["created: 2/2 workers"])
    # The guard fails a test in its teardown report, which pytest counts as an error.
    result.assert_outcomes(passed=4, errors=2)
    errored = [line for line in result.outlines if line.startswith("ERROR")]
    assert sorted(line.split()[1].split("::")[1] for line in errored) == [
        "test_reads_openspec",
        "test_reads_the_docs_untagged",
    ]
    result.stdout.fnmatch_lines_random(
        [
            "guard: tests/test_reads.py::test_reads_the_docs_untagged reads docs/x.md, *"
            "Tag the test `docs`*",
            "guard: tests/test_reads.py::test_reads_openspec reads openspec/changes/x.md, *"
            "skips `openspec/**`*",
        ]
    )


# A selection by node id across scopes (troupe-run/troupe#365; theatre-template-and-guard-xdist
# design D6, D7). Given `file::test` arguments, pytest collects each module inside the session's own
# collect report, so a guard that gave every enclosing collector a collection read blamed each test
# for the other selected modules' imports.

SELECTION_DECLARATION = """version = 1

[skip]
paths = ["openspec/**"]

[scopes.docs]
paths = ["docs/**"]

[scopes.alpha]
paths = ["alpha/**"]
tests = ["alpha/tests/**"]

[scopes.beta]
paths = ["beta/**"]
tests = ["beta/tests/**"]
"""

ALPHA = """from pathlib import Path


def test_alpha_reads_its_own_data():
    Path("alpha/data.txt").read_text(encoding="utf-8")


def test_alpha_reads_the_docs_untagged():
    Path("docs/x.md").read_text(encoding="utf-8")
"""

BETA = """def test_beta_reads_its_own_data(beta_data):
    assert beta_data == "beta\\n"
"""

BETA_CONFTEST = """from pathlib import Path

import pytest


@pytest.fixture
def beta_data():
    return Path("beta/data.txt").read_text(encoding="utf-8")
"""

ALPHA_TEST = "alpha/tests/test_alpha.py::test_alpha_reads_its_own_data"
BETA_TEST = "beta/tests/test_beta.py::test_beta_reads_its_own_data"
DOCS_TEST = "alpha/tests/test_alpha.py::test_alpha_reads_the_docs_untagged"


@pytest.fixture
def packages(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> pytest.Pytester:
    """Two packages, each a scope with its own tests (one with a conftest.py), and a docs scope."""
    monkeypatch.setenv(
        "PYTHONPATH", os.pathsep.join([str(SCRIPTS), os.environ.get("PYTHONPATH", "")])
    )
    pytester.makeini("[pytest]\n")
    for relative, text in {
        "scripts/check-paths.toml": SELECTION_DECLARATION,
        "docs/x.md": "# x\n",
        "alpha/data.txt": "alpha\n",
        "alpha/tests/test_alpha.py": ALPHA,
        "beta/data.txt": "beta\n",
        "beta/tests/conftest.py": BETA_CONFTEST,
        "beta/tests/test_beta.py": BETA,
    }.items():
        target = pytester.path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return pytester


def run_selection(packages: pytest.Pytester, workers: list[str], *tests: str) -> pytest.RunResult:
    return packages.runpytest_subprocess(
        "-p", "guard_pytest", "--strict-markers", "-p", "no:cacheprovider", "-rE", *workers, *tests
    )


@pytest.mark.parametrize("workers", [["-n", "2"], []], ids=["parallel", "one-process"])
def test_tests_from_two_scopes_selected_by_node_id_pass_with_no_guard_failure(
    packages: pytest.Pytester, workers: list[str]
) -> None:
    result = run_selection(packages, workers, ALPHA_TEST, BETA_TEST)

    if workers:  # the run really was split
        result.stdout.fnmatch_lines(["created: 2/2 workers"])
    assert [line for line in result.outlines if "guard:" in line] == []
    result.assert_outcomes(passed=2)


@pytest.mark.parametrize("workers", [["-n", "2"], []], ids=["parallel", "one-process"])
def test_an_untagged_docs_read_in_a_selection_by_node_id_fails_only_that_test(
    packages: pytest.Pytester, workers: list[str]
) -> None:
    result = run_selection(packages, workers, ALPHA_TEST, BETA_TEST, DOCS_TEST)

    # The guard fails a test in its teardown report, which pytest counts as an error.
    result.assert_outcomes(passed=3, errors=1)
    errored = [line for line in result.outlines if line.startswith("ERROR")]
    assert [line.split()[1] for line in errored] == [DOCS_TEST]
    assert [line for line in result.outlines if line.startswith("guard:")] == [
        line for line in result.outlines if line.startswith(f"guard: {DOCS_TEST} reads docs/x.md")
    ]
    result.stdout.fnmatch_lines([f"guard: {DOCS_TEST} reads docs/x.md, *Tag the test `docs`*"])
