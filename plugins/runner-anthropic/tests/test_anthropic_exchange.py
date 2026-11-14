"""One exchange with the service: classify's one table, retry_after, and exchange's retries and
transcript, driven through a stub ``open_`` with no network (spec: anthropic-runner, "Transient
failures are retried by the runner, not the library", "A rate limit's Retry-After is honoured within
a named cap", "Failures retrying can't fix end the run at once", "An endpoint or service that can't
serve the run is a configuration failure", "A broken stream is retried as a network failure", "A
reply the runner can't read ends the run", "A context-length refusal ends the run with
context-length", "Redirects are never followed", "The transcript is what the library exposes";
design D7, D8, D10, D11).

The stub stands where Service.stream does: it raises the service module's failures, or returns an
Opened whose events are the dicts the library's ``to_dict`` would give. That the real Service turns
the library's errors into these is test_anthropic_service's to show; what a run does with an
ExchangeFailedError is the loop's."""

import email.utils
import json
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

import pytest

from fake_messages import error_body, event, finish, start, text_block, tool_block
from troupe_runner_anthropic.exchange import (
    ExchangeFailedError,
    Retry,
    StoppedError,
    classify,
    exchange,
    retry_after,
)
from troupe_runner_anthropic.service import (
    NetworkError,
    NotAStreamError,
    Opened,
    StatusError,
    UnreadableError,
)

URL = "http://127.0.0.1:1234/v1/messages"
PARAMS: Mapping[str, Any] = {"model": "m", "max_tokens": 16, "messages": []}


def _status(
    status: int,
    error_type: str | None = None,
    message: str | None = "it failed",
    headers: Mapping[str, str] | None = None,
    in_stream: bool = False,
) -> StatusError:
    body = error_body(error_type, message or "") if error_type is not None else b"<html>nope</html>"
    return StatusError(status, headers or {}, body, error_type, message, in_stream)


def _reply_events(text: str = "Done.") -> list[dict[str, Any]]:
    return [start(), *text_block(0, text), *finish("end_turn")]


def _opened(
    events: Sequence[dict[str, Any]],
    raises: Exception | None = None,
    headers: dict[str, str] | None = None,
) -> Opened:
    def stream() -> Iterator[dict[str, Any]]:
        yield from events
        if raises is not None:
            raise raises

    return Opened(200, headers or {"content-type": "text/event-stream"}, stream())


Step = Opened | Exception


class Run:
    """One exchange against a script of steps: each attempt takes the next, raising it if it's an
    exception, else returning it. Keeps the retries, records, waits and calls seen."""

    def __init__(
        self, script: Sequence[Step], stop_wait: bool = False, begins: Sequence[bool] = ()
    ) -> None:
        self.script = list(script)
        self.sent: list[Mapping[str, Any]] = []
        self.retries: list[Retry] = []
        self.records: list[tuple[str, bytes]] = []
        self.waits: list[float] = []
        self.calls: list[str] = []
        """``begin``, ``open`` and ``end``, in the order exchange called them."""
        self.stop_wait = stop_wait
        self.begins = list(begins)

    def _open(self, params: Mapping[str, Any]) -> Opened:
        self.calls.append("open")
        self.sent.append(params)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    def _wait(self, seconds: float) -> bool:
        self.waits.append(seconds)
        return self.stop_wait

    def _begin(self) -> bool:
        self.calls.append("begin")
        return self.begins.pop(0) if self.begins else True

    def __call__(self, **limits: Any) -> Any:  # noqa: ANN401 - the Reply, or what it raises
        return exchange(
            self._open,
            PARAMS,
            URL,
            self.retries.append,
            lambda kind, data: self.records.append((kind, data)),
            self._wait,
            begin=self._begin,
            end=lambda: self.calls.append("end"),
            **limits,
        )

    @property
    def kinds(self) -> list[str]:
        return [kind for kind, _ in self.records]

    def notes(self) -> list[dict[str, Any]]:
        return [json.loads(data) for kind, data in self.records if kind == "note"]


def _failure(run: Run, **limits: Any) -> ExchangeFailedError:  # noqa: ANN401
    with pytest.raises(ExchangeFailedError) as raised:
        run(**limits)
    return raised.value


# classify: the one table (Requirement: Failures retrying can't fix end the run at once)


def _classified(failure: StatusError) -> ExchangeFailedError:
    with pytest.raises(ExchangeFailedError) as raised:
        classify(failure, URL)
    return raised.value


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_a_redirect_is_configuration_naming_the_status_and_location(status: int) -> None:
    """Requirement: Redirects are never followed."""
    failure = _classified(
        _status(status, headers={"Location": "https://elsewhere.example/v1/messages"})
    )
    assert failure.reason == "configuration"
    assert f"HTTP {status}" in failure.message
    assert "https://elsewhere.example/v1/messages" in failure.message


def test_a_redirect_without_a_location_says_so() -> None:
    assert "(no Location)" in _classified(_status(307)).message


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (401, "authentication_error"),
        (403, "permission_error"),
        (401, None),
        (403, None),
        (400, "authentication_error"),
        (400, "permission_error"),
    ],
)
def test_a_refused_credential_is_authentication_holding_the_services_message(
    status: int, error_type: str | None
) -> None:
    """Scenario "A rejected credential"."""
    failure = _classified(_status(status, error_type, "invalid x-api-key"))
    assert failure.reason == "authentication"
    assert "invalid x-api-key" in failure.message
    assert f"HTTP {status}" in failure.message


@pytest.mark.parametrize(
    ("status", "error_type"), [(402, "billing_error"), (402, None), (400, "billing_error")]
)
def test_an_account_that_cant_pay_is_quota(status: int, error_type: str | None) -> None:
    """Scenario "Out of credit"."""
    failure = _classified(_status(status, error_type, "credit balance too low"))
    assert failure.reason == "quota"
    assert "credit balance too low" in failure.message


def test_a_rate_limit_is_retryable_with_the_wait_retry_after_ms_asks() -> None:
    retryable = classify(_status(429, "rate_limit_error", "slow down", {"retry-after-ms": "1500"}))
    assert (retryable.reason, retryable.wait) == ("rate-limit", 1.5)
    assert retryable.message == "HTTP 429 rate_limit_error: slow down"


def test_a_rate_limit_is_retryable_with_the_wait_retry_after_asks() -> None:
    retryable = classify(_status(429, "rate_limit_error", "slow down", {"Retry-After": "2"}))
    assert (retryable.reason, retryable.wait) == ("rate-limit", 2.0)


def test_a_rate_limit_error_event_in_a_stream_is_a_rate_limit() -> None:
    retryable = classify(_status(200, "rate_limit_error", "slow down", in_stream=True))
    assert (retryable.reason, retryable.wait) == ("rate-limit", None)


def test_a_404_without_the_apis_error_shape_is_configuration_naming_the_url() -> None:
    """Scenario "Nothing at the endpoint's path"."""
    failure = _classified(_status(404, None, None))
    assert failure.reason == "configuration"
    assert URL in failure.message
    assert "base URL" in failure.message


def test_a_404_with_an_error_type_is_configuration_about_the_model() -> None:
    """Scenario "A model the service doesn't have"."""
    failure = _classified(_status(404, "not_found_error", "model: claude-nope"))
    assert failure.reason == "configuration"
    assert "model: claude-nope" in failure.message
    assert URL not in failure.message


@pytest.mark.parametrize(
    ("status", "error_type"),
    [(500, "api_error"), (529, "overloaded_error"), (503, None), (599, None)],
)
def test_a_5xx_is_retryable_as_server(status: int, error_type: str | None) -> None:
    retryable = classify(_status(status, error_type, "boom", {"retry-after": "7"}))
    assert (retryable.reason, retryable.wait) == ("server", 7.0)
    assert f"HTTP {status}" in retryable.message


@pytest.mark.parametrize("error_type", ["overloaded_error", "api_error"])
def test_a_stream_error_event_with_a_server_type_is_retryable_as_server(error_type: str) -> None:
    """Scenario "An error event mid-stream"."""
    retryable = classify(_status(200, error_type, "Overloaded", in_stream=True))
    assert retryable.reason == "server"
    assert retryable.message == f"an error event in the reply's stream, {error_type}: Overloaded"


def test_a_stream_error_event_of_another_type_is_other() -> None:
    assert (
        _classified(_status(200, "invalid_request_error", "bad", in_stream=True)).reason == "other"
    )


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (400, "invalid_request_error"),
        (413, "request_too_large"),
        (422, None),
        (400, None),
        (200, None),
    ],
)
def test_a_client_error_the_table_doesnt_name_is_other_holding_status_type_and_message(
    status: int, error_type: str | None
) -> None:
    failure = _classified(_status(status, error_type, "the service said no"))
    assert failure.reason == "other"
    assert f"HTTP {status}" in failure.message
    assert "the service said no" in failure.message
    if error_type is not None:
        assert error_type in failure.message


@pytest.mark.parametrize(
    "failure",
    [
        _status(400, "invalid_request_error", "prompt is too long: 210000 tokens > 200000 maximum"),
        _status(
            200,
            "api_error",
            "The number of tokens to keep from the initial prompt is greater than the context "
            "length",
            in_stream=True,
        ),
        _status(
            500, "api_error", "The number of tokens to keep ... greater than the context length"
        ),
    ],
    ids=["claude", "lm studio in a stream", "lm studio as a 500"],
)
def test_a_context_signal_is_context_length_and_not_retried(failure: StatusError) -> None:
    """Scenarios "Claude's refusal" and "LM Studio's refusal": not a server retry."""
    raised = _classified(failure)
    assert (raised.reason, raised.context) == ("context-length", True)
    assert "longer than the model's context" in raised.message


def test_every_other_failure_has_context_false() -> None:
    assert _classified(_status(400, "invalid_request_error", "bad")).context is False


def test_a_failure_with_no_message_takes_its_body_or_says_none() -> None:
    assert "<html>nope</html>" in _classified(_status(418, None, None)).message
    empty = StatusError(418, {}, b"  ", None, None)
    assert "(no message)" in _classified(empty).message


# retry_after (Requirement: A rate limit's Retry-After is honoured within a named cap)


@pytest.mark.parametrize(
    ("headers", "seconds"),
    [
        ({"retry-after-ms": "2500"}, 2.5),
        ({"retry-after-ms": "250", "retry-after": "9"}, 0.25),
        ({"retry-after-ms": "soon", "retry-after": "9"}, 9.0),
        ({"retry-after-ms": "nan", "retry-after": "9"}, 9.0),
        ({"retry-after-ms": "inf", "retry-after": "9"}, 9.0),
        ({"retry-after-ms": "-5"}, 0.0),
        ({"retry-after": "2"}, 2.0),
        ({"retry-after": " 2.5 "}, 2.5),
        ({"retry-after": "-1"}, 0.0),
        ({"retry-after": "3600"}, 3600.0),
    ],
    ids=repr,
)
def test_retry_after_reads_milliseconds_first_then_seconds(
    headers: dict[str, str], seconds: float
) -> None:
    assert retry_after(headers) == seconds


def test_retry_after_reads_an_http_date_against_now() -> None:
    now = 1_700_000_000.0
    date = email.utils.formatdate(now + 30, usegmt=True)
    assert retry_after({"retry-after": date}, now=now) == 30.0
    assert (
        retry_after({"retry-after": email.utils.formatdate(now - 30, usegmt=True)}, now=now) == 0.0
    )


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"retry-after": "soon"},
        {"retry-after": "inf"},
        {"retry-after": "nan"},
        {"retry-after-ms": "x"},
    ],
    ids=repr,
)
def test_retry_after_is_none_when_absent_or_unreadable(headers: dict[str, str]) -> None:
    assert retry_after(headers) is None


# exchange: success and the transcript (Requirement: The transcript is what the library exposes)


def test_a_reply_is_returned_with_sent_note_and_each_event_received_in_order() -> None:
    events = _reply_events("Done.")
    run = Run(
        [
            _opened(
                events,
                headers={
                    "content-type": "text/event-stream",
                    "request-id": "req_1",
                    "set-cookie": "s",
                },
            )
        ]
    )
    reply = run()
    assert reply.text == "Done."
    assert run.kinds == ["sent", "note", *["received"] * len(events)]
    assert json.loads(run.records[0][1]) == dict(PARAMS)
    assert run.notes() == [
        {"status": 200, "headers": {"content-type": "text/event-stream", "request-id": "req_1"}}
    ]
    assert [json.loads(data) for kind, data in run.records if kind == "received"] == events
    assert run.calls == ["begin", "open", "end"]
    assert run.retries == []
    assert run.waits == []


def test_a_status_failures_note_and_error_body_are_recorded_before_the_retry() -> None:
    failure = _status(
        529,
        "overloaded_error",
        "Overloaded",
        {"retry-after": "1", "anthropic-ratelimit-requests-remaining": "3", "x-other": "o"},
    )
    run = Run([failure, _opened(_reply_events())])
    run()
    assert run.kinds[:4] == ["sent", "note", "received", "note"]
    assert run.notes()[0] == {
        "status": 529,
        "headers": {"anthropic-ratelimit-requests-remaining": "3", "retry-after": "1"},
    }
    assert run.records[2] == ("received", failure.body)


# exchange: retried (Requirement: Transient failures are retried by the runner, not the library)


def test_overloaded_then_success_is_one_server_retry_with_the_backoff_delay() -> None:
    """Scenario "Overloaded, then success"."""
    run = Run([_status(529, "overloaded_error", "Overloaded"), _opened(_reply_events("ok"))])
    assert run().text == "ok"
    assert run.retries == [Retry(1, 5, 1.0, "server", "HTTP 529 overloaded_error: Overloaded")]
    assert run.waits == [1.0]
    assert len(run.sent) == 2
    assert run.calls == ["begin", "open", "end", "begin", "open", "end"]


def test_each_retry_doubles_the_delay_up_to_the_cap() -> None:
    run = Run([_status(500, "api_error", "boom")] * 4 + [_opened(_reply_events())])
    run(base_delay=1.0, max_delay=3.0)
    assert [r.delay_seconds for r in run.retries] == [1.0, 2.0, 3.0, 3.0]
    assert [r.attempt for r in run.retries] == [1, 2, 3, 4]


def test_when_attempts_run_out_the_failure_has_the_last_reason_and_names_the_attempts() -> None:
    """Scenario "Retries run out", with max_attempts counting the first request: three attempts
    are three requests and two retries."""
    run = Run(
        [
            NetworkError("reset"),
            _status(500, "api_error", "boom"),
            _status(500, "api_error", "boom again"),
        ]
    )
    failure = _failure(run, max_attempts=3)
    assert failure.reason == "server"
    assert failure.message == "HTTP 500 api_error: boom again. Gave up after 3 attempts."
    assert [r.reason for r in run.retries] == ["network", "server"]
    assert len(run.sent) == 3


def test_a_rate_limit_waits_what_retry_after_asks() -> None:
    """Scenario "A short wait"."""
    run = Run(
        [
            _status(429, "rate_limit_error", "slow down", {"Retry-After": "2"}),
            _opened(_reply_events()),
        ]
    )
    run()
    assert run.retries == [Retry(1, 5, 2.0, "rate-limit", "HTTP 429 rate_limit_error: slow down")]
    assert run.waits == [2.0]


def test_a_rate_limit_asking_longer_than_the_cap_ends_the_exchange_naming_both() -> None:
    """Scenario "A wait longer than the cap"."""
    run = Run([_status(429, "rate_limit_error", "slow down", {"retry-after": "3600"})])
    failure = _failure(run)
    assert failure.reason == "rate-limit"
    assert "asked to wait 3600 seconds" in failure.message
    assert "(60 seconds)" in failure.message
    assert len(run.sent) == 1
    assert run.retries == []
    assert run.waits == []


def test_a_server_errors_wait_longer_than_the_cap_is_cut_to_the_cap() -> None:
    run = Run([_status(503, None, "down", {"retry-after": "3600"}), _opened(_reply_events())])
    run(max_delay=10.0)
    assert [(r.reason, r.delay_seconds) for r in run.retries] == [("server", 10.0)]
    assert run.waits == [10.0]


def test_a_stream_error_event_with_overloaded_error_is_dropped_and_retried_as_server() -> None:
    """Scenario "An error event mid-stream"."""
    error = _status(200, "overloaded_error", "Overloaded", in_stream=True)
    run = Run([_opened([start()], raises=error), _opened(_reply_events("ok"))])
    assert run().text == "ok"
    assert [r.reason for r in run.retries] == ["server"]
    assert run.kinds[:5] == ["sent", "note", "received", "received", "note"]
    assert run.records[3] == ("received", error.body)


# exchange: a broken stream (Requirement: A broken stream is retried as a network failure)


def test_a_stream_ending_before_message_stop_is_dropped_and_retried_as_network() -> None:
    """Scenario "The connection drops mid-reply": the half tool call isn't in the reply used."""
    half = [start(), *tool_block(0, "toolu_1", "Write", {"file_path": "a.txt"})[:2]]
    run = Run(
        [
            _opened(half),
            _opened(
                [
                    start(),
                    *tool_block(0, "toolu_2", "Read", {"file_path": "b"}),
                    *finish("tool_use"),
                ]
            ),
        ]
    )
    reply = run()
    assert [use.call_id for use in reply.tool_uses] == ["toolu_2"]
    assert [r.reason for r in run.retries] == ["network"]
    dropped = next(i for i, (_, data) in enumerate(run.records) if b'"dropped"' in data)
    assert run.kinds[dropped] == "note"
    assert run.kinds[dropped - 1] == "received"
    assert json.loads(run.records[dropped][1]) == {"dropped": run.retries[0].message}
    assert "before message_stop" in run.retries[0].message


def test_a_stream_that_breaks_or_goes_quiet_is_retried_as_network() -> None:
    """Scenario "The stream goes quiet", as Service.stream reports a read timeout."""
    run = Run(
        [
            _opened([start()], raises=NetworkError("ReadTimeout: timed out")),
            _opened(_reply_events()),
        ]
    )
    run()
    assert [(r.reason, r.message) for r in run.retries] == [("network", "ReadTimeout: timed out")]


def test_a_failed_connection_is_retried_as_network() -> None:
    run = Run([NetworkError("ConnectError: refused"), _opened(_reply_events())])
    run()
    assert [r.reason for r in run.retries] == ["network"]
    assert run.notes()[0] == {"dropped": "ConnectError: refused"}


# exchange: not retried


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (_status(401, "authentication_error", "invalid x-api-key"), "authentication"),
        (_status(402, "billing_error", "no credit"), "quota"),
        (_status(404, None, None), "configuration"),
        (_status(307, headers={"location": "https://elsewhere.example"}), "configuration"),
        (_status(400, "invalid_request_error", "prompt is too long: 2 > 1"), "context-length"),
        (_status(400, "invalid_request_error", "bad"), "other"),
    ],
    ids=["401", "402", "404", "307", "context", "400"],
)
def test_a_failure_retrying_cant_fix_is_sent_once_and_not_retried(
    failure: StatusError, reason: str
) -> None:
    run = Run([failure, _opened(_reply_events("never"))])
    assert _failure(run).reason == reason
    assert len(run.sent) == 1
    assert run.retries == []


def test_a_2xx_that_isnt_a_stream_is_configuration_saying_a_stream_was_asked_for() -> None:
    """Scenario "An answer that isn't a stream"."""
    run = Run([NotAStreamError(200, "application/json", b'{"content": []}')])
    failure = _failure(run)
    assert failure.reason == "configuration"
    assert "application/json" in failure.message
    assert "text/event-stream" in failure.message
    assert run.notes() == [{"status": 200, "headers": {"content-type": "application/json"}}]
    assert run.records[-1] == ("received", b'{"content": []}')


@pytest.mark.parametrize(
    ("script", "words"),
    [
        (
            [_opened([start()], raises=UnreadableError("an event in the reply isn't JSON (x)"))],
            "isn't JSON",
        ),
        (
            [
                _opened(
                    [start(), event("content_block_delta", index=4, delta={"type": "text_delta"})]
                )
            ],
            "never started",
        ),
        ([_opened([start(), *tool_block(0, None, "Read", {}), *finish("tool_use")])], "has no id"),
    ],
    ids=["an event that isn't JSON", "a delta for an unstarted block", "a tool_use without an id"],
)
def test_a_reply_the_runner_cant_read_is_engine_and_not_retried(
    script: list[Step], words: str
) -> None:
    """Requirement: A reply the runner can't read ends the run."""
    run = Run([*script, _opened(_reply_events("never"))])
    failure = _failure(run)
    assert failure.reason == "engine"
    assert failure.message.startswith("The service's reply can't be read: ")
    assert words in failure.message
    assert len(run.sent) == 1
    assert run.retries == []


def test_a_finished_reply_in_the_wrong_shape_keeps_its_usage_for_the_run() -> None:
    script = [_opened([start(), *tool_block(0, "t", None, {}), *finish("tool_use", 9)])]
    assert (_failure(Run(script)).usage or {}).get("output_tokens") == 9


# exchange: stopping


def test_a_stopped_wait_raises_stopped_after_reporting_the_retry() -> None:
    run = Run([_status(500, "api_error", "boom"), _opened(_reply_events())], stop_wait=True)
    with pytest.raises(StoppedError):
        run()
    assert len(run.retries) == 1
    assert len(run.sent) == 1


def test_begin_returning_false_raises_stopped_before_anything_is_opened() -> None:
    run = Run([_opened(_reply_events())], begins=[False])
    with pytest.raises(StoppedError):
        run()
    assert run.sent == []
    assert run.calls == ["begin"]
    assert run.kinds == ["sent"]


def test_begin_returning_false_before_a_retry_raises_stopped_with_one_request_sent() -> None:
    run = Run([_status(500, "api_error", "boom"), _opened(_reply_events())], begins=[True, False])
    with pytest.raises(StoppedError):
        run()
    assert len(run.sent) == 1
    assert run.calls == ["begin", "open", "end", "begin"]
