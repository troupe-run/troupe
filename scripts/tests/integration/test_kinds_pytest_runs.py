"""The kinds plugin in real pytest runs, each in a child process so the run under test has its own
audit hook and its own events (spec: quality-check; test-split design D3a-D6)."""

import re
import textwrap
from pathlib import Path

import pytest

import kinds_pytest

pytest_plugins = ["pytester"]

SCRIPTS = Path(kinds_pytest.__file__).resolve().parent

EXAMPLES = {
    "a process": "import subprocess, sys\n"
    "subprocess.run([sys.executable, '-c', 'pass'], check=True)",
    "a git theatre": "import sys\nsys.audit('troupe.tests.theatre', 'theatre')",
    "a socket": "import socket\n"
    "with socket.socket() as listener:\n"
    "    listener.bind(('127.0.0.1', 0))",
}
"""A test body that reaches outside in each declared way. A kind added to kinds_pytest.OUTSIDE needs
an example here, or test_every_declared_reach_has_an_example fails."""


@pytest.fixture(name="suite")
def suite_fixture(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> pytest.Pytester:
    """A project with one suite, `suite`, run with the kinds plugin and nothing else of troupe's."""
    monkeypatch.setenv("PYTHONPATH", str(SCRIPTS))
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    pytester.makeini(
        "[pytest]\ntestpaths = suite\npythonpath = suite\n"
        "addopts = -p kinds_pytest -p no:cacheprovider\n"
    )
    return pytester


def write(pytester: pytest.Pytester, path: str, source: str) -> None:
    target = pytester.path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(textwrap.dedent(source), encoding="utf-8")


def refused(result: pytest.RunResult, count: int = 1, passed: int = 0) -> None:
    """The run failed, with `count` tests refused. A refusal fails a test at teardown, as the
    guard's do, so pytest counts it as an error after the test's own call passed."""
    outcomes = result.parseoutcomes()
    assert result.ret != 0
    assert outcomes.get("errors", 0) == count, outcomes
    assert outcomes.get("failed", 0) == 0, outcomes
    assert outcomes.get("passed", 0) == passed + count, outcomes


def body(code: str) -> str:
    return "def test_reaches():\n" + textwrap.indent(code, "    ") + "\n"


def test_every_declared_reach_has_an_example() -> None:
    assert set(EXAMPLES) == {reach.name for reach in kinds_pytest.OUTSIDE}


@pytest.mark.parametrize("reach", sorted(EXAMPLES))
def test_a_unit_test_that_reaches_outside_fails_naming_the_reach(
    suite: pytest.Pytester, reach: str
) -> None:
    write(suite, "suite/unit/test_a.py", body(EXAMPLES[reach]))
    result = suite.runpytest_subprocess()
    refused(result)
    output = result.stdout.str()
    assert f"kinds: a unit test reached outside its process: {reach}" in output
    assert "Move it to integration/" in output


@pytest.mark.parametrize("reach", sorted(EXAMPLES))
def test_the_same_test_under_integration_passes(suite: pytest.Pytester, reach: str) -> None:
    write(suite, "suite/integration/test_a.py", body(EXAMPLES[reach]))
    suite.runpytest_subprocess().assert_outcomes(passed=1)


def test_a_process_names_its_program(suite: pytest.Pytester) -> None:
    write(suite, "suite/unit/test_a.py", body(EXAMPLES["a process"]))
    output = suite.runpytest_subprocess().stdout.str()
    assert re.search(r"a process \(python[0-9.]*(\.exe)?\) x1", output), output


def test_a_session_fixture_an_earlier_test_set_up_fails_a_later_unit_test(
    suite: pytest.Pytester,
) -> None:
    write(
        suite,
        "suite/conftest.py",
        """\
        import subprocess, sys
        import pytest

        @pytest.fixture(scope="session")
        def started():
            subprocess.run([sys.executable, "-c", "pass"], check=True)
        """,
    )
    # integration/ sorts before unit/, so the integration test sets the fixture up.
    write(suite, "suite/integration/test_first.py", "def test_first(started):\n    pass\n")
    write(suite, "suite/unit/test_later.py", "def test_later(started):\n    pass\n")
    result = suite.runpytest_subprocess()
    refused(result, passed=1)
    assert "test_later.py::test_later" in result.stdout.str()
    assert "a unit test reached outside its process: a process" in result.stdout.str()


def test_a_socket_pair_in_a_unit_test_passes(suite: pytest.Pytester) -> None:
    write(
        suite,
        "suite/unit/test_a.py",
        body("import socket\nfirst, second = socket.socketpair()\nfirst.close()\nsecond.close()"),
    )
    suite.runpytest_subprocess().assert_outcomes(passed=1)


def test_an_integration_test_that_reaches_nothing_passes(suite: pytest.Pytester) -> None:
    write(suite, "suite/integration/test_a.py", "def test_nothing():\n    pass\n")
    suite.runpytest_subprocess().assert_outcomes(passed=1)


@pytest.mark.parametrize(
    "selection",
    [[], ["-m", "unit"], ["-m", "integration"], ["-m", "not integration"], ["-n", "2"]],
    ids=["all", "unit", "integration", "not-integration", "workers"],
)
def test_a_test_file_in_neither_directory_fails_the_run_whatever_it_selects(
    suite: pytest.Pytester, selection: list[str]
) -> None:
    write(suite, "suite/test_new.py", "def test_new():\n    pass\n")
    write(suite, "suite/unit/test_a.py", "def test_a():\n    pass\n")
    result = suite.runpytest_subprocess(*selection)
    # In one process the collection error stops the run; across workers the others still run.
    assert result.ret in (pytest.ExitCode.INTERRUPTED, pytest.ExitCode.TESTS_FAILED)
    assert (
        "kinds: suite/test_new.py is in neither kind's directory; "
        "move it to suite/unit/ or suite/integration/" in result.stdout.str()
    )


@pytest.mark.parametrize("mark", ["unit", "integration"])
def test_a_hand_written_kind_fails(suite: pytest.Pytester, mark: str) -> None:
    write(
        suite,
        "suite/unit/test_a.py",
        f"import pytest\n\n@pytest.mark.{mark}\ndef test_marked():\n    pass\n",
    )
    result = suite.runpytest_subprocess()
    refused(result)
    assert f"`{mark}` is written by hand" in result.stdout.str()


@pytest.mark.parametrize(
    "imported", ["suite/integration/test_b.py", "suite/unit/test_b.py"], ids=["other", "same"]
)
def test_a_test_module_importing_another_fails_naming_both(
    suite: pytest.Pytester, imported: str
) -> None:
    write(suite, imported, "CONFIGURED = 1\n\ndef test_b():\n    pass\n")
    write(
        suite,
        "suite/unit/test_a.py",
        "def test_a():\n    from test_b import CONFIGURED\n    assert CONFIGURED\n",
    )
    result = suite.runpytest_subprocess("suite/unit/test_a.py")
    # The import also fails when test_b is in the other directory; the refusal holds either way.
    assert result.ret != 0
    assert result.parseoutcomes().get("errors") == 1
    assert "test_a.py imports the test module test_b" in result.stdout.str()


def test_a_unit_test_starting_a_process_through_a_helper_fails(suite: pytest.Pytester) -> None:
    write(
        suite,
        "suite/helper.py",
        "import subprocess, sys\n\ndef run():\n"
        "    subprocess.run([sys.executable, '-c', 'pass'], check=True)\n",
    )
    write(suite, "suite/unit/test_a.py", "from helper import run\n\ndef test_a():\n    run()\n")
    result = suite.runpytest_subprocess()
    refused(result)
    assert "a unit test reached outside its process: a process" in result.stdout.str()


def test_kind_selections_agree_and_the_run_ends_with_each_kinds_summary(
    suite: pytest.Pytester,
) -> None:
    write(suite, "suite/unit/test_a.py", "def test_a():\n    pass\n\ndef test_b():\n    pass\n")
    write(suite, "suite/integration/test_c.py", "def test_c():\n    pass\n")
    unit = suite.runpytest_subprocess("-m", "unit", "--collect-only", "-q").stdout.lines
    not_integration = suite.runpytest_subprocess(
        "-m", "not integration", "--collect-only", "-q"
    ).stdout.lines
    by_directory = suite.runpytest_subprocess("suite/unit", "--collect-only", "-q").stdout.lines
    ids = [line for line in unit if "::" in line]
    assert ids == ["suite/unit/test_a.py::test_a", "suite/unit/test_a.py::test_b"]
    assert ids == [line for line in not_integration if "::" in line]
    assert ids == [line for line in by_directory if "::" in line]
    output = suite.runpytest_subprocess().stdout.str()
    assert re.search(r"kinds: unit: 2 tests, [0-9.]+s summed", output), output
    assert re.search(r"kinds: integration: 1 tests, [0-9.]+s summed", output), output


def test_the_same_results_across_workers(suite: pytest.Pytester) -> None:
    write(suite, "suite/unit/test_a.py", body(EXAMPLES["a process"]))
    write(suite, "suite/unit/test_b.py", "def test_b():\n    pass\n")
    write(suite, "suite/integration/test_c.py", body(EXAMPLES["a socket"]))
    result = suite.runpytest_subprocess("-n", "2")
    refused(result, passed=2)
    output = result.stdout.str()
    assert "a unit test reached outside its process: a process" in output
    assert re.search(r"kinds: unit: 2 tests", output), output


STARTS = "import subprocess, sys\nsubprocess.run([sys.executable, '-c', 'pass'], check=True)\n"


def test_a_unit_test_given_an_override_isnt_charged_for_the_fixture_it_overrides(
    suite: pytest.Pytester,
) -> None:
    write(
        suite,
        "suite/conftest.py",
        "import pytest\n\n@pytest.fixture(scope='session')\ndef server():\n"
        + textwrap.indent(STARTS, "    "),
    )
    write(suite, "suite/integration/test_first.py", "def test_real(server):\n    pass\n")
    write(
        suite,
        "suite/unit/conftest.py",
        "import pytest\n\n@pytest.fixture\ndef server():\n    return 'in-process'\n",
    )
    write(suite, "suite/unit/test_later.py", "def test_fake(server):\n    pass\n")
    suite.runpytest_subprocess().assert_outcomes(passed=2)


def test_a_unit_test_is_charged_only_for_its_own_parameter_of_a_shared_fixture(
    suite: pytest.Pytester,
) -> None:
    write(
        suite,
        "suite/conftest.py",
        "import pytest\n\n@pytest.fixture(scope='session')\ndef backend(request):\n"
        "    if request.param == 'real':\n"
        + textwrap.indent(STARTS, "        ")
        + "    return request.param\n",
    )
    parametrized = (
        "import pytest\n\n@pytest.mark.parametrize('backend', ['{}'], indirect=True)\n"
        "def test_backend(backend):\n    pass\n"
    )
    write(suite, "suite/integration/test_first.py", parametrized.format("real"))
    write(suite, "suite/unit/test_later.py", parametrized.format("fake"))
    suite.runpytest_subprocess().assert_outcomes(passed=2)
    write(suite, "suite/unit/test_real.py", parametrized.format("real"))
    refused(suite.runpytest_subprocess(), passed=2)


def test_a_broader_fixtures_teardown_isnt_charged_to_the_last_test(
    suite: pytest.Pytester,
) -> None:
    write(
        suite,
        "suite/conftest.py",
        "import pytest\n\n@pytest.fixture(scope='session')\ndef cleaned():\n    yield\n"
        + textwrap.indent(STARTS, "    "),
    )
    write(suite, "suite/integration/test_first.py", "def test_uses(cleaned):\n    pass\n")
    write(suite, "suite/unit/test_last.py", "def test_last():\n    pass\n")
    suite.runpytest_subprocess().assert_outcomes(passed=2)


def test_a_fixture_reached_through_getfixturevalue_is_charged(suite: pytest.Pytester) -> None:
    write(
        suite,
        "suite/conftest.py",
        "import pytest\n\n@pytest.fixture(scope='session')\ndef started():\n"
        + textwrap.indent(STARTS, "    "),
    )
    write(suite, "suite/integration/test_first.py", "def test_first(started):\n    pass\n")
    write(
        suite,
        "suite/unit/test_later.py",
        "def test_later(request):\n    request.getfixturevalue('started')\n",
    )
    refused(suite.runpytest_subprocess(), passed=1)
