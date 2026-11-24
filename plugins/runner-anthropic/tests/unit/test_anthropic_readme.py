"""The README names exactly the runner's options, named settings and error codes: no more and no
fewer (anthropic-runner task 13.3). Their values are checked by eye, not here."""

import json
import re
from pathlib import Path

from anthropic_harness import RUNNER_SCHEMAS
from troupe_runner_anthropic import defaults
from troupe_runner_anthropic.context import ENGINES

TESTS_ROOT = next(p for p in Path(__file__).resolve().parents if p.name == "tests")
"""This suite's tests directory, found by name so the file can sit at any depth under it."""

README = TESTS_ROOT.parent / "README.md"


def _section(heading: str) -> str:
    text = README.read_text(encoding="utf-8")
    start = text.index(f"\n## {heading}\n")
    end = text.find("\n## ", start + 1)
    return text[start : end if end != -1 else len(text)]


def _rows(heading: str) -> list[str]:
    return re.findall(r"^\| `([A-Za-z_.\-]+)` \|", _section(heading), flags=re.MULTILINE)


def test_every_option_in_the_schema_has_a_row_and_every_row_an_option() -> None:
    schema = json.loads((RUNNER_SCHEMAS / "options.schema.json").read_text(encoding="utf-8"))
    assert sorted(_rows("Options")) == sorted(schema["properties"])


def test_every_named_setting_has_a_row_and_every_row_a_setting() -> None:
    settings = [name for name in vars(defaults) if name.isupper()]
    assert sorted(_rows("Limits")) == sorted(settings)


def test_every_error_code_in_the_schema_has_a_row_and_every_row_a_code() -> None:
    schema = json.loads((RUNNER_SCHEMAS / "errors.schema.json").read_text(encoding="utf-8"))
    codes = [branch["properties"]["code"]["const"] for branch in schema["oneOf"]]
    assert sorted(_rows("Schemas")) == sorted(codes)


def test_every_relative_link_in_the_readme_names_a_path_that_exists() -> None:
    text = README.read_text(encoding="utf-8")
    targets = re.findall(r"\]\(([^)#:]+)(?:#[^)]*)?\)", text)
    missing = [t for t in targets if not (README.parent / t).exists()]
    assert targets
    assert missing == []


def test_the_readme_says_a_first_request_an_engine_cuts_silently_isnt_caught() -> None:
    # Spec: anthropic-runner, "A reply from a conversation the engine shrank isn't acted on",
    # "A first request an engine cut": the limit is stated, not claimed away.
    text = " ".join(_section("The context").split())
    assert "What can still be lost without a word." in text
    assert "On a first request it can't" in text
    assert "| `ollama` | **cut silently**, and the reply is acted on |" in text
    assert "| `claude` | refused" in text
    assert "| `lm-studio` | refused" in text


def test_the_readme_names_every_engine_in_the_table_for_usage_and_the_first_request() -> None:
    # Spec: anthropic-runner, "The runner counts by its runtime's engine and never guesses it";
    # troupe#418's done-when: the README says which engines can still lose content silently.
    usage = _section("Usage")
    context = _section("The context")
    for engine in ENGINES:
        assert f"| `{engine}` |" in usage
        assert f"| `{engine}` |" in context
