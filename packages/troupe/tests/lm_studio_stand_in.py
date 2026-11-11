"""A stand-in LM Studio for core's tests (lmstudio-runner design D14).

The fake lives with the plugin's tests (plugins/runner-lm-studio/tests/fake_lm_studio.py) and uses
only the standard library, so it's loaded here by path, as openai_stand_in.py loads the OpenAI
runner's. Core's tests give the real runner a runtime naming it, through the conformance suite.
"""

import importlib.util
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from functools import cache
from pathlib import Path
from types import ModuleType
from typing import Any

PLUGIN = Path(__file__).resolve().parents[3] / "plugins" / "runner-lm-studio"
MODEL = "google/gemma-4-e4b"
TEST_LIMITS = {"maxTurns": 4, "maxTotalTokens": 20_000}
"""The limits every run a test starts uses: the plugin's own, in
plugins/runner-lm-studio/tests/lm_studio_harness.py."""


@cache
def fake() -> ModuleType:
    """The plugin's fake LM Studio module."""
    spec = importlib.util.spec_from_file_location(
        "lm_studio_stand_in_fake", PLUGIN / "tests" / "fake_lm_studio.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("the stand-in LM Studio can't be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up while they're made
    spec.loader.exec_module(module)
    return module


@contextmanager
def serving(text: str = "Done.", pause: float = 0.0) -> Iterator[Any]:
    """A stand-in LM Studio that serves any number of runs, each one round that says ``text`` (a
    word every ``pause`` seconds) and asks for no tool, however each run ends: every request is
    answered by its kind, not from a queue a cancelled run could leave out of step. Its
    ``endpoint`` is a runtime's."""
    module = fake()
    script = module.Script(repeat=True)
    script.add("/system", [module.models_step()])
    script.add("/llm", [*module.load_steps(), module.predict_step(text, pause=pause)])
    with module.FakeLMStudio(script) as stand_in:
        yield stand_in
