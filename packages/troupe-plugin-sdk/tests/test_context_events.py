"""The SDK builds a context event numbered and fitted to the run's limits (spec: plugin-sdk,
"The SDK builds a context event fitted to the run's limits"; context-event design D7)."""

from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from runner_schemas import validate
from troupe_plugin_sdk import runner as p
from troupe_plugin_sdk.events import EventNumbering, context_event, encoded_size, utf8_size

RUN = "0f8fad5b-d9cb-469f-a165-70867728950e"
EVENT = "run-event.schema.json#/$defs/event"


def test_a_compaction_with_only_tokens_before_takes_the_next_seq_and_carries_only_it() -> None:
    numbering = EventNumbering(RUN, 65536, next_seq=4)

    event = context_event(numbering, "compacted", "engine", "compacted", tokens_before=41000)

    assert event.to_data() == {
        "runId": RUN,
        "seq": 4,
        "type": "context",
        "kind": "compacted",
        "by": "engine",
        "message": "compacted",
        "tokensBefore": 41000,
    }
    validate(event.to_data(), EVENT)
    assert numbering.next_seq == 5


def test_a_runner_that_counts_its_messages_sends_both_counts() -> None:
    numbering = EventNumbering(RUN, 65536, next_seq=1)
    event = context_event(
        numbering, "truncated", "runner", "dropped", messages_before=120, messages_after=34
    )
    assert (event.messages_before, event.messages_after, event.tokens_before) == (120, 34, None)
    assert "tokensBefore" not in event.to_data()


def test_a_message_over_the_summary_limit_is_cut_on_a_character_boundary_saying_how_much() -> None:
    numbering = EventNumbering(RUN, 65536, next_seq=1, summary_max_bytes=40)
    message = "é" * 100

    event = context_event(numbering, "compacted", "engine", message)

    assert utf8_size(event.message) <= 40
    assert event.message.startswith("é")
    assert event.message.endswith("bytes left out]")
    validate(event.to_data(), EVENT)


def test_a_message_that_would_overflow_the_event_is_cut_until_the_event_fits() -> None:
    numbering = EventNumbering(RUN, 300, next_seq=1)
    event = context_event(numbering, "other", "runner", "x" * 5000, tokens_before=1)
    assert encoded_size(event.to_data()) <= 300
    assert event.message.endswith("bytes left out]")


@pytest.mark.parametrize(
    ("kind", "by", "match"),
    [("pruned", "engine", "'pruned'"), ("compacted", "host", "'host'")],
)
def test_a_kind_or_by_off_the_list_raises_naming_it_and_leaves_the_counter(
    kind: str, by: str, match: str
) -> None:
    numbering = EventNumbering(RUN, 65536, next_seq=3)
    with pytest.raises(p.ProtocolError, match=match):
        context_event(numbering, kind, by, "m")  # type: ignore[arg-type]
    assert numbering.next_seq == 3


def test_a_negative_count_raises_and_leaves_the_counter() -> None:
    numbering = EventNumbering(RUN, 65536, next_seq=3)
    with pytest.raises(p.ProtocolError, match="tokensAfter"):
        context_event(numbering, "compacted", "engine", "m", tokens_after=-1)
    assert numbering.next_seq == 3


COUNT = st.none() | st.integers(0, 10**9)


@settings(max_examples=200, deadline=None)
@given(
    kind=st.sampled_from(["compacted", "truncated", "other"]),
    by=st.sampled_from(["engine", "runner"]),
    message=st.text(max_size=3000),
    counts=st.tuples(COUNT, COUNT, COUNT, COUNT),
    event_max_bytes=st.integers(260, 4096),
    summary_max_bytes=st.integers(1, 4096),
)
def test_any_message_and_counts_give_an_event_that_validates_and_fits(
    kind: Any,  # noqa: ANN401 - one of the contract's kinds
    by: Any,  # noqa: ANN401 - one of the contract's values
    message: str,
    counts: tuple[int | None, int | None, int | None, int | None],
    event_max_bytes: int,
    summary_max_bytes: int,
) -> None:
    numbering = EventNumbering(RUN, event_max_bytes, 7, summary_max_bytes)
    tokens_before, tokens_after, messages_before, messages_after = counts

    event = context_event(
        numbering,
        kind,
        by,
        message,
        tokens_before=tokens_before,
        tokens_after=tokens_after,
        messages_before=messages_before,
        messages_after=messages_after,
    )

    data = event.to_data()
    validate(data, EVENT)
    assert encoded_size(data) <= event_max_bytes
    assert utf8_size(event.message) <= summary_max_bytes
    assert [data.get(k) for k in ("tokensBefore", "tokensAfter", "messagesBefore")] == list(
        counts[:3]
    )
    assert data.get("messagesAfter") == messages_after
    assert numbering.next_seq == 8
