"""Config across branches: each line's net change, conflicts between whole changes, conflicts from
validation, the block on config, and resolving it (spec: config; config-model design D3, D4)."""

import json
from pathlib import Path
from typing import Any

import pytest

from configtesting import TESTER, branched, config_of, merged_feature, on, other_runner, set_config
from gitrepo import Repo, make_repo
from protocol_schemas import PROTOCOL_BASE, SCRIPTED, check_error, validator_for
from storetesting import git_service, segments
from troupe.core.config import aggregate
from troupe.core.config.changes import UNSET
from troupe.core.config.merge import merge
from troupe.core.config.stream import read, refuse_conflicts
from troupe.core.errors import TroupeError

__all__ = ["other_runner"]  # a fixture, used by name

RECORD = validator_for(PROTOCOL_BASE + "event-record.schema.json", SCRIPTED)

TESTER_PATH = ["actors", "tester"]
CHARACTER = ["actors", "tester", "character"]
EXPECT = ["actors", "tester", "expect"]
BASE: list[tuple[list[str], Any]] = [
    (TESTER_PATH, TESTER),
    (["actors", "reviewer"], {**TESTER, "character": "You review."}),
]


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    repo = make_repo(tmp_path)
    branched(repo, BASE)
    return repo


def _value(merged: Any, path: list[str]) -> object:  # noqa: ANN401
    node = merged.config
    for key in path:
        node = node[key]
    return node


# Requirement: A merge combines each line's net change


def test_two_branches_changing_different_actors_merge_with_no_conflict(repo: Repo) -> None:
    on(repo, "feature", [(["actors", "reviewer", "character"], "Review closely.")])
    on(repo, "main", [(CHARACTER, "Test everything.")])
    merged = merged_feature(repo)
    assert merged.conflicts == ()
    assert len(merged.heads) == 2
    assert _value(merged, ["actors", "reviewer", "character"]) == "Review closely."
    assert _value(merged, CHARACTER) == "Test everything."


def test_a_change_and_a_change_back_on_one_branch_gives_way_to_the_other(repo: Repo) -> None:
    on(repo, "feature", [(CHARACTER, "Try this.")])
    on(repo, "feature", [(CHARACTER, TESTER["character"])])  # and back
    on(repo, "main", [(CHARACTER, "New text.")])
    merged = merged_feature(repo)
    assert merged.conflicts == ()
    assert _value(merged, CHARACTER) == "New text."


def test_two_branches_making_the_same_change_agree(repo: Repo) -> None:
    on(repo, "feature", [(CHARACTER, "Same.")])
    on(repo, "main", [(CHARACTER, "Same.")])
    merged = merged_feature(repo)
    assert merged.conflicts == ()
    assert _value(merged, CHARACTER) == "Same."


def test_merging_in_either_direction_works_out_the_same_config_and_conflicts(repo: Repo) -> None:
    on(repo, "feature", [(CHARACTER, "From feature."), (EXPECT, [])])
    on(repo, "main", [(["actors", "reviewer", "character"], "From main.")])
    on(repo, "main", [(CHARACTER, "Also from main.")])
    on_main = merged_feature(repo)
    repo.git("reset", "-q", "--hard", "HEAD~1")
    repo.git("switch", "-q", "feature")
    repo.git("merge", "-q", "--no-edit", "main")
    on_feature = config_of(repo)
    assert on_feature.config == on_main.config
    assert [c.paths for c in on_feature.conflicts] == [c.paths for c in on_main.conflicts]
    assert {c.change for x in on_main.conflicts for c in x.changes} == {
        c.change for x in on_feature.conflicts for c in x.changes
    }


def test_the_order_events_arrive_in_doesnt_change_the_result(repo: Repo) -> None:
    on(repo, "feature", [(["actors", "reviewer", "character"], "A.")])
    on(repo, "main", [(CHARACTER, "B.")])
    merged_feature(repo)
    history = git_service(repo).history(aggregate.STREAM)
    *common, first, second = history  # the two branches' changes are the last two
    assert merge([*common, first, second]).config == merge([*common, second, first]).config


def test_a_line_whose_first_changes_start_from_different_values_conflicts(repo: Repo) -> None:
    on(repo, "feature", [(CHARACTER, "New.")])
    repo.git("branch", "other", "feature")
    on(repo, "feature", [(CHARACTER, "Other.")])
    on(repo, "other", [(CHARACTER, "Third.")])
    on(repo, "main", [(CHARACTER, UNSET)])
    repo.git("merge", "-q", "--no-edit", "other")
    assert config_of(repo).conflicts != ()  # "Third." from "New." against none from the base's text
    set_config(repo, [(CHARACTER, "New.")])  # settles them, resolving to the new text
    merged = merged_feature(repo)
    assert [c.paths for c in merged.conflicts] == [(tuple(CHARACTER),)]


# Requirement: The history before the lines works out a value no line's change is left at


def _settled_fork(repo: Repo) -> None:
    """``feature`` sets the character to new text, ``main`` to other text and back; main merges
    feature, a change to ``reviewer`` settles the fork, and ``feature`` starts again from there."""
    on(repo, "feature", [(CHARACTER, "New.")])
    on(repo, "main", [(CHARACTER, "Other.")])
    on(repo, "main", [(CHARACTER, TESTER["character"])])  # and back
    merged_feature(repo)
    set_config(repo, [(["actors", "reviewer", "character"], "Settled.")])
    assert _value(config_of(repo), CHARACTER) == "New."
    repo.git("branch", "-f", "feature")


def test_a_conflict_after_a_settle_shows_the_value_the_settle_left(repo: Repo) -> None:
    _settled_fork(repo)
    on(repo, "feature", [(CHARACTER, "X.")])
    on(repo, "main", [(CHARACTER, "Y.")])
    merged = merged_feature(repo)
    assert [c.paths for c in merged.conflicts] == [(tuple(CHARACTER),)]
    assert _value(merged, CHARACTER) == "New."


def test_lines_after_a_settle_that_change_a_value_back_leave_the_value_the_settle_left(
    repo: Repo,
) -> None:
    _settled_fork(repo)
    for branch, text in (("feature", "X."), ("main", "Y.")):
        on(repo, branch, [(CHARACTER, text)])
        on(repo, branch, [(CHARACTER, "New.")])  # and back
    merged = merged_feature(repo)
    assert merged.conflicts == ()
    assert _value(merged, CHARACTER) == "New."


# Requirement: Differing net changes to a value are a conflict between whole changes


def test_a_window_moved_on_one_branch_and_narrowed_on_another_conflict_whole(repo: Repo) -> None:
    on(repo, "feature", [(CHARACTER, "Moved."), (EXPECT, ["out/moved.txt"])])  # one intent
    on(repo, "main", [(CHARACTER, "Narrowed.")])
    merged = merged_feature(repo)
    [conflict] = merged.conflicts
    assert conflict.paths == (tuple(CHARACTER),)
    moved = next(c for c in conflict.changes if any(e["path"] == EXPECT for e in c.entries))
    assert {tuple(e["path"]) for e in moved.entries} == {tuple(CHARACTER), tuple(EXPECT)}
    assert len(conflict.changes) == 2


def test_a_group_removed_on_one_branch_and_changed_on_another_conflict(repo: Repo) -> None:
    on(repo, "feature", [(TESTER_PATH, UNSET)])
    on(repo, "main", [(CHARACTER, "Still here.")])
    merged = merged_feature(repo)
    [conflict] = merged.conflicts
    assert conflict.paths == (tuple(CHARACTER),)


# Requirement: A merged config that fails validation is a conflict


def test_options_that_no_longer_suit_the_runner_are_a_conflict_naming_the_actor(
    repo: Repo, other_runner: str
) -> None:
    on(
        repo,
        "feature",
        [
            (["actors", "tester", "runner"], other_runner),
            (["actors", "tester", "options"], {"model": "opus"}),
        ],
    )
    on(
        repo, "main", [(["actors", "tester", "options", "replayDelays"], True)]
    )  # suits scripted only
    merged = merged_feature(repo)
    [conflict] = merged.conflicts
    assert conflict.paths == (tuple(TESTER_PATH),)
    assert conflict.rule is not None
    assert "the modelled runner's options schema" in conflict.rule
    assert len(conflict.changes) == 2


# Requirement: Any conflict blocks config


def test_a_conflict_on_one_actor_blocks_config_for_every_actor(repo: Repo) -> None:
    on(repo, "feature", [(CHARACTER, "One.")])
    on(repo, "main", [(CHARACTER, "Two.")])
    merged = merged_feature(repo)
    with pytest.raises(TroupeError) as caught:
        refuse_conflicts(merged)  # what perform reviewer does first (task 10.3 checks perform)
    assert caught.value.code == "config.conflict"
    check_error(caught.value.to_data())
    assert "actors.tester.character" in caught.value.problem
    assert "troupe config set" in caught.value.fix
    [listed] = caught.value.details["conflicts"]
    assert listed["paths"] == [CHARACTER]


def test_reading_config_with_a_conflict_still_shows_it_and_records_nothing(repo: Repo) -> None:
    on(repo, "feature", [(CHARACTER, "One.")])
    on(repo, "main", [(CHARACTER, "Two.")])
    repo.git("merge", "-q", "--no-edit", "feature")
    before = sorted((repo.path / ".troupe" / "events").iterdir())
    merged = read(git_service(repo))
    assert merged.conflicts
    assert sorted((repo.path / ".troupe" / "events").iterdir()) == before


# Requirement: A change resolves conflicts by setting every conflicting value


def test_a_change_that_sets_every_conflicting_value_resolves_it_and_records_who(
    repo: Repo,
) -> None:
    on(repo, "feature", [(CHARACTER, "Moved."), (EXPECT, ["out/moved.txt"])])
    on(repo, "main", [(CHARACTER, "Narrowed.")])
    merged_feature(repo)
    set_config(repo, [(CHARACTER, "Both, considered."), (EXPECT, ["out/both.txt"])])
    merged = config_of(repo)
    assert merged.conflicts == ()
    assert len(merged.heads) == 1
    assert _value(merged, CHARACTER) == "Both, considered."
    resolution = merged.changes[-1]
    assert resolution.actor["kind"] == "human"


def test_a_change_that_resolves_nothing_is_refused_naming_what_is_left(repo: Repo) -> None:
    on(repo, "feature", [(CHARACTER, "One.")])
    on(repo, "main", [(CHARACTER, "Two.")])
    merged_feature(repo)
    before = sorted((repo.path / ".troupe" / "events").iterdir())
    with pytest.raises(TroupeError) as caught:
        set_config(repo, [(["actors", "reviewer", "character"], "Unrelated.")])
    assert caught.value.code == "config.conflict"
    assert "actors.tester.character" in caught.value.problem
    assert sorted((repo.path / ".troupe" / "events").iterdir()) == before


# Requirement: Settling a fork is recorded with the next write


def test_the_first_write_after_a_merge_settles_the_fork_and_changes_in_one_batch(
    repo: Repo,
) -> None:
    on(repo, "feature", [(["actors", "reviewer", "character"], "A.")])
    on(repo, "main", [(CHARACTER, "B.")])
    heads = set(merged_feature(repo).heads)
    set_config(repo, [(EXPECT, [])])
    *_, settling, change = git_service(repo).history(aggregate.STREAM)
    assert settling.topic == aggregate.SETTLED
    assert set(settling.parents) == heads
    assert change.parents == (settling.id,)
    lines = [
        json.loads(line)
        for path in segments(repo.path)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    batches = {line["batch"]["id"] for line in lines if line.get("id") in {settling.id, change.id}}
    assert len(batches) == 1
    assert all(RECORD.is_valid(line) for line in lines)
    assert len(config_of(repo).heads) == 1
