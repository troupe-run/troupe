"""Config's changes: one event per command, each value's old hash and new value, groups removed
and set whole (spec: config; config-model design D2)."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from gitrepo import make_repo
from protocol_schemas import PROTOCOL_BASE, SCRIPTED, validator_for
from storetesting import git_service, segments
from troupe.core import strict_json
from troupe.core.config import aggregate
from troupe.core.config.changes import UNSET, apply, change, set_value, unset, value_hash
from troupe.core.errors import TroupeError

RECORD = validator_for(PROTOCOL_BASE + "event-record.schema.json", SCRIPTED)

TESTER: dict[str, Any] = {
    "runner": "scripted",
    "options": {"script": {"steps": [{"exit": 0}]}},
    "expect": ["out/hello.txt"],
}
CONFIG: dict[str, Any] = {"actors": {"tester": TESTER}}

# Requirement: A command records one change


def test_a_command_setting_two_values_records_one_event_with_an_entry_for_each(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    entries = change(
        {},
        [
            (["actors", "tester", "runner"], "scripted"),
            (["actors", "tester", "expect"], ["out/hello.txt"]),
        ],
    )
    git_service(repo).command(via="cli").record([aggregate.changed(1, entries, [])])
    lines = [
        json.loads(line)
        for path in segments(repo.path)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    [recorded] = [line for line in lines if line.get("topic") == aggregate.CHANGED]
    assert [e["path"] for e in recorded["state"]["changes"]] == [
        ["actors", "tester", "expect"],
        ["actors", "tester", "runner"],
    ]
    assert recorded["stream"] == str(aggregate.STREAM)
    assert all(RECORD.is_valid(line) for line in lines), [
        error.message for line in lines for error in RECORD.iter_errors(line)
    ]


def test_two_commands_in_a_row_record_two_events_each_with_its_own_change_id(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    first = set_value({}, ["actors", "tester", "runner"], "scripted")
    second = set_value(apply({}, first), ["actors", "tester", "runner"], "other")
    for version, entries in ((1, first), (2, second)):
        git_service(repo).command(via="cli").record([aggregate.changed(version, entries, [])])
    history = git_service(repo).history(aggregate.STREAM)
    assert [record.version for record in history] == [1, 2]
    changes = {record.lineage["change"] for record in history if record.lineage is not None}
    assert len(changes) == 2


def test_setting_a_value_to_what_it_already_is_changes_nothing() -> None:
    assert set_value(CONFIG, ["actors", "tester", "runner"], "scripted") == []


def test_the_config_stream_has_the_same_id_in_every_theatre(tmp_path: Path) -> None:
    streams = set()
    for name in ("one", "two"):
        repo = make_repo(tmp_path / name)
        entries = set_value({}, ["actors", "tester", "runner"], "scripted")
        git_service(repo).command(via="cli").record([aggregate.changed(1, entries, [])])
        [line] = [
            json.loads(line)
            for path in segments(repo.path)
            for line in path.read_text(encoding="utf-8").splitlines()
            if '"topic"' in line
        ]
        streams.add(line["stream"])
    assert streams == {str(aggregate.STREAM)}


# Requirement: A change entry holds the path, the old value's hash and the new value


def test_a_changed_value_records_the_hash_of_the_old_and_the_new_value() -> None:
    [entry] = set_value(CONFIG, ["actors", "tester", "runner"], "claude-code")
    assert entry == {
        "path": ["actors", "tester", "runner"],
        "before": value_hash("scripted"),
        "after": "claude-code",
    }


def test_a_new_value_has_an_after_and_no_before() -> None:
    [entry] = set_value(CONFIG, ["actors", "tester", "character"], "You are the tester.")
    assert entry == {"path": ["actors", "tester", "character"], "after": "You are the tester."}


def test_the_hash_is_the_sha256_of_the_canonical_json() -> None:
    value = {"b": [1, 2.5, True, "é"], "a": "x"}
    canonical = strict_json.dumps(value).encode("utf-8")
    assert value_hash(value) == "sha256:" + hashlib.sha256(canonical).hexdigest()


VALUES = st.recursive(
    st.booleans() | st.integers() | st.floats(allow_nan=False, allow_infinity=False) | st.text(),
    lambda inner: st.lists(inner, max_size=3),
    max_leaves=6,
)


@given(VALUES, VALUES)
def test_a_before_is_the_hash_of_the_earlier_after_for_every_kind_of_value(
    first: object, second: object
) -> None:
    [set_first] = set_value({}, ["a"], first)
    later = set_value(apply({}, [set_first]), ["a"], second)
    if value_hash(first) == value_hash(second):
        assert later == []
    else:
        [entry] = later
        assert entry["before"] == value_hash(set_first["after"])


def test_a_null_value_is_refused_naming_the_path_and_the_fix() -> None:
    with pytest.raises(TroupeError) as caught:
        set_value(CONFIG, ["actors", "tester", "options", "script"], {"steps": [None]})
    assert caught.value.code == "config.invalid"
    assert caught.value.details["path"] == ["actors", "tester", "options", "script", "steps"]
    assert "troupe config unset" in caught.value.fix


# Requirement: Objects are groups, and every other value is whole


def test_setting_a_list_inside_a_group_is_one_entry_holding_the_whole_list() -> None:
    steps = [{"event": {"type": "result"}}, {"exit": 3}]
    [entry] = set_value(CONFIG, ["actors", "tester", "options", "script", "steps"], steps)
    assert entry["path"] == ["actors", "tester", "options", "script", "steps"]
    assert entry["after"] == steps


def test_no_entry_ever_holds_an_object_as_its_after() -> None:
    entries = set_value(CONFIG, ["actors", "reviewer"], {**TESTER, "character": "Review."})
    assert entries
    assert not any(isinstance(entry.get("after"), dict) for entry in entries)


# Requirement: A group is removed as one entry


def test_removing_an_actor_is_one_entry_addressed_to_its_group() -> None:
    [entry] = unset(CONFIG, ["actors", "tester"])
    assert entry == {"path": ["actors", "tester"], "before": value_hash(TESTER)}
    assert apply(CONFIG, [entry]) == {}


def test_unsetting_what_isnt_there_changes_nothing() -> None:
    assert unset(CONFIG, ["actors", "nobody"]) == []


# Requirement: A group can be set whole from a file


def test_setting_an_actor_whole_sets_adds_and_removes_each_value_under_it() -> None:
    entries = set_value(CONFIG, ["actors", "tester"], {"runner": "other", "expect": []})
    by_path = {tuple(entry["path"]): entry for entry in entries}
    assert by_path[("actors", "tester", "runner")]["after"] == "other"
    assert by_path[("actors", "tester", "expect")]["after"] == []
    removed = by_path[("actors", "tester", "options", "script", "steps")]
    assert "after" not in removed
    assert apply(CONFIG, entries) == {"actors": {"tester": {"runner": "other", "expect": []}}}


def test_a_value_where_a_group_is_needed_is_removed_first() -> None:
    config = {"actors": "not a group"}
    entries = set_value(config, ["actors", "tester", "runner"], "scripted")
    assert [entry["path"] for entry in entries] == [["actors"], ["actors", "tester", "runner"]]
    assert apply(config, entries) == {"actors": {"tester": {"runner": "scripted"}}}


def test_a_path_changed_twice_in_one_command_records_its_net_change() -> None:
    entries = change(
        CONFIG,
        [
            (["actors", "tester", "runner"], "other"),
            (["actors", "tester", "runner"], "third"),
            (["actors", "tester", "expect"], []),
            (["actors", "tester", "expect"], ["out/hello.txt"]),
        ],
    )
    assert entries == [
        {"path": ["actors", "tester", "runner"], "before": value_hash("scripted"), "after": "third"}
    ]


def test_a_command_can_unset_one_value_and_set_another() -> None:
    entries = change(
        CONFIG, [(["actors", "tester", "options"], UNSET), (["actors", "x", "runner"], "s")]
    )
    assert apply(CONFIG, entries) == {
        "actors": {
            "tester": {"runner": "scripted", "expect": ["out/hello.txt"]},
            "x": {"runner": "s"},
        }
    }
