"""What test_openai_stream.py and test_openai_stream_integration.py share."""

from pathlib import Path

import httpx2

from troupe_runner_openai.service import Service, parse_endpoint
from troupe_runner_openai.stream import Reply as Parsed
from troupe_runner_openai.stream import ReplyReader

DATA = Path(__file__).parent / "data"
OPENAI = DATA / "openai-responses-loop"
OLLAMA = DATA / "ollama-responses-loop"


class _Body:
    """The body the next response is: what _service's transport answers every request with."""

    data = b""


def _answer(_: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=_Body.data)


_SERVICE = Service(
    parse_endpoint("http://127.0.0.1:9/v1"), None, transport=httpx2.MockTransport(_answer)
)
"""The library reading a body held in memory, through the runner's line cap: the stream as the
runner reads it, without a socket (openai-library design D4)."""


def _read(data: bytes) -> Parsed:
    """The reply ``data`` reads as, through the library, or the error reading it raises."""
    _Body.data = data
    reader = ReplyReader()
    for each in _SERVICE.stream({"model": "m", "stream": True}).events:
        if reader.feed(each):
            break
    return reader.reply()
