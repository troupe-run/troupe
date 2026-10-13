"""The segment line codec (spec: event-store, "Events are stored as mergeable text" and "Event IDs
are content hashes that ignore lineage"; design D3)."""

import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from event_schemas import is_valid
from troupe.core import strict_json
from troupe.core.errors import TroupeError
from troupe_store_text.codec import Header, Record, content_id, decode, encode_event, encode_header

PATH = Path("segment.jsonl")
BATCH = ("01K7ZX3N8V4Q2M6R9T5W1Y0B3C", 0, 1)
PARENT = "sha256:" + "ab" * 32

streams = st.uuids() | st.text(min_size=1, max_size=20)
topics = st.text(min_size=1, max_size=30)
versions = st.integers(min_value=-(2**40), max_value=2**40)
json_leaf = (
    st.none()
    | st.booleans()
    | st.integers()
    | st.text(max_size=10)
    | st.floats(allow_nan=False, allow_infinity=False)
)
payloads = st.dictionaries(
    st.text(max_size=8),
    st.recursive(
        json_leaf,
        lambda inner: (
            st.lists(inner, max_size=3) | st.dictionaries(st.text(max_size=5), inner, max_size=3)
        ),
        max_leaves=8,
    ),
    max_size=5,
)


def canonical(payload: dict[str, Any]) -> bytes:
    return strict_json.dumps(payload).encode("utf-8")


def record_of(line: bytes) -> Record:
    decoded = decode(line, PATH, 7)
    assert isinstance(decoded, Record)
    return decoded


@given(streams, versions, topics, st.binary(max_size=300))
def test_any_state_bytes_round_trip_exactly(
    stream: UUID | str, version: int, topic: str, state: bytes
) -> None:
    event_id, line = encode_event(stream, version, topic, (PARENT,), state, BATCH)
    record = record_of(line)
    assert record.state == state
    assert (record.id, record.stream, record.version, record.topic) == (
        event_id,
        stream,
        version,
        topic,
    )
    assert record.parents == (PARENT,)


@given(payloads)
def test_a_canonical_json_state_is_written_inline_and_the_line_is_strict_json(
    payload: dict[str, Any],
) -> None:
    _, line = encode_event(uuid4(), 1, "t", (), canonical(payload), BATCH)
    assert line.endswith(b"\n")
    assert line.count(b"\n") == 1
    data = strict_json.loads(line)
    assert isinstance(data, dict)
    assert data["state"] == payload
    assert "state_b64" not in data


def test_a_non_canonical_state_is_kept_as_base64_so_its_bytes_survive() -> None:
    state = b'{"b": 1, "a": 2}'
    _, line = encode_event("s", 1, "t", (), state, BATCH)
    data = json.loads(line)
    assert "state_b64" in data
    assert record_of(line).state == state


@given(payloads, payloads, st.text(max_size=20), st.text(max_size=20))
def test_the_id_ignores_lineage_and_time(
    payload: dict[str, Any], lineage_a: dict[str, Any], time_a: str, time_b: str
) -> None:
    body = {k: v for k, v in payload.items() if k not in ("lineage", "timestamp")}
    stream = uuid4()
    first = canonical({**body, "lineage": lineage_a, "timestamp": time_a})
    second = canonical({**body, "lineage": {"actor": {"kind": "unknown"}}, "timestamp": time_b})
    assert content_id(stream, 3, "t", (PARENT,), first) == content_id(
        stream, 3, "t", (PARENT,), second
    )


@given(payloads, st.sampled_from(["stream", "version", "topic", "parents", "payload"]))
def test_the_id_changes_with_every_content_field(payload: dict[str, Any], field: str) -> None:
    body = {k: v for k, v in payload.items() if k not in ("lineage", "timestamp")}
    base: dict[str, Any] = {
        "stream": "s",
        "version": 1,
        "topic": "t",
        "parents": (PARENT,),
        "state": canonical(body),
    }
    changed = dict(base)
    if field == "stream":
        changed["stream"] = "s2"
    elif field == "version":
        changed["version"] = 2
    elif field == "topic":
        changed["topic"] = "t2"
    elif field == "parents":
        changed["parents"] = ()
    else:
        changed["state"] = canonical({**body, "__changed__": True})
    assert content_id(**base) != content_id(**changed)


def test_the_parent_order_doesnt_change_the_id() -> None:
    other = "sha256:" + "cd" * 32
    state = canonical({"x": 1})
    assert content_id("s", 2, "t", (PARENT, other), state) == content_id(
        "s", 2, "t", (other, PARENT), state
    )


@pytest.mark.parametrize("branch", ["main", None], ids=["on a branch", "with no branch"])
def test_a_header_line_reads_back_and_validates(branch: str | None) -> None:
    header = Header(session="01K7ZX3N8V4Q2M6R9T5W1Y0B3C", vcs="git", branch=branch)
    line = encode_header(header)
    assert decode(line, PATH, 1) == header
    assert is_valid(json.loads(line), "event-record.schema.json")


def test_a_header_written_with_no_branch_leaves_branch_out() -> None:
    line = encode_header(Header(session="01K7ZX3N8V4Q2M6R9T5W1Y0B3C", vcs="git", branch=None))
    assert json.loads(line)["segment"] == {"session": "01K7ZX3N8V4Q2M6R9T5W1Y0B3C", "vcs": "git"}


@pytest.mark.parametrize("branch", [None, ""], ids=["null", "empty"])
def test_a_header_whose_branch_is_null_or_empty_is_refused_naming_file_and_line(
    branch: str | None,
) -> None:
    line = {"format": 1, "segment": {"session": "01K7ZX3N8V4Q2M6R9T5W1Y0B3C", "vcs": "git"}}
    line["segment"]["branch"] = branch  # type: ignore[index]
    assert not is_valid(line, "event-record.schema.json")
    with pytest.raises(TroupeError) as caught:
        decode(json.dumps(line).encode(), PATH, 1)
    assert caught.value.code == "events.malformed-record"
    assert "branch" in caught.value.problem
    assert caught.value.path == str(PATH.absolute())
    assert caught.value.details["line"] == 1


def test_crlf_line_endings_are_accepted() -> None:
    _, line = encode_event("s", 1, "t", (), canonical({"x": 1}), BATCH)
    assert record_of(line.replace(b"\n", b"\r\n")).state == canonical({"x": 1})


# Strict reading: a duplicate key or a non-finite number anywhere in a line is refused.


def render(value: object, objects: list[int], target: int, mutation: str) -> str:
    """JSON text for ``value``. The ``target``-th object (in document order) gets ``mutation``:
    its first key repeated, or a NaN, Infinity or -Infinity added under a fresh key."""
    if isinstance(value, dict):
        index = len(objects)
        objects.append(index)
        parts = [
            f"{json.dumps(k)}:{render(v, objects, target, mutation)}" for k, v in value.items()
        ]
        if index == target:
            if mutation == "duplicate" and value:
                first = next(iter(value))
                parts.append(f"{json.dumps(first)}:{json.dumps(value[first])}")
            elif mutation != "duplicate":
                parts.append(f'"__extra__":{mutation}')
        return "{" + ",".join(parts) + "}"
    if isinstance(value, list):
        return "[" + ",".join(render(v, objects, target, mutation) for v in value) + "]"
    return json.dumps(value)


def object_count(value: object) -> int:
    if isinstance(value, dict):
        return 1 + sum(object_count(v) for v in value.values())
    if isinstance(value, list):
        return sum(object_count(v) for v in value)
    return 0


@given(payloads, st.data(), st.sampled_from(["duplicate", "NaN", "Infinity", "-Infinity"]))
def test_a_duplicate_key_or_non_finite_number_anywhere_is_refused_and_the_clean_line_reads(
    payload: dict[str, Any], data: st.DataObject, mutation: str
) -> None:
    _, line = encode_event(uuid4(), 1, "t", (PARENT,), canonical(payload), BATCH)
    parsed = json.loads(line)
    target = data.draw(st.integers(min_value=0, max_value=object_count(parsed) - 1))
    clean = render(parsed, [], -1, mutation).encode("utf-8") + b"\n"
    assert record_of(clean).state == canonical(payload)
    broken = render(parsed, [], target, mutation).encode("utf-8") + b"\n"
    if broken == clean:  # an empty object has no first key to repeat
        return
    with pytest.raises(TroupeError) as caught:
        decode(broken, PATH, 7)
    assert caught.value.code == "events.malformed-record"
    assert caught.value.details["line"] == 7
    assert caught.value.path == str(PATH.absolute())


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"id": "sha256:" + "00" * 32}, id="an id that doesn't match the content"),
        pytest.param({"version": "1"}, id="a string version"),
        pytest.param({"version": True}, id="a boolean version"),
        pytest.param({"parents": ["nope"]}, id="a parent that isn't a hash"),
        pytest.param({"batch": {"id": "x", "index": 1, "size": 1}}, id="an index past the size"),
        pytest.param({"colour": "blue"}, id="an extra field"),
        pytest.param({"stream_type": "int"}, id="an unknown stream type"),
    ],
)
def test_a_line_that_breaks_the_record_rules_is_refused(change: dict[str, Any]) -> None:
    _, line = encode_event("s", 1, "t", (), canonical({"x": 1}), BATCH)
    data = json.loads(line) | change
    with pytest.raises(TroupeError) as caught:
        decode(json.dumps(data).encode(), PATH, 3)
    assert caught.value.code == "events.malformed-record"


def test_an_unknown_format_is_refused_saying_to_upgrade() -> None:
    _, line = encode_event("s", 1, "t", (), canonical({"x": 1}), BATCH)
    data = json.loads(line) | {"format": 2}
    with pytest.raises(TroupeError) as caught:
        decode(json.dumps(data).encode(), PATH, 3)
    assert caught.value.code == "events.unknown-format"
    assert "Upgrade troupe" in caught.value.fix
