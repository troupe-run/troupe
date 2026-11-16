"""The SDK builds a context event numbered and fitted to the run's limits (spec: plugin-sdk,
"The SDK builds a context event fitted to the run's limits"; context-event design D7)."""

from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from runner_schemas import validate
from sdk_tools import no_context
from troupe_plugin_sdk import runner as p
from troupe_plugin_sdk.events import EventNumbering, context_event, encoded_size, utf8_size

RUN = "0f8fad5b-d9cb-469f-a165-70867728950e"
EVENT = "run-event.schema.json#/$defs/event"


def test_a_compaction_with_only_tokens_before_takes_the_next_seq_and_carries_only_it() -> None:
    numbering = EventNumbering(RUN, 65536, next_seq=4, send_context=no_context)

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
    numbering = EventNumbering(RUN, 65536, next_seq=1, send_context=no_context)
    event = context_event(
        numbering, "truncated", "runner", "dropped", messages_before=120, messages_after=34
    )
    assert (event.messages_before, event.messages_after, event.tokens_before) == (120, 34, None)
    assert "tokensBefore" not in event.to_data()


def test_a_message_over_the_summary_limit_is_cut_on_a_character_boundary_saying_how_much() -> None:
    numbering = EventNumbering(
        RUN, 65536, next_seq=1, summary_max_bytes=40, send_context=no_context
    )
    message = "é" * 100

    event = context_event(numbering, "compacted", "engine", message)

    assert utf8_size(event.message) <= 40
    assert event.message.startswith("é")
    assert event.message.endswith("bytes left out]")
    validate(event.to_data(), EVENT)


def test_a_message_that_would_overflow_the_event_is_cut_until_the_event_fits() -> None:
    numbering = EventNumbering(RUN, 300, next_seq=1, send_context=no_context)
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
    numbering = EventNumbering(RUN, 65536, next_seq=3, send_context=no_context)
    with pytest.raises(p.ProtocolError, match=match):
        context_event(numbering, kind, by, "m")  # type: ignore[arg-type]
    assert numbering.next_seq == 3


def test_a_negative_count_raises_and_leaves_the_counter() -> None:
    numbering = EventNumbering(RUN, 65536, next_seq=3, send_context=no_context)
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
    numbering = EventNumbering(RUN, event_max_bytes, 7, summary_max_bytes, send_context=no_context)
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


# Requirement: A message's strings are Unicode text: a runner records each replacement
# (host-robustness design D3b)


def _numbering(sent: list[p.RunEvent]) -> EventNumbering:
    return EventNumbering(RUN, 65536, send_context=sent.append)


def test_an_event_holding_a_lone_surrogate_follows_a_context_event_naming_it() -> None:
    sent: list[p.RunEvent] = []
    numbering = _numbering(sent)
    init = numbering.numbered({"type": "init", "runner": {"name": "x", "version": "1"}})
    turn = numbering.numbered({"type": "turn", "role": "assistant", "text": "a\ud800b\udfff"})
    assert init["seq"] == 0
    assert [(e.TYPE, e.seq) for e in sent] == [("context", 1)]
    context = sent[0]
    assert isinstance(context, p.ContextEvent)
    assert (context.kind, context.by) == ("other", "runner")
    assert context.message == (
        "The engine's text wasn't Unicode: 2 lone surrogates in the turn event's text were "
        "replaced with U+FFFD."
    )
    assert (turn["seq"], turn["text"]) == (2, "a�b�")
    assert numbering.next_seq == 3


def test_a_replacement_before_init_is_recorded_just_after_init() -> None:
    sent: list[p.RunEvent] = []
    numbering = _numbering(sent)
    numbering.lost("Ollama's answer", 1)
    init = numbering.numbered({"type": "init", "runner": {"name": "x\ud800", "version": "1"}})
    assert (init["seq"], init["runner"]["name"]) == (0, "x�")
    assert sent == []  # a context event can't come before init
    log = numbering.numbered({"type": "log", "level": "info", "message": "m"})
    assert [(e.TYPE, e.seq) for e in sent] == [("context", 1), ("context", 2)]
    assert "1 lone surrogate in Ollama's answer was replaced" in sent[0].message  # type: ignore[attr-defined]
    assert "the init event's runner.name" in sent[1].message  # type: ignore[attr-defined]
    assert log["seq"] == 3


def test_an_event_with_nothing_replaced_is_numbered_as_before() -> None:
    sent: list[p.RunEvent] = []
    numbering = _numbering(sent)
    numbering.numbered({"type": "init", "runner": {"name": "x", "version": "1"}})
    body = {"type": "log", "level": "info", "message": "é \U0001f600"}
    log = numbering.numbered(body)
    assert sent == []
    assert log == {"runId": RUN, "seq": 1, **body}


def test_replacements_reported_for_the_same_place_are_one_context_event() -> None:
    # A streamed answer reports each delta; the run gets one event per place (review of #437).
    sent: list[p.RunEvent] = []
    numbering = _numbering(sent)
    numbering.numbered({"type": "init", "runner": {"name": "x", "version": "1"}})
    for replaced in (1, 2, 3):
        numbering.lost("Ollama's answer", replaced)
    numbering.lost("Ollama's error", 1)
    numbering.numbered({"type": "log", "level": "info", "message": "m"})
    messages = [e.message for e in sent if isinstance(e, p.ContextEvent)]
    assert len(messages) == 2
    assert "6 lone surrogates in Ollama's answer were replaced" in messages[0]
    assert "1 lone surrogate in Ollama's error was replaced" in messages[1]


def test_a_numbering_without_a_way_to_record_a_replacement_fails_when_its_built() -> None:
    # Owner, 2026-11-17: a runner can't forget it; caught where it's written, never mid-run.
    with pytest.raises(TypeError, match="send_context"):
        EventNumbering(RUN, 65536, next_seq=1)  # type: ignore[call-arg]
