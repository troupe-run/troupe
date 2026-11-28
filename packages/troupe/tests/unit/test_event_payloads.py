"""The event payload schemas, checked against payloads built in each test: a Run.Ended payload
validates only when its ending, audit, transcript and transcript format agree, a Run.Noticed
payload only when it holds one declared notice, and an end's recording only when it names a run
event or a notice. Also checks that the topics troupe records are the topics the event-record
schema defines, that each payload schema's title names its topic, and that an ended run's error
refers to the error catalogue (spec: event-store; strict-schemas design D6).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_event_payloads_integration.py."""

from typing import Any

import pytest

from catalogues import branches
from protocol_schemas import SCHEMAS, SCRIPTED, load, validator_for
from troupe.core.config import aggregate as config_aggregate
from troupe.core.runs import performance
from troupe.core.runs.aggregate import (
    TOPICS,
)

PERFORMANCE = "1a2b3c4d-0000-4000-8000-000000000000"


@pytest.mark.parametrize(
    ("change", "label"),
    [
        ({"ending": "exited", "drop": "exitCode"}, "an exited end without an exit code"),
        ({"ending": "never-started", "drop": None}, "a never-started end with a transcript"),
    ],
)
def test_an_end_that_contradicts_its_ending_does_not_validate(
    change: dict[str, Any], label: str
) -> None:
    ended = load(SCHEMAS / "events" / "run-ended.schema.json")
    validator = validator_for(ended["$id"], SCRIPTED)
    outcome = {
        "outcome": "succeeded",
        "exitCode": 0,
        "ending": change["ending"],
        "transcript": "sha256:" + "a" * 64,
        "transcriptFormat": "native",
        "stderr": "sha256:" + "b" * 64,
        "limits": {
            "start_timeout": 1,
            "run_timeout": 1,
            "cancel_grace": 1,
            "silence_announce": 1,
            "max_message_bytes": 1,
            "event_max_bytes": 1,
            "transcript_max_bytes": 1,
            "stderr_max_bytes": 1,
            "fail_fast_on_auth_retry": False,
        },
    }
    if change["drop"]:
        del outcome[change["drop"]]
    if change["ending"] == "never-started":
        del outcome["exitCode"], outcome["stderr"]
    else:
        outcome["audit"] = {"outside": []}
    state = {
        "lineage": {
            "actor": {"kind": "unknown"},
            "via": "runner",
            "at": "2026-10-13T00:00:00.000Z",
            "change": "01K7ZX3N8V4Q2M6R9T5W1Y0B3C",
            "cause": {"kind": "command", "id": "01K7ZX3N8V4Q2M6R9T5W1Y0B3C"},
            "approvals": [],
            "vcs": {"adapter": "files"},
            "performance": PERFORMANCE,
        },
        "timestamp": {"_type_": "datetime_iso", "_data_": "2026-10-13T00:00:00+00:00"},
        "outcome": outcome,
    }
    assert not validator.is_valid(state), label
    outcome.pop("transcript")
    outcome.pop("transcriptFormat")
    if change["drop"]:
        outcome[change["drop"]] = 0
        outcome["transcript"] = "sha256:" + "a" * 64
        outcome["transcriptFormat"] = "native"
    assert validator.is_valid(state), f"{label}, once consistent"


def _ended(outcome: dict[str, Any]) -> dict[str, Any]:
    """A Run.Ended payload around ``outcome``, with an exited runner unless it says otherwise."""
    return {
        "lineage": {
            "actor": {"kind": "unknown"},
            "via": "runner",
            "at": "2026-10-13T00:00:00.000Z",
            "change": "01K7ZX3N8V4Q2M6R9T5W1Y0B3C",
            "cause": {"kind": "command", "id": "01K7ZX3N8V4Q2M6R9T5W1Y0B3C"},
            "approvals": [],
            "vcs": {"adapter": "files"},
            "performance": PERFORMANCE,
        },
        "timestamp": {"_type_": "datetime_iso", "_data_": "2026-10-13T00:00:00+00:00"},
        "outcome": {
            "outcome": "cancelled",
            "exitCode": 0,
            "ending": "exited",
            "transcript": "sha256:" + "a" * 64,
            "transcriptFormat": "native",
            "stderr": "sha256:" + "b" * 64,
            "limits": {
                "start_timeout": 1,
                "run_timeout": 1,
                "cancel_grace": 1,
                "silence_announce": 1,
                "max_message_bytes": 1,
                "event_max_bytes": 1,
                "transcript_max_bytes": 1,
                "stderr_max_bytes": 1,
                "fail_fast_on_auth_retry": False,
            },
            **outcome,
        },
    }


AUDIT_ERROR = {
    "code": "vcs.failed",
    "problem": "git ls-files failed.",
    "fix": "Check the repository with git status.",
    "details": {"command": "git ls-files", "exitStatus": 128},
}


@pytest.mark.parametrize(
    ("audit", "valid"),
    [
        ({"outside": []}, True),
        ({"outside": [{"path": "src/a.py", "change": "added", "needs": "write"}]}, True),
        (
            {
                "outside": [
                    {"path": "drafts/a.md", "change": "moved", "needs": "move", "to": "docs/a.md"}
                ]
            },
            True,
        ),
        ({"error": AUDIT_ERROR}, True),
        ({"outside": [], "error": AUDIT_ERROR}, False),
        ({}, False),
        ({"outside": [{"path": "drafts/a.md", "change": "moved", "needs": "move"}]}, False),
        (
            {"outside": [{"path": "a", "change": "added", "needs": "write", "to": "b"}]},
            False,
        ),
        ({"outside": [{"path": "a", "change": "renamed", "needs": "write"}]}, False),
    ],
    ids=[
        "every change declared",
        "a change outside",
        "a move outside",
        "an audit that couldn't run",
        "both findings and an error",
        "neither findings nor an error",
        "a move with no destination",
        "a destination that isn't a move's",
        "an unknown kind of change",
    ],
)
def test_an_ends_audit_validates_exactly_when_it_holds_findings_or_an_error(
    audit: dict[str, Any], valid: bool
) -> None:
    ended = load(SCHEMAS / "events" / "run-ended.schema.json")
    validator = validator_for(ended["$id"], SCRIPTED)
    assert validator.is_valid(_ended({"audit": audit})) is valid


def test_an_end_whose_runner_never_started_validates_only_without_an_audit() -> None:
    ended = load(SCHEMAS / "events" / "run-ended.schema.json")
    validator = validator_for(ended["$id"], SCRIPTED)
    start_failed = {
        "code": "runner.start-failed",
        "problem": "Couldn't start the runner.",
        "fix": "Check that the runner is installed.",
        "details": {"command": "nothing"},
    }
    never = {"outcome": "could-not-start", "ending": "never-started", "error": start_failed}
    state = _ended(never)
    for field in ("exitCode", "transcript", "transcriptFormat", "stderr"):
        del state["outcome"][field]
    assert validator.is_valid(state)
    state["outcome"]["audit"] = {"outside": []}
    assert not validator.is_valid(state)


# Requirement: A run's end says which form its transcript is


@pytest.mark.parametrize("format_", ["native", "kinds"])
def test_an_end_with_a_transcript_validates_with_either_format(format_: str) -> None:
    ended = load(SCHEMAS / "events" / "run-ended.schema.json")
    assert validator_for(ended["$id"], SCRIPTED).is_valid(
        _ended({"transcriptFormat": format_, "audit": {"outside": []}})
    )


def test_an_end_with_a_transcript_and_no_format_does_not_validate() -> None:
    ended = load(SCHEMAS / "events" / "run-ended.schema.json")
    state = _ended({"audit": {"outside": []}})
    del state["outcome"]["transcriptFormat"]
    assert not validator_for(ended["$id"], SCRIPTED).is_valid(state)


def test_an_end_with_a_format_the_schema_doesnt_define_does_not_validate() -> None:
    ended = load(SCHEMAS / "events" / "run-ended.schema.json")
    assert not validator_for(ended["$id"], SCRIPTED).is_valid(
        _ended({"transcriptFormat": "framed", "audit": {"outside": []}})
    )


def test_an_exited_end_with_a_format_and_no_transcript_does_not_validate() -> None:
    ended = load(SCHEMAS / "events" / "run-ended.schema.json")
    state = _ended({"audit": {"outside": []}})
    del state["outcome"]["transcript"]
    assert not validator_for(ended["$id"], SCRIPTED).is_valid(state)


def test_a_never_started_end_with_a_format_and_no_transcript_does_not_validate() -> None:
    ended = load(SCHEMAS / "events" / "run-ended.schema.json")
    start_failed = {
        "code": "runner.start-failed",
        "problem": "Couldn't start the runner.",
        "fix": "Check that the runner is installed.",
        "details": {"command": "nothing"},
    }
    state = _ended({"outcome": "could-not-start", "ending": "never-started", "error": start_failed})
    for field in ("exitCode", "transcript", "stderr"):
        del state["outcome"][field]
    assert not validator_for(ended["$id"], SCRIPTED).is_valid(state)
    del state["outcome"]["transcriptFormat"]
    assert validator_for(ended["$id"], SCRIPTED).is_valid(state)


@pytest.mark.parametrize("ending", ["exited", "killed"])
def test_an_end_whose_runner_started_does_not_validate_without_its_audit(ending: str) -> None:
    ended = load(SCHEMAS / "events" / "run-ended.schema.json")
    validator = validator_for(ended["$id"], SCRIPTED)
    assert validator.is_valid(_ended({"ending": ending, "audit": {"outside": []}}))
    assert not validator.is_valid(_ended({"ending": ending}))


SILENT = {
    "code": "run.silent",
    "problem": "The run has sent no event for 30s.",
    "fix": "Wait, or cancel the run if it seems stuck.",
    "details": {"seconds": 30.0},
}
RECORDING_ERROR = {
    "code": "internal.unexpected",
    "problem": "troupe hit an unexpected error: OSError: disk full",
    "fix": "This is a bug in troupe.",
}


def _noticed(**fields: object) -> dict[str, Any]:
    """A Run.Noticed payload holding the run.silent notice, with ``fields`` replacing its own."""
    state = _ended({})
    del state["outcome"]
    state["lineage"]["via"] = "cli"
    return {**state, "notice": SILENT, **fields}


@pytest.mark.parametrize(
    ("change", "valid"),
    [
        ({}, True),
        ({"notice": {**SILENT, "code": "run.no-such-notice"}}, False),
        ({"notice": {"code": "run.silent", "problem": "Silent."}}, False),
        ({"seq": 3}, False),
    ],
    ids=["a notice", "an undeclared code", "a notice with no fix", "a seq"],
)
def test_a_noticed_payload_validates_exactly_when_it_holds_one_declared_notice(
    change: dict[str, Any], valid: bool
) -> None:
    noticed = load(SCHEMAS / "events" / "run-noticed.schema.json")
    assert validator_for(noticed["$id"], SCRIPTED).is_valid(_noticed(**change)) is valid


def test_a_noticed_payload_without_its_notice_does_not_validate() -> None:
    noticed = load(SCHEMAS / "events" / "run-noticed.schema.json")
    state = _noticed()
    del state["notice"]
    assert not validator_for(noticed["$id"], SCRIPTED).is_valid(state)


@pytest.mark.parametrize(
    ("recording", "valid"),
    [
        ({"failedAt": 2, "error": RECORDING_ERROR}, True),
        ({"notice": "run.silent", "error": RECORDING_ERROR}, True),
        ({"failedAt": 2, "notice": "run.silent", "error": RECORDING_ERROR}, False),
        ({"error": RECORDING_ERROR}, False),
        ({"notice": "not a code", "error": RECORDING_ERROR}, False),
    ],
    ids=["a run event", "a notice", "both", "neither", "a notice that isn't a code"],
)
def test_an_ends_recording_validates_exactly_when_it_names_an_event_or_a_notice(
    recording: dict[str, Any], valid: bool
) -> None:
    ended = load(SCHEMAS / "events" / "run-ended.schema.json")
    state = {**_ended({"audit": {"outside": []}}), "recording": recording}
    assert validator_for(ended["$id"], SCRIPTED).is_valid(state) is valid


# Requirement: The event schemas say which events name a performance (spec: lineage)


def test_a_run_event_whose_lineage_names_no_performance_does_not_validate() -> None:
    ended = load(SCHEMAS / "events" / "run-ended.schema.json")
    state = _ended({"audit": {"outside": []}})
    validator = validator_for(ended["$id"], SCRIPTED)
    assert validator.is_valid(state)
    del state["lineage"]["performance"]
    assert not validator.is_valid(state)


def test_a_config_event_whose_lineage_names_a_performance_does_not_validate() -> None:
    changed = load(SCHEMAS / "events" / "config-changed.schema.json")
    validator = validator_for(changed["$id"], SCRIPTED)
    lineage = {**_ended({})["lineage"], "via": "cli"}
    del lineage["performance"]
    state = {
        "lineage": lineage,
        "timestamp": {"_type_": "datetime_iso", "_data_": "2026-10-13T00:00:00+00:00"},
        "changes": [{"path": ["actors", "tester", "runner"], "after": "scripted"}],
        "files": [],
    }
    assert validator.is_valid(state)
    state["lineage"] = {**lineage, "performance": PERFORMANCE}
    assert not validator.is_valid(state)


# Requirement: Each event troupe defines has a payload schema (every topic has a schema)


def test_the_topics_troupe_records_and_the_topics_the_protocol_defines_are_the_same() -> None:
    record = load(SCHEMAS / "event-record.schema.json")
    defined = record["$defs"]["troupeEvent"]["properties"]["topic"]["enum"]
    chosen = [
        branch["if"]["properties"]["topic"]["const"]
        for branch in record["$defs"]["troupeEvent"]["allOf"]
    ]
    assert set(defined) == set(chosen) == {*TOPICS, *performance.TOPICS, *config_aggregate.TOPICS}


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
    assert ended["properties"]["outcome"]["properties"]["error"]["$ref"] == "../error.schema.json"
    assert "run.error-result" in branches("error.schema.json")
