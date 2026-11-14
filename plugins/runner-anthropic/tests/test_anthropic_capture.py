"""The capture tool: it scrubs every fixture it writes of the key, request ids and the capturing
host's home, and won't record a fixture from a hosted service without a key (spec:
anthropic-runner, "Fixtures hold no secrets", "Fixtures that need a working credential are captured
by the owner"; design D12). It's loaded by path, as the owner runs it."""

import importlib.util
import sys
from functools import cache
from pathlib import Path
from types import ModuleType

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "capture_anthropic.py"
KEY = "sk-ant-api03-capture0123456789abcd"


@cache
def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("capture_anthropic", TOOL)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_key_is_scrubbed_wherever_it_appears() -> None:
    assert _tool()._scrub(f"Bearer {KEY} and {KEY}", KEY) == "Bearer [credential] and [credential]"


def test_a_masked_echo_of_the_key_is_scrubbed() -> None:
    body = '{"message": "invalid key: sk-ant-****abcd. Check it"}'
    assert _tool()._scrub(body, KEY) == '{"message": "invalid key: [credential]. Check it"}'


def test_request_ids_and_the_capturing_hosts_home_are_scrubbed() -> None:
    text = f'"request_id":"req_011CVabcdef0123" at {Path.home()}/notes'
    assert _tool()._scrub(text, "") == '"request_id":"req_scrubbed" at ~/notes'


@pytest.mark.parametrize("kind", ["loop", "context", "outgrow", "output-limit"])
def test_a_capture_from_a_hosted_service_without_a_key_stops_and_writes_nothing(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The owner's first capture ran without the key and recorded a 401 as each fixture
    # (2026-11-14): the tool now refuses before sending anything.
    tool = _tool()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(tool, "FIXTURES", tmp_path)
    monkeypatch.setattr(tool, "_post", lambda *_: pytest.fail("a request was sent"))
    with pytest.raises(SystemExit, match="ANTHROPIC_API_KEY isn't set"):
        tool.main([kind, "x", "--endpoint", "https://api.anthropic.com", "--model", "m"])
    assert list(tmp_path.iterdir()) == []


def test_a_capture_from_a_local_engine_needs_no_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _tool()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(tool, "FIXTURES", tmp_path)
    monkeypatch.setattr(tool, "_post", lambda *_: {"status": 200, "headers": [], "lines": []})
    assert (
        tool.main(["output-limit", "x", "--endpoint", "http://127.0.0.1:1234", "--model", "m"]) == 0
    )
    assert (tmp_path / "x" / "replies.json").is_file()
