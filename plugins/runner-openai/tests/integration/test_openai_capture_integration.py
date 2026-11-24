"""The capture tool sends nothing to a proxy for an endpoint on this machine, even with a proxy set
in the environment (spec: openai-runner; design D13). It's loaded by path, as the owner runs it.

Its tests that stay in their own process are in unit/test_openai_capture.py."""

import pytest

from openai_capture_shared import KEY, _tool


def test_the_tool_sends_nothing_to_a_proxy_for_an_endpoint_on_this_machine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fake_endpoint import FakeEndpoint, text_reply

    with FakeEndpoint([text_reply("proxied")]) as proxy, FakeEndpoint([text_reply("ok")]) as fake:
        base = proxy.endpoint.removesuffix("/v1")
        for name in ("HTTP_PROXY", "http_proxy"):
            monkeypatch.setenv(name, base)
        for name in ("NO_PROXY", "no_proxy"):
            monkeypatch.delenv(name, raising=False)
        _tool()._post(fake.endpoint, {}, KEY)
        assert proxy.requests == []
        assert len(fake.requests) == 1
