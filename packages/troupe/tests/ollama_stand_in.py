"""A stand-in Ollama for core's tests (local-model-runner design D12).

The fake lives with the plugin's tests (plugins/runner-ollama/tests/fake_ollama.py) and uses only
the standard library, so it's loaded here by path, as claude_stand_in.py loads the stand-in claude.
``serving(fixture)`` serves one of the plugin's fixtures: its preflight answers and its /api/chat
answers, in turn. Core's tests point the real runner's runtime at it, through the host, the
conformance suite and perform.
"""

import importlib.util
import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from functools import cache
from pathlib import Path
from types import ModuleType
from typing import Any

PLUGIN = Path(__file__).resolve().parents[3] / "plugins" / "runner-ollama"
FIXTURES = PLUGIN / "fixtures" / "ollama"
NAMES = sorted(path.name for path in FIXTURES.iterdir() if path.is_dir())


@cache
def _fake() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "ollama_stand_in_fake", PLUGIN / "tests" / "fake_ollama.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("the stand-in Ollama can't be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up while they're made
    spec.loader.exec_module(module)
    return module


def load(name: str, file: str) -> Any:  # noqa: ANN401 - JSON
    return json.loads((FIXTURES / name / file).read_text(encoding="utf-8"))


def options(name: str) -> dict[str, Any]:
    """The runner options the fixture was captured with. Its model is the runtime's: see
    ``provenance``."""
    loaded: dict[str, Any] = load(name, "provenance.json")["options"]
    return dict(loaded)


def provenance(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = load(name, "provenance.json")
    return loaded


def records(name: str) -> list[str]:
    """The fixture's transcript records, with ``<scratch>`` and ``<workspace>`` for host paths."""
    return (FIXTURES / name / "transcript.jsonl").read_text(encoding="utf-8").splitlines()


def events(name: str) -> list[dict[str, Any]]:
    loaded: list[dict[str, Any]] = load(name, "events.json")
    return loaded


def _answers(name: str) -> list[Any]:
    fake = _fake()
    path = FIXTURES / name / "answers.json"
    if not path.exists():
        return []
    played = []
    for answer in json.loads(path.read_text(encoding="utf-8")):
        if answer["status"] != 200:
            played.append(fake.Answer(status=answer["status"], body=answer["body"].encode()))
        else:
            played.append(
                fake.Answer(
                    [line.encode() for line in answer["lines"]],
                    close_after=answer.get("closeAfter"),
                )
            )
    return played


def _settings(name: str) -> Any:  # noqa: ANN401 - the fake's Settings
    preflight = load(name, "preflight.json")
    models = {} if preflight["show"] is None else {preflight["model"]: preflight["show"]}
    return _fake().Settings(version=preflight["version"], models=models)


@contextmanager
def serving(name: str) -> Iterator[Any]:
    """A stand-in Ollama serving fixture ``name``; its ``url`` is the runner's endpoint."""
    fake = _fake().FakeOllama(_answers(name), _settings(name)).start()
    try:
        yield fake
    finally:
        fake.stop()


@contextmanager
def slow() -> Iterator[Any]:
    """A stand-in Ollama for the model ``fake`` whose answer starts and then waits a minute, for
    cancelling mid-stream."""
    module = _fake()
    answer = module.Answer([module.message("Thinking"), module.Line(b"{}", delay=60)])
    fake = module.FakeOllama([answer]).start()
    try:
        yield fake
    finally:
        fake.stop()


@contextmanager
def answering(count: int, delay: float) -> Iterator[Any]:
    """A stand-in Ollama for the model ``fake`` that gives ``count`` final answers, each after
    ``delay`` seconds, for the conformance suite's runs, each started afresh."""
    module = _fake()
    answer = module.Answer(
        [module.message("Done."), module.Line(json.dumps(module.done()).encode(), delay=delay)]
    )
    fake = module.FakeOllama([answer] * count).start()
    try:
        yield fake
    finally:
        fake.stop()
