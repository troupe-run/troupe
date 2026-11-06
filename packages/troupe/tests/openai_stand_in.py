"""A stand-in Responses API service for core's tests (openai-style-runner design D13).

The fake lives with the plugin's tests (plugins/runner-openai/tests/fake_endpoint.py) and uses
only the standard library, so it's loaded here by path, as ollama_stand_in.py loads Ollama's. Core's
tests give the real runner a runtime naming it, through the conformance suite and perform.
"""

import importlib.util
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from functools import cache
from pathlib import Path
from types import ModuleType
from typing import Any

PLUGIN = Path(__file__).resolve().parents[3] / "plugins" / "runner-openai"

TEST_LIMITS = {"maxTurns": 5, "maxTotalTokens": 20_000}
"""The limits every run a test starts uses (openai-style-runner design D7): the plugin's own, in
plugins/runner-openai/tests/openai_harness.py."""


@cache
def fake() -> ModuleType:
    """The plugin's fake endpoint module."""
    spec = importlib.util.spec_from_file_location(
        "openai_stand_in_fake", PLUGIN / "tests" / "fake_endpoint.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("the stand-in Responses API service can't be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up while they're made
    spec.loader.exec_module(module)
    return module


@contextmanager
def serving(replies: list[Any]) -> Iterator[Any]:
    """A stand-in service answering ``replies`` in turn; its ``endpoint`` is a runtime's."""
    with fake().FakeEndpoint(replies) as endpoint:
        yield endpoint


def text_reply(text: str) -> Any:  # noqa: ANN401 - the fake's Reply
    """A streamed reply that says ``text`` and stops."""
    return fake().text_reply(text)


def write_reply(path: str, content: str) -> Any:  # noqa: ANN401 - the fake's Reply
    """A streamed reply asking to Write ``content`` to ``path``."""
    return fake().tool_reply([("call_write", "Write", {"file_path": path, "content": content})])
