"""Tests for the cli spec. Every command line goes through run_cli, which checks that the exit code
it returns is one of the documented codes ("Every returned code is documented")."""

import argparse
import io
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from importlib.metadata import version
from pathlib import Path
from typing import Any, TextIO

import jsonschema
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from protocol_schemas import check_error
from troupe.cli import COMMANDS, main
from troupe.cli.parser import HELP_FIX, Command, _Declared, _declared, parse
from troupe.cli.render import render_error
from troupe.core.errors import TroupeError
from troupe.core.exit_codes import ExitCode


def _configure_echo(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("value")
    parser.add_argument("--upper", action="store_true")


def _run_echo(arguments: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> ExitCode:
    value = str(arguments.value)
    print(value.upper() if arguments.upper else value, file=stdout)
    return ExitCode.OK


def _run_failing(arguments: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> ExitCode:
    raise TroupeError(
        "lock.timeout",
        problem="timed out waiting for the theatre lock",
        fix="Wait for the other troupe command to finish, then try again.",
        path=str(Path.home() / "theatre" / ".troupe"),
        details={"waitedSeconds": 5.0},
    )


def _run_crashing(arguments: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> ExitCode:
    raise RuntimeError("boom")


def _configure_choose(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--colour", choices=["red", "blue"])
    parser.add_argument("count", nargs="?", type=int)


class _RaisesInArgparse(argparse.Action):
    """Fails only once argparse runs it, which troupe's own checks can't see."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[Any] | None,
        option_string: str | None = None,
    ) -> None:
        raise argparse.ArgumentError(self, "refused by its action")


class _ErrorsInArgparse(argparse.Action):
    """Reports through the parser's ``error`` only once argparse runs it."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[Any] | None,
        option_string: str | None = None,
    ) -> None:
        parser.error("refused by its action")


def _configure_odd(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--raises", action=_RaisesInArgparse)
    parser.add_argument("--errors", action=_ErrorsInArgparse)


def _never_runs(arguments: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> ExitCode:
    raise AssertionError("a test-only command that only tests parsing ran")


ECHO = Command("echo", "Print a value (test only).", _configure_echo, _run_echo)
FAILING = Command("failing", "Fail with a path (test only).", lambda parser: None, _run_failing)
CRASHING = Command("crashing", "Crash (test only).", lambda parser: None, _run_crashing)
CHOOSE = Command("choose", "Take a choice and a count (test only).", _configure_choose, _never_runs)
ODD = Command("odd", "Refuse only inside argparse (test only).", _configure_odd, _never_runs)
TEST_COMMANDS = (ECHO, FAILING, CRASHING, CHOOSE, ODD)


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
    assert "github.com/troupe-run/troupe/issues" in err


@pytest.mark.parametrize(
    "argv",
    [("verison",), ("--bogus",), ("echo", "-5"), ("echo",), ("echo", "x", "y")],
    ids=["unknown-command", "unknown-flag", "dash-value", "missing-argument", "extra-argument"],
)
def test_usage_error_data_matches_the_protocol_schema(argv: tuple[str, ...]) -> None:
    check_error(usage_error(*argv).to_data())


@pytest.mark.parametrize(
    "data",
    [
        {"code": "usage.invalid", "problem": "p", "fix": "f"},
        {"code": "usage.unknown-flag", "problem": "p", "fix": "f",
         "details": {"flag": "--x", "suggestion": None}},
    ],
    ids=["usage.invalid", "usage.unknown-flag"],
)  # fmt: skip
def test_usage_error_data_without_its_command_does_not_match_the_protocol_schema(
    data: dict[str, object],
) -> None:
    with pytest.raises(jsonschema.ValidationError):
        check_error(data)


def test_internal_and_command_error_data_matches_the_protocol_schema() -> None:
    with pytest.raises(TroupeError) as caught:
        _run_failing(argparse.Namespace(), io.StringIO(), io.StringIO())
    check_error(caught.value.to_data())
    internal = TroupeError("internal.unexpected", problem="p", fix="f")
    check_error(internal.to_data())


# Requirement: Usage errors and unknown commands


def test_unknown_subcommand_near_a_global_flag_suggests_the_flag() -> None:
    code, out, err = run_cli("verison", commands=())
    assert code == ExitCode.USAGE
    assert out == ""
    assert "`verison` is not a troupe command" in err
    assert "Did you mean `--version`?" in err


def test_unknown_subcommand_near_a_command_suggests_the_command() -> None:
    assert "Did you mean `echo`?" in run_cli("ecoh", "x")[2]


def test_an_empty_argument_as_the_command_is_an_unknown_command_naming_it_empty() -> None:
    error = usage_error("", "echo")
    check_error(error.to_data())
    assert error.problem == "An empty argument is not a troupe command."
    assert error.details == {"command": "", "suggestion": None}


@pytest.mark.parametrize("argv", [("--",), ("--", "echo", "x"), ("--version", "--", "echo")])
def test_a_separator_before_any_command_is_refused_as_an_unknown_command(
    argv: tuple[str, ...],
) -> None:
    error = usage_error(*argv)
    check_error(error.to_data())
    assert error.code == "usage.unknown-command"
    assert error.problem == "`--` comes before any command."
    assert error.details == {"command": "--", "suggestion": None}


def test_unknown_subcommand_with_no_near_match_points_at_help() -> None:
    error = usage_error("zzzzzz")
    assert error.code == "usage.unknown-command"
    assert "troupe --help" in error.fix


def test_unknown_flag_is_a_usage_error_that_names_the_flag() -> None:
    code, out, err = run_cli("echo", "x", "--bogus")
    assert code == ExitCode.USAGE
    assert out == ""
    assert "`--bogus` is not an option of `troupe echo`" in err


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


# Requirement: A usage problem carries no surface prefix

# One command line per usage shape, through troupe's real commands.
USAGE_SHAPES = {
    "unknown-command": ("nosuchthing",),
    "unknown-flag": ("status", "--bogus"),
    "dash-value": ("logs", "-5"),
    "missing-argument": ("perform", "tester", "--no-effect-check"),
    "missing-one-of": ("perform", "tester", "--runner", "scripted"),
    "conflicting-options": (
        "perform", "tester", "--runner", "scripted", "--expect", "out.txt", "--no-effect-check",
    ),
    "extra-argument": ("status", "one", "two"),
    "missing-value": ("status", "--limit"),
    "invalid-value": ("status", "--limit", "notanumber"),
}  # fmt: skip


def test_a_command_s_usage_error_prints_the_troupe_prefix_once() -> None:
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(["perform", "tester", "--runner", "scripted"], stdout=stdout, stderr=stderr)
    first_line = stderr.getvalue().splitlines()[0]
    assert code == ExitCode.USAGE
    assert first_line.startswith("troupe: ")
    assert "troupe: troupe:" not in first_line


@pytest.mark.parametrize("argv", USAGE_SHAPES.values(), ids=USAGE_SHAPES.keys())
def test_no_usage_problem_starts_with_the_troupe_prefix(argv: tuple[str, ...]) -> None:
    error = usage_error(*argv, commands=COMMANDS)
    assert not error.problem.startswith("troupe:")


def refused(*argv: str) -> TroupeError:
    """The usage error troupe's real commands give for ``argv``, after checking that running it
    exits 2, prints nothing on stdout, renders exactly that error and matches the schema."""
    error = usage_error(*argv, commands=COMMANDS)
    check_error(error.to_data())
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=stdout, stderr=stderr)
    assert (code, stdout.getvalue()) == (ExitCode.USAGE, "")
    assert stderr.getvalue() == render_error(error) + "\n"
    return error


# Requirement: A usage error names the command it concerns and points at its help


def test_a_command_s_usage_error_names_the_command_and_points_at_its_help() -> None:
    error = refused("logs")
    assert "`troupe logs`" in error.problem
    assert error.fix == "Run `troupe logs --help` to see its options."


def test_an_error_before_any_command_points_at_the_root_help() -> None:
    assert refused("nosuchthing").fix == HELP_FIX


def test_unknown_flag_after_a_command_names_the_command_and_points_at_its_help() -> None:
    error = refused("status", "--bogus")
    assert error.code == "usage.unknown-flag"
    assert error.problem == "`--bogus` is not an option of `troupe status`."
    assert error.fix.startswith("Run `troupe status --help` to see its options. ")
    assert error.details == {"flag": "--bogus", "suggestion": None, "command": "status"}


def test_unknown_flag_before_any_command_has_no_command_and_points_at_the_root_help() -> None:
    error = refused("--bogus")
    assert error.problem == "`--bogus` is not a troupe option."
    assert error.fix.startswith(HELP_FIX)
    assert error.details == {"flag": "--bogus", "suggestion": None, "command": None}


# Requirement: Each usage shape has its own code


def test_a_missing_required_option_is_a_missing_argument_naming_it() -> None:
    error = refused("perform", "tester", "--no-effect-check")
    assert error.code == "usage.missing-argument"
    assert error.problem == "`troupe perform` needs --runner."
    assert error.fix == "Run `troupe perform --help` to see its options."
    assert error.details == {"command": "perform", "argument": "--runner"}


def test_a_missing_required_positional_is_a_missing_argument_naming_it() -> None:
    error = refused("logs")
    assert error.code == "usage.missing-argument"
    assert error.problem == "`troupe logs` needs <run>."
    assert error.details == {"command": "logs", "argument": "run"}


def test_missing_arguments_are_reported_in_declaration_order() -> None:
    error = refused("perform")
    assert error.details == {"command": "perform", "argument": "--runner"}
    assert refused("perform", "--runner", "scripted", "--no-effect-check").details == {
        "command": "perform",
        "argument": "actor",
    }


def test_a_required_group_with_none_given_is_a_missing_one_of_in_the_issue_s_words() -> None:
    error = refused("perform", "tester", "--runner", "scripted")
    assert error.code == "usage.missing-one-of"
    assert error.details == {"command": "perform", "options": ["--expect", "--no-effect-check"]}
    assert render_error(error) == (
        "troupe: `troupe perform` needs one of --expect or --no-effect-check.\n"
        "  fix: Run `troupe perform --help` to see its options."
    )


def test_two_options_of_an_exclusive_group_are_conflicting_options_naming_both() -> None:
    error = refused(
        "perform", "tester", "--runner", "scripted", "--expect", "out.txt", "--no-effect-check"
    )
    assert error.code == "usage.conflicting-options"
    assert error.problem == "`troupe perform` takes --expect or --no-effect-check, not both."
    assert error.details == {"command": "perform", "options": ["--expect", "--no-effect-check"]}


def test_a_repeatable_option_given_twice_is_not_a_conflict() -> None:
    parsed = parse(
        ["perform", "tester", "--runner", "scripted", "--expect", "a.txt", "--expect", "b.txt"],
        COMMANDS,
    )
    assert parsed.arguments.expect == ["a.txt", "b.txt"]


@pytest.mark.parametrize(
    ("argv", "command", "value"),
    [
        (("status", "one", "two"), "status", "two"),
        (("logs", "abc", "def"), "logs", "def"),
        (("status", "--", "-5", "-6"), "status", "-6"),
    ],
    ids=["status", "logs", "after-separator"],
)
def test_too_many_positional_values_is_an_extra_argument_naming_the_first_extra(
    argv: tuple[str, ...], command: str, value: str
) -> None:
    error = refused(*argv)
    assert error.code == "usage.extra-argument"
    assert error.problem == f"`troupe {command}` got an extra value, `{value}`."
    assert error.details == {"command": command, "value": value}


@pytest.mark.parametrize(
    ("argv", "option"),
    [
        (("status", "--limit"), "--limit"),
        (("status", "--limit", "--json"), "--limit"),
        (("status", "--limit", "--"), "--limit"),
        (("perform", "tester", "--runner"), "--runner"),
    ],
    ids=["last", "before-a-flag", "before-the-separator", "perform"],
)
def test_an_option_with_no_value_is_a_missing_value_naming_it(
    argv: tuple[str, ...], option: str
) -> None:
    error = refused(*argv)
    assert error.code == "usage.missing-value"
    assert error.problem == f"`troupe {argv[0]}` needs a value after {option}."
    assert f"`{option}=<value>`" in error.fix
    assert error.details == {"command": argv[0], "option": option}


def test_a_dash_leading_option_value_still_reaches_argparse_as_a_value() -> None:
    assert parse(["status", "--limit", "-5"], COMMANDS).arguments.limit == -5


def test_a_dash_leading_option_value_with_a_space_is_still_taken_as_the_value() -> None:
    argv = ["perform", "tester", "--runner", "scripted", "--no-effect-check"]
    parsed = parse([*argv, "--instructions", "--dry-run first"], COMMANDS)
    assert parsed.arguments.instructions == "--dry-run first"


def test_a_value_its_type_rejects_is_an_invalid_value_naming_it() -> None:
    error = refused("status", "--limit", "notanumber")
    assert error.code == "usage.invalid-value"
    assert error.problem == "`troupe status` can't use `notanumber` for --limit."
    assert error.fix == "Run `troupe status --help` to see what --limit takes."
    assert error.details == {"command": "status", "argument": "--limit", "value": "notanumber"}


def test_a_value_outside_its_choices_is_an_invalid_value() -> None:
    error = usage_error("choose", "--colour", "green")
    check_error(error.to_data())
    assert error.code == "usage.invalid-value"
    assert error.details == {"command": "choose", "argument": "--colour", "value": "green"}


def test_a_typed_positional_value_its_type_rejects_is_an_invalid_value() -> None:
    error = usage_error("choose", "--colour", "red", "many")
    assert error.code == "usage.invalid-value"
    assert error.details == {"command": "choose", "argument": "<count>", "value": "many"}


def test_what_was_typed_wrong_is_reported_before_what_is_missing() -> None:
    error = refused("perform", "tester", "extra", "--no-effect-check")
    assert error.code == "usage.extra-argument"
    assert error.details == {"command": "perform", "value": "extra"}


def test_help_still_answers_a_line_with_an_option_missing_its_value() -> None:
    parsed = parse(["status", "--limit", "--help"], COMMANDS)
    assert parsed.command is None
    assert "--limit" in parsed.help_text


# Requirement: An unanticipated usage problem is still reported as structured data


@pytest.mark.parametrize("flag", ["--raises", "--errors"])
def test_a_refusal_only_argparse_makes_is_usage_invalid_naming_the_command(flag: str) -> None:
    code, out, err = run_cli("odd", flag, "x")
    error = usage_error("odd", flag, "x")
    check_error(error.to_data())
    assert (code, out) == (ExitCode.USAGE, "")
    assert error.code == "usage.invalid"
    assert error.problem.startswith("`troupe odd`: ")
    assert "refused by its action" in error.problem
    assert error.fix == "Run `troupe odd --help` to see its options."
    assert error.details == {"command": "odd"}
    assert err.count("troupe:") == 1


# What troupe reads from argparse (design D4)


def _declared_for(command: Command) -> _Declared:
    parser = argparse.ArgumentParser(prog=f"troupe {command.name}", add_help=False)
    command.configure(parser)
    return _declared(parser)


def _shape(declared: _Declared) -> dict[str, object]:
    return {
        "options": [(o.name, o.takes_value, o.required, o.convert) for o in declared.options],
        "positionals": [(p.dest, p.name, p.least, p.most) for p in declared.positionals],
        "groups": [(g.dests, g.required) for g in declared.groups],
    }


def test_declared_reads_perform_status_and_logs_as_they_declare_their_arguments() -> None:
    by_name = {command.name: _shape(_declared_for(command)) for command in COMMANDS}
    assert by_name == {
        "perform": {
            "options": [
                ("--runner", True, True, None),
                ("--runner-options", True, False, None),
                ("--instructions", True, False, None),
                ("--expect", True, False, None),
                ("--no-effect-check", False, False, None),
            ],
            "positionals": [("actor", "<actor>", 1, 1)],
            "groups": [(("expect", "no_effect_check"), True)],
        },
        "status": {
            "options": [("--limit", True, False, int), ("--json", False, False, None)],
            "positionals": [("run", "<run>", 0, 1)],
            "groups": [],
        },
        "logs": {
            "options": [("--follow", False, False, None), ("--json", False, False, None)],
            "positionals": [("run", "<run>", 1, 1)],
            "groups": [],
        },
    }


@pytest.mark.parametrize(
    "declare",
    [
        lambda parser: parser.add_argument("--many", nargs="+"),
        lambda parser: parser.add_argument("rest", nargs=argparse.REMAINDER),
        lambda parser: parser.add_argument("--file", type=argparse.FileType("r")),
    ],
    ids=["option-nargs", "remainder", "file-type"],
)
def test_declared_refuses_an_argument_the_checks_cannot_read(
    declare: Callable[[argparse.ArgumentParser], object],
) -> None:
    parser = argparse.ArgumentParser(prog="troupe odd", add_help=False)
    declare(parser)
    with pytest.raises(TroupeError) as caught:
        _declared(parser)
    assert caught.value.code == "internal.unexpected"
    assert "`troupe odd`" in caught.value.problem


# Property: troupe's checks and argparse agree (design: Risks)

# Commands whose every refusal troupe's own checks should make: the real ones, and test ones with
# choices, a typed positional and a required positional. ODD is left out: it refuses inside
# argparse on purpose, to reach the backstop.
CHECKED = (*COMMANDS, ECHO, CHOOSE)
VALUES = [
    *("x", "5", "-5", "red", "green", "", "--", "-", "--bogus", "-q"),
    *("--limit=x", "a=b", "--dry-run first", "-x y"),
]


@st.composite
def command_lines(draw: st.DrawFn) -> list[str]:
    command = draw(st.sampled_from(CHECKED))
    parser = argparse.ArgumentParser(add_help=False)
    command.configure(parser)
    flags = [*sorted(_declared(parser).strings), "--help", "--version"]
    tokens = draw(st.lists(st.sampled_from(flags + VALUES), max_size=8))
    # Half the time the command comes first; otherwise flags and values may come before it.
    first = draw(st.booleans())
    at = 0 if first else draw(st.integers(min_value=0, max_value=len(tokens)))
    return [*tokens[:at], command.name, *tokens[at:]]


@settings(max_examples=500, deadline=None)
@given(command_lines())
def test_every_refusal_is_a_named_usage_shape_with_no_prefix(argv: list[str]) -> None:
    refusal: TroupeError | None = None
    try:
        parsed = parse(argv, CHECKED)
    except TroupeError as error:
        refusal = error
    if refusal is None:
        assert isinstance(parsed.arguments, argparse.Namespace)
        return
    assert refusal.code.startswith("usage."), (argv, refusal)
    assert refusal.code != "usage.invalid", f"argparse refused {argv} after the checks: {refusal}"
    assert refusal.exit_code is ExitCode.USAGE
    assert not refusal.problem.startswith("troupe:")
    check_error(refusal.to_data())
