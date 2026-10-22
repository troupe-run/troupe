"""troupe config set, config unset, config get and flush on the command line (spec: cli, config;
config-model design D10)."""

import io
import json
from pathlib import Path

import pytest

from client_schemas import check
from configtesting import on
from gitrepo import Repo
from runtesting import ADA, theatre
from storetesting import git_service
from troupe.cli import COMMANDS, main
from troupe.cli.config import SHOWN
from troupe.cli.parser import parse
from troupe.core.config import aggregate
from troupe.core.errors import CODES, TroupeError
from troupe.core.exit_codes import ExitCode

STEPS = '[{"exit": 0}]'


def cli(*argv: str) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Repo:
    made = theatre(tmp_path)
    for name, value in {**made.env, **ADA}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.chdir(made.path)
    return made


def _tester(*more: str) -> tuple[int, str, str]:
    return cli(
        "config",
        "set",
        "actors.tester.runner=scripted",
        'actors.tester.expect=["out/hello.txt"]',
        f"actors.tester.options.script.steps={STEPS}",
        *more,
    )


def _get(path: str) -> object:
    code, out, _ = cli("config", "get", path, "--json")
    assert code == 0
    return json.loads(out).get("value")


# Requirement: Config commands


def test_config_set_records_one_change_writes_the_files_and_says_so(repo: Repo) -> None:
    code, out, _ = _tester()
    assert code == 0
    assert "set actors.tester.runner" in out
    assert "wrote .troupe/actors/tester.yaml (for this change)" in out
    assert "recorded change " in out
    assert len(git_service(repo).history(aggregate.STREAM)) == 1
    assert (repo.path / ".troupe" / "actors" / "tester.yaml").is_file()


def test_a_character_from_a_file_is_the_files_text_exactly(repo: Repo) -> None:
    _tester()
    (repo.path / "tester-character.md").write_bytes(b"You are the tester.\r\nTest it.\n")
    code, _, _ = cli("config", "set", "actors.tester.character=@tester-character.md")
    assert code == 0
    assert _get("actors.tester.character") == "You are the tester.\r\nTest it.\n"


def test_a_reason_is_recorded_in_the_changes_lineage(repo: Repo) -> None:
    _tester("--reason", "offline tests")
    [event] = git_service(repo).history(aggregate.STREAM)
    assert event.lineage is not None
    assert event.lineage["reason"] == "offline tests"


def test_config_unset_removes_an_actor_and_its_files(repo: Repo) -> None:
    _tester()
    code, out, _ = cli("config", "unset", "actors.tester")
    assert code == 0
    assert "unset actors.tester" in out
    assert not (repo.path / ".troupe" / "actors").exists()


def test_setting_what_config_already_holds_says_nothing_changed(repo: Repo) -> None:
    _tester()
    code, out, _ = cli("config", "set", "actors.tester.runner=scripted")
    assert code == 0
    assert out == "Nothing changed: config already holds that.\n"


def test_config_get_as_json_is_one_document_in_the_results_shape(repo: Repo) -> None:
    _tester()
    code, out, _ = cli("config", "get", "--json")
    assert code == 0
    check(json.loads(out), "config-get-result.schema.json")


def test_config_get_shows_a_string_value_as_it_is(repo: Repo) -> None:
    _tester()
    code, out, _ = cli("config", "get", "actors.tester.runner")
    assert (code, out) == (0, "scripted\n")


def test_config_get_with_a_conflict_shows_what_each_side_set_it_to(repo: Repo) -> None:
    character = ["actors", "tester", "character"]
    assert _tester()[0] == 0
    repo.commit_all("tester")
    repo.git("branch", "feature")
    on(repo, "feature", [(character, "x" * 100)])
    on(repo, "main", [(character, "You test.")])
    repo.git("merge", "-q", "--no-edit", "feature")
    code, out, _ = cli("config", "get")
    assert code == 0
    assert "conflict at actors.tester.character: these changes set it differently" in out
    assert 'set actors.tester.character to "You test."' in out
    assert f'to "{"x" * (SHOWN - 1)}... (102 characters in all)' in out


def test_a_file_git_left_conflicted_is_refused_with_how_to_take_a_side(repo: Repo) -> None:
    assert _tester()[0] == 0
    repo.commit_all("tester")
    repo.git("branch", "feature")
    for branch, character in (("feature", "One."), ("main", "Two.")):
        repo.git("switch", "-q", branch)
        assert cli("config", "set", f"actors.tester.character={character}")[0] == 0
        repo.commit_all(character)
    with pytest.raises(AssertionError, match="git merge"):
        repo.git("merge", "-q", "--no-edit", "feature")
    unmerged = repo.git("diff", "--name-only", "--diff-filter=U").split()
    assert unmerged == [".troupe/actors/tester.md"]
    code, _, err = cli("config", "set", "actors.tester.character=Both.")
    assert code == CODES["config.file-not-troupes"]
    assert "has git's conflict markers in it" in err
    assert "git checkout --ours .troupe/actors/tester.md" in err
    repo.git("checkout", "--ours", ".troupe/actors/tester.md")
    assert cli("config", "set", "actors.tester.character=Both.")[0] == 0
    assert (repo.path / ".troupe" / "actors" / "tester.md").read_text(encoding="utf-8") == "Both."
    assert cli("flush", "--rehearse")[0] == 0


def test_flush_with_nothing_to_do_says_so(repo: Repo) -> None:
    _tester()
    code, out, _ = cli("flush")
    assert (code, out) == (0, "Nothing to do: the config files are what config says.\n")


def test_flush_writes_a_deleted_file_again_and_says_why(repo: Repo) -> None:
    _tester()
    (repo.path / ".troupe" / "actors" / "tester.yaml").unlink()
    code, out, err = cli("flush")
    assert code == 0
    assert "wrote .troupe/actors/tester.yaml" in out
    assert "wrote it again" in err


# Requirement: Command-line values are typed by the schema


def test_a_number_for_a_string_field_is_the_string(repo: Repo) -> None:
    _tester()
    cli("config", "set", "actors.tester.character=3")
    assert _get("actors.tester.character") == "3"


def test_a_boolean_that_isnt_one_is_refused_naming_the_path(repo: Repo) -> None:
    _tester()
    code, _, err = cli("config", "set", "actors.tester.options.replayDelays=yes")
    assert code == 1
    assert "actors.tester.options.replayDelays is true or false, not 'yes'" in err
    assert "Write true or false" in err


def test_a_boolean_option_is_read_by_the_runners_options_schema(repo: Repo) -> None:
    _tester()
    cli("config", "set", "actors.tester.options.replayDelays=true")
    assert _get("actors.tester.options.replayDelays") is True


def test_a_value_with_no_single_type_needs_json(repo: Repo) -> None:
    _tester()
    code, _, err = cli("config", "set", "actors.tester.options.nope=x")
    assert code == 1
    assert "doesn't give actors.tester.options.nope one type" in err
    assert "--json" in err


def test_json_reads_a_value_whatever_the_schema_says(repo: Repo) -> None:
    _tester()
    code, _, _ = cli("config", "set", "--json", 'actors.tester.character="quoted"')
    assert code == 0
    assert _get("actors.tester.character") == "quoted"


def test_an_assignment_without_a_value_is_refused_saying_how_to_write_one(repo: Repo) -> None:
    code, _, err = cli("config", "set", "actors.tester.runner")
    assert code == 1
    assert "troupe config unset actors.tester.runner" in err


# The config group on the command line


def test_config_alone_needs_one_of_its_commands() -> None:
    with pytest.raises(TroupeError) as caught:
        parse(["config"], COMMANDS)
    assert caught.value.code == "usage.missing-argument"
    assert "set, unset or get" in caught.value.problem


def test_a_misspelt_config_command_suggests_the_closest(repo: Repo) -> None:
    with pytest.raises(TroupeError) as caught:
        parse(["config", "sett", "x=1"], COMMANDS)
    assert caught.value.code == "usage.unknown-command"
    assert caught.value.fix == "Did you mean `troupe config set`?"


def test_a_config_commands_unknown_flag_is_refused_naming_it() -> None:
    with pytest.raises(TroupeError) as caught:
        parse(["config", "get", "--force"], COMMANDS)
    assert caught.value.code == "usage.unknown-flag"


# Requirement: Every command that changes anything can be rehearsed


def test_rehearsing_a_config_change_shows_it_and_records_and_writes_nothing(repo: Repo) -> None:
    code, out, _ = _tester("--rehearse")
    assert code == ExitCode.WOULD_CHANGE
    assert "would set actors.tester.runner" in out
    assert "would write .troupe/actors/tester.yaml" in out
    assert "Rehearsal: nothing was recorded or written." in out
    assert git_service(repo).history(aggregate.STREAM) == []
    assert not (repo.path / ".troupe" / "actors").exists()


def test_rehearsing_an_unset_records_nothing(repo: Repo) -> None:
    _tester()
    code, out, _ = cli("config", "unset", "actors.tester", "--rehearse")
    assert code == ExitCode.WOULD_CHANGE
    assert "would unset actors.tester" in out
    assert len(git_service(repo).history(aggregate.STREAM)) == 1
    assert (repo.path / ".troupe" / "actors" / "tester.yaml").exists()


# Requirement: A rehearsal's exit code says what it found


def test_flush_rehearsed_with_a_file_out_of_date_exits_would_change_naming_it(
    repo: Repo,
) -> None:
    _tester()
    (repo.path / ".troupe" / "actors" / "tester.yaml").unlink()
    code, out, _ = cli("flush", "--rehearse")
    assert code == ExitCode.WOULD_CHANGE
    assert int(ExitCode.WOULD_CHANGE) == 3
    assert "would write .troupe/actors/tester.yaml" in out
    assert not (repo.path / ".troupe" / "actors" / "tester.yaml").exists()


def test_flush_rehearsed_with_files_in_line_exits_0(repo: Repo) -> None:
    _tester()
    assert cli("flush", "--rehearse")[0] == ExitCode.OK


def test_a_rehearsal_that_would_be_refused_exits_with_the_refusals_code(repo: Repo) -> None:
    _tester()
    (repo.path / ".troupe" / "actors" / "tester.yaml").write_text("# mine\n", encoding="utf-8")
    code, _, err = cli("flush", "--rehearse")
    assert code == CODES["config.file-not-troupes"]
    assert ".troupe/actors/tester.yaml" in err


def test_a_rehearsed_change_that_changes_nothing_exits_0(repo: Repo) -> None:
    _tester()
    assert cli("config", "set", "actors.tester.runner=scripted", "--rehearse")[0] == ExitCode.OK
