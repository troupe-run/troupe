"""Properties of the mapping on lines nobody wrote by hand (design D5; task 5.2).

Random bytes, random JSON and mutated fixture records go through the mapper. Whatever comes in,
the events that come out must be ones troupe's host accepts: valid, init first, every tool result
after its call, nothing after the result, and each within the event limit.
"""

import json
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from claude_harness import FIXTURES, recording, validator
from troupe_runner_claude_code.mapping import Event, Mapper, event_size

RUN_ID = "00000000-0000-4000-8000-0000000000aa"
EVENT = validator("run-event.schema.json#/$defs/event")

_RECORDS: list[dict[str, Any]] = [
    json.loads(line["transcript"])
    for name in sorted(path.name for path in FIXTURES.iterdir() if path.is_dir())
    for line in recording(name)
    if "transcript" in line
]

_JSON = st.recursive(
    st.none()
    | st.booleans()
    | st.integers(min_value=-(2**63), max_value=2**63)
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(max_size=40),
    lambda children: (
        st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=12), children, max_size=5)
    ),
    max_leaves=12,
)


_LONG_TEXT = st.text(min_size=700, max_size=3000)
"""Longer than the smallest event limit the test uses, so cutting to fit is exercised."""


@st.composite
def _mutated(draw: st.DrawFn) -> dict[str, Any]:
    """A fixture record with some keys dropped or replaced, at the top or one level down."""
    record: dict[str, Any] = json.loads(json.dumps(draw(st.sampled_from(_RECORDS))))
    for _ in range(draw(st.integers(0, 3))):
        target = record
        if draw(st.booleans()):
            nested = [k for k, v in record.items() if isinstance(v, dict) and v]
            if nested:
                target = record[draw(st.sampled_from(sorted(nested)))]
        key = draw(st.sampled_from(sorted(target)))
        if draw(st.booleans()):
            del target[key]
        else:
            target[key] = draw(_JSON | _LONG_TEXT)
        if not target:
            break
    return record


_LONG_SUMMARIES = st.one_of(
    _LONG_TEXT.map(
        lambda text: {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}
    ),
    _LONG_TEXT.map(
        lambda text: {"type": "result", "subtype": "success", "is_error": True, "result": text}
    ),
    _LONG_TEXT.map(
        lambda text: {
            "type": "system",
            "subtype": "api_retry",
            "attempt": 1,
            "retry_delay_ms": 1,
            "error_status": None,
            "error": text,
        }
    ),
)
"""Records whose summary field is longer than the smallest event limit."""

_LINE = (
    st.binary(max_size=64)
    | _JSON.map(lambda value: json.dumps(value).encode())
    | _mutated().map(lambda record: json.dumps(record, ensure_ascii=False).encode())
    | st.sampled_from(_RECORDS).map(lambda record: json.dumps(record).encode())
    | _LONG_SUMMARIES.map(lambda record: json.dumps(record).encode())
)


@given(
    lines=st.lists(_LINE, max_size=12),
    limit=st.sampled_from([600, 2048, 65536]),
    exit_status=st.none() | st.integers(-15, 255),
)
def test_whatever_claude_code_writes_the_events_are_ones_the_host_accepts(
    lines: list[bytes], limit: int, exit_status: int | None
) -> None:
    mapper = Mapper("0.0.1", limit)
    outs = [out for line in lines for out in mapper.feed(line)]
    outs.extend(mapper.finish(exit_status))
    events = [out.event for out in outs if isinstance(out, Event)]
    calls: set[str] = set()
    for seq, event in enumerate(events):
        numbered = {"runId": RUN_ID, "seq": seq, **event}
        errors = [error.message for error in EVENT.iter_errors(numbered)]
        assert errors == [], (seq, event)
        assert (event["type"] == "init") == (seq == 0)
        # An init has no summary to cut (mapping.SUMMARY_FIELDS); troupe stores it out of line.
        assert event_size(event) <= limit or event["type"] == "init", event
        if event["type"] == "tool_call":
            calls.add(event["callId"])
        if event["type"] == "tool_result":
            assert event["callId"] in calls
        if event["type"] == "result":
            assert seq == len(events) - 1
