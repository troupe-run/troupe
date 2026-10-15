"""scripts/on.py runs a command on any supported Python, in that version's own environment (spec:
python-support). uv is replaced by a recorder, so these tests check what on.py asks uv to do; the
switch itself is verified end to end on a machine with several Pythons (tasks 3.3)."""

from pathlib import Path

import pytest
from conftest import REPO

import on


class Recorder:
    """Stands in for running uv: records each call and returns a set exit code."""

    def __init__(self, code: int = 0) -> None:
        self.code = code
        self.calls: list[tuple[list[str], Path, dict[str, str]]] = []

    def __call__(self, command: list[str], cwd: Path, env: dict[str, str]) -> int:
        self.calls.append((command, cwd, env))
        return self.code


@pytest.fixture
def uv(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    monkeypatch.setenv("UV", "/path/to/uv")
    monkeypatch.setenv("VIRTUAL_ENV", "/somewhere/else")
    return Recorder()


def test_a_supported_version_runs_the_command_in_its_own_environment(uv: Recorder) -> None:
    assert on.main(["3.13", "scripts/check.py"], run=uv) == 0
    [(command, cwd, env)] = uv.calls
    assert command == ["/path/to/uv", "run", "--python", "3.13", "--", "scripts/check.py"]
    assert cwd == REPO
    assert env["UV_PROJECT_ENVIRONMENT"] == str(REPO / ".venvs" / "3.13")


def test_another_activated_environment_is_not_passed_to_uv(uv: Recorder) -> None:
    """uv would warn that it doesn't match the version's environment, then ignore it anyway."""
    on.main(["3.12", "python", "-V"], run=uv)
    [(_, _, env)] = uv.calls
    assert "VIRTUAL_ENV" not in env


def test_the_commands_arguments_are_forwarded_unchanged(uv: Recorder) -> None:
    arguments = ["pytest", "-q", "--", "-k", "a b", "--python", "3.15", ""]
    on.main(["3.12", *arguments], run=uv)
    [(command, _, _)] = uv.calls
    assert command[command.index("--") + 1 :] == arguments


def test_the_commands_exit_code_is_passed_through(uv: Recorder) -> None:
    uv.code = 3
    assert on.main(["3.12", "scripts/check.py"], run=uv) == 3


@pytest.mark.parametrize("version", ["3.x", "3", "3.13.1", "", "py3.13", "--python", "3.013"])
def test_a_malformed_version_is_refused_showing_the_form_and_nothing_runs(
    uv: Recorder, version: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert on.main([version, "scripts/check.py"], run=uv) == 2
    assert uv.calls == []
    assert capsys.readouterr().err == (
        f"on: {version!r} isn't a Python version: give a minor version like 3.13, for example "
        "`uv run scripts/on.py 3.13 scripts/check.py`.\n"
    )


def test_an_unsupported_version_is_refused_listing_the_supported_ones_and_nothing_runs(
    uv: Recorder, capsys: pytest.CaptureFixture[str]
) -> None:
    assert on.main(["3.15", "scripts/check.py"], run=uv) == 2
    assert uv.calls == []
    assert capsys.readouterr().err == (
        'on: Python 3.15 isn\'t supported: requires-python ">=3.12,<3.14" in pyproject.toml '
        "supports 3.12 and 3.13. Run on one of those, or widen the bound and CI's matrix "
        "together.\n"
    )


def test_a_version_with_no_command_is_refused(
    uv: Recorder, capsys: pytest.CaptureFixture[str]
) -> None:
    assert on.main(["3.13"], run=uv) == 2
    assert uv.calls == []
    assert capsys.readouterr().err == (
        "on: name a command to run on 3.13, for example "
        "`uv run scripts/on.py 3.13 scripts/check.py`.\n"
    )


def test_no_arguments_is_refused_with_the_usage(
    uv: Recorder, capsys: pytest.CaptureFixture[str]
) -> None:
    assert on.main([], run=uv) == 2
    assert uv.calls == []
    assert capsys.readouterr().err.startswith("usage: uv run scripts/on.py VERSION COMMAND...")


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_help_prints_the_usage_and_the_supported_versions(
    uv: Recorder, flag: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert on.main([flag], run=uv) == 0
    assert uv.calls == []
    out = capsys.readouterr().out
    assert out.startswith("usage: uv run scripts/on.py VERSION COMMAND...")
    assert "Supported versions: 3.12, 3.13." in out
