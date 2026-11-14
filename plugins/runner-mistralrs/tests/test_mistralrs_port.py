"""The engine's own words for each failure map to what they mean, in one table (in-process-runner
design D7; spec: mistralrs-runner, "A run never carries on past its context window", "An unsupported
macOS Python is refused before the run is acknowledged"). Each message is one mistral.rs 0.9.5 gave
in the probe on #414 (comment 6866903650); a version that words them differently fails here."""

import pytest

from troupe_runner_mistralrs.port import ChatRequest, EngineFailure, classify

PROMPT_OVER_LENGTH = (
    "Prompt sequence length is greater than 40960, perhaps consider using `truncate_sequence`?"
)
OVER_KV = "Sequence 1 with 1025 tokens exceeds the total KV cache capacity of 1024 tokens."
METAL_SDK_27 = (
    "Metal error Error while loading library: Error while loading library: program_source:318:14: "
    "error: constructor for 'BlockMMA<float, float, 32, 32, 16, 2, 2, false, false, 20, 36>' must "
    "explicitly initialize the member 'Asimd' which does not have a default constructor"
)
METAL_SDK_12 = (
    "Error while loading library: Error while loading library: program_source:523:35: error: "
    "use of undeclared identifier 'bfloat'; did you mean 'float'?"
)
NO_TEMPLATE = (
    "Received messages for a model which does not have a chat template. Either use a different "
    "model or pass a single string as the prompt"
)


@pytest.mark.parametrize(
    ("message", "kind"),
    [
        (PROMPT_OVER_LENGTH, "too-long"),
        (OVER_KV, "too-long"),
        (METAL_SDK_27, "metal"),
        (METAL_SDK_12, "metal"),
        (NO_TEMPLATE, "other"),
        ("cannot find tensor model.language_model.layers.0.linear_attn.dt_bias", "other"),
    ],
)
def test_each_failure_the_engine_reported_in_the_probe_means_what_it_says(
    message: str, kind: str
) -> None:
    assert classify(message) == kind
    assert EngineFailure(message).kind == kind


def test_a_request_records_its_fields_and_never_asks_the_engine_to_truncate() -> None:
    request = ChatRequest(
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "Read"}}],
        max_tokens=100,
        temperature=0.0,
        think=False,
    )
    assert request.to_data() == {
        "messages": [{"role": "user", "content": "hi"}],
        "tool_schemas": [{"type": "function", "function": {"name": "Read"}}],
        "tool_choice": "auto",
        "truncate_sequence": False,
        "max_tokens": 100,
        "temperature": 0.0,
        "enable_thinking": False,
    }
    assert ChatRequest([], [], 5).settings() == {"max_tokens": 5}
