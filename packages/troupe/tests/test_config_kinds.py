"""Config is checked before a change is recorded, naming the path and the rule (spec: config;
config-model design D6)."""

from typing import Any

import pytest

from protocol_schemas import check_error
from troupe.core.config.kinds import check, problems
from troupe.core.errors import TroupeError

SCRIPT = {"script": {"steps": [{"exit": 0}]}}
TESTER: dict[str, Any] = {"runner": "scripted", "options": SCRIPT, "expect": ["out/hello.txt"]}


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


def test_an_actor_without_an_effect_check_is_refused_saying_an_empty_list_means_none() -> None:
    error = _refused(_actor(expect=...))
    assert error.details["path"] == ["actors", "tester", "expect"]
    assert "[] means no effect check" in error.problem
    assert "[] means no effect check" in error.fix


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
