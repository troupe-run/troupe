"""The flows config kind: its rules, its file, and how renames treat it (spec: flows, config-files,
config-renames; actor-sequences design D1)."""

from typing import Any

import pytest

from troupe.core.config.changes import Rename, apply, change, value_hash
from troupe.core.config.kinds import check, file_kind, flow_file, problems
from troupe.core.config.moves import files_of, refuse_move
from troupe.core.config.projection import render, render_flow
from troupe.core.errors import TroupeError

OPTIONS: dict[str, Any] = {"script": {"steps": [{"exit": 0}]}}
WRITER: dict[str, Any] = {
    "runner": "scripted",
    "options": OPTIONS,
    "expect": [],
    "workspace": "worktree",
}
REVIEWER: dict[str, Any] = {"runner": "scripted", "options": OPTIONS, "expect": []}


def config(*steps: dict[str, Any], **actors: dict[str, Any]) -> dict[str, Any]:
    return {
        "actors": actors or {"writer": WRITER, "reviewer": REVIEWER},
        "flows": {"review": {"steps": list(steps)}},
    }


# Requirement: A flow is a config kind of its own


def test_a_flow_of_known_worktree_actors_is_valid() -> None:
    check(config({"actor": "writer"}, {"actor": "reviewer", "direction": "review it"}))


def test_a_flow_naming_the_same_actor_twice_is_valid() -> None:
    check(config({"actor": "writer"}, {"actor": "reviewer"}, {"actor": "writer"}))


def test_a_steps_approvers_follow_an_actors_rules() -> None:
    check(config({"actor": "writer", "approvers": ["director"]}))
    found = problems(config({"actor": "writer", "approvers": ["troupe"]}))
    assert [p.path for p in found] == [("flows", "review", "steps")]
    assert "step 1 (writer)'s approvers" in found[0].rule


# Requirement: A flow's steps must be performable


def test_a_step_naming_a_missing_actor_is_refused_naming_flow_step_and_rule() -> None:
    with pytest.raises(TroupeError) as caught:
        check(config({"actor": "writer"}, {"actor": "nobody"}))
    assert caught.value.code == "config.invalid"
    assert caught.value.details["path"] == ["flows", "review", "steps"]
    assert "step 2 (nobody) names an actor config doesn't have" in caught.value.problem


def test_removing_an_actor_a_flow_uses_leaves_config_invalid_naming_the_flow() -> None:
    whole = config({"actor": "writer"})
    del whole["actors"]["writer"]
    [found] = problems(whole)
    assert found.path == ("flows", "review", "steps")
    assert found.related == (("actors", "writer"),)


def test_a_step_whose_actor_works_in_the_theatre_is_refused() -> None:
    found = problems(
        config({"actor": "writer"}, writer={**WRITER, "workspace": "theatre"}, reviewer=REVIEWER)
    )
    assert [p.path for p in found] == [("flows", "review", "steps")]
    assert "works in the theatre" in found[0].rule
    assert found[0].related == (("actors", "writer", "workspace"),)


def test_an_empty_step_list_is_refused() -> None:
    found = problems(config())
    assert [p.path[:2] for p in found] == [("flows", "review")]


# Requirement: Flows and actors share one namespace


def test_a_flow_named_like_an_actor_is_refused_naming_both() -> None:
    whole = config({"actor": "writer"})
    whole["flows"] = {"writer": whole["flows"]["review"]}
    [found] = problems(whole)
    assert found.path == ("flows", "writer")
    assert found.related == (("actors", "writer"),)
    assert "an actor is named 'writer' too" in found.rule


# Requirement: Each flow is projected to its own file


def test_a_flow_is_written_to_its_own_file_with_its_steps_in_order() -> None:
    whole = config({"actor": "writer"}, {"actor": "reviewer", "direction": "review it"})
    files = render(whole)
    text = files[flow_file("review")].decode()
    assert text.startswith("# yaml-language-server: $schema=")
    assert "config/flow.schema.json" in text
    assert text.index("actor: writer") < text.index("actor: reviewer")
    assert "direction: review it" in text
    assert files[flow_file("review")] == render_flow(whole["flows"]["review"])


def test_a_flows_file_is_recognised_as_a_flow_file() -> None:
    kind = file_kind("flows/review.yaml")
    assert kind is not None
    assert kind.kind == "flows"
    assert files_of("flows", "review") == ("flows/review.yaml",)


# Requirement: Only a whole actor, runtime or flow can be renamed; An actor's rename carries the
# flows that name it


def test_a_flow_can_be_renamed() -> None:
    whole = config({"actor": "writer"})
    refuse_move(whole, ("flows", "check"), ("flows", "review"))
    after = apply(whole, change(whole, [(("flows", "check"), Rename(("flows", "review")))]))
    assert after["flows"] == {"check": {"steps": [{"actor": "writer"}]}}


def test_a_value_path_is_not_a_renameable_entity_naming_flows() -> None:
    with pytest.raises(TroupeError) as caught:
        refuse_move(config(), ("flows", "review", "x"), ("flows", "review", "steps"))
    assert caught.value.code == "config.move-not-entity"
    assert "flows.<name>" in caught.value.problem


def test_an_actors_rename_sets_every_flow_step_that_names_it() -> None:
    steps = [{"actor": "writer"}, {"actor": "reviewer"}, {"actor": "writer", "direction": "d"}]
    whole = config(*steps)
    entries = change(whole, [(("actors", "author"), Rename(("actors", "writer")))])
    renamed = [{"actor": "author"}, {"actor": "reviewer"}, {"actor": "author", "direction": "d"}]
    assert {
        "path": ["flows", "review", "steps"],
        "before": value_hash(steps),
        "after": renamed,
    } in (entries)
    after = apply(whole, entries)
    assert after["flows"]["review"]["steps"] == renamed
    check(after)
