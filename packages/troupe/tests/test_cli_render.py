"""One line per run event in troupe logs (spec: cli, "Status and logs commands")."""

import json

import pytest

from runner_schemas import RUNNER_SCHEMAS, load
from troupe.cli.render import render_event

AT = "2026-11-07T00:00:00Z"


def _logged(event: dict[str, object]) -> dict[str, object]:
    return {"seq": 1, "at": AT, "event": event}


def test_a_served_model_line_names_the_model() -> None:
    line = render_event(_logged({"type": "served_model", "model": "gpt-6-luna-2026-03-05"}))
    assert line == f"     1 {AT} served_model: gpt-6-luna-2026-03-05"


def _host_event_types() -> list[str]:
    defs = load(RUNNER_SCHEMAS / "run-event.schema.json")["$defs"]
    return [ref["$ref"].rsplit("/", 1)[1] for ref in defs["hostEvent"]["oneOf"]]


@pytest.mark.parametrize("type_", _host_event_types())
def test_every_host_event_type_has_a_summary_after_its_type(type_: str) -> None:
    line = render_event(_logged({"type": type_}))
    assert not line.endswith(f"{type_}:"), json.dumps(line)
