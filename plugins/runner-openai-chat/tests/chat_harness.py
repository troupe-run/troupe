"""Shared helpers for the OpenAI-style runner's tests: the schemas, the test limits, and (with
fake_endpoint) driving the runner as troupe would.

Self-contained: no troupe imports. The contract's schemas are read from protocol/ at the repository
root, and the runner's own from its package's schemas/ directory, so messages are validated with
the runner's schemas filling the contract's extension points, as troupe would see them.
"""

import json
from functools import cache
from pathlib import Path
from typing import Any, Final
from urllib.parse import urljoin

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ROOT = Path(__file__).resolve().parents[3]
SCHEMAS = ROOT / "protocol" / "schemas"
RUNNER_SCHEMAS = (
    Path(__file__).resolve().parents[1] / "src" / "troupe_runner_openai_chat" / "schemas"
)
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chat-completions"
BASE = "https://troupe.run/protocol/runner/"
OWN = "https://troupe.run/plugins/runner-openai-chat/"

TEST_LIMITS: Final[dict[str, int]] = {"maxTurns": 5, "maxTotalTokens": 20_000}
"""The limits every run a test starts uses, unless the test sets its own and says why
(openai-style-runner design D7). Low, so a runaway loop or a misread finish stops within a few
turns: fast against the fake endpoint, and a few cents against a real service. The runner's
defaults are for real work and are checked by parsing options, never by running a service on
them."""


@cache
def _registry() -> Registry[Any]:
    paths = [
        SCHEMAS / "error.schema.json",
        SCHEMAS / "effects.schema.json",
        *sorted((SCHEMAS / "runner").glob("*.schema.json")),
        *sorted(RUNNER_SCHEMAS.glob("*.schema.json")),
    ]
    schemas = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    return Registry().with_resources(
        (s["$id"], Resource.from_contents(s, default_specification=DRAFT202012)) for s in schemas
    )


def bound(ref: str) -> dict[str, Any]:
    """The contract's schema at ``ref``, with this runner's schemas filling its extension points."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": urljoin(OWN, "bound.schema.json"),
        "$ref": urljoin(BASE, ref),
        "$defs": {
            "options": {
                "$dynamicAnchor": "runnerOptions",
                "$ref": urljoin(OWN, "options.schema.json"),
            },
            "errors": {
                "$dynamicAnchor": "runnerErrors",
                "$ref": urljoin(OWN, "errors.schema.json"),
            },
        },
    }


def validator(ref: str) -> jsonschema.Draft202012Validator:
    """A validator for the contract's schema at ``ref``, bound to this runner's schemas."""
    return jsonschema.Draft202012Validator(bound(ref), registry=_registry())


def own_validator(ref: str) -> jsonschema.Draft202012Validator:
    """A validator for this runner's own schema at ``ref``, such as options.schema.json."""
    return jsonschema.Draft202012Validator({"$ref": urljoin(OWN, ref)}, registry=_registry())
