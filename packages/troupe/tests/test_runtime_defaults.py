"""troupe's built-in runtimes (spec: runtimes, "troupe has built-in runtimes")."""

import pytest

from protocol_schemas import PROTOCOL_BASE, validator_for
from troupe.core import defaults

RUNTIME = validator_for(PROTOCOL_BASE + "config/runtime.schema.json")


def test_the_built_in_runtimes_are_openai_ollama_and_lm_studio() -> None:
    assert sorted(defaults.RUNTIMES) == ["lm-studio", "ollama", "openai"]
    assert defaults.RUNTIMES["openai"] == {
        "endpoint": "https://api.openai.com/v1",
        "credential": {"env": "OPENAI_API_KEY"},
    }
    assert defaults.RUNTIMES["ollama"] == {"endpoint": "http://127.0.0.1:11434"}
    assert defaults.RUNTIMES["lm-studio"] == {"endpoint": "http://127.0.0.1:1234"}


@pytest.mark.parametrize("name", sorted(defaults.RUNTIMES))
def test_each_built_in_runtime_is_a_valid_runtime_with_no_model(name: str) -> None:
    RUNTIME.validate(defaults.RUNTIMES[name])
    assert "model" not in defaults.RUNTIMES[name]
