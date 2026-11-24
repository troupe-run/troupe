"""Parts of one exchange with the service: Retry-After is read as seconds or as an HTTP date, a
response's events are closed when the attempt ends rather than when they're collected, and a 401
whose body never ends, answered by an httpx2 mock transport, is read only to the body limit and
ends as an authentication failure without a retry (spec: openai-runner, "A rate limit's
Retry-After is honoured within a named cap", "Failures retrying can't fix end the run at once",
"A body read whole stops at a named limit", "An error that never ends").

Its tests that start a process, open a socket or use a git theatre are in
integration/test_openai_exchange.py."""

from collections.abc import Iterator
from typing import Any

import httpx2
import pytest

from fake_endpoint import (
    final,
    message,
    usage,
)
from openai_exchange_shared import KEY, PARAMS
from troupe_runner_openai.exchange import (
    ExchangeFailedError,
    Retry,
    exchange,
    retry_after,
)
from troupe_runner_openai.failures import Opened
from troupe_runner_openai.service import Service, parse_endpoint

# Retry-After


@pytest.mark.parametrize(
    ("value", "seconds"),
    [("2", 2.0), ("0.5", 0.5), ("-3", 0.0), (None, None), ("soon", None), ("nan", None)],
)
def test_retry_after_is_read_as_seconds(value: str | None, seconds: float | None) -> None:
    assert retry_after(value) == seconds


def test_retry_after_as_an_http_date_is_the_seconds_until_it() -> None:
    assert retry_after("Wed, 21 Oct 2015 07:28:10 GMT", now=1445412480.0) == 10.0


def test_a_responses_events_are_closed_when_the_attempt_ends_not_when_collected() -> None:
    closed: list[str] = []

    def events(items: list[dict[str, Any]]) -> Any:  # noqa: ANN401 - a generator
        try:
            yield from items
        finally:
            closed.append("closed")

    done = final([message("ok")], used=usage(1, 1))
    held: list[Any] = []

    def open_(_: Any) -> Opened:  # noqa: ANN401 - the parameters
        stream = events([done, {"type": "never.read"}])
        held.append(stream)  # kept alive, so only an explicit close can run its finally
        return Opened(200, {}, stream)

    reply = exchange(
        open_,
        PARAMS,
        "http://x/v1/responses",
        lambda _: None,
        lambda *_: None,
        lambda _: False,
        on_lost=lambda *_: None,
    )
    assert reply.text == "ok"
    assert closed == ["closed"]


def test_a_401_whose_body_never_ends_is_read_to_the_limit_and_ends_as_authentication() -> None:
    """Spec: openai-runner, "A body read whole stops at a named limit", "An error that never
    ends" (review of #440)."""
    read: list[int] = []

    def answer(_: httpx2.Request) -> httpx2.Response:
        def body() -> Iterator[bytes]:
            while True:
                read.append(1)
                yield b"short line\n"

        return httpx2.Response(401, headers={"content-type": "text/plain"}, content=body())

    endpoint = parse_endpoint("http://127.0.0.1:9/v1")
    service = Service(endpoint, KEY, transport=httpx2.MockTransport(answer), body_max_bytes=1100)
    retries: list[Retry] = []
    with pytest.raises(ExchangeFailedError) as raised:
        exchange(
            service.stream,
            PARAMS,
            endpoint.responses_url,
            retries.append,
            lambda *_: None,
            lambda _: False,
            on_lost=lambda *_: None,
        )
    assert raised.value.reason == "authentication"
    assert retries == []
    assert len(read) <= 1100 // len(b"short line\n") + 1
