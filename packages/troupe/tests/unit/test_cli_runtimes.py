"""A resolved runtime, as text (spec: runtimes; runtimes design D9): what ``config get --resolved``
and a rehearsed ``perform`` print for one. Each fixture is checked against the protocol's
ResolvedRuntime first, so the lines are those of a shape troupe really sends."""

from typing import Any

import pytest

from troupe.cli.runtimes import price_text, runtime_lines
from troupe.core.client import messages as m


def _runtime(**fields: Any) -> dict[str, Any]:  # noqa: ANN401
    m.ResolvedRuntime.from_data(fields)  # a shape troupe sends
    return fields


def test_a_remote_runtime_with_every_value_shows_each_with_its_source() -> None:
    runtime = _runtime(
        name="openai",
        endpoint={"value": "https://api.openai.com/v1", "source": "default"},
        model={"value": "gpt-test", "source": "theatre"},
        credential={"env": {"value": "OPENAI_API_KEY", "source": "default"}, "set": True},
        engine={"value": "claude", "source": "env"},
        price={"value": {"input": 2, "output": 8}, "source": "actor"},
    )
    assert runtime_lines(runtime) == [
        "runtime openai",
        "  endpoint: https://api.openai.com/v1 (from default)",
        "  model: gpt-test (from theatre)",
        "  credential: from OPENAI_API_KEY (named by default), set",
        "  engine: claude (from env)",
        "  price: US$ per million tokens: input 2, output 8 (from actor)",
    ]


def test_an_in_process_runtime_with_nothing_resolved_says_how_a_model_is_set() -> None:
    # The variable's name is the runtime's, upper-cased, with its dashes as underscores.
    runtime = _runtime(name="my-local-llm")
    assert runtime_lines(runtime) == [
        "runtime my-local-llm",
        "  endpoint: none (the runner loads the model in its own process)",
        "  model: none (an actor's model, runtimes.my-local-llm.model or "
        "TROUPE_RUNTIME_MY_LOCAL_LLM_MODEL sets one)",
        "  credential: none",
    ]


def test_a_credential_named_by_a_variable_shows_that_variable_and_not_set() -> None:
    runtime = _runtime(
        name="openai",
        endpoint={"value": "https://api.openai.com/v1", "source": "default"},
        model={"value": "gpt-test", "source": "env"},
        credential={
            "env": {"namedBy": "TROUPE_RUNTIME_OPENAI_CREDENTIAL_ENV", "source": "env"},
            "set": False,
        },
    )
    assert runtime_lines(runtime)[-1] == (
        "  credential: from the variable TROUPE_RUNTIME_OPENAI_CREDENTIAL_ENV names "
        "(named by env), not set"
    )


def test_every_line_takes_the_indent_given() -> None:
    runtime = _runtime(
        name="openai",
        endpoint={"value": "https://api.openai.com/v1", "source": "default"},
        credential={"env": {"value": "OPENAI_API_KEY", "source": "default"}, "set": False},
    )
    assert runtime_lines(runtime, indent="    ") == [
        "    runtime openai",
        "      endpoint: https://api.openai.com/v1 (from default)",
        "      model: none (an actor's model, runtimes.openai.model or "
        "TROUPE_RUNTIME_OPENAI_MODEL sets one)",
        "      credential: from OPENAI_API_KEY (named by default), not set",
    ]


@pytest.mark.parametrize(
    ("price", "text"),
    [
        ({"input": 2, "output": 8}, "input 2, output 8"),
        (
            {"input": 2.5, "output": 10, "cacheRead": 0.25, "cacheWrite": 3.75},
            "input 2.5, cache read 0.25, cache write 3.75, output 10",
        ),
        ({"cacheWrite": 0, "output": 0.6, "input": 0.15}, "input 0.15, cache write 0, output 0.6"),
        ({"cacheRead": 0.1, "output": 1, "input": 1e-05}, "input 1e-05, cache read 0.1, output 1"),
    ],
    ids=["input and output", "every rate", "no cache read", "no cache write"],
)
def test_a_price_names_each_rate_it_gives_in_order_with_output_last(
    price: dict[str, Any], text: str
) -> None:
    m.SourcedPrice.from_data({"value": price, "source": "theatre"})  # a price troupe accepts
    assert price_text(price) == f"US$ per million tokens: {text}"
