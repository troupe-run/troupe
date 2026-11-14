"""The real engine: mistral.rs's Python package, ``mistralrs``, loading a GGUF model in this
process (in-process-runner design D6).

This is the one module that imports ``mistralrs`` (an import-linter contract keeps it so), and the
runner imports it only after its entry point has moved file descriptor 1 off the protocol channel,
since the engine writes its log lines there (design D3).

Every call blocks the calling thread, with the GIL released, and none can be interrupted: the
runner stops by ending its process (design D2). Nothing here makes a network request: the model is
a local file, and Hugging Face is never asked for a token (``token_source="none"``). The engine's
own tools, tool loop, search, shell and code execution are never configured: the tools are
troupe's.
"""

import sys
from importlib.metadata import version
from importlib.resources import as_file, files
from typing import Any, cast

import mistralrs

from troupe_runner_mistralrs.port import (
    Answer,
    ChatRequest,
    EngineFailure,
    LoadSpec,
    ToolCall,
    tool_schema_text,
)

CHECK_MODEL = "check_model/stories260K.gguf"
"""The model the package carries for the platform check and the tests (design D4, D10)."""

ENGINE_VERSION = version("mistralrs")


def _gguf(directory: str, filename: str) -> "mistralrs.Which":
    """A GGUF file to load. The library's stub types its variants apart from Which, which takes
    them at run time."""
    return cast(
        "mistralrs.Which",
        mistralrs.Which.GGUF(quantized_model_id=directory, quantized_filename=filename),
    )


def _runner(spec: LoadSpec) -> "mistralrs.Runner":
    which = _gguf(str(spec.model.parent), spec.model.name)
    extra: dict[str, Any] = {}
    if spec.kv_tokens is not None:
        extra["memory_goal"] = f"{spec.kv_tokens}tokens"
    try:
        return mistralrs.Runner(
            which=which,
            token_source="none",  # noqa: S106 - no Hugging Face token: a local file
            max_seqs=1,
            seed=spec.seed,
            **extra,
        )
    except ValueError as error:
        raise EngineFailure(str(error)) from None


def load(spec: LoadSpec) -> "MistralRs":
    """The run's model, loaded. Raises EngineFailure with the engine's own words."""
    return MistralRs(_runner(spec))


def check_platform() -> None:
    """On macOS, load the check model, which needs mistral.rs's Metal kernels to compile under this
    Python: they don't under some Pythons, depending on the SDK each was built with (design D4).
    Paged attention is off, which the check model's small heads can't use. Raises EngineFailure.
    Elsewhere, nothing to check: the engine runs on the CPU."""
    if sys.platform != "darwin":
        return
    with as_file(files("troupe_runner_mistralrs").joinpath(CHECK_MODEL)) as path:
        which = _gguf(str(path.parent), path.name)
        try:
            checked = mistralrs.Runner(
                which=which,
                token_source="none",  # noqa: S106 - no Hugging Face token: a local file
                max_seqs=1,
                no_paged_attn=True,
            )
        except ValueError as error:
            raise EngineFailure(str(error)) from None
        del checked


def serialised(response: "mistralrs.ChatCompletionResponse") -> dict[str, Any]:
    """The response as the library returned it, for the transcript: its id, model, choices (each
    message's content, reasoning and tool calls, and the finish reason) and usage's token counts.
    Usage's timings are left out (design D9)."""
    choices = []
    for choice in response.choices:
        message = choice.message
        calls = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.function.name, "arguments": call.function.arguments},
            }
            for call in message.tool_calls or []
        ]
        entry: dict[str, Any] = {"role": message.role, "content": message.content}
        if message.reasoning_content is not None:
            entry["reasoning_content"] = message.reasoning_content
        if calls:
            entry["tool_calls"] = calls
        choices.append(
            {"index": choice.index, "finish_reason": choice.finish_reason, "message": entry}
        )
    usage = response.usage
    return {
        "id": response.id,
        "object": response.object,
        "created": response.created,
        "model": response.model,
        "system_fingerprint": response.system_fingerprint,
        "choices": choices,
        "usage": {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
        },
    }


def answer_of(response: "mistralrs.ChatCompletionResponse") -> Answer:
    """The runner's view of a response: its first choice, and the token counts."""
    choice = response.choices[0]
    message = choice.message
    return Answer(
        content=message.content or "",
        reasoning=message.reasoning_content or "",
        tool_calls=[
            ToolCall(call.id, call.function.name, call.function.arguments)
            for call in message.tool_calls or []
        ],
        finish_reason=choice.finish_reason,
        prompt_tokens=response.usage.prompt_tokens,
        completion_tokens=response.usage.completion_tokens,
        record=serialised(response),
    )


class MistralRs:
    """A model loaded by mistral.rs."""

    def __init__(self, runner: "mistralrs.Runner") -> None:
        self._runner = runner

    @property
    def version(self) -> str:
        return ENGINE_VERSION

    def max_sequence_length(self) -> int | None:
        return self._runner.max_sequence_length()

    def count(self, text: str) -> int:
        try:
            return len(self._runner.tokenize_text(text, False, None))
        except ValueError as error:
            raise EngineFailure(str(error)) from None

    def chat(self, request: ChatRequest) -> Answer:
        library_request = mistralrs.ChatCompletionRequest(
            model="mistralrs",
            messages=request.messages,
            tool_schemas=tool_schema_text(request.tools),
            tool_choice=mistralrs.ToolChoice.Auto,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            enable_thinking=request.think,
            truncate_sequence=False,
        )
        try:
            response = self._runner.send_chat_completion_request(library_request)
        except ValueError as error:
            raise EngineFailure(str(error)) from None
        if not isinstance(response, mistralrs.ChatCompletionResponse):  # a stream: never asked
            raise EngineFailure("the engine streamed an answer the runner didn't ask to stream")
        return answer_of(response)


__all__ = ["CHECK_MODEL", "ENGINE_VERSION", "MistralRs", "answer_of", "check_platform", "load"]
