"""Recorded events validate by topic, from real runs (spec: event-store; strict-schemas design D6).

Each test performs real runs with the scripted runner in a git theatre, then validates every line
the event store wrote against the event-record schema, which picks each payload's schema by topic.
The payloads are what troupe really records, not hand-written examples.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from catalogues import branches
from protocol_guard import ProtocolGuardError
from protocol_schemas import PROTOCOL_BASE, SCHEMAS, SCRIPTED, load, validator_for
from runtesting import INIT, OK, Harness, failing_at, request, script, theatre, turn
from storetesting import git_service, segments
from troupe.core.errors import TroupeError
from troupe.core.runs.aggregate import ENDED, REPORTED, STARTED, TOPICS, Run

RECORD = validator_for(PROTOCOL_BASE + "event-record.schema.json", SCRIPTED)
ERROR = {"event": {"type": "result", "status": "error", "message": "401 Unauthorized"}}
TOOLS: list[dict[str, Any]] = [
    {"event": {"type": "tool_call", "callId": "c1", "tool": "Write", "inputSummary": "a.txt"}},
    {
        "event": {
            "type": "tool_result",
            "callId": "c1",
            "isError": False,
            "outputSummary": "ok",
            "outputBytes": 2,
        }
    },
]


def _lines(harness: Harness) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for path in segments(harness.repo.path)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def _problems(lines: list[dict[str, Any]]) -> list[str]:
    return [
        f"{line.get('topic', 'header')}: {error.message}"
        for line in lines
        for error in RECORD.iter_errors(line)
    ]


def test_every_line_a_succeeded_run_records_validates_by_topic(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path))
    harness.perform(request(script(INIT, turn("hello"), *TOOLS, OK)))
    lines = _lines(harness)
    assert [line.get("topic") for line in lines if "topic" in line] == [
        STARTED,
        *[REPORTED] * 5,
        ENDED,
    ]
    assert _problems(lines) == []


def test_every_line_a_failed_run_records_validates_by_topic(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path))
    harness.perform(request(script(INIT, ERROR)))
    lines = _lines(harness)
    ended = next(line for line in lines if line.get("topic") == ENDED)
    assert ended["state"]["outcome"]["error"]["code"] == "run.error-result"
    assert _problems(lines) == []


def test_every_line_a_run_whose_runner_refused_it_records_validates_by_topic(
    tmp_path: Path,
) -> None:
    harness = Harness(theatre(tmp_path))
    harness.perform(request({"script": {"steps": []}, "speed": 2}))
    lines = _lines(harness)
    started = next(line for line in lines if line.get("topic") == STARTED)
    ended = next(line for line in lines if line.get("topic") == ENDED)
    assert started["state"]["runner_reported"] is None
    assert ended["state"]["outcome"]["error"]["details"]["runnerError"]["code"] == (
        "scripted.unknown-option"
    )
    assert _problems(lines) == []


def test_every_line_a_run_whose_recording_failed_records_validates_by_topic(
    tmp_path: Path,
) -> None:
    harness = Harness(theatre(tmp_path), store_wrapper=failing_at(1))
    with pytest.raises(TroupeError):
        harness.perform(request(script(INIT, turn("hello"), OK)))
    lines = _lines(harness)
    ended = next(line for line in lines if line.get("topic") == ENDED)
    assert ended["state"]["recording"]["failedAt"] == 1
    assert _problems(lines) == []


def test_a_recorded_payload_with_a_field_its_topic_does_not_define_is_refused(
    tmp_path: Path,
) -> None:
    harness = Harness(theatre(tmp_path))
    harness.perform(request(script(INIT, OK)))
    reported = next(line for line in _lines(harness) if line.get("topic") == REPORTED)
    reported["state"]["colour"] = "blue"
    assert not RECORD.is_valid(reported)


# Requirement: Each event troupe defines has a payload schema (every topic has a schema)


def test_the_topics_troupe_records_and_the_topics_the_protocol_defines_are_the_same() -> None:
    record = load(SCHEMAS / "event-record.schema.json")
    defined = record["$defs"]["troupeEvent"]["properties"]["topic"]["enum"]
    chosen = [
        branch["if"]["properties"]["topic"]["const"]
        for branch in record["$defs"]["troupeEvent"]["allOf"]
    ]
    assert set(defined) == set(chosen) == set(TOPICS)


def test_each_payload_schema_names_its_topic_in_its_title() -> None:
    record = load(SCHEMAS / "event-record.schema.json")
    for branch in record["$defs"]["troupeEvent"]["allOf"]:
        topic = branch["if"]["properties"]["topic"]["const"]
        schema = load(SCHEMAS / branch["then"]["properties"]["state"]["$ref"])
        assert topic.endswith(schema["title"]), topic


def test_the_error_catalogue_is_what_an_ended_runs_error_validates_against() -> None:
    # Run.Ended's outcome error refers to the error catalogue, so a run's recorded error is
    # held to the same codes and details as any other.
    ended = load(SCHEMAS / "events" / "run-ended.schema.json")
    assert ended["properties"]["outcome"]["properties"]["error"] == {
        "anyOf": [{"$ref": "../error.schema.json"}, {"type": "null"}]
    }
    assert "run.error-result" in branches("error.schema.json")


# Requirement: Every error, notice and recorded event is checked as tests make it

HASH = "sha256:" + "ab" * 32
STAGE = {
    "name": "local",
    "effects": "unenforced",
    "allowedBy": {"setting": "allow_unenforced_local_stage", "source": "env"},
}


def _run() -> Run:
    return Run(
        run_id="0f8fad5b-d9cb-469f-a165-70867728950e",
        actor="tester",
        runner_requested="scripted",
        runner_reported=None,
        stage=STAGE,
        effect_check={"kind": "none"},
        instructions=HASH,
        options=HASH,
    )


def test_recording_a_payload_with_a_field_its_topic_does_not_define_fails_naming_the_topic(
    tmp_path: Path,
) -> None:
    store = git_service(theatre(tmp_path))
    run = _run()
    event = {**INIT["event"], "runId": run.run_id, "seq": 0, "colour": "blue"}
    run.report(0, event)
    with pytest.raises(ProtocolGuardError, match=r"Run\.Reported.*'colour' was unexpected"):
        store.command(via="cli").record(run.collect_events())


def test_recording_a_run_whose_payloads_match_their_topics_passes_the_guard(
    tmp_path: Path,
) -> None:
    store = git_service(theatre(tmp_path))
    run = _run()
    run.report(0, {**INIT["event"], "runId": run.run_id, "seq": 0})
    assert len(store.command(via="cli").record(run.collect_events())) == 2
