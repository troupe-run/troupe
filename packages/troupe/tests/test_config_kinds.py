"""Config is checked before a change is recorded, naming the path and the rule (spec: config;
config-model design D6)."""

from dataclasses import replace
from typing import Any

import pytest

from protocol_schemas import check_error
from troupe.core import interim
from troupe.core.config.kinds import check, problems
from troupe.core.errors import TroupeError

SCRIPT = {"script": {"steps": [{"exit": 0}]}}
TESTER: dict[str, Any] = {
    "runner": "scripted",
    "options": SCRIPT,
    "expect": ["out/hello.txt"],
    "effects": {"write": ["out/**"]},
}


def _actor(**changes: object) -> dict[str, Any]:
    actor = dict(TESTER)
    for key, value in changes.items():
        if value is ...:
            actor.pop(key, None)
        else:
            actor[key] = value
    return {"actors": {"tester": actor}}


def _refused(config: dict[str, Any]) -> TroupeError:
    with pytest.raises(TroupeError) as caught:
        check(config)
    assert caught.value.code == "config.invalid"
    check_error(caught.value.to_data())
    return caught.value


# Requirement: Values are checked before a change is recorded


def test_an_actor_with_its_runner_options_and_effect_check_is_valid() -> None:
    assert problems(_actor()) == []
    check(_actor(character="You are the tester."))


def test_a_misspelt_field_is_refused_naming_it_and_saying_theres_no_such_field() -> None:
    error = _refused(_actor(runnr="scripted"))
    assert error.details["path"] == ["actors", "tester", "runnr"]
    assert "no such field" in error.problem
    assert "actors.tester.runnr" in error.fix


def test_an_option_the_runner_doesnt_define_is_refused_naming_the_runners_schema() -> None:
    error = _refused(_actor(options={**SCRIPT, "speed": 2}))
    assert error.details["path"] == ["actors", "tester", "options", "speed"]
    assert "the scripted runner's options schema" in error.problem


def test_a_claude_code_actor_with_valid_options_is_accepted() -> None:
    options = {
        "permissionMode": "plan",
        "allowedTools": ["Bash(git status)"],
        "maxBudgetUsd": 2,
    }
    check(_actor(runner="claude-code", options=options))


def test_a_claude_code_actor_that_accepts_edits_is_refused_when_its_set() -> None:
    # What Claude Code may change comes from the actor's effects (declared-effects design D8).
    error = _refused(_actor(runner="claude-code", options={"permissionMode": "acceptEdits"}))
    assert error.details["path"] == ["actors", "tester", "options", "permissionMode"]
    assert "the claude-code runner's options schema" in error.problem


def test_an_option_the_claude_code_runner_doesnt_define_is_refused_naming_its_schema() -> None:
    error = _refused(_actor(runner="claude-code", options={"speed": 2}))
    assert error.details["path"] == ["actors", "tester", "options", "speed"]
    assert "the claude-code runner's options schema" in error.problem


def test_a_claude_code_option_of_the_wrong_shape_is_refused_naming_its_path() -> None:
    error = _refused(_actor(runner="claude-code", options={"permissionMode": "yolo"}))
    assert error.details["path"] == ["actors", "tester", "options", "permissionMode"]


def test_an_ollama_actor_with_valid_options_is_accepted() -> None:
    options = {
        "model": "qwen3.5:4b",
        "endpoint": "http://gpu-box.local:11434",
        "contextLength": 32768,
    }
    check(_actor(runner="ollama", options=options))


def test_an_option_the_ollama_runner_doesnt_define_is_refused_naming_its_schema() -> None:
    error = _refused(_actor(runner="ollama", options={"model": "qwen3.5:4b", "speed": 2}))
    assert error.details["path"] == ["actors", "tester", "options", "speed"]
    assert "the ollama runner's options schema" in error.problem


def test_an_ollama_actor_without_a_model_is_refused_naming_model_as_required() -> None:
    error = _refused(_actor(runner="ollama", options={}))
    assert error.details["path"] == ["actors", "tester", "options", "model"]
    assert "required" in error.problem


def test_an_ollama_endpoint_holding_a_password_is_refused_without_repeating_it() -> None:
    options = {"model": "m", "endpoint": "http://user:secret@127.0.0.1:11434"}
    error = _refused(_actor(runner="ollama", options=options))
    assert error.details["path"] == ["actors", "tester", "options", "endpoint"]
    assert "secret" not in f"{error.problem} {error.fix} {error.details}"


def test_an_actor_without_an_effect_check_is_refused_saying_an_empty_list_means_none() -> None:
    error = _refused(_actor(expect=...))
    assert error.details["path"] == ["actors", "tester", "expect"]
    assert "[] means no file has to change" in error.problem
    assert "[] means no file has to change" in error.fix


def test_an_effect_check_path_outside_the_theatre_is_refused_naming_it() -> None:
    error = _refused(_actor(expect=["../elsewhere.txt"]))
    assert error.details["path"][:3] == ["actors", "tester", "expect"]
    assert "leaves the theatre" in error.problem


def test_an_actor_name_that_doesnt_fit_is_refused_naming_the_name_and_the_pattern() -> None:
    error = _refused({"actors": {"Tester": TESTER}})
    assert error.details["path"] == ["actors", "Tester"]
    assert "'Tester' isn't an actor name" in error.problem
    assert "lowercase letters, digits and -" in error.problem


def test_a_runner_set_to_a_group_is_refused_saying_it_must_be_a_string() -> None:
    error = _refused(_actor(runner={"name": "scripted"}))
    assert error.details["path"] == ["actors", "tester", "runner"]
    assert "must be a string, not a group" in error.problem


def test_a_runner_troupe_doesnt_know_is_refused_naming_the_ones_it_does() -> None:
    error = _refused(_actor(runner="claude"))
    assert "doesn't know a runner named 'claude'" in error.problem
    assert "scripted" in error.fix


def test_a_kind_config_doesnt_have_is_refused_naming_the_kinds() -> None:
    error = _refused({"roles": {"owner": "ada"}})
    assert error.details["path"] == ["roles"]
    assert "the kinds are: actors" in error.problem


def test_a_character_that_isnt_text_is_refused() -> None:
    error = _refused(_actor(character=["You are", "the tester"]))
    assert error.details["path"] == ["actors", "tester", "character"]


def test_the_schema_key_is_troupes_to_write_never_set() -> None:
    error = _refused(_actor(**{"$schema": "https://example.com/mine.json"}))
    assert error.details["path"] == ["actors", "tester", "$schema"]
    assert "written by troupe" in error.problem


def test_scripted_options_that_are_missing_are_refused_by_the_runners_schema() -> None:
    error = _refused(_actor(options=...))
    assert error.details["path"] == ["actors", "tester", "options"]
    assert "a script, inline or as a path" in error.problem


def test_every_problem_is_listed_and_the_refusal_says_how_many_more() -> None:
    config = _actor(runnr="x", expect=...)
    assert [problem.path for problem in problems(config)] == [
        ("actors", "tester", "expect"),
        ("actors", "tester", "runnr"),
    ]
    assert "(1 more)" in _refused(config).problem


# Requirement: An actor declares its effects as three lists of patterns (spec: effects)


def test_an_actor_declaring_each_effect_is_valid() -> None:
    check(_actor(effects={"write": ["out/**"], "delete": ["drafts/*"], "move": ["docs/**"]}))


def test_an_effect_the_schema_doesnt_define_is_refused_naming_it() -> None:
    error = _refused(_actor(effects={"write": ["out/**"], "network": ["example.com"]}))
    assert error.details["path"] == ["actors", "tester", "effects", "network"]


# Requirement: A pattern that can't be meant is refused (spec: effects)


def test_an_absolute_pattern_is_refused_naming_the_list_the_pattern_and_scratch() -> None:
    error = _refused(_actor(expect=[], effects={"write": ["/tmp/**"]}))  # noqa: S108
    assert error.details["path"] == ["actors", "tester", "effects", "write"]
    assert "actors.tester.effects.write: '/tmp/**' is absolute" in error.problem
    assert "relative to the workspace" in error.problem
    assert "scratch directory" in error.problem


def test_a_pattern_into_troupes_own_directory_is_refused_saying_no_effect_allows_it() -> None:
    error = _refused(_actor(expect=[], effects={"write": [".troupe/**"]}))
    assert "'.troupe'" in error.problem
    assert "no effect can allow changing it" in error.problem


# Requirement: Every expected file is covered by the declaration (spec: effects)


def test_expecting_a_file_the_actor_cant_write_is_refused_naming_it_and_the_fix() -> None:
    error = _refused(_actor(effects=...))
    assert error.details["path"] == ["actors", "tester", "expect", "0"]
    assert "'out/hello.txt' is expected" in error.problem
    assert (
        error.fix
        == "Declare it: troupe config set actors.tester.effects.write='[\"out/hello.txt\"]'"
    )


def test_the_fix_adds_the_expected_file_to_what_write_already_declares() -> None:
    error = _refused(_actor(effects={"write": ["src/**"]}))
    assert error.fix.endswith('actors.tester.effects.write=\'["src/**", "out/hello.txt"]\'')


def test_expecting_a_file_inside_a_declared_pattern_is_valid() -> None:
    check(_actor(expect=["out/hello.txt"], effects={"write": ["out/**"]}))


def test_expecting_a_file_a_move_creates_is_valid() -> None:
    check(_actor(expect=["docs/a.md"], effects={"move": ["docs/**"]}))


def test_expecting_a_file_only_delete_covers_is_refused() -> None:
    error = _refused(_actor(expect=["docs/a.md"], effects={"delete": ["docs/**"]}))
    assert "'docs/a.md' is expected" in error.problem


def test_expecting_nothing_needs_no_effect() -> None:
    check(_actor(expect=[], effects=...))


# Requirement: Config's kinds are actors and runtimes (spec: config); and spec: runtimes

MYHOST = {"endpoint": "https://llm.example/v1", "model": "llama", "credential": {"env": "K"}}


def _with(runtimes: dict[str, Any], **changes: object) -> dict[str, Any]:
    return {**_actor(**changes), "runtimes": runtimes}


def test_a_kind_that_doesnt_exist_is_refused_naming_both_kinds() -> None:
    error = _refused({**_actor(), "services": {"openai": {"endpoint": "https://x.example"}}})
    assert error.details["path"] == ["services"]
    assert "the kinds are: actors, runtimes" in error.problem


def test_an_actor_on_a_runtime_in_config_is_valid() -> None:
    assert problems(_with({"myhost": MYHOST}, runtime="myhost", model="llama3.2")) == []


def test_an_actor_on_a_built_in_runtime_needs_no_runtime_config() -> None:
    assert problems(_actor(runtime="ollama", model="llama3.2")) == []


def test_removing_a_runtime_an_actor_uses_is_refused_naming_the_actors_runtime() -> None:
    error = _refused(_actor(runtime="myhost"))
    assert error.details["path"] == ["actors", "tester", "runtime"]
    assert "no runtime named 'myhost'" in error.problem
    assert "lm-studio, ollama, openai" in error.problem


def test_a_runtime_that_doesnt_exist_is_refused_naming_those_that_do() -> None:
    error = _refused(_with({"myhost": MYHOST}, runtime="nowhere"))
    assert error.details["path"] == ["actors", "tester", "runtime"]
    assert "(there are: lm-studio, myhost, ollama, openai)" in error.problem


def test_a_runner_that_takes_no_runtime_is_refused() -> None:
    error = _refused(_actor(runner="claude-code", options={}, runtime="openai"))
    assert error.details["path"] == ["actors", "tester", "runtime"]
    assert "the claude-code runner takes no runtime" in error.problem


def test_a_model_without_a_runtime_is_refused_naming_the_runtime() -> None:
    error = _refused(_actor(model="gpt-test"))
    assert error.details["path"] == ["actors", "tester", "runtime"]


def test_a_runner_that_needs_a_runtime_is_refused_without_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scripted = interim.RUNNERS["scripted"]
    monkeypatch.setitem(interim.RUNNERS, "scripted", replace(scripted, runtime="required"))
    error = _refused(_actor())
    assert error.details["path"] == ["actors", "tester", "runtime"]
    assert "the scripted runner needs a runtime" in error.problem


def test_what_each_runner_takes() -> None:
    assert interim.RUNNERS["claude-code"].runtime == "none"
    assert interim.RUNNERS["ollama"].runtime == "none"  # its endpoint and model are options for now
    assert interim.RUNNERS["scripted"].runtime == "optional"


# Requirement: A runtime is a named service with an endpoint, a model and a credential reference


def test_a_credential_by_reference_is_valid() -> None:
    assert problems({"runtimes": {"openai": {"credential": {"env": "MY_OPENAI_KEY"}}}}) == []


@pytest.mark.parametrize(
    ("runtime", "path", "words"),
    [
        pytest.param(
            {"myhost": {"endpoint": "https://user:secret@example.com/v1"}},
            ["runtimes", "myhost", "endpoint"],
            "no user info, query, fragment",
            id="user info",
        ),
        pytest.param(
            {"openai": {"credential": {"env": "MY KEY"}}},
            ["runtimes", "openai", "credential", "env"],
            "Letters, digits and _",
            id="a variable name that isn't one",
        ),
        pytest.param(
            {"myhost": {"model": "llama"}},
            ["runtimes", "myhost", "endpoint"],
            "required for a runtime that isn't one of troupe's built-in ones",
            id="a new runtime without an endpoint",
        ),
        pytest.param(
            {"MyHost": MYHOST},
            ["runtimes", "MyHost"],
            "isn't a runtime name",
            id="a name that doesn't fit",
        ),
        pytest.param(
            {"myhost": "https://llm.example"},
            ["runtimes", "myhost"],
            "a runtime is a group of values",
            id="a runtime that's a value",
        ),
    ],
)
def test_a_runtime_that_breaks_a_rule_is_refused_naming_the_path(
    runtime: dict[str, Any], path: list[str], words: str
) -> None:
    error = _refused({"runtimes": runtime})
    assert error.details["path"] == path
    assert words in error.problem


# Requirement: A credential can't name troupe's own variables


def test_troupes_hand_off_variable_is_refused() -> None:
    error = _refused({"runtimes": {"openai": {"credential": {"env": "TROUPE_RUNTIME_CREDENTIAL"}}}})
    assert error.details["path"] == ["runtimes", "openai", "credential", "env"]
    assert "not starting with TROUPE_" in error.problem


def test_a_credentials_value_is_refused_saying_it_holds_only_env() -> None:
    found = problems({"runtimes": {"openai": {"credential": {"value": "sk-x"}}}})
    by_path = {problem.path: problem.rule for problem in found}
    assert "there's no such field" in by_path[("runtimes", "openai", "credential", "value")]
    assert "required" in by_path[("runtimes", "openai", "credential", "env")]
    _refused({"runtimes": {"openai": {"credential": {"value": "sk-x"}}}})
