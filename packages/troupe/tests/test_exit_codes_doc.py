import re
from pathlib import Path

import pytest

from troupe.core.exit_codes import ExitCode

pytestmark = pytest.mark.docs  # reads docs/ (scripts/check-paths.toml)

DOC = Path(__file__).resolve().parents[3] / "docs" / "cli" / "exit-codes.md"
ROW = re.compile(r"^\| (\d+) \| `([A-Z_]+)` \|", re.MULTILINE)


def test_exit_code_document_lists_exactly_the_codes_in_the_enum() -> None:
    documented = {(int(code), name) for code, name in ROW.findall(DOC.read_text(encoding="utf-8"))}
    assert documented == {(member.value, member.name) for member in ExitCode}
