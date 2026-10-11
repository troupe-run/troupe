"""Task 6.4: docs/development-workflow.md lists exactly the guard's rules."""

import re

from conftest import REPO

import guard

DOC = REPO / "docs" / "development-workflow.md"
ROW = re.compile(r"^\| `([a-z-]+)` \| (git|Claude) \|", re.MULTILINE)


def test_the_docs_list_exactly_the_guard_s_rules() -> None:
    documented = ROW.findall(DOC.read_text(encoding="utf-8"))
    assert sorted(rule for rule, _ in documented) == sorted(guard.RULES)


def test_the_docs_say_the_tamper_rule_can_t_be_overridden() -> None:
    row = next(
        line
        for line in DOC.read_text(encoding="utf-8").splitlines()
        if f"`{guard.TAMPER_RULE}`" in line
    )
    assert "No override unlocks this rule" in row
