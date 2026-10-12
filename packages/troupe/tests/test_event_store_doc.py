"""docs/event-store.md lists exactly the event store's notices and errors, and its links resolve
(event-store task 9.5)."""

import re
from pathlib import Path

from troupe.core.errors import CODES
from troupe.core.notices import CODES as NOTICE_CODES

DOC = Path(__file__).resolve().parents[3] / "docs" / "event-store.md"
TEXT = DOC.read_text(encoding="utf-8")
PREFIXES = {"events", "identity", "vcs"}


def _table_codes() -> set[str]:
    return set(re.findall(r"^\| `([a-z-]+\.[a-z.-]+)` \|", TEXT, re.MULTILINE))


def test_the_tables_list_exactly_the_event_stores_notices_and_errors() -> None:
    notices = {code for code in NOTICE_CODES if code.split(".")[0] in PREFIXES}
    errors = {code for code in CODES if code.split(".")[0] in PREFIXES}
    assert notices
    assert _table_codes() == notices | errors


def test_every_relative_link_resolves() -> None:
    for target in re.findall(r"\]\(((?:\.\./|[a-z])[^)#:]*)(?:#[^)]*)?\)", TEXT):
        assert (DOC.parent / target).exists(), target


def test_the_benchmark_the_doc_cites_exists() -> None:
    assert "scripts/benchmark_event_store.py" in TEXT
    assert (DOC.parents[1] / "scripts" / "benchmark_event_store.py").is_file()
