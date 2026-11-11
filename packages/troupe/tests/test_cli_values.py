"""A value the CLI can't type is refused without repeating any of it (spec: config, "A refused
config value is repeated nowhere"; config-set-json-redacts design D1, D2).

Each kind ``value_of`` reads is given generated text holding a canary that the kind refuses, and the
error's problem, fix and details must hold none of the canary.
"""

import json
from collections.abc import Callable

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from troupe.cli import values
from troupe.core.errors import TroupeError

CANARY = "q7ZxW9pL4vR2canary"
PATH = ("actors", "tester", "options", "field")

KINDS: dict[str, tuple[set[str], bool]] = {
    "boolean": ({"boolean"}, False),
    "integer": ({"integer"}, False),
    "number": ({"integer", "number"}, False),
    "list": ({"array"}, False),
    "group": ({"object"}, False),
    "no single type": (set(), False),
    "--json": ({"string"}, True),
}

around = st.text(st.characters(codec="utf-8", exclude_characters="\x00"), max_size=20)


def _refused(as_json: bool, text: str) -> TroupeError | None:
    try:
        values.value_of(PATH, text, runner="scripted", as_json=as_json)
    except TroupeError as error:
        return error
    return None


@pytest.mark.parametrize("kind", list(KINDS))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=150)
@given(before=around, after=around)
def test_a_refused_value_of_any_kind_holds_none_of_the_canary(
    kind: str, before: str, after: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    kinds, as_json = KINDS[kind]
    kinds_at: Callable[..., set[str]] = lambda path, runner: kinds  # noqa: E731
    monkeypatch.setattr(values, "kinds_at", kinds_at)
    text = before + CANARY + after
    if text.startswith("@"):
        text = " " + text  # a file is read, not the text: covered by the CLI's tests
    refused = _refused(as_json, text)
    if refused is None:
        return  # the kind accepts it, as JSON holding the canary in a string can be
    assert refused.code == "config.invalid"
    assert CANARY not in json.dumps([refused.problem, refused.fix, refused.details])
    assert list(refused.details["path"]) == list(PATH)


@pytest.mark.parametrize("kind", list(KINDS))
def test_each_kind_refuses_a_bare_canary(kind: str, monkeypatch: pytest.MonkeyPatch) -> None:
    # So the property above can't pass by never being refused.
    kinds, as_json = KINDS[kind]
    monkeypatch.setattr(values, "kinds_at", lambda path, runner: kinds)
    refused = _refused(as_json, CANARY)
    assert refused is not None
    assert CANARY not in json.dumps([refused.problem, refused.fix, refused.details])
