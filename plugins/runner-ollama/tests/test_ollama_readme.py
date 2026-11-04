"""The README documents exactly what the runner has: its options, its named settings, and what it
requires (local-model-runner task 6.2)."""

import json
import re
from pathlib import Path

from ollama_harness import RUNNER_SCHEMAS
from troupe_runner_ollama import defaults
from troupe_runner_ollama.requirements import load

README = Path(__file__).resolve().parents[1] / "README.md"


def _section(heading: str) -> str:
    text = README.read_text(encoding="utf-8")
    start = text.index(f"\n## {heading}\n")
    end = text.find("\n## ", start + 1)
    return text[start : end if end != -1 else len(text)]


def _rows(heading: str) -> list[str]:
    return re.findall(r"^\| `([A-Za-z_]+)` \|", _section(heading), flags=re.MULTILINE)


def test_every_option_in_the_schema_has_a_row_and_every_row_an_option() -> None:
    schema = json.loads((RUNNER_SCHEMAS / "options.schema.json").read_text(encoding="utf-8"))
    assert sorted(_rows("Options")) == sorted(schema["properties"])


def test_every_named_setting_has_a_row_and_every_row_a_setting() -> None:
    settings = [name for name in vars(defaults) if name.isupper()]
    assert sorted(_rows("Limits")) == sorted(settings)


def test_the_readme_states_the_ollama_version_the_runner_requires() -> None:
    (requirement,) = load()
    assert f"Ollama {requirement.minimum} or" in _section("Before the run starts")


def test_every_relative_link_in_the_readme_names_a_path_that_exists() -> None:
    text = README.read_text(encoding="utf-8")
    targets = re.findall(r"\]\(([^)#:]+)(?:#[^)]*)?\)", text)
    missing = [t for t in targets if not (README.parent / t).exists()]
    assert targets
    assert missing == []
