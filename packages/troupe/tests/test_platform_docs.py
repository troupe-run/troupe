import re
from pathlib import Path

from troupe.core import defaults

DOC = Path(__file__).resolve().parents[3] / "docs" / "platform.md"
ROW = re.compile(r"^\| `([A-Z_]+)` \| ([0-9.]+) \|$", re.MULTILINE)


def test_platform_doc_lists_exactly_the_defaults_and_their_values() -> None:
    documented = {
        name: float(value) for name, value in ROW.findall(DOC.read_text(encoding="utf-8"))
    }
    actual = {
        name: float(value)
        for name, value in vars(defaults).items()
        if name.isupper() and isinstance(value, int | float)
    }
    assert documented == actual
