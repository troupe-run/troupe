"""The capture tool scrubs every fixture it writes of the key and the capturing host's home
(spec: openai-runner, "Fixtures hold no secrets"; design D13). It's loaded by path, as the owner
runs it."""

import importlib.util
import sys
from functools import cache
from pathlib import Path
from types import ModuleType

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "capture_openai.py"
KEY = "sk-proj-capture0123456789abcd"


@cache
def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("capture_openai", TOOL)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_key_is_scrubbed_wherever_it_appears() -> None:
    assert _tool()._scrub(f"Bearer {KEY} and {KEY}", KEY) == "Bearer [credential] and [credential]"


def test_a_masked_echo_of_the_key_is_scrubbed() -> None:
    body = '{"message": "Incorrect API key provided: sk-p****abcd. You can"}'
    assert (
        _tool()._scrub(body, KEY)
        == '{"message": "Incorrect API key provided: [credential]. You can"}'
    )


def test_the_capturing_hosts_home_is_scrubbed() -> None:
    assert _tool()._scrub(f"{Path.home()}/troupe/notes", "") == "~/troupe/notes"


def test_the_invalid_key_the_tool_sends_is_shaped_to_fail() -> None:
    assert _tool().INVALID_KEY.startswith("sk-troupe-capture-invalid-")


def test_the_tool_refuses_to_send_a_key_over_plain_http_to_another_host() -> None:
    with pytest.raises(SystemExit, match="plain http"):
        _tool()._post("http://models.example.com/v1", {}, KEY)


def test_the_tool_never_follows_a_redirect() -> None:
    assert _tool()._NoRedirect().redirect_request() is None


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
