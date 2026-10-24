"""The README documents exactly the options the published schema defines (task 4.3)."""

import json
import re
from pathlib import Path

from claude_harness import RUNNER_SCHEMAS
from troupe_runner_claude_code.defaults import DEFAULT_MAX_BUDGET_USD

README = Path(__file__).resolve().parents[1] / "README.md"


def _section(heading: str) -> str:
    text = README.read_text(encoding="utf-8")
    start = text.index(f"\n## {heading}\n")
    end = text.find("\n## ", start + 1)
    return text[start : end if end != -1 else len(text)]


def test_every_option_in_the_schema_has_a_row_and_every_row_an_option() -> None:
    schema = json.loads((RUNNER_SCHEMAS / "options.schema.json").read_text(encoding="utf-8"))
    rows = re.findall(r"^\| `([A-Za-z]+)` \|", _section("Options"), flags=re.MULTILINE)
    assert sorted(rows) == sorted(schema["properties"])


def test_the_readme_states_the_default_budget_the_runner_uses() -> None:
    assert f"USD {DEFAULT_MAX_BUDGET_USD:g}" in _section("Options")


def test_every_relative_link_in_the_readme_names_a_path_that_exists() -> None:
    text = README.read_text(encoding="utf-8")
    targets = re.findall(r"\]\(([^)#:]+)(?:#[^)]*)?\)", text)
    missing = [t for t in targets if not (README.parent / t).exists()]
    assert targets
    assert missing == []
