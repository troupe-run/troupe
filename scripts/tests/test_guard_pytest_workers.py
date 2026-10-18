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
