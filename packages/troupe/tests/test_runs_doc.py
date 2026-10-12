"""docs/runs.md describes runs, stages and policy as the code defines them."""

import re
from pathlib import Path

from troupe.core import defaults
from troupe.core.policy import ALLOW_UNENFORCED_LOCAL_STAGE, env_name

DOC = Path(__file__).resolve().parents[3] / "docs" / "runs.md"
TEXT = DOC.read_text(encoding="utf-8")


def _section(heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", TEXT, re.M | re.S)
    assert match is not None, f"docs/runs.md has no section {heading!r}"
    return match.group(1)


def test_the_policy_table_gives_each_settings_default_as_the_code_does() -> None:
    rows = dict(re.findall(r"^\| `([a-z_]+)` \| `([a-z]+)` \|", _section("Policy"), re.M))
    assert rows == {
        ALLOW_UNENFORCED_LOCAL_STAGE: str(defaults.ALLOW_UNENFORCED_LOCAL_STAGE).lower()
    }


def test_the_policy_section_names_the_variable_the_code_reads() -> None:
    assert env_name(ALLOW_UNENFORCED_LOCAL_STAGE) in _section("Policy")


def test_every_relative_link_resolves() -> None:
    for target in re.findall(r"\]\(((?:\.\./|[a-z])[^)#:]*)(?:#[^)]*)?\)", TEXT):
        assert (DOC.parent / target).exists(), target
