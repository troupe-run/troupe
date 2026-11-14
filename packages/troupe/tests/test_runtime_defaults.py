"""troupe's built-in runtimes (spec: runtimes, "troupe has built-in runtimes")."""

import pytest

from protocol_schemas import PROTOCOL_BASE, validator_for
from troupe.core import defaults

RUNTIME = validator_for(PROTOCOL_BASE + "config/runtime.schema.json")


def test_the_built_in_runtimes_are_openai_anthropic_ollama_lm_studio_and_mistralrs() -> None:
    assert sorted(defaults.RUNTIMES) == ["anthropic", "lm-studio", "mistralrs", "ollama", "openai"]
    assert defaults.RUNTIMES["openai"] == {
        "endpoint": "https://api.openai.com/v1",
        "credential": {"env": "OPENAI_API_KEY"},
    }
    assert defaults.RUNTIMES["anthropic"] == {
        "endpoint": "https://api.anthropic.com",
        "credential": {"env": "ANTHROPIC_API_KEY"},
    }
    assert defaults.RUNTIMES["ollama"] == {"endpoint": "http://127.0.0.1:11434"}
    assert defaults.RUNTIMES["lm-studio"] == {"endpoint": "http://127.0.0.1:1234"}
    assert defaults.RUNTIMES["mistralrs"] == {}  # in-process: no endpoint (in-process-runner D5)
    assert sorted(defaults.IN_PROCESS_RUNTIMES) == ["mistralrs"]


@pytest.mark.parametrize("name", sorted(defaults.RUNTIMES))
def test_each_built_in_runtime_is_a_valid_runtime_with_no_model(name: str) -> None:
    RUNTIME.validate(defaults.RUNTIMES[name])
    assert "model" not in defaults.RUNTIMES[name]
