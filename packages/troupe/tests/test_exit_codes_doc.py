import re
from pathlib import Path

import pytest

from troupe.core.exit_codes import ExitCode

TESTS_ROOT = next(p for p in Path(__file__).resolve().parents if p.name == "tests")
"""This suite's tests directory, found by name so the file can sit at any depth under it."""

pytestmark = pytest.mark.docs  # reads docs/ (scripts/check-paths.toml)

DOC = TESTS_ROOT.parents[2] / "docs" / "prompt-book" / "cli.md"
ROW = re.compile(r"^\| (\d+) \| `([A-Z_]+)` \|", re.MULTILINE)


def test_exit_code_document_lists_exactly_the_codes_in_the_enum() -> None:
    documented = {(int(code), name) for code, name in ROW.findall(DOC.read_text(encoding="utf-8"))}
    assert documented == {(member.value, member.name) for member in ExitCode}
