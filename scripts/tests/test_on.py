"""scripts/on.py runs a command on any supported Python, in that version's own environment (spec:
python-support). uv is replaced by a recorder, so these tests check what on.py asks uv to do; the
switch itself is verified end to end on a machine with several Pythons. Versions come from the
repository's bound, so widening it needs no test edits (python-3-14-3-15 design D3)."""

from pathlib import Path

import pytest
from conftest import BOUND, HIGHEST, LOWEST, REPO, SUPPORTED, listed, minor_after

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
    assert on.main([HIGHEST, "scripts/check.py"], run=uv) == 0
    [(command, cwd, env)] = uv.calls
    assert command == ["/path/to/uv", "run", "--python", HIGHEST, "--", "scripts/check.py"]
    assert cwd == REPO
    assert env["UV_PROJECT_ENVIRONMENT"] == str(REPO / ".venvs" / HIGHEST)


def test_another_activated_environment_is_not_passed_to_uv(uv: Recorder) -> None:
    """uv would warn that it doesn't match the version's environment, then ignore it anyway."""
    on.main([LOWEST, "python", "-V"], run=uv)
    [(_, _, env)] = uv.calls
    assert "VIRTUAL_ENV" not in env


def test_the_commands_arguments_are_forwarded_unchanged(uv: Recorder) -> None:
    arguments = ["pytest", "-q", "--", "-k", "a b", "--python", "3.15", ""]
    on.main([LOWEST, *arguments], run=uv)
    [(command, _, _)] = uv.calls
    assert command[command.index("--") + 1 :] == arguments


def test_the_commands_exit_code_is_passed_through(uv: Recorder) -> None:
    uv.code = 3
    assert on.main([LOWEST, "scripts/check.py"], run=uv) == 3


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
    unsupported = minor_after(HIGHEST)
    assert on.main([unsupported, "scripts/check.py"], run=uv) == 2
    assert uv.calls == []
    assert capsys.readouterr().err == (
        f'on: Python {unsupported} isn\'t supported: requires-python "{BOUND}" in pyproject.toml '
        f"supports {listed(SUPPORTED)}. Run on one of those, or widen the bound and CI's matrix "
        "together.\n"
    )


def test_a_version_with_no_command_is_refused(
    uv: Recorder, capsys: pytest.CaptureFixture[str]
) -> None:
    assert on.main([HIGHEST], run=uv) == 2
    assert uv.calls == []
    assert capsys.readouterr().err == (
        f"on: name a command to run on {HIGHEST}, for example "
        f"`uv run scripts/on.py {HIGHEST} scripts/check.py`.\n"
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
    assert f"Supported versions: {', '.join(SUPPORTED)}." in out
