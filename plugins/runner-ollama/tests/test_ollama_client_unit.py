"""The Ollama client's address check and error text: a bracketed host that isn't an IPv6 address is
unreachable rather than a crash, and an error's text is its status followed by Ollama's message
or the body (spec: ollama-runner; local-model-runner design D9).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_ollama_client.py."""

import pytest

from troupe_runner_ollama.client import (
    Client,
    UnreachableError,
    error_text,
)


def test_a_bracketed_host_that_isnt_an_ipv6_address_is_unreachable_not_a_crash() -> None:
    with pytest.raises(UnreachableError, match="isn't an address"):
        Client("http://[:]:11434")


def test_error_text_is_the_status_then_ollamas_message_or_the_body() -> None:
    assert error_text(b'{"error":"boom"}', 500) == "status 500: boom"
    assert error_text(b"bad gateway", 502) == "status 502: bad gateway"
    assert error_text(b"", 503) == "status 503"
