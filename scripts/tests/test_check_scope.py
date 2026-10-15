"""check.py --scope runs every gate, narrows only the tests, and refuses what isn't declared
(spec: quality-check; commit-check-paths design D8)."""

import sys
from pathlib import Path

import pytest

import check
import guard

DECLARATION = """\
version = 1

[skip]
paths = ["openspec/**"]

[scopes.api]
paths = ["api/**"]

[scopes.docs]
paths = ["docs/**"]
"""


def declare(root: Path, text: str) -> Path:
    (root / "scripts").mkdir()
    (root / "scripts" / "check-paths.toml").write_text(text, encoding="utf-8")
    return root


def exit_code(code: int) -> list[str]:
    return [sys.executable, "-c", f"raise SystemExit({code})"]


class Recorder:
    """Stands in for run_gates, so main's refusals can be seen to come before any gate."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[tuple[str, list[str]]], tuple[str, ...]]] = []

    def __call__(
        self, steps: list[tuple[str, list[str]]], cwd: Path, scopes: tuple[str, ...] = ()
    ) -> int:
        self.calls.append((steps, scopes))
        return 0


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    recorded = Recorder()
    monkeypatch.setattr(check, "run_gates", recorded)
    return recorded


def test_requested_scopes_are_sorted_and_each_named_once() -> None:
    declaration = guard.check_paths(DECLARATION)
    assert check.requested_scopes(["docs", "api", "docs"], declaration) == ("api", "docs")


def test_an_undeclared_scope_exits_naming_the_scope_and_the_declaration() -> None:
    with pytest.raises(SystemExit) as refused:
        check.requested_scopes(["docs", "nope"], guard.check_paths(DECLARATION))
    message = str(refused.value.code)
    assert "`nope`" in message
    assert "`docs`" not in message
    assert "scripts/check-paths.toml" in message


def test_with_no_declaration_every_scope_is_undeclared() -> None:
    with pytest.raises(SystemExit) as refused:
        check.requested_scopes(["docs"], None)
    message = str(refused.value.code)
    assert "`docs`" in message
    assert "scripts/check-paths.toml" in message


def test_an_undeclared_scope_is_refused_before_any_gate_runs(
    tmp_path: Path, recorder: Recorder
) -> None:
    root = declare(tmp_path, DECLARATION)
    with pytest.raises(SystemExit) as refused:
        check.main(["--scope", "nope"], root=root)
    assert "`nope`" in str(refused.value.code)
    assert recorder.calls == []


def test_a_malformed_declaration_is_refused_with_the_guards_message_before_any_gate_runs(
    tmp_path: Path, recorder: Recorder
) -> None:
    root = declare(tmp_path, 'version = 1\n[skip]\npaths = ["docs/*.md"]\n')
    with pytest.raises(SystemExit) as refused:
        check.main(["--scope", "docs"], root=root)
    message = str(refused.value.code)
    assert "scripts/check-paths.toml is malformed" in message
    assert "`docs/*.md` uses a wildcard other than a trailing `/**`" in message
    assert "fix:" in message
    assert recorder.calls == []


def test_without_scopes_the_declaration_is_not_read(tmp_path: Path, recorder: Recorder) -> None:
    root = declare(tmp_path, "this isn't TOML")
    assert check.main([], root=root) == 0
    [(steps, scopes)] = recorder.calls
    assert scopes == ()
    assert "-m" not in dict(steps)["tests"]


def test_main_passes_the_declared_scopes_sorted_and_once_each_to_the_gates(
    tmp_path: Path, recorder: Recorder
) -> None:
    root = declare(tmp_path, DECLARATION)
    assert check.main(["--scope", "docs", "--scope", "api", "--scope", "docs"], root=root) == 0
    [(steps, scopes)] = recorder.calls
    assert scopes == ("api", "docs")
    assert dict(steps)["tests"][-2:] == ["-m", "api or docs"]


def test_the_unscoped_gates_are_the_full_check_with_no_marker_expression() -> None:
    labels = [label for label, _ in check.gates()]
    assert labels == ["ruff lint", "ruff format", "mypy --strict", "import contracts", "tests"]
    assert "-m" not in dict(check.gates())["tests"]


def test_a_scoped_check_runs_every_gate_and_narrows_only_the_tests() -> None:
    full = dict(check.gates())
    scoped = dict(check.gates(("docs",)))
    assert list(scoped) == list(full)
    for label in full:
        if label != "tests":
            assert scoped[label] == full[label]
    assert scoped["tests"] == [*full["tests"], "-m", "docs"]


def test_no_tests_ran_passes_a_scoped_check_and_says_nothing_was_tagged(
    capfd: pytest.CaptureFixture[str],
) -> None:
    code = check.run_gates([("tests", exit_code(check.NO_TESTS_RAN))], Path.cwd(), ("docs",))
    assert code == 0
    output = capfd.readouterr().out
    assert "no test is tagged `docs`, so there was nothing to test" in output
    assert "check: all gates passed" in output


def test_no_tests_ran_fails_the_full_check(capfd: pytest.CaptureFixture[str]) -> None:
    code = check.run_gates([("tests", exit_code(check.NO_TESTS_RAN))], Path.cwd())
    assert code == check.NO_TESTS_RAN
    assert "check: tests failed (exit 5)" in capfd.readouterr().out


@pytest.mark.parametrize("scopes", [(), ("docs",)], ids=["full", "scoped"])
def test_a_failing_gate_stops_the_check_and_names_itself(
    scopes: tuple[str, ...], capfd: pytest.CaptureFixture[str]
) -> None:
    steps = [("ruff lint", exit_code(1)), ("tests", exit_code(0))]
    assert check.run_gates(steps, Path.cwd(), scopes) == 1
    output = capfd.readouterr().out
    assert "check: ruff lint failed (exit 1)" in output
    assert "==> tests" not in output


def test_a_scoped_check_still_fails_on_a_failing_test_gate(
    capfd: pytest.CaptureFixture[str],
) -> None:
    assert check.run_gates([("tests", exit_code(1))], Path.cwd(), ("docs",)) == 1
    assert "check: tests failed (exit 1)" in capfd.readouterr().out
