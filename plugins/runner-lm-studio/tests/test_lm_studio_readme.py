"""The README names exactly the runner's options, named settings and error codes: no more and no
fewer (lmstudio-runner task 11.3). Their values are checked by eye, not here."""

import json
import re
from pathlib import Path

from lm_studio_harness import RUNNER_SCHEMAS
from troupe_runner_lm_studio import defaults

README = Path(__file__).resolve().parents[1] / "README.md"


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
