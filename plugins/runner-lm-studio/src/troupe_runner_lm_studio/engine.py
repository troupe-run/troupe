"""The one module that uses LM Studio's client library, lmstudio (lmstudio-runner design D1, D3,
D10; an import-linter contract keeps every other module off it, and off the network).

It turns the library's types and errors into plain ones the run uses (Model, Round, EngineError),
so the run's logic is tested with a stand-in Engine and this module with a fake LM Studio. How the
runner talks to LM Studio is decided here: the host and port it names (always, so the library never
probes ports of its own), every timeout the library applies (from the runner's named settings, never
the library's defaults), no proxy and no redirect, and closing the client as the way to stop.
"""

import logging
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Literal

import httpx
import lmstudio
import msgspec
from lmstudio import _ws_impl
from lmstudio.json_api import ChatResponseEndpoint

from troupe_runner_lm_studio.defaults import (
    CHECK_TIMEOUT_SECONDS,
    MESSAGE_TIMEOUT_SECONDS,
    WEBSOCKET_CLOSE_TIMEOUT_SECONDS,
)

Failure = Literal[
    "unreachable", "incompatible", "lost", "timeout", "model", "engine", "unreadable", "stopped"
]
"""What an EngineError is: LM Studio not there (or not LM Studio), there but its library can't list
models, the connection lost mid-run, a message not arriving within the timeout, the model not
found, any other failure on LM Studio's side, a message the library couldn't read (such as a stop
reason it doesn't know), or the client closed by the runner."""


class EngineError(Exception):
    """A failure talking to LM Studio, with what kind it is and the library's message."""

    def __init__(self, failure: Failure, message: str) -> None:
        super().__init__(message)
        self.failure = failure
        self.message = message


@dataclass(frozen=True)
class Model:
    """A model LM Studio has downloaded, as its listing gives it."""

    key: str
    type: str
    trained_for_tool_use: bool
    info: dict[str, Any]
    """The listing's entry, as the library gives it: the transcript's record of it."""


@dataclass(frozen=True)
class Round:
    """One prediction round's result."""

    index: int
    stop_reason: str
    prompt_tokens: int | None
    predicted_tokens: int | None
    model_key: str | None
    record: dict[str, Any]
    """The round's result as the library gives it, serialised: the transcript's record of it."""


@dataclass(frozen=True)
class ToolSpec:
    """One tool as the run offers it: the SDK's name, description and input schema."""

    name: str
    description: str
    input_schema: Mapping[str, Any]


Fragment = Callable[[str, bool], None]
"""Told each piece of a round's text as it streams, and whether it's reasoning."""


def configure() -> None:
    """Set the library's timeouts from the runner's named settings, and keep its logging to
    warnings and above (design D10, D11). Process-wide, which a runner process, one run long, is."""
    lmstudio.set_sync_api_timeout(MESSAGE_TIMEOUT_SECONDS)
    _ws_impl.AsyncWebsocketHandler.WS_DISCONNECT_TIMEOUT = WEBSOCKET_CLOSE_TIMEOUT_SECONDS  # type: ignore[assignment]
    logging.getLogger().setLevel(logging.WARNING)


def _serialised(value: object) -> Any:  # noqa: ANN401 - JSON
    """``value``, one of the library's structs, as plain JSON data."""
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    return msgspec.to_builtins(value)


def greet(endpoint: str, api_host: str, timeout: float = CHECK_TIMEOUT_SECONDS) -> None:
    """Check that LM Studio answers at ``api_host`` before the library is asked anything: the
    library's own check has a fixed one-second timeout and doesn't say what it got. No proxy and no
    redirect: a 3xx is "not LM Studio here", naming where it pointed (design D6, D10)."""
    url = f"http://{api_host}/lmstudio-greeting"
    try:
        response = httpx.get(url, timeout=timeout, follow_redirects=False, trust_env=False)
    except httpx.HTTPError as error:
        raise EngineError(
            "unreachable", f"Nothing answered at {endpoint} ({type(error).__name__}: {error})."
        ) from None
    if response.is_redirect:
        where = response.headers.get("location", "(no location)")
        raise EngineError(
            "unreachable",
            f"{endpoint} answered with a redirect ({response.status_code} to {where}), which the "
            "runner doesn't follow.",
        )
    try:
        answered = response.status_code == httpx.codes.OK and response.json().get("lmstudio")
    except ValueError:
        answered = False
    if not answered:
        raise EngineError(
            "unreachable",
            f"{endpoint} answered, but not as LM Studio does (status {response.status_code}).",
        )


def _engine_error(error: BaseException) -> EngineError:
    """The library's ``error`` as an EngineError."""
    message = f"{type(error).__name__}: {error}"
    if isinstance(error, msgspec.ValidationError):
        return EngineError("unreadable", message)
    if isinstance(error, lmstudio.LMStudioTimeoutError):
        return EngineError("timeout", message)
    if isinstance(error, lmstudio.LMStudioModelNotFoundError):
        return EngineError("model", message)
    if isinstance(error, lmstudio.LMStudioWebsocketError | lmstudio.LMStudioCancelledError):
        return EngineError("lost", message)
    if isinstance(error, lmstudio.LMStudioClientError | OSError):
        return EngineError("lost", message)
    return EngineError("engine", message)


def _parameter(prop: Mapping[str, Any], required: bool) -> Any:  # noqa: ANN401 - a type
    """One of the SDK's properties as the library's parameter: its type, with its description
    and minimum, and an optional one unset by default, so the schema the library sends is the
    SDK's property exactly, and null is refused (design D7)."""
    python = {"string": str, "integer": int, "boolean": bool}[prop["type"]]
    meta: dict[str, Any] = {"description": prop["description"]}
    if "minimum" in prop:
        meta["ge"] = prop["minimum"]
    typed = Annotated[python, msgspec.Meta(**meta)]  # type: ignore[valid-type]
    if required:
        return typed
    return {"type": typed | msgspec.UnsetType, "default": msgspec.UNSET}


def tool_definitions(
    tools: Sequence[ToolSpec], carry_out: Callable[[str, dict[str, Any]], str]
) -> list[lmstudio.ToolFunctionDef]:
    """The SDK's tools as the library's: each calls ``carry_out`` with its name and the arguments
    the library converted, leaving out any the model didn't give."""

    def implementation(name: str) -> Callable[..., str]:
        def call(**arguments: Any) -> str:  # noqa: ANN401 - the tool's input
            given = {k: v for k, v in arguments.items() if v is not msgspec.UNSET}
            return carry_out(name, given)

        return call

    definitions = []
    for tool in tools:
        required = set(tool.input_schema.get("required", []))
        parameters = {
            key: _parameter(prop, key in required)
            for key, prop in tool.input_schema["properties"].items()
        }
        definitions.append(
            lmstudio.ToolFunctionDef(
                name=tool.name,
                description=tool.description,
                parameters=parameters,
                implementation=implementation(tool.name),
            )
        )
    return definitions


def sent_tools(definitions: Sequence[lmstudio.ToolFunctionDef]) -> list[dict[str, Any]]:
    """The tools as the library sends them to LM Studio: name, description and JSON schema."""
    array, _ = ChatResponseEndpoint.parse_tools(definitions)
    tools: list[dict[str, Any]] = _serialised(array)["tools"]
    return tools


class Engine:
    """One run's connection to LM Studio, through the library."""

    def __init__(self, endpoint: str, api_host: str) -> None:
        self._endpoint = endpoint
        self._api_host = api_host
        self._client: lmstudio.Client | None = None
        self._lock = threading.Lock()
        self._closed = False

    def open(self) -> None:
        """Connect: LM Studio's greeting, then the library's client on the runtime's host and
        port. A new connection after close() is refused as stopped."""
        greet(self._endpoint, self._api_host)
        with self._lock:
            if self._closed:
                raise EngineError("stopped", "The run was stopped.")
            client = lmstudio.Client(self._api_host)
            try:
                client.__enter__()
            except Exception as error:  # the library's own greeting, after ours passed
                client.close()
                raise EngineError(
                    "unreachable", f"LM Studio's library couldn't connect: {error}"
                ) from None
            self._client = client

    def _require(self) -> lmstudio.Client:
        if self._client is None or self._closed:
            raise EngineError("stopped", "The run was stopped.")
        return self._client

    def models(self) -> list[Model]:
        """LM Studio's downloaded models, within the pre-run check's limit rather than the
        library's message timeout, so run/start is answered well inside troupe's start limit
        (design D6). No answer in time is ``unreachable``; LM Studio there but its library unable
        to list them is ``incompatible``."""
        client = self._require()
        lmstudio.set_sync_api_timeout(CHECK_TIMEOUT_SECONDS)
        try:
            listed = client.list_downloaded_models()
        except lmstudio.LMStudioTimeoutError as error:
            raise EngineError(
                "unreachable",
                f"LM Studio didn't list its models within {CHECK_TIMEOUT_SECONDS:g}s ({error}).",
            ) from None
        except Exception as error:
            raise EngineError("incompatible", f"{type(error).__name__}: {error}") from None
        finally:
            lmstudio.set_sync_api_timeout(MESSAGE_TIMEOUT_SECONDS)
        models = []
        for entry in listed:
            info = _serialised(entry.info)
            models.append(
                Model(
                    key=str(info.get("modelKey", "")),
                    type=str(info.get("type", "")),
                    trained_for_tool_use=info.get("trainedForToolUse") is True,
                    info=info,
                )
            )
        return models

    def load(
        self, model: str, context_length: int, progress: Callable[[float], None]
    ) -> tuple[Any, int, str | None]:
        """The model's handle, loading it with ``context_length`` when it isn't loaded, the
        context length it has (an already loaded model keeps its own), and the model key LM Studio
        gives the loaded model."""
        client = self._require()
        try:
            handle = client.llm.model(
                model,
                config={"contextLength": context_length},
                on_load_progress=progress,
            )
            served = _serialised(handle.get_info()).get("modelKey")
            return handle, int(handle.get_context_length()), served
        except Exception as error:
            raise _engine_error(error) from None

    def act(
        self,
        handle: Any,  # noqa: ANN401 - the library's model handle
        history: dict[str, Any],
        definitions: Sequence[lmstudio.ToolFunctionDef],
        *,
        temperature: float | None,
        fragment: Fragment,
        round_done: Callable[[Round], None],
        round_end: Callable[[int], None],
        message: Callable[[dict[str, Any]], None],
        invalid: Callable[[str, str | None, object], str],
    ) -> int:
        """Run the library's tool loop; how many rounds it made. Every round is offered the
        tools: the library's own round limit, which sends its last round without them, isn't used,
        and the run's caller stops it after its last round instead (design D5). ``invalid`` answers
        a call the library rejected, with its error, the tool's name and its raw arguments."""
        self._require()

        def on_fragment(piece: Any, _round: int) -> None:  # noqa: ANN401 - library type
            reasoning = getattr(piece, "reasoning_type", "none") not in (None, "none")
            fragment(str(getattr(piece, "content", "")), reasoning)

        def on_completed(result: Any) -> None:  # noqa: ANN401 - library type
            stats = result.stats
            model_info = _serialised(result.model_info)
            record = {
                "roundIndex": result.round_index,
                "content": result.content,
                "stats": _serialised(stats),
                "modelInfo": model_info,
            }
            round_done(
                Round(
                    index=result.round_index,
                    stop_reason=str(stats.stop_reason),
                    prompt_tokens=stats.prompt_tokens_count,
                    predicted_tokens=stats.predicted_tokens_count,
                    model_key=model_info.get("modelKey"),
                    record=record,
                )
            )

        def on_invalid(error: Exception, request: Any) -> str:  # noqa: ANN401 - library type
            if request is None:
                return invalid(str(error), None, None)
            return invalid(str(error), str(request.name), request.arguments)

        config: dict[str, Any] = {}
        if temperature is not None:
            config["temperature"] = temperature
        try:
            result = handle.act(
                history,
                list(definitions),
                max_parallel_tool_calls=1,
                config=config or None,
                on_message=lambda m: message(_serialised(m)),
                on_prediction_fragment=on_fragment,
                on_prediction_completed=on_completed,
                on_round_end=round_end,
                handle_invalid_tool_request=on_invalid,
            )
        except Exception as error:
            if self._closed:
                raise EngineError("stopped", "The run was stopped.") from None
            raise _engine_error(error) from None
        return int(result.rounds)

    def close(self) -> None:
        """Close the client, which is how the runner stops a prediction (design D9). Safe from
        any thread, and more than once."""
        with self._lock:
            self._closed = True
            client, self._client = self._client, None
        if client is not None:
            client.close()

    def reopen(self) -> "Engine":
        """A new Engine on the same host, for a retry: this one's client closed first."""
        with self._lock:
            client, self._client = self._client, None
        if client is not None:
            client.close()
        return Engine(self._endpoint, self._api_host)


__all__ = [
    "Engine",
    "EngineError",
    "Failure",
    "Fragment",
    "Model",
    "Round",
    "ToolSpec",
    "configure",
    "greet",
    "sent_tools",
    "tool_definitions",
]
