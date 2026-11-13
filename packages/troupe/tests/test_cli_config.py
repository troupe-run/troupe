"""troupe config set, config unset, config get and flush on the command line (spec: cli, config;
config-model design D10)."""

import io
import json
import shlex
from dataclasses import replace
from pathlib import Path

import jsonschema
import pytest
from ruamel import yaml

from client_schemas import check
from configtesting import on
from gitrepo import Repo
from protocol_schemas import PROTOCOL_BASE, SCHEMAS, SCRIPTED, validator_for
from runtesting import ADA, theatre
from storetesting import git_service
from troupe.cli import COMMANDS, main
from troupe.cli.config import SHOWN
from troupe.cli.parser import parse
from troupe.core import interim
from troupe.core.config import aggregate
from troupe.core.config.projection import file_hash
from troupe.core.errors import CODES, TroupeError
from troupe.core.exit_codes import ExitCode

STEPS = '[{"exit": 0}]'
ACTOR_FILE = validator_for(PROTOCOL_BASE + "config/actor.schema.json", SCRIPTED)


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
        'actors.tester.effects.write=["out/**"]',
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


def test_an_actors_file_holds_every_field_config_sets_in_the_schemas_order(repo: Repo) -> None:
    # Every field of the actor schema: a field added to the schema and not to the file fails here
    # (spec: config-files, "Each actor is projected to its own files").
    code, _, err = _tester(
        "actors.tester.workspace=theatre",
        "actors.tester.onContextFull=compact",
        "actors.tester.runtime=ollama",
        "actors.tester.model=llama3.2",
    )
    assert code == 0, err
    text = (repo.path / ".troupe" / "actors" / "tester.yaml").read_text(encoding="utf-8")
    data = yaml.YAML(typ="safe", pure=True).load(text)
    schema = json.loads((SCHEMAS / "config" / "actor.schema.json").read_text(encoding="utf-8"))
    assert list(data) == list(schema["properties"])
    assert data["effects"] == {"write": ["out/**"]}
    assert data["workspace"] == "theatre"
    assert data["onContextFull"] == "compact"
    assert data["runtime"] == "ollama"
    assert data["model"] == "llama3.2"
    ACTOR_FILE.validate(data)


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


def test_a_file_git_left_conflicted_is_written_by_the_config_set_that_resolves_it(
    repo: Repo,
) -> None:
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
    conflicted = (repo.path / ".troupe" / "actors" / "tester.md").read_bytes()
    code, _, err = cli("config", "set", "actors.tester.character=Both.")
    assert code == 0, err
    assert (repo.path / ".troupe" / "actors" / "tester.md").read_bytes() == b"Both."
    assert file_hash(conflicted) in err
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
    assert "actors.tester.options.replayDelays is true or false, and the value given isn't" in err
    assert "Write true or false" in err
    assert "yes" not in err


def test_a_boolean_option_is_read_by_the_runners_options_schema(repo: Repo) -> None:
    _tester()
    cli("config", "set", "actors.tester.options.replayDelays=true")
    assert _get("actors.tester.options.replayDelays") is True


def test_a_value_with_no_single_type_needs_json(repo: Repo) -> None:
    _tester()
    code, _, err = cli("config", "set", "actors.tester.options.nope=xylophone")
    assert code == 1
    assert "doesn't give actors.tester.options.nope one type" in err
    assert "--json" in err
    assert "xylophone" not in err


def test_json_reads_a_value_whatever_the_schema_says(repo: Repo) -> None:
    _tester()
    code, _, _ = cli("config", "set", "--json", 'actors.tester.character="quoted"')
    assert code == 0
    assert _get("actors.tester.character") == "quoted"


CANARY = "q7ZxW9pL4vR2canary"
WITH_PASSWORD = f"https://user:{CANARY}@example.com/v1"


def _refused_value(*argv: str) -> TroupeError:
    """The error ``config set`` refused ``argv`` with, through the CLI's own reading of values."""
    from troupe.cli.config import _assignments
    from troupe.cli.values import value_of

    as_json = "--json" in argv
    [(path, text)] = _assignments([a for a in argv if a != "--json"])
    runner = "scripted" if path[:1] == ("actors",) else None
    with pytest.raises(TroupeError) as caught:
        value_of(path, text, runner=runner, as_json=as_json)
    return caught.value


@pytest.mark.parametrize(
    ("argv", "says"),
    [
        pytest.param(
            ("--json", f"runtimes.box.endpoint={WITH_PASSWORD}"),
            "the value for runtimes.box.endpoint isn't JSON: Expecting value (line 1, column 1)",
            id="--json",
        ),
        pytest.param(
            (f"actors.tester.options.replayDelays={CANARY}",),
            "actors.tester.options.replayDelays is true or false",
            id="boolean",
        ),
        pytest.param(
            (f"runtimes.box.prices[m].input={CANARY}",),
            "runtimes.box.prices.m.input is a number, and the value given isn't one",
            id="number",
        ),
        pytest.param(
            (f'actors.tester.expect=["{CANARY}"',),
            "actors.tester.expect is a JSON list, and the value given isn't JSON",
            id="list",
        ),
        pytest.param(
            (f"actors.tester.options.script={WITH_PASSWORD}",),
            "actors.tester.options.script is a JSON group, and the value given isn't JSON",
            id="group",
        ),
        pytest.param(
            (f"actors.tester.options.nope={WITH_PASSWORD}",),
            "doesn't give actors.tester.options.nope one type",
            id="no single type",
        ),
    ],
)
def test_a_value_the_cli_cant_type_is_refused_naming_the_path_never_the_value(
    repo: Repo, argv: tuple[str, ...], says: str
) -> None:
    _tester()
    code, out, err = cli("config", "set", *argv)
    assert code == 1
    assert says in err
    assert CANARY not in out + err
    assert "example.com" not in out + err
    refused = _refused_value(*argv)
    message = json.dumps([refused.problem, refused.fix, refused.details])
    assert CANARY not in message
    assert "example.com" not in message


def test_json_that_isnt_json_gives_the_line_and_column_in_its_details(repo: Repo) -> None:
    refused = _refused_value("--json", 'actors.tester.options.script={\n "a": 1,\n "b" 2}')
    assert refused.details == {
        "path": ["actors", "tester", "options", "script"],
        "rule": "the value for actors.tester.options.script isn't JSON: Expecting ':' delimiter",
        "line": 3,
        "column": 6,
    }
    # Each error is checked against its code's details schema as it's made (protocol_guard); this
    # names the schema the line and column must fit.
    validator_for(PROTOCOL_BASE + "error.schema.json").validate(refused.to_data())


@pytest.mark.parametrize(
    ("name", "content", "says"),
    [
        pytest.param(
            "options.yaml",
            f"script:\n  steps: [1, 2\n  key: {CANARY}\n".encode(),
            "options.yaml isn't YAML troupe can read (line 3, column ",
            id="yaml",
        ),
        pytest.param(
            "options.yaml",
            f"script: 1\nscript: {CANARY}\n".encode(),
            "options.yaml isn't YAML troupe can read (line 2, column 1)",
            id="yaml repeated key",
        ),
        pytest.param(
            "options.json",
            f'{{"script": {{"steps": ["{CANARY}",]}}}}'.encode(),
            # The decoder's words for a trailing comma differ between Python versions.
            "options.json isn't JSON: ",
            id="json",
        ),
    ],
)
def test_a_value_file_that_cant_be_read_names_the_file_and_where_never_its_text(
    repo: Repo, name: str, content: bytes, says: str
) -> None:
    _tester()
    (repo.path / name).write_bytes(content)
    code, out, err = cli("config", "set", f"actors.tester.options=@{name}")
    assert code == 1
    assert says in err
    assert ", column " in err
    assert CANARY not in out + err
    refused = _refused_value(f"actors.tester.options=@{name}")
    assert CANARY not in json.dumps([refused.problem, refused.fix, refused.details])


def test_a_text_file_that_isnt_utf8_says_which_byte_never_its_text(repo: Repo) -> None:
    _tester()
    (repo.path / "character.md").write_bytes(CANARY.encode() + b"\xff")
    code, out, err = cli("config", "set", "actors.tester.character=@character.md")
    assert code == 1
    assert f"character.md isn't UTF-8 text (at byte {len(CANARY) + 1})" in err
    assert CANARY not in out + err


def test_an_assignment_without_a_value_is_refused_saying_how_to_write_one(repo: Repo) -> None:
    code, _, err = cli("config", "set", "actors.tester.runner")
    assert code == 1
    assert "path=value 1 doesn't set anything: a value is written <path>=<value>" in err
    assert "troupe config unset <path>" in err


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


# Requirement: An actor is defined by its runner, options, effect check and character (workspace)


def test_an_actors_workspace_can_be_set_to_theatre(repo: Repo) -> None:
    _tester()
    code, _, err = cli("config", "set", "actors.tester.workspace=theatre")
    assert code == 0, err
    assert _get("actors.tester.workspace") == "theatre"


def test_a_workspace_that_doesnt_exist_is_refused_naming_the_path_and_both_values_not_its_own(
    repo: Repo,
) -> None:
    _tester()
    code, _, err = cli("config", "set", "actors.tester.workspace=sandbox")
    assert code == 1
    assert (
        "actors.tester.workspace: it must be one of 'worktree', 'theatre' (the actor schema)" in err
    )
    assert "sandbox" not in err


# Requirement: An actor says what its runs do when the context fills (compaction-opt-in)


def test_an_actor_can_opt_in_to_compaction(repo: Repo) -> None:
    _tester()
    code, _, err = cli("config", "set", "actors.tester.onContextFull=compact")
    assert code == 0, err
    assert _get("actors.tester.onContextFull") == "compact"
    text = (repo.path / ".troupe" / "actors" / "tester.yaml").read_text(encoding="utf-8")
    assert "onContextFull: compact" in text


def test_an_on_context_full_off_the_list_is_refused_naming_the_path_and_both_values(
    repo: Repo,
) -> None:
    _tester()
    before = (repo.path / ".troupe" / "actors" / "tester.yaml").read_bytes()
    code, _, err = cli("config", "set", "actors.tester.onContextFull=summarise")
    assert code == 1
    assert (
        "actors.tester.onContextFull: it must be one of 'fail', 'compact' (the actor schema)" in err
    )
    assert (repo.path / ".troupe" / "actors" / "tester.yaml").read_bytes() == before


# Requirement: A runtime is a named service... (spec: runtimes), set on the command line


def test_a_credential_by_reference_records_only_the_variables_name(repo: Repo) -> None:
    code, out, err = cli("config", "set", "runtimes.openai.credential.env=MY_OPENAI_KEY")
    assert code == 0, err
    assert "wrote .troupe/runtimes/openai.yaml" in out
    assert _get("runtimes.openai") == {"credential": {"env": "MY_OPENAI_KEY"}}


def test_an_actor_on_a_runtime(repo: Repo) -> None:
    code, _, err = _tester("actors.tester.runtime=ollama", "actors.tester.model=llama3.2")
    assert code == 0, err
    assert _get("actors.tester.runtime") == "ollama"
    assert _get("actors.tester.model") == "llama3.2"


def _record_an_old_ollama_actor(monkeypatch: pytest.MonkeyPatch, options: str) -> None:
    """Record ``lead`` as the Ollama audition did before its options moved to a runtime, under
    the rules of the time: no runtime, and model and endpoint as options."""
    with monkeypatch.context() as then:
        then.setitem(interim.RUNNERS, "ollama", replace(interim.RUNNERS["ollama"], runtime="none"))
        then.setattr(interim, "MOVED_TO_RUNTIME", {})
        then.setattr(interim, "options_validator", lambda name: jsonschema.Draft202012Validator({}))
        code, _, err = cli(
            "config",
            "set",
            "--json",
            'actors.lead.runner="ollama"',
            "actors.lead.expect=[]",
            f"actors.lead.options={options}",
        )
        assert code == 0, err


def test_an_old_ollama_actor_is_moved_by_running_its_refusals_fix_as_given(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Spec: runtimes, "The fix run as given" (ollama-uses-runtime design D5).
    _record_an_old_ollama_actor(monkeypatch, '{"model": "qwen3:4b", "maxTurns": 20}')
    code, _, err = _tester()  # an unrelated change is refused: config would still break the rule
    assert code == 1
    assert "actors.lead.options.model: model moved to the actor's runtime" in err
    fix = err.split("Move it in one change: ", 1)[1].splitlines()[0]
    argv = shlex.split(fix)
    assert argv[:3] == ["troupe", "config", "set"]
    code, _, err = cli(*argv[1:])
    assert code == 0, err
    assert _get("actors.lead.runtime") == "ollama"
    assert _get("actors.lead.model") == "qwen3:4b"
    assert _get("actors.lead.options") == {"maxTurns": 20}
    code, _, err = _tester()
    assert code == 0, err


def test_a_field_a_runtime_doesnt_have_is_refused(repo: Repo) -> None:
    code, _, err = cli("config", "set", "runtimes.openai.credential.value=sk-test")
    assert code == 1
    assert "runtimes.openai.credential" in err


# Requirement: A runtime can price its models (spec: runtimes), set on the command line


def test_pricing_a_model(repo: Repo) -> None:
    code, _, err = cli("config", "set", 'runtimes.openai.prices.gpt-test={"input": 2, "output": 8}')
    assert code == 0, err
    assert _get("runtimes.openai") == {"prices": {"gpt-test": {"input": 2, "output": 8}}}


def test_one_rate_of_a_models_price(repo: Repo) -> None:
    cli("config", "set", 'runtimes.openai.prices.gpt-test={"input": 2, "output": 8}')
    code, _, err = cli("config", "set", "runtimes.openai.prices.gpt-test.cacheRead=0.5")
    assert code == 0, err
    assert _get("runtimes.openai.prices.gpt-test") == {"input": 2, "output": 8, "cacheRead": 0.5}


def test_a_price_with_an_unknown_field_is_refused_naming_the_path_and_the_fields_it_takes(
    repo: Repo,
) -> None:
    # The unknown key is inside the value, so it's part of the value and isn't repeated (design D7).
    code, _, err = cli(
        "config",
        "set",
        'runtimes.openai.prices.gpt-test={"input": 2, "output": 8, "currency": "EUR"}',
    )
    assert code == 1
    assert (
        "runtimes.openai.prices.gpt-test: it holds 1 field the runtime schema doesn't define "
        "(it defines: cacheRead, cacheWrite, input, output)"
    ) in err
    assert "currency" not in err


def test_an_unknown_field_typed_as_a_path_is_named(repo: Repo) -> None:
    code, _, err = cli("config", "set", "--json", 'runtimes.openai.prices.gpt-test.currency="EUR"')
    assert code == 1
    assert "runtimes.openai.prices.gpt-test.currency: there's no such field" in err


def test_a_price_without_an_output_rate_is_refused_naming_the_path(repo: Repo) -> None:
    code, _, err = cli("config", "set", 'runtimes.openai.prices.gpt-test={"input": 2}')
    assert code == 1
    assert "runtimes.openai.prices.gpt-test" in err
    assert "output" in err


def test_a_models_name_with_a_dot_is_priced_by_setting_the_whole_map(repo: Repo) -> None:
    prices = {"gpt-4.1": {"input": 2, "output": 8}}
    code, _, err = cli("config", "set", f"runtimes.openai.prices={json.dumps(prices)}")
    assert code == 0, err
    assert _get("runtimes.openai") == {"prices": prices}


# Requirement: Config get shows a runtime's resolved values and their sources


def test_the_built_in_openai_runtime_resolved(repo: Repo, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-canary-0123456789")
    code, out, err = cli("config", "get", "--resolved", "runtimes.openai")
    assert code == 0, err
    assert out.splitlines() == [
        "runtime openai",
        "  endpoint: https://api.openai.com/v1 (from default)",
        "  model: none (an actor's model, runtimes.openai.model or TROUPE_RUNTIME_OPENAI_MODEL "
        "sets one)",
        "  credential: from OPENAI_API_KEY (named by default), set",
    ]
    assert "sk-test-canary" not in out + err


def test_the_built_in_lm_studio_runtime_resolves_to_lm_studios_server_root(repo: Repo) -> None:
    code, out, err = cli("config", "get", "--resolved", "runtimes.lm-studio")
    assert code == 0, err
    assert "  endpoint: http://127.0.0.1:1234 (from default)" in out.splitlines()


def test_the_built_in_anthropic_runtime_resolves_to_claudes_api_with_its_key_variable(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    code, out, err = cli("config", "get", "--resolved", "runtimes.anthropic")
    assert code == 0, err
    assert out.splitlines() == [
        "runtime anthropic",
        "  endpoint: https://api.anthropic.com (from default)",
        "  model: none (an actor's model, runtimes.anthropic.model or "
        "TROUPE_RUNTIME_ANTHROPIC_MODEL sets one)",
        "  credential: from ANTHROPIC_API_KEY (named by default), not set",
    ]


def test_resolved_as_json_shows_each_value_and_its_source(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("TROUPE_RUNTIME_OLLAMA_MODEL", "qwen3")
    cli("config", "set", "runtimes.openai.model=gpt-test")
    code, out, _ = cli("config", "get", "--resolved", "--json")
    assert code == 0
    result = json.loads(out)
    check(result, "config-get-result.schema.json")
    assert sorted(result["runtimes"]) == ["anthropic", "lm-studio", "ollama", "openai"]
    assert result["runtimes"]["openai"]["model"] == {"value": "gpt-test", "source": "theatre"}
    assert result["runtimes"]["openai"]["credential"]["set"] is False
    assert result["runtimes"]["ollama"]["model"] == {"value": "qwen3", "source": "env"}
    assert result["value"] == {"runtimes": {"openai": {"model": "gpt-test"}}}


def test_the_price_of_the_runtimes_model_resolved(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-canary-0123456789")
    price = {"input": 2, "output": 8, "cacheRead": 0.5, "cacheWrite": 0}
    cli(
        "config",
        "set",
        "runtimes.openai.model=gpt-test",
        f"runtimes.openai.prices.gpt-test={json.dumps(price)}",
    )
    code, out, err = cli("config", "get", "--resolved", "runtimes.openai")
    assert code == 0, err
    assert out.splitlines()[-1] == (
        "  price: US$ per million tokens: input 2, cache read 0.5, cache write 0, output 8 "
        "(from theatre)"
    )
    code, out, _ = cli("config", "get", "--resolved", "--json")
    result = json.loads(out)
    check(result, "config-get-result.schema.json")
    assert result["runtimes"]["openai"]["price"] == {"value": price, "source": "theatre"}


def test_resolved_with_another_path_is_refused_naming_it(repo: Repo) -> None:
    code, _, err = cli("config", "get", "--resolved", "actors.tester")
    assert code == ExitCode.USAGE
    assert "actors.tester has no resolved values: only runtimes do" in err


@pytest.mark.parametrize("as_json", [False, True], ids=["text", "json"])
def test_resolved_with_a_key_where_a_variables_name_should_be_never_shows_the_key(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, as_json: bool
) -> None:
    monkeypatch.setenv("TROUPE_RUNTIME_OPENAI_CREDENTIAL_ENV", "sk-test q7ZxW9pL4vR2")
    flags = ["--json"] if as_json else []
    code, out, err = cli("config", "get", "--resolved", *flags, "runtimes.openai")
    assert code == CODES["runtime.invalid-value"]
    assert "TROUPE_RUNTIME_OPENAI_CREDENTIAL_ENV" in out + err
    assert "q7ZxW9pL4vR2" not in out + err


NAMED = "a3f9c2e17b4d8e05f6a1"


def test_resolved_names_the_variable_that_named_the_credential_not_the_name(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Spec: runtimes, "A credential variable's name from the environment": a key put there by
    # mistake passes for a name, so the name is never shown (#306).
    monkeypatch.setenv("TROUPE_RUNTIME_OPENAI_CREDENTIAL_ENV", NAMED)
    code, out, err = cli("config", "get", "--resolved", "runtimes.openai")
    assert code == 0, err
    assert out.splitlines()[-1] == (
        "  credential: from the variable TROUPE_RUNTIME_OPENAI_CREDENTIAL_ENV names "
        "(named by env), not set"
    )
    assert NAMED not in out + err
    code, out, err = cli("config", "get", "--resolved", "--json", "runtimes.openai")
    assert code == 0, err
    result = json.loads(out)
    check(result, "config-get-result.schema.json")
    assert result["runtimes"]["openai"]["credential"] == {
        "env": {"namedBy": "TROUPE_RUNTIME_OPENAI_CREDENTIAL_ENV", "source": "env"},
        "set": False,
    }
    assert NAMED not in out + err


def test_resolved_says_whether_the_variable_an_environment_name_names_is_set(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TROUPE_RUNTIME_OPENAI_CREDENTIAL_ENV", "MY_OPENAI_KEY")
    monkeypatch.setenv("MY_OPENAI_KEY", "sk-test-canary-0123456789")
    code, out, err = cli("config", "get", "--resolved", "runtimes.openai")
    assert code == 0, err
    assert out.splitlines()[-1].endswith("(named by env), set")
    assert "MY_OPENAI_KEY" not in out


def test_resolved_shows_a_name_from_config_as_it_is(repo: Repo) -> None:
    cli("config", "set", "runtimes.openai.credential.env=MY_OPENAI_KEY")
    code, out, err = cli("config", "get", "--resolved", "runtimes.openai")
    assert code == 0, err
    assert "  credential: from MY_OPENAI_KEY (named by theatre), not set" in out.splitlines()


def test_resolved_for_a_runtime_that_doesnt_exist_is_refused(repo: Repo) -> None:
    code, _, err = cli("config", "get", "--resolved", "runtimes.nowhere")
    assert code == 1
    assert "no runtime named 'nowhere'" in err


# Requirement: A rehearsal shows the run's runtime (spec: runs), on the command line


def test_a_rehearsal_on_the_command_line_shows_the_runtime(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE", "true")
    _tester(
        "actors.tester.runtime=ollama",
        "actors.tester.model=llama3.2",
        "actors.tester.workspace=theatre",
    )
    code, out, err = cli("perform", "tester", "--rehearse")
    assert code == ExitCode.WOULD_CHANGE, err
    assert "  runtime ollama" in out
    assert "    endpoint: http://127.0.0.1:11434 (from default)" in out
    assert "    model: llama3.2 (from actor)" in out
    assert "    credential: none" in out


def test_an_options_value_on_an_uninstalled_runner_is_refused_naming_the_actors_path(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The CLI's value typing doesn't refuse first: core's check does, naming the actor's runner
    path and its extra (spec: config; review of #338)."""
    monkeypatch.setitem(
        interim.RUNNERS, "lm-studio", replace(interim.RUNNERS["scripted"], in_extra=True)
    )
    code, _, err = _tester()
    assert code == 0, err
    code, _, err = cli("config", "set", "actors.tester.runner=lm-studio")
    assert code == 0, err
    gone = replace(interim.RUNNERS["lm-studio"], package="troupe_runner_not_installed")
    monkeypatch.setitem(interim.RUNNERS, "lm-studio", gone)
    before = len(git_service(repo).history(aggregate.STREAM))
    code, _, err = cli("config", "set", "--json", 'actors.tester.options.script={"steps": []}')
    assert code == ExitCode.FAILURE
    assert "actors.tester.runner: " in err
    assert "troupe-run[lm-studio]" in err
    assert len(git_service(repo).history(aggregate.STREAM)) == before
