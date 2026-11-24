"""Reading a streamed Responses API response into one reply (spec: openai-runner, "A broken stream
is retried as a network failure", "A completed reply without tool calls ends the run"; design D4,
D15). Tested on two recorded runs: OpenAI's gpt-6-luna and local Ollama's qwen3.5:4b.

Its tests that stay in their own process are in unit/test_openai_stream.py."""

from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from fake_endpoint import (
    FakeEndpoint,
    Reply,
)
from openai_stream_shared import OLLAMA, OPENAI, _read
from troupe_runner_openai.service import Service, parse_endpoint
from troupe_runner_openai.stream import Reply as Parsed
from troupe_runner_openai.stream import ReplyReader

# However the bytes arrive


def _through_the_network(fake: FakeEndpoint) -> Parsed:
    service = Service(parse_endpoint(fake.endpoint), None)
    try:
        reader = ReplyReader()
        for each in service.stream({"model": "m", "stream": True}).events:
            if reader.feed(each):
                break
        return reader.reply()
    finally:
        service.close()


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    cuts=st.lists(st.integers(min_value=0), max_size=12), which=st.sampled_from([OPENAI, OLLAMA])
)
def test_however_a_recorded_streams_bytes_are_split_into_reads_the_reply_is_the_same(
    cuts: list[int], which: Path
) -> None:
    data = (which / "stream-1.txt").read_bytes()
    points = sorted({c % (len(data) + 1) for c in cuts})
    pieces = [data[a:b] for a, b in zip([0, *points], [*points, len(data)], strict=True)]
    with FakeEndpoint([Reply(chunks=[p for p in pieces if p])]) as fake:
        reply = _through_the_network(fake)
    assert reply == _read(data)
