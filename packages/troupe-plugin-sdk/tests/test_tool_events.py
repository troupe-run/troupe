"""Each call is a numbered pair of run events that fits the run's limits (spec: runner-tools, "Each
call and result is a pair of run events", "Run events fit the run's limits"; runner-sdk design
D11)."""

from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from sdk_tools import RUN, call, tools_for, workspace
from troupe_plugin_sdk.effects import Effects
from troupe_plugin_sdk.events import EventNumbering, cut, encoded_size, fit, utf8_size


def test_an_allowed_call_is_a_tool_call_then_a_tool_result_continuing_the_runs_seq(
    tmp_path: Path,
) -> None:
    tools = tools_for(workspace(tmp_path, {"README.md": b"hello\n"}))
    numbering = EventNumbering(RUN, 65536, next_seq=5)

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
    numbering = EventNumbering(RUN, 65536, next_seq=1)

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
    numbering = EventNumbering(RUN, 1000, next_seq=3)
    assert [numbering.take() for _ in range(3)] == [3, 4, 5]
