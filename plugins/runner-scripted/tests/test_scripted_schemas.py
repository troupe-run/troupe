"""The scripted runner's published schemas (spec: scripted-runner; strict-schemas design D3).

The schemas themselves are checked for strictness with every other schema troupe ships, in troupe's
own tests. These check that they describe what the runner takes and ships.
"""

import json
import re
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from scripted_harness import OWN, RUNNER_SCHEMAS, SCHEMAS, _registry

# The Claude Code runner's recordings, which this runner replays (claude-code-runner design D13).
FIXTURES = Path(__file__).resolve().parents[2] / "runner-claude-code" / "fixtures" / "claude-code"
RECORDINGS = sorted(FIXTURES.glob("*/recording.jsonl"))
OPTIONS = json.loads((RUNNER_SCHEMAS / "options.schema.json").read_text(encoding="utf-8"))
CONTRACT_EVENTS = json.loads(
    (SCHEMAS / "runner" / "run-event.schema.json").read_text(encoding="utf-8")
)["$defs"]


def _validator(ref: str) -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator({"$ref": OWN + ref}, registry=_registry())


@pytest.mark.runner_claude_code  # reads its fixtures (scripts/check-paths.toml)
@pytest.mark.parametrize("path", RECORDINGS, ids=lambda path: path.parent.name)
def test_every_line_of_each_shipped_recording_validates_as_a_recording_line(path: Path) -> None:
    validator = _validator("options.schema.json#/$defs/recordingLine")
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        errors = [error.message for error in validator.iter_errors(json.loads(line))]
        assert errors == [], f"{path.parent.name}:{number}"


@pytest.mark.parametrize(
    "type_", [ref["$ref"].rsplit("/", 1)[1] for ref in OPTIONS["$defs"]["event"]["oneOf"]]
)
def test_each_event_step_has_the_contracts_fields_with_run_id_and_seq_optional(type_: str) -> None:
    """runId and seq are optional in every step, and init's effects too, which the runner fills
    in as ``checked`` (declared-effects design D9)."""
    step: dict[str, Any] = OPTIONS["$defs"][type_]
    contract: dict[str, Any] = CONTRACT_EVENTS[type_]
    filled = {"runId", "seq", "effects"} if type_ == "init" else {"runId", "seq"}
    assert step["properties"].keys() == contract["properties"].keys()
    assert set(step["required"]) == set(contract["required"]) - filled


def _ref(choice: dict[str, Any]) -> str:
    """The def a oneOf choice names: its $ref, or its allOf's first $ref (init, whose effects a
    runner must send)."""
    ref = choice["$ref"] if "$ref" in choice else choice["allOf"][0]["$ref"]
    return str(ref).rsplit("/", 1)[1]


def test_the_event_steps_cover_every_event_type_a_runner_sends() -> None:
    steps = {_ref(choice) for choice in OPTIONS["$defs"]["event"]["oneOf"]}
    contract = {_ref(choice) for choice in CONTRACT_EVENTS["event"]["oneOf"]}
    assert steps == contract


@pytest.mark.parametrize(
    "options",
    [
        {"script": {"steps": []}},
        {"scriptPath": "script.json", "replayDelays": True},
        {
            "script": {
                "onCancel": "ignore",
                "steps": [{"event": {"type": "log", "level": "info", "message": "m"}}],
            }
        },
    ],
)
def test_options_the_runner_takes_validate(options: dict[str, Any]) -> None:
    assert _validator("options.schema.json").is_valid(options)


@pytest.mark.parametrize(
    "options",
    [
        {},
        {"script": {"steps": []}, "scriptPath": "script.json"},
        {"script": {"steps": []}, "speed": 2},
        {
            "script": {
                "steps": [{"event": {"type": "log", "level": "info", "message": "m", "x": 1}}]
            }
        },
        {"script": {"steps": [{"event": {"type": "thought", "text": "hmm"}}]}},
    ],
    ids=[
        "neither script",
        "both scripts",
        "unknown option",
        "unknown event field",
        "unknown event type",
    ],
)
def test_options_outside_the_schema_do_not_validate(options: dict[str, Any]) -> None:
    # At run time the runner checks only that an event step has a type; the schema checks the
    # whole event, as the contract defines it.
    assert not _validator("options.schema.json").is_valid(options)


@pytest.mark.docs  # reads the README (scripts/check-paths.toml)
def test_the_readmes_options_table_lists_exactly_the_options_schemas_properties() -> None:
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    section = readme.split("## Options", 1)[1].split("\n## ", 1)[0]
    documented = set(re.findall(r"^\| `([^`]+)` \|", section, re.M))
    assert documented == set(OPTIONS["properties"])


# Requirement: A script's steps cover what a runner can send or do

LISTED_STEPS = {
    "event",
    "transcript",
    "stderr",
    "wait",
    "writeFile",
    "tool",
    "hang",
    "exit",
    "rawStdout",
}
"""The step kinds the requirement lists. It says "cover", so the schema may define more."""


def _step_kinds(options_schema: dict[str, Any]) -> set[str]:
    return {key for step in options_schema["$defs"]["step"]["oneOf"] for key in step["required"]}


def test_the_options_schema_defines_a_step_for_each_kind_the_requirement_lists() -> None:
    assert LISTED_STEPS - _step_kinds(OPTIONS) == set()


# Requirement: A script's error result can say it wasn't retried


@pytest.mark.parametrize(
    ("result", "valid"),
    [
        ({"status": "error", "reason": "network", "notRetried": "side-effect"}, True),
        ({"status": "error", "reason": "quota", "notRetried": "side-effect"}, False),
        ({"status": "ok", "notRetried": "side-effect"}, False),
        ({"status": "error", "reason": "network", "notRetried": "unsafe"}, False),
    ],
    ids=["beside network", "beside quota", "on ok", "off the list"],
)
def test_the_options_schema_holds_a_result_steps_not_retried_to_the_contracts_rule(
    result: dict[str, Any], valid: bool
) -> None:
    step = {"type": "result", "message": "m", **result}
    assert _validator("options.schema.json#/$defs/result").is_valid(step) is valid
