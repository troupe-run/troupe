"""The one module that uses LM Studio's library, in-process (lmstudio-runner design D3, D7, D10;
spec: lm-studio-runner)."""

import json
import socket
import threading
import time
from pathlib import Path
from typing import Any

import lmstudio
import msgspec
import pytest
from lmstudio.json_api import ChatResponseEndpoint

from fake_lm_studio import FakeLMStudio, Script, Step, run_script
from troupe_plugin_sdk.tools import Tools
from troupe_runner_lm_studio import defaults, engine
from troupe_runner_lm_studio.engine import Engine, EngineError, greet, sent_tools, tool_definitions
from troupe_runner_lm_studio.loop import tool_specs


@pytest.fixture
def tools(tmp_path: Path) -> Tools:
    ws = tmp_path / "ws"
    ws.mkdir()
    return Tools(ws)


# Requirement: The model is offered the SDK's tools


def test_the_tools_the_library_sends_are_the_sdks_without_additional_properties(
    tools: Tools,
) -> None:
    definitions = tool_definitions(tool_specs(tools), lambda name, args: "")
    sent = sent_tools(definitions)
    assert [t["function"]["name"] for t in sent] == list(Tools.names())
    for tool, offered in zip(sent, tools.offered(), strict=True):
        assert tool["function"]["description"] == offered.description
        expected = {k: v for k, v in offered.input_schema.items() if k != "additionalProperties"}
        parameters = tool["function"]["parameters"]
        assert parameters["type"] == "object"
        assert parameters["properties"] == expected["properties"]
        assert sorted(parameters.get("required", [])) == sorted(expected["required"])


def test_an_optional_parameter_is_its_type_with_its_minimum_not_nullable_and_not_required(
    tools: Tools,
) -> None:
    sent = sent_tools(tool_definitions(tool_specs(tools), lambda name, args: ""))
    read = next(t for t in sent if t["function"]["name"] == "Read")["function"]["parameters"]
    assert read["properties"]["offset"] == {
        "type": "integer",
        "description": "The first line to read, from 1.",
        "minimum": 1,
    }
    assert "offset" not in read["required"]


def _converted(tools: Tools, arguments: dict[str, Any]) -> dict[str, Any] | str:
    """What the library hands the Read implementation for ``arguments``, or its error."""
    _, client_tools = ChatResponseEndpoint.parse_tools(
        tool_definitions(tool_specs(tools), lambda name, args: json.dumps(args))
    )
    struct, implementation, _ = client_tools["Read"]
    try:
        converted = msgspec.convert(arguments, struct)
    except msgspec.ValidationError as error:
        return str(error)
    given: dict[str, Any] = json.loads(implementation(**msgspec.structs.asdict(converted)))
    return given


def test_an_argument_the_model_leaves_out_isnt_passed_to_the_tool(tools: Tools) -> None:
    assert _converted(tools, {"file_path": "a.txt"}) == {"file_path": "a.txt"}


def test_the_library_drops_an_argument_name_the_tool_doesnt_define(tools: Tools) -> None:
    # The one place the runner can't keep the SDK's behaviour (design D7): pinned here, so a
    # library change that starts refusing it, or passing it on, is noticed.
    assert _converted(tools, {"file_path": "a.txt", "colour": "red"}) == {"file_path": "a.txt"}


def test_the_library_refuses_null_and_a_value_under_the_minimum(tools: Tools) -> None:
    assert isinstance(_converted(tools, {"file_path": "a.txt", "offset": None}), str)
    assert isinstance(_converted(tools, {"file_path": "a.txt", "offset": 0}), str)


# Requirement: The runtime's endpoint is the library's host and port


def test_the_client_is_always_given_the_runtimes_host_and_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    given: list[object] = []

    class Client:
        def __init__(self, api_host: object = None) -> None:
            given.append(api_host)

        def __enter__(self) -> "Client":
            return self

        def close(self) -> None:
            pass

    monkeypatch.setattr(engine, "greet", lambda *args, **kwargs: None)
    monkeypatch.setattr(lmstudio, "Client", Client)
    Engine("http://127.0.0.1:1234", "127.0.0.1:1234").open()
    assert given == ["127.0.0.1:1234"]


# Requirement: Redirects are never followed


def test_a_redirected_greeting_is_unreachable_naming_the_status_and_where_it_pointed() -> None:
    with FakeLMStudio(Script(greeting="redirect")) as fake, pytest.raises(EngineError) as caught:
        greet(fake.endpoint, fake.endpoint.removeprefix("http://"))
    assert caught.value.failure == "unreachable"
    assert "307" in caught.value.message
    assert "http://192.0.2.1:9/" in caught.value.message


def test_an_answer_that_isnt_lm_studios_greeting_is_unreachable() -> None:
    with (
        FakeLMStudio(Script(greeting="not-lm-studio")) as fake,
        pytest.raises(EngineError) as caught,
    ):
        greet(fake.endpoint, fake.endpoint.removeprefix("http://"))
    assert caught.value.failure == "unreachable"
    assert "404" in caught.value.message


def test_nothing_listening_is_unreachable() -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with pytest.raises(EngineError) as caught:
        greet(f"http://127.0.0.1:{port}", f"127.0.0.1:{port}")
    assert caught.value.failure == "unreachable"


def test_a_proxy_in_the_environment_isnt_used_for_lm_studio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://192.0.2.1:9")
    monkeypatch.setenv("NO_PROXY", "")
    with FakeLMStudio(Script()) as fake:
        greet(fake.endpoint, fake.endpoint.removeprefix("http://"), timeout=5)
        assert fake.greetings == 1


# Requirement: Every limit the library applies is one of the runner's named settings


def test_the_librarys_timeouts_come_from_the_runners_named_settings() -> None:
    engine.configure()
    assert lmstudio.get_sync_api_timeout() == defaults.MESSAGE_TIMEOUT_SECONDS
    from lmstudio import _ws_impl

    assert (
        _ws_impl.AsyncWebsocketHandler.WS_DISCONNECT_TIMEOUT
        == defaults.WEBSOCKET_CLOSE_TIMEOUT_SECONDS
    )


def test_a_server_that_never_answers_is_a_timeout_within_the_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(engine, "MESSAGE_TIMEOUT_SECONDS", 1.0)
    engine.configure()
    stalled = Step("rpcCall", "listDownloadedModels", [])  # answered with nothing
    with FakeLMStudio(Script().add("/system", [stalled])) as fake:
        connection = Engine(fake.endpoint, fake.endpoint.removeprefix("http://"))
        connection.open()
        started = time.monotonic()
        with pytest.raises(EngineError):
            connection.models()
        assert time.monotonic() - started < 10
        connection.close()
    engine.configure()


# Requirement: Cancel and end of input stop the run at once (closing the client is the cancel)


def test_closing_the_engine_from_another_thread_stops_a_prediction_in_flight(
    tmp_path: Path,
) -> None:
    from fake_lm_studio import predict_step

    script = run_script(predict_step(" ".join(["word"] * 200), pause=0.05))
    with FakeLMStudio(script) as fake:
        connection = Engine(fake.endpoint, fake.endpoint.removeprefix("http://"))
        connection.open()
        connection.models()
        handle, _, _ = connection.load("google/gemma-4-e4b", 8192, lambda _: None)
        outcome: list[object] = []

        def act() -> None:
            try:
                connection.act(
                    handle,
                    {"messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]},
                    tool_definitions(tool_specs(Tools(tmp_path)), lambda n, a: ""),
                    temperature=None,
                    fragment=lambda text, reasoning: None,
                    round_done=lambda r: None,
                    round_end=lambda i: None,
                    message=lambda m: None,
                    invalid=lambda e, n, a: "",
                )
                outcome.append("finished")
            except EngineError as error:
                outcome.append(error.failure)

        worker = threading.Thread(target=act)
        worker.start()
        time.sleep(0.5)
        started = time.monotonic()
        connection.close()
        worker.join(10)
        assert not worker.is_alive()
        assert time.monotonic() - started < 5
    assert outcome == ["stopped"]
