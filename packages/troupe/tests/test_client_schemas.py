"""The client protocol's schemas accept what they should and refuse what they shouldn't (spec:
client-protocol; perform-status-logs design D2)."""

import copy
from typing import Any

import pytest

from client_schemas import CLIENT_SCHEMAS, MESSAGES, is_valid

RUN_ID = "0f8fad5b-d9cb-469f-a165-70867728950e"
HASH = "sha256:" + "ab" * 32
AT = "2026-10-12T03:04:05.678Z"
PERFORM: dict[str, Any] = {
    "actor": "tester",
    "runner": "scripted",
    "options": {"script": {"steps": []}},
    "instructions": "say hello",
    "effectCheck": {"kind": "files", "paths": ["out/hello.txt"]},
}
SUMMARY: dict[str, Any] = {
    "runId": RUN_ID,
    "actor": "tester",
    "startedBy": {"kind": "human", "id": "ada@example.com", "source": "vcs"},
    "runner": {"requested": "scripted", "reported": {"name": "scripted", "version": "0.1.0"}},
    "stage": {
        "name": "local",
        "effects": "unenforced",
        "allowedBy": {"setting": "allow_unenforced_local_stage", "source": "env"},
    },
    "effectCheck": {"kind": "none"},
    "state": "ended",
    "outcome": "failed",
    "error": {
        "code": "run.error-result",
        "problem": "It failed.",
        "fix": "Look.",
        "details": {"message": "401"},
    },
    "events": 2,
    "startedAt": AT,
    "endedAt": AT,
    "transcript": HASH,
    "stderr": HASH,
    "recording": None,
}
EVENT: dict[str, Any] = {
    "kind": "event",
    "runId": RUN_ID,
    "seq": 0,
    "at": AT,
    "event": {
        "runId": RUN_ID,
        "seq": 0,
        "type": "init",
        "runner": {"name": "scripted", "version": "0.1.0"},
        "tools": [],
    },
}
NOTICE = {
    "kind": "notice",
    "notice": {
        "code": "run.silent",
        "problem": "Quiet.",
        "fix": "Wait.",
        "details": {"seconds": 30},
    },
}


def changed(data: dict[str, Any], **changes: object) -> dict[str, Any]:
    result = copy.deepcopy(data)
    for key, value in changes.items():
        if value is None and key.startswith("drop_"):
            del result[key.removeprefix("drop_")]
        else:
            result[key] = value
    return result


def test_each_method_has_exactly_its_message_schemas() -> None:
    files = {path.name for path in CLIENT_SCHEMAS.glob("*.schema.json")}
    expected = {name for parts in MESSAGES.values() for name in parts.values()}
    assert files == expected | {"run.schema.json"}


ACCEPTED = [
    ("perform-request.schema.json", PERFORM, "everything"),
    (
        "perform-request.schema.json",
        {"actor": "t", "runner": "scripted", "effectCheck": {"kind": "none"}},
        "only what's required",
    ),
    ("perform-update.schema.json", {"kind": "started", "runId": RUN_ID}, "started"),
    ("perform-update.schema.json", EVENT, "an event"),
    (
        "perform-update.schema.json",
        changed(
            EVENT,
            event={
                "runId": RUN_ID,
                "seq": 0,
                "type": "oversized",
                "originalType": "turn",
                "bytes": 70000,
                "ref": HASH,
            },
        ),
        "an oversized event",
    ),
    ("perform-update.schema.json", NOTICE, "a notice"),
    ("perform-result.schema.json", {"run": SUMMARY}, "a failed run"),
    (
        "perform-result.schema.json",
        {
            "run": changed(
                SUMMARY,
                runner={"requested": "scripted", "reported": None},
                outcome="could-not-start",
                transcript=None,
                stderr=None,
            )
        },
        "a run whose runner never started",
    ),
    ("status-request.schema.json", {}, "list with the default limit"),
    ("status-request.schema.json", {"limit": 5}, "list with a limit"),
    ("status-request.schema.json", {"run": "0f8fad5b"}, "an 8-digit prefix"),
    ("status-request.schema.json", {"run": RUN_ID}, "a full id"),
    ("status-result.schema.json", {"runs": [SUMMARY], "notices": []}, "a list"),
    (
        "status-result.schema.json",
        {
            "runs": [changed(SUMMARY, state="running", outcome=None, error=None, endedAt=None)],
            "notices": [NOTICE["notice"]],
        },
        "a running run",
    ),
    ("logs-request.schema.json", {"run": RUN_ID, "follow": True}, "follow"),
    ("logs-update.schema.json", EVENT, "an event"),
    ("logs-result.schema.json", {"run": SUMMARY, "events": [EVENT], "notices": []}, "a log"),
    (
        "perform-result.schema.json",
        {
            "run": changed(
                SUMMARY,
                recording={
                    "failedAt": 2,
                    "error": {
                        "code": "events.version-conflict",
                        "problem": "p",
                        "fix": "f",
                        "details": {"reason": "another writer recorded first"},
                    },
                },
            )
        },
        "a run whose recording failed",
    ),
]


@pytest.mark.parametrize(("schema", "value", "label"), ACCEPTED, ids=[a[2] for a in ACCEPTED])
def test_the_schema_accepts(schema: str, value: dict[str, Any], label: str) -> None:
    assert is_valid(value, schema), label


def files(*paths: str) -> dict[str, Any]:
    return changed(PERFORM, effectCheck={"kind": "files", "paths": list(paths)})


REFUSED = [
    ("perform-request.schema.json", files("/etc/passwd"), "an absolute path"),
    ("perform-request.schema.json", files("C:/x.txt"), "a drive"),
    ("perform-request.schema.json", files("out\\x.txt"), "a backslash"),
    ("perform-request.schema.json", files("../outside.txt"), "a path that leaves with .."),
    ("perform-request.schema.json", files("a/../../b"), "a .. in the middle"),
    ("perform-request.schema.json", files(), "a files check with no paths"),
    ("perform-request.schema.json", files("a", "a"), "a repeated path"),
    (
        "perform-request.schema.json",
        changed(PERFORM, effectCheck={"kind": "maybe"}),
        "an effect check that is neither none nor files",
    ),
    (
        "perform-request.schema.json",
        changed(PERFORM, effectCheck={"kind": "none", "paths": ["a"]}),
        "none with paths",
    ),
    ("perform-request.schema.json", changed(PERFORM, drop_effectCheck=None), "no effect check"),
    ("perform-request.schema.json", changed(PERFORM, actor="Tester"), "an actor in capitals"),
    ("perform-request.schema.json", changed(PERFORM, actor="1tester"), "an actor from a digit"),
    ("perform-request.schema.json", changed(PERFORM, actor="t" * 65), "an actor too long"),
    ("perform-request.schema.json", changed(PERFORM, runner="a b"), "a runner with a space"),
    (
        "perform-request.schema.json",
        changed(PERFORM, runner=["python", "-m", "x"]),
        "a runner as a command line",
    ),
    ("perform-request.schema.json", changed(PERFORM, argv=["sh"]), "an unknown field: argv"),
    (
        "perform-request.schema.json",
        changed(PERFORM, allow_unenforced_local_stage=True),
        "an unknown field: a policy value",
    ),
    ("perform-request.schema.json", changed(PERFORM, options=[]), "options that aren't an object"),
    ("perform-update.schema.json", {"kind": "started"}, "started with no run id"),
    ("perform-update.schema.json", changed(EVENT, at="2026-10-12"), "an event with a bad time"),
    ("perform-update.schema.json", changed(EVENT, extra=1), "an unknown field in an update"),
    ("perform-result.schema.json", {"run": changed(SUMMARY, state="done")}, "an unknown state"),
    (
        "perform-result.schema.json",
        {"run": changed(SUMMARY, drop_recording=None)},
        "a summary missing a field",
    ),
    ("status-request.schema.json", {"run": "0f8fad5"}, "a prefix shorter than 8"),
    ("status-request.schema.json", {"run": "0F8FAD5B"}, "a prefix in capitals"),
    ("status-request.schema.json", {"run": RUN_ID, "limit": 3}, "a run and a limit"),
    ("status-request.schema.json", {"limit": 0}, "a zero limit"),
    ("status-request.schema.json", {"verbose": True}, "an unknown field at the top"),
    ("logs-request.schema.json", {}, "logs with no run"),
    ("logs-request.schema.json", {"run": RUN_ID, "follow": "yes"}, "follow that isn't a boolean"),
    ("logs-result.schema.json", {"run": SUMMARY, "events": [{}], "notices": []}, "an empty event"),
]


@pytest.mark.parametrize(("schema", "value", "label"), REFUSED, ids=[r[2] for r in REFUSED])
def test_the_schema_refuses(schema: str, value: dict[str, Any], label: str) -> None:
    assert not is_valid(value, schema), label


# perform's options are the runner's extension point (strict-schemas design D2)


def test_perform_options_validate_against_the_contract_alone_only_when_empty() -> None:
    assert is_valid({**PERFORM, "options": {}}, "perform-request.schema.json", runner=None)
    assert not is_valid(PERFORM, "perform-request.schema.json", runner=None)
    assert is_valid(PERFORM, "perform-request.schema.json")  # the scripted runner's schema bound
