"""One exchange with the service: each row of design D8's failure table, against the fake endpoint
(spec: openai-runner, "Transient failures are retried and reported", "A rate limit's
Retry-After is honoured within a named cap", "Failures retrying can't fix end the run at once", "A
broken stream is retried as a network failure", "Redirects are never followed")."""

import json
from typing import Any

import pytest

from fake_endpoint import (
    Cut,
    FakeEndpoint,
    Pause,
    Reply,
    error_event_reply,
    error_reply,
    event,
    function_call,
    sse,
    status_reply,
    text_reply,
    tool_reply,
)
from troupe_runner_openai.exchange import ExchangeFailedError, Retry, exchange, retry_after
from troupe_runner_openai.service import AbortedError, Call, Endpoint, parse_endpoint

KEY = "sk-canary-0123456789"


class Run:
    """One exchange's retries, transcript records and waits, as the runner would see them."""

    def __init__(self, fake: FakeEndpoint | str, **limits: Any) -> None:  # noqa: ANN401
        self.endpoint = fake if isinstance(fake, str) else fake.endpoint
        self.retries: list[Retry] = []
        self.records: list[tuple[str, bytes]] = []
        """Each transcript record: its kind and its bytes."""
        self.waits: list[float] = []
        self.limits = limits

    def __call__(self, stream_timeout: float = 5.0, stop: bool = False) -> Any:  # noqa: ANN401
        def make(endpoint: Endpoint, body: bytes, credential: str | None) -> Call:
            return Call(endpoint, body, credential, stream_timeout=stream_timeout)

        def wait(seconds: float) -> bool:
            self.waits.append(seconds)
            return stop

        return exchange(
            parse_endpoint(self.endpoint),
            b'{"model": "m"}',
            KEY,
            self.retries.append,
            lambda kind, data: self.records.append((kind, data)),
            wait,
            make_call=make,
            **self.limits,
        )


def _failed(run: Run) -> str:
    with pytest.raises(ExchangeFailedError) as raised:
        run()
    return raised.value.message


# Success, and what the transcript keeps


def test_a_reply_is_returned_with_the_request_response_and_lines_recorded_in_order() -> None:
    with FakeEndpoint([text_reply("Done.")]) as fake:
        run = Run(fake)
        reply = run()
    assert reply.text == "Done."
    kinds = [kind for kind, _ in run.records]
    assert kinds[:2] == ["sent", "note"]
    assert set(kinds[2:]) == {"received"}
    assert run.records[0] == ("sent", b'{"model": "m"}')
    assert json.loads(run.records[1][1])["status"] == 200
    *_, named, data, blank = run.records
    assert named == ("received", b"event: response.completed")
    assert data[1].startswith(b'data: {"type": "response.completed"')
    assert blank == ("received", b"")


def test_only_the_named_response_headers_are_kept_and_no_request_header() -> None:
    headers = [("x-request-id", "r1"), ("x-ratelimit-remaining-requests", "9"), ("set-cookie", "s")]
    with FakeEndpoint([Reply(headers=headers, lines=text_reply("ok").lines)]) as fake:
        run = Run(fake)
        run()
    assert json.loads(run.records[1][1])["headers"] == {
        "x-ratelimit-remaining-requests": "9",
        "x-request-id": "r1",
    }
    assert all(b"authorization" not in data.lower() for _, data in run.records)


# Retried


def test_a_server_error_then_success_is_one_server_retry_with_the_backoff_delay() -> None:
    with FakeEndpoint(
        [error_reply(503, "overloaded", kind="server_error"), text_reply("ok")]
    ) as fake:
        run = Run(fake)
        assert run().text == "ok"
    assert run.retries == [Retry(1, 5, 1.0, "server", "HTTP 503: overloaded")]
    assert run.waits == [1.0]
    assert len(fake.requests) == 2


def test_each_retry_doubles_the_delay_up_to_the_cap() -> None:
    script = [error_reply(500, "boom")] * 4 + [text_reply("ok")]
    with FakeEndpoint(script) as fake:
        run = Run(fake, base_delay=1.0, max_delay=3.0)
        run()
    assert [r.delay_seconds for r in run.retries] == [1.0, 2.0, 3.0, 3.0]
    assert [r.attempt for r in run.retries] == [1, 2, 3, 4]


def test_when_the_attempts_run_out_the_failure_names_the_status_and_the_attempts() -> None:
    with FakeEndpoint([error_reply(500, "boom")] * 3) as fake:
        message = _failed(Run(fake, max_attempts=3))
    assert message == "HTTP 500: boom. Gave up after 3 attempts."


def test_a_rate_limit_waits_what_retry_after_asks() -> None:
    reply = error_reply(429, "slow down", kind="requests", headers=[("Retry-After", "2")])
    with FakeEndpoint([reply, text_reply("ok")]) as fake:
        run = Run(fake)
        run()
    assert run.retries == [Retry(1, 5, 2.0, "rate-limit", "HTTP 429: slow down")]


def test_a_rate_limit_asking_longer_than_the_cap_ends_the_exchange_naming_both() -> None:
    reply = error_reply(429, "slow down", headers=[("Retry-After", "3600")])
    with FakeEndpoint([reply]) as fake:
        message = _failed(Run(fake))
    assert "asked to wait 3600 seconds" in message
    assert "60 seconds" in message
    assert len(fake.requests) == 1


def test_a_refused_connection_is_retried_as_network() -> None:
    with FakeEndpoint() as gone:
        endpoint = gone.endpoint
    run = Run(endpoint, max_attempts=2)
    message = _failed(run)
    assert [r.reason for r in run.retries] == ["network"]
    assert endpoint in message


def test_a_stream_cut_mid_tool_call_is_dropped_and_retried_as_network() -> None:
    start = event("response.output_item.added", item=function_call("c1", "Write", '{"fi'))
    broken = Reply(lines=[*sse([start]), Cut()])
    with FakeEndpoint([broken, tool_reply([("c2", "Read", {"file_path": "a"})])]) as fake:
        run = Run(fake)
        reply = run()
    assert [c.call_id for c in reply.tool_calls] == ["c2"]
    assert [r.reason for r in run.retries] == ["network"]
    kinds = [kind for kind, _ in run.records]
    dropped = next(i for i, (kind, data) in enumerate(run.records) if b'"dropped"' in data)
    assert kinds[dropped] == "note"
    assert kinds[dropped - 1] == "received"  # after the broken stream's last line
    assert json.loads(run.records[dropped][1]) == {"dropped": run.retries[0].message}


def test_a_stream_silent_past_the_timeout_is_abandoned_and_retried_as_network() -> None:
    with FakeEndpoint([Reply(lines=sse([Pause(2)])), text_reply("ok")]) as fake:
        run = Run(fake)
        assert run(stream_timeout=0.3).text == "ok"
    assert run.retries[0].reason == "network"
    assert "sent nothing for 0.3 seconds" in run.retries[0].message


def test_a_stop_during_the_retry_delay_ends_the_exchange() -> None:
    with FakeEndpoint([error_reply(500, "boom")]) as fake:
        run = Run(fake)
        with pytest.raises(AbortedError):
            run(stop=True)
    assert len(fake.requests) == 1


def test_a_response_the_service_failed_on_its_side_is_retried_as_server() -> None:
    failed = status_reply("failed", error={"code": "server_error", "message": "boom"})
    with FakeEndpoint([failed, text_reply("ok")]) as fake:
        run = Run(fake)
        assert run().text == "ok"
    assert [(r.reason, r.message) for r in run.retries] == [
        ("server", "The service failed the response (server_error: boom)")
    ]


def test_an_error_event_with_the_services_own_code_is_retried_as_server() -> None:
    with FakeEndpoint([error_event_reply("server_error", "overloaded"), text_reply("ok")]) as fake:
        run = Run(fake)
        assert run().text == "ok"
    assert [r.reason for r in run.retries] == ["server"]


# Not retried


def test_a_response_failed_for_another_reason_isnt_retried_and_names_the_code() -> None:
    failed = status_reply("failed", error={"code": "invalid_prompt", "message": "flagged"})
    with FakeEndpoint([failed]) as fake:
        message = _failed(Run(fake))
    assert message == "The service failed the response (invalid_prompt: flagged)."
    assert len(fake.requests) == 1


def test_a_rejected_credential_isnt_retried_and_names_the_services_message() -> None:
    reply = error_reply(401, "Incorrect API key provided: sk-cana****6789.", code="invalid_api_key")
    with FakeEndpoint([reply]) as fake:
        message = _failed(Run(fake))
    assert message.startswith("The service refused the credential (HTTP 401): Incorrect API key")
    assert len(fake.requests) == 1


def test_a_forbidden_request_is_a_refused_credential_too() -> None:
    with FakeEndpoint([error_reply(403, "model not allowed")]) as fake:
        assert "refused the credential (HTTP 403)" in _failed(Run(fake))


def test_out_of_quota_isnt_retried() -> None:
    reply = error_reply(429, "You exceeded your quota.", code="insufficient_quota")
    with FakeEndpoint([reply]) as fake:
        message = _failed(Run(fake))
    assert message == "The account is out of quota (HTTP 429): You exceeded your quota."
    assert len(fake.requests) == 1


def test_a_context_length_error_isnt_retried() -> None:
    reply = error_reply(
        400, "This model's maximum context length is 8192.", code="context_length_exceeded"
    )
    with FakeEndpoint([reply]) as fake:
        message = _failed(Run(fake))
    assert message.startswith("The conversation is longer than the model's context (HTTP 400)")


def test_another_client_error_names_its_status_and_message() -> None:
    with FakeEndpoint([error_reply(404, "The model `nope` does not exist")]) as fake:
        message = _failed(Run(fake))
    assert message == "The service refused the request (HTTP 404): The model `nope` does not exist"


def test_a_404_without_openais_shape_names_the_url_and_says_what_the_endpoint_must_be() -> None:
    with FakeEndpoint([Reply(404, body=b"404 page not found")]) as fake:
        message = _failed(Run(fake))
    assert message.startswith(f"Nothing answered at {fake.endpoint}/responses (HTTP 404)")
    assert "often ending in /v1" in message


def test_a_body_that_isnt_openais_shape_is_quoted_as_text() -> None:
    with FakeEndpoint([Reply(422, body=b"bad things\n")]) as fake:
        assert _failed(Run(fake)) == "The service refused the request (HTTP 422): bad things"


def test_a_redirect_names_its_status_and_location_and_isnt_followed() -> None:
    location = "https://elsewhere.example/v1/responses"
    with FakeEndpoint([Reply(307, headers=[("Location", location)])]) as fake:
        message = _failed(Run(fake))
    assert "(HTTP 307)" in message
    assert location in message
    assert len(fake.requests) == 1


def test_an_error_body_is_recorded_for_the_transcript() -> None:
    with FakeEndpoint([error_reply(400, "nope")]) as fake:
        run = Run(fake)
        _failed(run)
    assert run.records[1] == ("note", b'{"status":400,"headers":{}}')
    kind, body = run.records[2]
    assert kind == "received"
    assert json.loads(body)["error"]["message"] == "nope"


def test_a_429_is_recorded_as_a_status_note_then_its_body_byte_for_byte() -> None:
    reply = error_reply(429, "slow down", headers=[("retry-after", "0")])
    with FakeEndpoint([reply, text_reply("ok")]) as fake:
        run = Run(fake)
        run()
    assert run.records[1] == ("note", b'{"status":429,"headers":{"retry-after":"0"}}')
    assert run.records[2] == ("received", reply.body)


def test_an_error_body_that_isnt_utf_8_is_recorded_as_its_bytes() -> None:
    body = b"\xff\xfe not text"
    with FakeEndpoint([Reply(400, body=body)]) as fake:
        run = Run(fake)
        _failed(run)
    assert run.records[2] == ("received", body)


# Retry-After


@pytest.mark.parametrize(
    ("value", "seconds"),
    [("2", 2.0), ("0.5", 0.5), ("-3", 0.0), (None, None), ("soon", None), ("nan", None)],
)
def test_retry_after_is_read_as_seconds(value: str | None, seconds: float | None) -> None:
    assert retry_after(value) == seconds


def test_retry_after_as_an_http_date_is_the_seconds_until_it() -> None:
    assert retry_after("Wed, 21 Oct 2015 07:28:10 GMT", now=1445412480.0) == 10.0


def test_a_server_error_asking_longer_than_the_cap_is_retried_after_the_cap() -> None:
    reply = error_reply(503, "busy", headers=[("Retry-After", "120")])
    with FakeEndpoint([reply, text_reply("ok")]) as fake:
        run = Run(fake)
        run()
    assert run.retries == [Retry(1, 5, 60.0, "server", "HTTP 503: busy")]
    assert len(fake.requests) == 2


def test_a_refusal_whose_message_has_no_full_stop_still_reads_as_two_sentences() -> None:
    with FakeEndpoint([error_reply(401, "bad key", code="invalid_api_key")]) as fake:
        message = _failed(Run(fake))
    assert "bad key. Check" in message
