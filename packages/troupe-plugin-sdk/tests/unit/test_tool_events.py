"""Each call is a numbered pair of run events that fits the run's limits (spec: runner-tools, "Each
call and result is a pair of run events", "Run events fit the run's limits"; runner-sdk design
D11)."""

from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from sdk_tools import RUN, call, no_context, tools_for, workspace
from troupe_plugin_sdk import runner as p
from troupe_plugin_sdk.effects import Effects
from troupe_plugin_sdk.events import EventNumbering, cut, encoded_size, fit, utf8_size


def test_an_allowed_call_is_a_tool_call_then_a_tool_result_continuing_the_runs_seq(
    tmp_path: Path,
) -> None:
    tools = tools_for(workspace(tmp_path, {"README.md": b"hello\n"}))
    numbering = EventNumbering(RUN, 65536, next_seq=5, send_context=no_context)

    step = call(tools, "Read", {"file_path": "README.md"}, numbering, call_id="c1")

    assert step.call.to_data() == {
        "type": "tool_call",
        "runId": RUN,
        "seq": 5,
        "callId": "c1",
        "tool": "Read",
        "inputSummary": '{"file_path":"README.md"}',
    }
    assert (step.result.seq, step.result.call_id, step.result.is_error) == (6, "c1", False)
    assert numbering.next_seq == 7


def test_a_refused_call_is_still_a_pair_with_the_result_an_error(tmp_path: Path) -> None:
    root = workspace(tmp_path, {"out/old.txt": b"x"})
    step = call(tools_for(root, Effects(write=("**",))), "Delete", {"file_path": "out/old.txt"})
    assert (step.call.call_id, step.result.call_id) == ("c1", "c1")
    assert step.result.is_error
    assert step.result.output_summary == step.output


def test_a_grep_returning_over_200kb_fits_event_max_bytes_and_keeps_its_full_size(
    tmp_path: Path,
) -> None:
    padding = b"x" * 480
    lines = b"".join(b"match %03d %s\n" % (n, padding) for n in range(500))
    root = workspace(tmp_path, {"big.txt": lines})
    numbering = EventNumbering(RUN, 65536, next_seq=1, send_context=no_context)

    step = call(tools_for(root), "Grep", {"pattern": "match"}, numbering)

    assert utf8_size(step.output) > 200_000
    assert encoded_size(step.result.to_data()) <= 65536
    assert step.result.output_bytes == utf8_size(step.output)
    assert utf8_size(step.result.output_summary) <= 4096


def test_a_200kb_output_cut_to_a_65536_byte_event_keeps_its_full_size() -> None:
    output = "é" * 100_000  # 200,000 bytes of two-byte characters
    data = {
        "runId": RUN,
        "seq": 7,
        "type": "tool_result",
        "callId": "c1",
        "isError": False,
        "outputSummary": output,
        "outputBytes": utf8_size(output),
    }
    fitted = fit(data, "outputSummary", 10**6, 65536)
    assert encoded_size(fitted) <= 65536
    assert fitted["outputBytes"] == 200_000
    assert fitted["outputSummary"].endswith("bytes left out]")


@given(st.text(max_size=3000), st.integers(1, 6000), st.integers(200, 6000))
def test_fitting_any_text_stays_within_both_limits_and_on_a_character_boundary(
    text: str, summary_limit: int, event_max: int
) -> None:
    data = {"runId": RUN, "seq": 1, "type": "tool_call", "callId": "c", "tool": "Read"}
    fitted = fit({**data, "inputSummary": text}, "inputSummary", summary_limit, event_max)
    assert utf8_size(fitted["inputSummary"]) <= summary_limit
    assert encoded_size(fitted) <= event_max
    fitted["inputSummary"].encode("utf-8")  # whole characters only


@given(st.text(max_size=500), st.integers(0, 600))
def test_cut_keeps_text_that_fits_and_cuts_text_that_doesnt_to_the_limit(
    text: str, limit: int
) -> None:
    result = cut(text, limit)
    if utf8_size(text) <= limit:
        assert result == text
    else:
        assert utf8_size(result) <= limit


def test_the_numbering_hands_out_each_seq_once_in_order() -> None:
    numbering = EventNumbering(RUN, 1000, next_seq=3, send_context=no_context)
    assert [numbering.take() for _ in range(3)] == [3, 4, 5]


# Requirement: A message's strings are Unicode text: each replacement is recorded
# (host-robustness design D3b)


def test_a_lone_surrogate_in_a_calls_input_is_recorded_before_both_of_its_events(
    tmp_path: Path,
) -> None:
    root = workspace(tmp_path, {"a.txt": b"one\n"})
    sent: list[object] = []
    numbering = EventNumbering(RUN, 65536, next_seq=1, send_context=sent.append)
    step = call(tools_for(root), "Grep", {"pattern": "x\ud800"}, numbering)
    (context,) = sent
    assert isinstance(context, p.ContextEvent)
    assert (context.seq, context.kind, context.by) == (1, "other", "runner")
    assert "1 lone surrogate in the input of a 'Grep' tool call was replaced" in context.message
    assert (step.call.seq, step.result.seq) == (2, 3)
    assert "�" in step.call.input_summary


def test_a_lone_surrogate_escaped_in_a_calls_json_text_is_written_as_u_fffd_and_recorded(
    tmp_path: Path,
) -> None:
    # The escape is only a surrogate once the input's text is parsed (review of #437).
    root = workspace(tmp_path)
    sent: list[object] = []
    numbering = EventNumbering(RUN, 65536, next_seq=1, send_context=sent.append)
    arguments = '{"file_path": "a.txt", "content": "x\\ud800y"}'
    step = call(tools_for(root, Effects(write=("**",))), "Write", arguments, numbering)
    assert not step.is_error, step.output
    assert (root / "a.txt").read_text(encoding="utf-8") == "x�y"
    (context,) = sent
    assert isinstance(context, p.ContextEvent)
    assert "1 lone surrogate in the input of a 'Write' tool call was replaced" in context.message
    assert (context.seq, step.call.seq, step.result.seq) == (1, 2, 3)


def test_a_lone_surrogate_in_a_call_id_is_recorded_before_both_events_in_seq_order(
    tmp_path: Path,
) -> None:
    # Review of #437: the id is in both events, so it's cleaned once, before either is numbered.
    root = workspace(tmp_path, {"a.txt": b"one\n"})
    sent: list[p.RunEvent] = []
    numbering = EventNumbering(RUN, 65536, next_seq=1, send_context=sent.append)
    step = call(tools_for(root), "Read", {"file_path": "a.txt"}, numbering, call_id="c\ud800")
    sent += list(step.events)
    assert [event.seq for event in sent] == [1, 2, 3]
    assert isinstance(sent[0], p.ContextEvent)
    assert "1 lone surrogate in the id of a 'Read' tool call was replaced" in sent[0].message
    assert step.call.call_id == step.result.call_id == "c�"
