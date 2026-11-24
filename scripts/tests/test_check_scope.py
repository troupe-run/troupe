"""check.py --scope runs every gate, narrows only the tests, and refuses what isn't declared
(spec: quality-check; commit-check-paths design D8).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_check_scope_integration.py."""

import tomllib
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
    assert labels == [
        "ruff lint",
        "ruff format",
        "mypy --strict",
        "import contracts",
        "complexity",
        "size",
        "tests",
    ]
    assert "-m" not in dict(check.gates())["tests"]


@pytest.mark.parametrize("scopes", [(), ("docs",)], ids=["full", "scoped"])
def test_the_tests_gate_runs_pytest_across_a_worker_per_cpu_with_work_stealing(
    scopes: tuple[str, ...],
) -> None:
    tests = dict(check.gates(scopes))["tests"]
    assert tests[1:5] == ["-n", "auto", "--dist", "worksteal"]


def test_the_pytest_configuration_turns_on_no_xdist_option_so_pytest_stays_one_process() -> None:
    pyproject = Path(check.ROOT, "pyproject.toml").read_text(encoding="utf-8")
    addopts = tomllib.loads(pyproject)["tool"]["pytest"]["ini_options"]["addopts"]
    xdist = ("-n", "--numprocesses", "--dist", "--maxprocesses")
    assert [opt for opt in addopts if opt.split("=")[0] in xdist or opt.startswith("-n")] == []


def test_a_scoped_check_runs_every_gate_and_narrows_only_the_tests() -> None:
    full = dict(check.gates())
    scoped = dict(check.gates(("docs",)))
    assert list(scoped) == list(full)
    for label in full:
        if label != "tests":
            assert scoped[label] == full[label]
    assert scoped["tests"] == [*full["tests"], "-m", "docs"]


@pytest.mark.parametrize(
    "paths",
    [
        ["contributing/runs.md"],
        ["docs/the-company/theatres.md"],
        ["contributing/runs.md", "openspec/x.md"],
    ],
    ids=["contributor-doc", "user-doc", "with-openspec"],
)
def test_troupes_declaration_scopes_the_user_and_contributor_docs_to_docs(paths: list[str]) -> None:
    declaration = guard.check_paths(
        (Path(__file__).resolve().parents[2] / guard.CHECK_PATHS).read_text(encoding="utf-8")
    )
    assert guard.check_scope(paths, declaration).names == ("docs",)
