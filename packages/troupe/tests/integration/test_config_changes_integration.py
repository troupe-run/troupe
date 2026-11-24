"""Config's changes recorded in a real theatre: a command setting two values records one event with
an entry for each, two commands record two events with their own change ids, and the config
stream has the same id in every theatre (spec: config; config-model design D2).

Its tests that stay in their own process are in unit/test_config_changes.py."""

import json
from pathlib import Path

from gitrepo import make_repo
from protocol_schemas import PROTOCOL_BASE, SCRIPTED, validator_for
from storetesting import git_service, segments
from troupe.core.config import aggregate
from troupe.core.config.changes import (
    apply,
    change,
    set_value,
)

RECORD = validator_for(PROTOCOL_BASE + "event-record.schema.json", SCRIPTED)

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
