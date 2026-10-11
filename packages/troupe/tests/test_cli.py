"""Tests for the cli spec. Every command line goes through run_cli, which checks that the exit code
it returns is one of the documented codes ("Every returned code is documented")."""

import argparse
import io
import json
import shutil
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Any, TextIO

import jsonschema
import pytest

from troupe.cli import main
from troupe.cli.parser import Command, parse
from troupe.core.errors import TroupeError
from troupe.core.exit_codes import ExitCode

SCHEMA_PATH = Path(__file__).resolve().parents[3] / "protocol" / "schemas" / "error.schema.json"
SCHEMA: dict[str, Any] = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _configure_echo(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("value")
    parser.add_argument("--upper", action="store_true")


def _run_echo(arguments: argparse.Namespace, stdout: TextIO) -> ExitCode:
    value = str(arguments.value)
    print(value.upper() if arguments.upper else value, file=stdout)
    return ExitCode.OK


def _run_failing(arguments: argparse.Namespace, stdout: TextIO) -> ExitCode:
    raise TroupeError(
        "lock.timeout",
        problem="timed out waiting for the theatre lock",
        fix="Wait for the other troupe command to finish, then try again.",
        path=str(Path.home() / "theatre" / ".troupe"),
    )


def _run_crashing(arguments: argparse.Namespace, stdout: TextIO) -> ExitCode:
    raise RuntimeError("boom")


ECHO = Command("echo", "Print a value (test only).", _configure_echo, _run_echo)
FAILING = Command("failing", "Fail with a path (test only).", lambda parser: None, _run_failing)
CRASHING = Command("crashing", "Crash (test only).", lambda parser: None, _run_crashing)
TEST_COMMANDS = (ECHO, FAILING, CRASHING)


def run_cli(*argv: str, commands: tuple[Command, ...] = TEST_COMMANDS) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(list(argv), commands=commands, stdout=stdout, stderr=stderr)
    assert isinstance(code, ExitCode), f"{argv} returned {code!r}, not in the exit-code table"
    return code, stdout.getvalue(), stderr.getvalue()


def usage_error(*argv: str, commands: tuple[Command, ...] = TEST_COMMANDS) -> TroupeError:
    with pytest.raises(TroupeError) as caught:
        parse(list(argv), commands)
    return caught.value


# Requirement: Version reporting


def test_version_flag_prints_the_installed_version_from_a_directory_with_no_theatre(
    tmp_path: Path,
) -> None:
    executable = shutil.which("troupe", path=str(Path(sys.executable).parent))
    assert executable is not None, "the troupe console script is not installed in this environment"
    result = subprocess.run(
        [executable, "--version"], cwd=tmp_path, capture_output=True, text=True, check=False
    )
    assert not (tmp_path / ".troupe").exists()
    assert result.returncode == ExitCode.OK
    assert version("troupe") in result.stdout
    assert result.stderr == ""


# Requirement: Global flags are accepted anywhere


def test_version_flag_before_the_subcommand_prints_the_version() -> None:
    code, out, _ = run_cli("--version", "echo", "x")
    assert (code, out) == (ExitCode.OK, f"troupe {version('troupe')}\n")


def test_version_flag_after_the_subcommand_gives_the_same_result_as_before_it() -> None:
    assert run_cli("echo", "x", "--version") == run_cli("--version", "echo", "x")
    assert run_cli("echo", "--version", "x") == run_cli("--version", "echo", "x")


def test_help_flag_after_the_subcommand_shows_that_subcommand_s_help() -> None:
    code, out, err = run_cli("echo", "--help")
    assert code == ExitCode.OK
    assert "--upper" in out
    assert err == ""


def test_global_flags_cannot_be_abbreviated() -> None:
    error = usage_error("--vers")
    assert error.code == "usage.unknown-flag"
    assert "`--version`" in error.fix


# Requirement: Dash-leading values follow the -- convention


@pytest.mark.parametrize("value", ["-5", "-.inf", "-"])
def test_dash_leading_value_without_separator_is_a_usage_error_that_names_the_fix(
    value: str,
) -> None:
    code, out, err = run_cli("echo", value)
    assert code == ExitCode.USAGE
    assert out == ""
    assert f"`{value}`" in err
    assert "--" in err.split("fix:", 1)[1]


@pytest.mark.parametrize("value", ["-5", "-.inf", "-"])
def test_dash_leading_value_after_separator_is_accepted(value: str) -> None:
    assert run_cli("echo", "--", value) == (ExitCode.OK, f"{value}\n", "")


# Requirement: Errors are rendered from structured data


def test_an_error_writes_problem_path_and_fix_to_stderr_and_nothing_to_stdout() -> None:
    code, out, err = run_cli("failing")
    assert code == ExitCode.FAILURE
    assert out == ""
    assert "timed out waiting for the theatre lock" in err
    assert "fix: Wait for the other troupe command to finish" in err
    expected_path = "~" + ("\\" if sys.platform == "win32" else "/") + "theatre"
    assert f"path: {expected_path}" in err


def test_an_unexpected_exception_is_reported_as_a_structured_internal_error() -> None:
    code, out, err = run_cli("crashing")
    assert code == ExitCode.FAILURE
    assert out == ""
    assert "RuntimeError: boom" in err
    assert "github.com/troupe-run/troupe.run/issues" in err


@pytest.mark.parametrize(
    "argv",
    [("verison",), ("--bogus",), ("echo", "-5"), ("echo",), ("echo", "x", "y")],
    ids=["unknown-command", "unknown-flag", "dash-value", "missing-argument", "extra-argument"],
)
def test_usage_error_data_matches_the_protocol_schema(argv: tuple[str, ...]) -> None:
    jsonschema.validate(usage_error(*argv).to_data(), SCHEMA)


def test_internal_and_command_error_data_matches_the_protocol_schema() -> None:
    with pytest.raises(TroupeError) as caught:
        _run_failing(argparse.Namespace(), io.StringIO())
    jsonschema.validate(caught.value.to_data(), SCHEMA)
    internal = TroupeError("internal.unexpected", problem="p", fix="f")
    jsonschema.validate(internal.to_data(), SCHEMA)


# Requirement: Usage errors and unknown commands


def test_unknown_subcommand_near_a_global_flag_suggests_the_flag() -> None:
    code, out, err = run_cli("verison", commands=())
    assert code == ExitCode.USAGE
    assert out == ""
    assert "`verison` is not a troupe command" in err
    assert "Did you mean `--version`?" in err


def test_unknown_subcommand_near_a_command_suggests_the_command() -> None:
    assert "Did you mean `echo`?" in run_cli("ecoh", "x")[2]


def test_unknown_subcommand_with_no_near_match_points_at_help() -> None:
    error = usage_error("zzzzzz")
    assert error.code == "usage.unknown-command"
    assert "troupe --help" in error.fix


def test_unknown_flag_is_a_usage_error_that_names_the_flag() -> None:
    code, out, err = run_cli("echo", "x", "--bogus")
    assert code == ExitCode.USAGE
    assert out == ""
    assert "`--bogus` is not a troupe option" in err


def test_unknown_flag_near_a_known_flag_suggests_it() -> None:
    assert "`--upper`" in usage_error("echo", "x", "--uper").fix


def test_unknown_short_flag_is_an_unknown_flag_not_a_dash_value() -> None:
    assert usage_error("echo", "x", "-q").code == "usage.unknown-flag"


# Requirement: Exit codes are defined in one place


@pytest.mark.parametrize(
    "argv",
    [
        (),
        ("--help",),
        ("--version",),
        ("echo", "x"),
        ("echo", "--", "-x"),
        ("verison",),
        ("--bogus",),
        ("echo", "-5"),
        ("echo",),
        ("failing",),
        ("crashing",),
    ],
)
def test_every_exit_code_the_cli_returns_is_in_the_exit_code_table(argv: tuple[str, ...]) -> None:
    code, _, _ = run_cli(*argv)
    assert code in set(ExitCode)


def test_version_flag_after_an_incomplete_subcommand_still_prints_the_version() -> None:
    assert run_cli("echo", "--version") == run_cli("--version")
