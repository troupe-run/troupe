"""Config is checked before a change is recorded, naming the path and the rule (spec: config;
config-model design D6)."""

import json
from dataclasses import replace
from typing import Any

import jsonschema
import pytest

from protocol_schemas import check_error
from troupe.core import defaults, interim
from troupe.core.config.kinds import check, problems
from troupe.core.errors import TroupeError

CANARY = "q7ZxW9pL4vR2canary"
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


OLLAMA: dict[str, Any] = {"runner": "ollama", "runtime": "ollama", "model": "qwen3.5:4b"}


def test_an_ollama_actor_with_valid_options_is_accepted() -> None:
    check(_actor(**OLLAMA, options={"contextLength": 32768, "think": False}))


def test_an_option_the_ollama_runner_doesnt_define_is_refused_naming_its_schema() -> None:
    error = _refused(_actor(**OLLAMA, options={"speed": 2}))
    assert error.details["path"] == ["actors", "tester", "options", "speed"]
    assert "the ollama runner's options schema" in error.problem


# Requirement: Options a runner moved to its runtime are refused with the move (spec: runtimes;
# ollama-uses-runtime design D5)


def _old_ollama(options: dict[str, Any], **fields: Any) -> dict[str, Any]:  # noqa: ANN401
    """An ollama actor as the audition wrote it before its options moved to a runtime."""
    return _actor(runner="ollama", options=options, **fields)


def _move(error: TroupeError) -> str:
    """The command a moved-option refusal's fix gives."""
    assert error.fix is not None
    prefix, _, command = error.fix.partition(": ")
    assert prefix.startswith("Move it in one change")
    return command


@pytest.mark.parametrize(
    ("key", "value"), [("model", "qwen3.5:4b"), ("endpoint", "http://gpu-box.local:11434")]
)
def test_an_ollama_actors_endpoint_or_model_in_its_options_is_refused_naming_it(
    key: str, value: str
) -> None:
    error = _refused(_actor(**OLLAMA, options={key: value}))
    assert error.details["path"] == ["actors", "tester", "options", key]
    assert f"{key} moved to the actor's runtime" in error.problem


def test_the_model_the_audition_used_to_write_is_refused_with_the_set_that_moves_it() -> None:
    error = _refused(_old_ollama({"model": "qwen3:4b"}))
    assert error.details["path"] == ["actors", "tester", "options", "model"]
    assert "moved to the actor's runtime" in error.problem
    assert "more)" not in error.problem  # one rule: no schema or missing-runtime problem too
    assert _move(error) == (
        "troupe config set actors.tester.runtime=ollama actors.tester.model=qwen3:4b "
        "'actors.tester.options={}'"
    )


def test_the_moves_other_options_are_kept() -> None:
    error = _refused(_old_ollama({"model": "qwen3:4b", "maxTurns": 20}))
    assert _move(error).endswith(""" 'actors.tester.options={"maxTurns":20}'""")


def test_the_built_in_endpoint_moves_to_the_ollama_runtime_defining_none() -> None:
    error = _refused(_old_ollama({"model": "m", "endpoint": "http://127.0.0.1:11434/"}))
    assert error.details["path"] == ["actors", "tester", "options", "endpoint"]
    assert "actors.tester.runtime=ollama" in _move(error)
    assert "runtimes." not in _move(error)


def test_an_endpoint_on_another_host_needs_a_runtime_whose_name_the_person_chooses() -> None:
    error = _refused(_old_ollama({"model": "m", "endpoint": "http://gpu-box.local:11434"}))
    command = _move(error)
    assert "'runtimes.<name>.endpoint=http://gpu-box.local:11434'" in command
    assert "'actors.tester.runtime=<name>'" in command
    assert "runtimes.ollama" not in command
    assert "choosing a <name>" in str(error.fix)


def test_the_actors_own_runtime_and_model_are_kept() -> None:
    error = _refused(_old_ollama({"model": "old"}, runtime="ollama", model="new"))
    command = _move(error)
    assert "actors.tester.runtime=ollama" in command
    assert "actors.tester.model=new" in command
    assert "old" not in command


def test_an_endpoint_elsewhere_isnt_lost_when_the_actor_already_names_a_runtime() -> None:
    # Found by a review of PR #322: the fix kept the actor's runtime and dropped the endpoint.
    error = _refused(
        _old_ollama({"model": "m", "endpoint": "http://gpu-box:11434"}, runtime="ollama")
    )
    command = _move(error)
    assert "'runtimes.<name>.endpoint=http://gpu-box:11434'" in command
    assert "'actors.tester.runtime=<name>'" in command


def test_a_runtime_the_actor_names_that_doesnt_exist_isnt_kept_in_the_fix() -> None:
    # Found by a review of PR #322: the fix kept runtime=gpu, which config then refused.
    error = _refused(_old_ollama({"model": "m"}, runtime="gpu"))
    assert "actors.tester.runtime=ollama" in _move(error)
    assert "gpu" not in _move(error)


@pytest.mark.parametrize("model", [5, {"a": 1}, ""])
def test_a_model_that_isnt_text_is_left_out_of_the_fix(model: object) -> None:
    error = _refused(_old_ollama({"model": model}))
    assert "actors.tester.model=" not in _move(error)


def test_an_ollama_endpoint_holding_a_password_is_refused_without_repeating_it() -> None:
    error = _refused(_old_ollama({"endpoint": "http://user:secret@127.0.0.1:11434"}))
    assert error.details["path"] == ["actors", "tester", "options", "endpoint"]
    assert "secret" not in f"{error.problem} {error.fix} {error.details}"
    assert "runtimes.<name>.endpoint=<url>" in str(error.fix)


def test_a_moved_option_refuses_a_change_to_another_actor_with_the_same_fix() -> None:
    config = _old_ollama({"model": "qwen3:4b"})
    config["actors"]["other"] = dict(TESTER)
    error = _refused(config)
    assert error.details["path"] == ["actors", "tester", "options", "model"]
    assert "actors.tester.model=qwen3:4b" in _move(error)


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


def test_an_absolute_pattern_is_refused_naming_the_list_its_position_and_scratch() -> None:
    error = _refused(_actor(expect=[], effects={"write": ["out/**", "/tmp/**"]}))  # noqa: S108
    assert error.details["path"] == ["actors", "tester", "effects", "write"]
    assert "actors.tester.effects.write: item 2 is absolute" in error.problem
    assert "relative to the workspace" in error.problem
    assert "scratch directory" in error.problem
    assert error.fix == "Change or remove item 2 of actors.tester.effects.write."
    assert "/tmp" not in json.dumps([error.problem, error.fix, error.details])  # noqa: S108


@pytest.mark.parametrize(
    "pattern",
    [
        f"https://user:{CANARY}@example.com/v1",  # a ':'
        f"/{CANARY}",  # absolute
        f"{CANARY}/../x",  # '..'
        f"{CANARY}//x",  # an empty part
        f"a{CANARY}**",  # '**' inside a part
        f"{CANARY}\x01",  # a control character
        f".git/{CANARY}",  # git's own
    ],
)
def test_a_refused_effect_pattern_is_never_repeated(pattern: str) -> None:
    error = _refused(_actor(expect=[], effects={"write": [pattern]}))
    assert error.details["path"] == ["actors", "tester", "effects", "write"]
    assert "item 1 " in error.problem
    message = json.dumps([error.problem, error.fix, error.details])
    assert CANARY not in message
    assert "example.com" not in message


def test_a_pattern_into_troupes_own_directory_is_refused_saying_no_effect_allows_it() -> None:
    error = _refused(_actor(expect=[], effects={"write": [".troupe/**"]}))
    assert "'.troupe'" in error.problem
    assert "no effect can allow changing it" in error.problem


# Requirement: Every expected file is covered by the declaration (spec: effects)


def test_expecting_a_file_the_actor_cant_write_is_refused_naming_its_position_and_the_fix() -> None:
    error = _refused(_actor(effects=...))
    assert error.details["path"] == ["actors", "tester", "expect"]
    assert "actors.tester.expect: expect's item 1 isn't covered by a write or move effect" in (
        error.problem
    )
    assert error.fix == (
        "Declare a pattern that covers it, in place of the placeholder: troupe config set "
        "actors.tester.effects.write='[\"<a pattern covering item 1 of actors.tester.expect>\"]'"
    )
    assert "hello" not in json.dumps([error.problem, error.fix, error.details])


def test_the_fix_keeps_what_write_already_declares_and_adds_a_placeholder() -> None:
    error = _refused(_actor(effects={"write": ["src/**"]}))
    assert error.fix.endswith(
        'actors.tester.effects.write=\'["src/**", '
        '"<a pattern covering item 1 of actors.tester.expect>"]\''
    )


def test_an_uncovered_expect_path_holding_a_password_is_never_repeated() -> None:
    # A theatre path's shape check lets a URL through, so the path is never named (review of #384).
    url = f"https://user:{CANARY}@example.com/x"
    error = _refused(_actor(expect=["out/hello.txt", url], effects={"write": ["out/**"]}))
    assert "expect's item 2 isn't covered" in error.problem
    assert CANARY not in json.dumps([error.problem, error.fix, error.details])


def test_expecting_a_file_inside_a_declared_pattern_is_valid() -> None:
    check(_actor(expect=["out/hello.txt"], effects={"write": ["out/**"]}))


def test_expecting_a_file_a_move_creates_is_valid() -> None:
    check(_actor(expect=["docs/a.md"], effects={"move": ["docs/**"]}))


def test_expecting_a_file_only_delete_covers_is_refused() -> None:
    error = _refused(_actor(expect=["docs/a.md"], effects={"delete": ["docs/**"]}))
    assert "expect's item 1 isn't covered" in error.problem


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
    assert "lm-studio, mistralrs, ollama, openai" in error.problem


def test_a_runtime_that_doesnt_exist_is_refused_naming_those_that_do() -> None:
    error = _refused(_with({"myhost": MYHOST}, runtime="nowhere"))
    assert error.details["path"] == ["actors", "tester", "runtime"]
    assert "(there are: anthropic, lm-studio, mistralrs, myhost, ollama, openai)" in error.problem


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
    assert interim.RUNNERS["ollama"].runtime == "required"
    assert interim.RUNNERS["openai"].runtime == "required"
    assert interim.RUNNERS["scripted"].runtime == "optional"


def test_an_ollama_actor_without_a_runtime_is_refused_naming_only_the_runtimes_that_fit() -> None:
    # Spec: runtimes, "An Ollama actor without a runtime".
    error = _refused(_actor(runner="ollama", options={}))
    assert error.details["path"] == ["actors", "tester", "runtime"]
    assert "the ollama runner needs a runtime" in error.problem
    assert "(these fit it: ollama)" in error.problem
    assert "Set actors.tester.runtime to one of: ollama." in error.fix
    for unfit in ("lm-studio", "openai"):  # lm-studio has ollama's shape, but is LM Studio's
        assert unfit not in error.problem + error.fix


def test_an_anthropic_actor_without_a_runtime_is_refused_naming_its_runtime_path() -> None:
    # Task 13.1: the anthropic runner needs a runtime (runtime="required").
    error = _refused(_actor(runner="anthropic", options={}))
    assert error.details["path"] == ["actors", "tester", "runtime"]
    assert "the anthropic runner needs a runtime" in error.problem
    assert "anthropic" in error.fix


def test_an_anthropic_actor_on_a_local_engines_runtime_of_your_own_is_accepted() -> None:
    # Spec: anthropic-runner, "A local engine through a runtime of your own".
    config = _with(
        {"lm-studio-messages": {"endpoint": "http://127.0.0.1:1234"}},
        runner="anthropic",
        options={},
        runtime="lm-studio-messages",
        model="google/gemma-4-e4b",
    )
    assert problems(config) == []


def test_an_in_process_actor_on_a_served_runtime_is_refused_listing_mistralrs() -> None:
    # Spec: runtimes, "An actor's runtime fits its runner": "An in-process actor on a served
    # runtime".
    error = _refused(_actor(runner="mistralrs", options={}, runtime="ollama"))
    assert error.details["path"] == ["actors", "tester", "runtime"]
    assert "the mistralrs runner runs its model in its own process" in error.problem
    assert "one that fits: mistralrs" in error.fix


def test_a_served_actor_on_the_in_process_runtime_is_refused_listing_ollama() -> None:
    # Spec: runtimes, "An actor's runtime fits its runner": "A served actor on the in-process
    # runtime".
    error = _refused(_actor(runner="ollama", options={}, runtime="mistralrs"))
    assert error.details["path"] == ["actors", "tester", "runtime"]
    assert (
        "the ollama runner needs an endpoint, and the runtime 'mistralrs' has none" in error.problem
    )
    assert "one that fits: ollama" in error.fix


def test_an_in_process_actors_fix_names_the_built_in_never_a_runtime_to_define() -> None:
    # A runtime config defines always has an endpoint, so it could never fit (design D5).
    unfit = _refused(_actor(runner="mistralrs", options={}, runtime="ollama"))
    assert "define" not in unfit.fix.lower()
    unknown = _refused(_actor(runner="mistralrs", options={}, runtime="nope"))
    assert "Set it to one of: mistralrs." in unknown.fix
    assert "endpoint" not in unknown.fix
    broken = _refused(
        {
            "runtimes": {"mistralrs": {"credential": {"env": "FOO"}}},
            "actors": {"tester": {**TESTER, "runner": "mistralrs", "options": {}}},
        }
    )
    assert "Only troupe's built-in 'mistralrs' can fit" in broken.fix
    assert "runtimes.mistralrs" in broken.fix


def test_a_mistralrs_actor_on_the_in_process_runtime_is_valid() -> None:
    check(_actor(runner="mistralrs", options={}, runtime="mistralrs"))


def test_an_actor_naming_a_runtime_that_doesnt_exist_is_told_only_those_that_fit() -> None:
    error = _refused(_actor(runner="ollama", options={}, runtime="nowhere"))
    assert "no runtime named 'nowhere'" in error.problem
    assert "(there are, that fit the ollama runner: ollama)" in error.problem
    for unfit in ("lm-studio", "openai"):
        assert unfit not in error.problem + error.fix


def test_when_no_runtime_fits_the_error_says_so_and_how_to_define_one() -> None:
    # Spec: runtimes, "No runtime fits".
    config = _with({"ollama": {"credential": {"env": "MY_KEY"}}}, runner="ollama", options={})
    error = _refused(config)
    assert error.details["path"] == ["actors", "tester", "runtime"]
    assert "no runtime there is fits the ollama runner" in error.problem
    assert "troupe config set runtimes.<name>.endpoint=<url>" in error.fix
    assert "no path" in error.fix
    assert "no credential" in error.fix


# Requirement: An actor's runtime fits its runner


DEFINED = {
    "lm-studio-openai": {"endpoint": "http://127.0.0.1:1234/v1"},
    "remote-lm": {"endpoint": "https://lm.example.com"},
}
"""Runtimes defined in config for the fit cases no built-in shows: LM Studio's OpenAI-compatible
base, with a path, and an https endpoint with none."""


@pytest.mark.parametrize(
    ("runner", "runtime", "says", "fits"),
    [
        pytest.param(
            "ollama",
            "openai",
            "the ollama runner sends no credential, and the runtime 'openai' has one",
            "ollama, remote-lm",
            id="ollama on a runtime with a credential",
        ),
        pytest.param(
            "ollama",
            "lm-studio-openai",
            "the ollama runner needs an endpoint with no path, and the runtime 'lm-studio-openai' "
            "has one with a path",
            "ollama, remote-lm",
            id="ollama on an endpoint with a path",
        ),
        pytest.param(
            "openai",
            "ollama",
            "the openai runner needs an endpoint with a path, such as /v1, and the runtime "
            "'ollama' has one without",
            "lm-studio-openai, openai",
            id="openai on an endpoint with no path",
        ),
        pytest.param(
            "lm-studio",
            "remote-lm",
            "the lm-studio runner can only reach a plain http endpoint, and the runtime "
            "'remote-lm' has an https one",
            "lm-studio",
            id="lm-studio on an https endpoint",
        ),
        pytest.param(
            "lm-studio",
            "openai",
            "the lm-studio runner sends no credential, and the runtime 'openai' has one",
            "lm-studio",
            id="lm-studio on a runtime with a credential",
        ),
        pytest.param(
            "ollama",
            "lm-studio",
            "the runtime 'lm-studio' is troupe's built-in for the lm-studio runner, and the ollama "
            "runner can't use it",
            "ollama, remote-lm",
            id="ollama on lm-studio's built-in, though its shape fits",
        ),
        pytest.param(
            "lm-studio",
            "ollama",
            "the runtime 'ollama' is troupe's built-in for the ollama runner, and the lm-studio "
            "runner can't use it",
            "lm-studio",
            id="lm-studio on ollama's built-in, though its shape fits",
        ),
    ],
)
def test_a_runtime_that_doesnt_fit_its_actors_runner_is_refused_naming_both_and_what_fits(
    runner: str, runtime: str, says: str, fits: str
) -> None:
    error = _refused(_with(DEFINED, runner=runner, options={}, runtime=runtime))
    assert error.details["path"] == ["actors", "tester", "runtime"]
    assert says in error.problem
    assert f"Set actors.tester.runtime to one that fits: {fits}" in error.fix


def test_an_anthropic_actor_on_an_endpoint_ending_in_v1_is_refused_naming_the_base_to_use() -> None:
    # Spec: runtimes, "An Anthropic actor on an endpoint ending in /v1" (owner, 2026-11-14).
    error = _refused(
        _with(
            {"claude-v1": {"endpoint": "https://api.anthropic.com/v1"}},
            runner="anthropic",
            options={},
            runtime="claude-v1",
        )
    )
    assert error.details["path"] == ["actors", "tester", "runtime"]
    assert (
        "the anthropic runner adds /v1/... below its endpoint itself, and the runtime 'claude-v1' "
        "has an endpoint that already ends in /v1 (use https://api.anthropic.com)" in error.problem
    )
    assert "Set actors.tester.runtime to one that fits: anthropic" in error.fix


def test_an_anthropic_actor_on_a_gateways_own_path_fits() -> None:
    config = _with(
        {"gateway": {"endpoint": "https://gateway.example/anthropic"}},
        runner="anthropic",
        options={},
        runtime="gateway",
    )
    assert problems(config) == []


def test_an_ollama_actor_on_a_runtime_defined_in_config_without_a_path_fits() -> None:
    config = _with(
        {"gpu-box": {"endpoint": "http://10.0.0.5:11434"}},
        runner="ollama",
        options={},
        runtime="gpu-box",
    )
    assert problems(config) == []


@pytest.mark.parametrize("runner", ["ollama", "lm-studio"])
def test_a_runtime_of_your_own_of_the_shared_shape_fits_both_runners(runner: str) -> None:
    # Spec: runtimes, "A runtime of your own of the same shape": troupe can't tell which engine it
    # serves, so it's judged by shape alone, unlike the built-ins.
    config = _with(
        {"gpu-box": {"endpoint": "http://10.0.0.5:1234"}},
        runner=runner,
        options={},
        runtime="gpu-box",
    )
    assert problems(config) == []


def test_a_trailing_slash_alone_isnt_a_path() -> None:
    config = _with(
        {"gpu-box": {"endpoint": "http://10.0.0.5:11434/"}},
        runner="ollama",
        options={},
        runtime="gpu-box",
    )
    assert problems(config) == []


def test_a_change_to_a_runtime_that_makes_its_actor_unfit_is_refused_naming_the_actor() -> None:
    # Spec: runtimes, "A change to the runtime makes its actor unfit": the problem is the actor's,
    # and spans the runtime, so a merge's change to the runtime counts as a change to it.
    config = _with(
        {"ollama": {"credential": {"env": "MY_KEY"}}}, runner="ollama", options={}, runtime="ollama"
    )
    [problem] = problems(config)
    assert problem.path == ("actors", "tester", "runtime")
    assert ("runtimes", "ollama") in problem.related
    assert "sends no credential" in problem.rule


def test_a_runtime_with_problems_of_its_own_is_not_judged_for_fit() -> None:
    config = _with(
        {"gpu-box": {"model": "m"}},  # no endpoint: its own problem
        runner="ollama",
        options={},
        runtime="gpu-box",
    )
    found = problems(config)
    assert [p.path for p in found] == [("runtimes", "gpu-box", "endpoint")]


@pytest.mark.parametrize(
    ("runtimes", "path"),
    [
        pytest.param({"myhost": "https://x.example"}, ["runtimes", "myhost"], id="a value"),
        pytest.param(
            {"openai": {"credential": "MY_KEY"}},
            ["runtimes", "openai", "credential"],
            id="a credential that isn't a group",
        ),
        pytest.param(
            {"myhost": {"endpoint": 7}}, ["runtimes", "myhost", "endpoint"], id="an endpoint number"
        ),
    ],
)
def test_a_malformed_runtime_is_refused_naming_it_with_an_actor_in_config(
    runtimes: dict[str, Any], path: list[str]
) -> None:
    # Fit is judged only for runtimes with no problems of their own, so a shape the schema refuses
    # is config.invalid naming it, never a crash.
    for actor in ({}, {"runner": "ollama", "options": {}, "runtime": "ollama"}):
        error = _refused(_with(runtimes, **actor))
        assert error.details["path"] == path


def test_a_runtime_with_problems_of_its_own_is_never_offered_as_one_that_fits() -> None:
    config = _with({"gpu-box": {"model": "m"}}, runner="ollama", options={})
    found = problems(config)
    [actor] = [p for p in found if p.path == ("actors", "tester", "runtime")]
    assert "gpu-box" not in actor.rule + actor.fix
    assert "(these fit it: ollama)" in actor.rule


@pytest.mark.parametrize("runtime", sorted(defaults.RUNTIMES))
def test_every_runtime_fits_a_runner_that_takes_any(runtime: str) -> None:
    # Spec: runtimes, "Every runtime fits a runner that takes any".
    assert problems(_actor(runtime=runtime, model="m")) == []


def test_an_ollama_actor_on_the_ollama_runtime_with_a_model_is_valid() -> None:
    assert problems(_actor(runner="ollama", options={}, runtime="ollama", model="qwen3:4b")) == []


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


# A rule refused for its shape never repeats the value (spec: config, "A refused config value is
# repeated nowhere"; config-set-json-redacts design D4).
LONG_CANARY = CANARY * 4
"""Long enough to break any length rule, and a string the canary is a part of."""


@pytest.mark.parametrize(
    ("schema", "instance", "words"),
    [
        ({"enum": ["worktree", "theatre"]}, CANARY, "it must be one of 'worktree', 'theatre'"),
        ({"const": "result"}, CANARY, "it must be 'result'"),
        ({"minLength": 100}, CANARY, "it must be at least 100 characters"),
        ({"maxLength": 4}, CANARY, "it must be at most 4 characters"),
        ({"pattern": "^[a-z]+$"}, CANARY, "it must match the pattern ^[a-z]+$"),
        (
            {"not": {"required": ["a", "b"]}},
            {"a": CANARY, "b": 1},
            "it can't have a and b together",
        ),
        ({"oneOf": [{"type": "integer"}, {"type": "boolean"}]}, CANARY, "it doesn't fit any shape"),
        ({"anyOf": [{"type": "integer"}, {"type": "boolean"}]}, CANARY, "it doesn't fit any shape"),
        ({"uniqueItems": True}, [CANARY, CANARY], "its items must all differ"),
        ({"minItems": 3}, [CANARY], "it must hold at least 3 items"),
        ({"maxItems": 1}, [CANARY, CANARY + "2"], "it must hold at most 1 item"),
        ({"minProperties": 2}, {"a": CANARY}, "it must hold at least 2 fields"),
        ({"maxProperties": 1}, {"a": CANARY, "b": CANARY}, "it must hold at most 1 field"),
        ({"minimum": 10**30}, 10**20 + 7, "it must be at least"),
        ({"exclusiveMinimum": 10**30}, 10**20 + 7, "it must be more than"),
        ({"maximum": 1}, 10**20 + 7, "it must be at most 1"),
        ({"exclusiveMaximum": 1}, 10**20 + 7, "it must be less than 1"),
        (
            {"dependentRequired": {"price": ["model"]}},
            {"price": CANARY},
            "some fields need others with them: price needs model",
        ),
        ({"type": "integer"}, CANARY, "it must be a whole number, not a string"),
    ],
    ids=lambda value: next(iter(value)) if isinstance(value, dict) else None,
)
def test_each_rule_is_put_in_words_that_never_hold_the_value(
    schema: dict[str, Any], instance: object, words: str
) -> None:
    from troupe.core.config.kinds import WORDED, _rule

    [error] = jsonschema.Draft202012Validator(schema).iter_errors(instance)
    assert error.validator in WORDED
    rule = _rule(error, "the actor schema")
    assert rule.startswith(words)
    assert rule.endswith("(the actor schema)")
    assert CANARY not in rule
    assert "100000000000000000007" not in rule  # a number given is a value too


def test_a_rule_with_a_description_gives_the_description_not_the_value() -> None:
    from troupe.core.config.kinds import _rule

    schema = {"pattern": "^[a-z]+$", "description": "lowercase letters"}
    [error] = jsonschema.Draft202012Validator(schema).iter_errors(CANARY)
    assert _rule(error, "the actor schema") == "it doesn't fit the actor schema: lowercase letters"


def test_a_rule_with_no_words_says_which_rule_and_never_the_value() -> None:
    from troupe.core.config.kinds import _rule

    [error] = jsonschema.Draft202012Validator({"multipleOf": 7}).iter_errors(10**20 + 3)
    assert _rule(error, "the actor schema") == (
        "it breaks the schema's multipleOf rule (the actor schema)"
    )


def test_an_option_refused_by_its_runners_schema_never_repeats_the_value() -> None:
    error = _refused(
        {
            "actors": {
                "tester": {
                    **TESTER,
                    "options": {"script": {"steps": [{"exit": CANARY}]}},
                }
            }
        }
    )
    assert error.details["path"][:3] == ["actors", "tester", "options"]
    assert CANARY not in json.dumps([error.problem, error.fix, error.details])


# Every rule the config and options schemas use has words (design D4).

HANDLED_BEFORE = frozenset({"additionalProperties", "required"})
"""Refused by _schema_problems before _rule, naming fields, never values."""
APPLICATORS = frozenset(
    {
        "$ref",
        "$dynamicRef",
        "properties",
        "patternProperties",
        "items",
        "prefixItems",
        "allOf",
        "if",
        "then",
        "else",
        "propertyNames",
        "dependentSchemas",
        "contains",
    }
)
"""Keywords whose errors are their subschemas', each with a validator of its own."""
NOT_KEYWORDS = frozenset({"const", "enum", "default", "examples", "description", "title"})


def _keywords(contents: object, resolver: Any, seen: set[int], found: set[str]) -> None:  # noqa: ANN401
    if isinstance(contents, list):
        for item in contents:
            _keywords(item, resolver, seen, found)
        return
    if not isinstance(contents, dict) or id(contents) in seen:
        return
    seen.add(id(contents))
    for key, value in contents.items():
        if key in jsonschema.Draft202012Validator.VALIDATORS:
            found.add(key)
        if key == "$ref":
            resolved = resolver.lookup(value)
            _keywords(resolved.contents, resolved.resolver, seen, found)
        elif key in ("properties", "patternProperties", "$defs", "dependentSchemas"):
            for sub in value.values() if isinstance(value, dict) else ():
                _keywords(sub, resolver, seen, found)
        elif key not in NOT_KEYWORDS:
            _keywords(value, resolver, seen, found)


def _keywords_used() -> set[str]:
    from troupe.cli.values import ACTOR_SCHEMA, RUNTIME_SCHEMA
    from troupe.core import schemas

    found: set[str] = set()
    registry = schemas.registry()
    for uri in (ACTOR_SCHEMA, RUNTIME_SCHEMA):
        _keywords(registry.contents(uri), registry.resolver(uri), set(), found)
    for runner in sorted(interim.RUNNERS):
        if not interim.installed(runner):
            continue
        options = interim.options_schema(runner)
        own = schemas.registry(interim.runner(runner).package)
        _keywords(options, own.resolver(options["$id"]), set(), found)
    return found


def _unworded(worded: frozenset[str]) -> set[str]:
    return _keywords_used() - worded - HANDLED_BEFORE - APPLICATORS


def test_every_rule_the_config_and_options_schemas_use_has_words() -> None:
    from troupe.core.config.kinds import WORDED

    assert _unworded(WORDED) == set()


def test_a_rule_with_no_words_would_fail_that_check() -> None:
    from troupe.core.config.kinds import WORDED

    assert "pattern" in _keywords_used()
    assert _unworded(WORDED - {"pattern"}) == {"pattern"}


# A key from inside a value is part of the value (design D7; review of #384).


def _refused_typed(config: dict[str, Any], typed: set[tuple[str, ...]] | None) -> TroupeError:
    with pytest.raises(TroupeError) as caught:
        check(config, typed=typed)
    check_error(caught.value.to_data())
    return caught.value


def test_a_key_set_inside_a_value_is_never_named() -> None:
    config = {"actors": {"tester": {**TESTER, CANARY: 1}}}
    error = _refused_typed(config, {("actors", "tester")})
    assert error.details["path"] == ["actors", "tester"]
    assert "it holds 1 field the actor schema doesn't define" in error.problem
    assert CANARY not in json.dumps([error.problem, error.fix, error.details])


def test_a_key_typed_as_a_path_is_named() -> None:
    config = {"actors": {"tester": {**TESTER, "runnr": "scripted"}}}
    error = _refused_typed(config, {("actors", "tester", "runnr")})
    assert error.details["path"] == ["actors", "tester", "runnr"]
    assert "there's no such field" in error.problem


def test_with_nothing_typed_a_key_is_named_as_before() -> None:
    # A merge or a perform checks config no one just typed: what it holds is named.
    error = _refused_typed({"actors": {"tester": {**TESTER, "runnr": "scripted"}}}, None)
    assert error.details["path"] == ["actors", "tester", "runnr"]


@pytest.mark.parametrize(
    ("kind", "body"), [("runtimes", {"endpoint": "https://e.org"}), ("actors", TESTER)]
)
def test_a_name_set_inside_a_value_that_isnt_one_is_never_named(
    kind: str, body: dict[str, Any]
) -> None:
    name = f"https://user:{CANARY}@example.com"
    error = _refused_typed({kind: {name: body}}, {(kind,)})
    assert error.details["path"] == [kind]
    assert "whose name isn't one" in error.problem
    assert CANARY not in json.dumps([error.problem, error.fix, error.details])


# A key of a map from inside a value is part of the value (design D7; review of #384).


def test_a_rule_broken_under_a_map_key_from_a_value_never_names_the_key() -> None:
    url = f"https://user:{CANARY}@example.com"
    config = {
        "runtimes": {
            "box": {
                "endpoint": "https://llm.example/v1",
                "prices": {url: {"input": "x", "output": 1}},
            }
        }
    }
    error = _refused_typed(config, {("runtimes", "box", "prices")})
    assert error.details["path"] == ["runtimes", "box", "prices"]
    assert "input in one of its entries: it must be a number" in error.problem
    assert CANARY not in json.dumps([error.problem, error.fix, error.details])


def test_a_field_missing_or_extra_under_a_map_key_from_a_value_never_names_the_key() -> None:
    url = f"https://user:{CANARY}@example.com"
    for entry, says in (({"input": 1}, "it needs"), ({"input": 1, "output": 1, "x": 1}, "a field")):
        config = {
            "runtimes": {"box": {"endpoint": "https://llm.example/v1", "prices": {url: entry}}}
        }
        error = _refused_typed(config, {("runtimes", "box", "prices")})
        assert error.details["path"] == ["runtimes", "box", "prices"]
        assert says in error.problem
        assert CANARY not in json.dumps([error.problem, error.fix, error.details])


def test_a_map_key_typed_as_a_path_is_named() -> None:
    config = {
        "runtimes": {
            "box": {
                "endpoint": "https://llm.example/v1",
                "prices": {"m": {"input": "x", "output": 1}},
            }
        }
    }
    error = _refused_typed(config, {("runtimes", "box", "prices", "m", "input")})
    assert error.details["path"] == ["runtimes", "box", "prices", "m", "input"]
