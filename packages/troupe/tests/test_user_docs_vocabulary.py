"""The user docs use troupe's vocabulary, with the glossary as its single source (spec: user-docs;
user-docs design D5).

Ported from the website's tests/unit/vocabulary.test.ts, which held these rules while the docs lived
there. The checks of the brand guide's §6 against the glossary stay with the website.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from userdocs import DOCS, pages

pytestmark = pytest.mark.docs  # reads docs/ (scripts/check-paths.toml)

GLOSSARY = "prompt-book/glossary.md"
HOUSE_PAGE = "the-company/the-house.md"
REQUIRED_TERMS = ("stage", "rehearsal", "system", "cue")

WORDS = re.compile(r"\b(projects?|repos?|repository|repositories)\b", re.IGNORECASE)
UNCONFIRMED = re.compile(r"\bTBC\b|isn['\u2019]t final", re.IGNORECASE)


@dataclass(frozen=True)
class Use:
    page: str  # its path under docs/
    text: str  # a fragment of the line, so an edit elsewhere in the page doesn't break the match
    reason: str  # why it isn't a theatre


# Every line in docs/ that says "project", "repo" or "repository", with why it isn't a theatre.
# Where it means a theatre, say "theatre" instead (brand guide §7).
USES = (
    Use(GLOSSARY, "A project directory with troupe config", "explains what a theatre is"),
    Use(
        "programme/what-is-troupe.md",
        "the project directory troupe works in",
        "explains what a theatre is",
    ),
    Use(
        "programme/principles.md",
        "A theatre is your project directory.",
        "explains what a theatre is",
    ),
    Use(
        "opening-night/first-theatre.md",
        "Setting up troupe in a project directory.",
        "a theatre is made from a project directory",
    ),
    Use(
        "opening-night/first-theatre.md",
        "in an existing project directory, step by step",
        "a theatre is made from a project directory",
    ),
)


@dataclass(frozen=True)
class Found:
    page: str
    line: int
    text: str

    def __str__(self) -> str:
        return f"{self.page}:{self.line}: {self.text.strip()}"


def found(root: Path) -> list[Found]:
    """Every line in the pages under ``root`` that says one of the recorded words."""
    lines = []
    for path in pages(root):
        page = path.relative_to(root).as_posix()
        for number, text in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if WORDS.search(text):
                lines.append(Found(page, number, text))
    return lines


def unrecorded(root: Path, uses: tuple[Use, ...]) -> list[str]:
    return [
        str(line)
        for line in found(root)
        if not any(use.page == line.page and use.text in line.text for use in uses)
    ]


def stale(root: Path, uses: tuple[Use, ...]) -> list[str]:
    lines = found(root)
    return [
        f'{use.page}: "{use.text}"'
        for use in uses
        if not any(use.page == line.page and use.text in line.text for line in lines)
    ]


def glossary_rows(text: str) -> list[tuple[str, str]]:
    """The glossary table's rows, as they're written: the term cell and the meaning cell."""
    rows = [line for line in text.splitlines() if line.startswith("|")]
    cells = [[cell.strip() for cell in row.strip("|").split("|")] for row in rows[2:]]
    return [(term, meaning) for term, meaning in cells]


def glossary_problems(text: str) -> list[str]:
    rows = glossary_rows(text)
    terms = [term for term, _ in rows]
    problems = [
        f"the term {term!r} is in code font: write it plainly, and name any literal value in its "
        "meaning"
        for term in terms
        if "`" in term
    ]
    problems += [
        f"the glossary has no row for {term}" for term in REQUIRED_TERMS if term not in terms
    ]
    meaning = dict(rows).get("cue", "")
    if "cue" in terms and not re.search("provisional", meaning, re.IGNORECASE):
        problems.append("the glossary's cue row doesn't say the name is provisional")
    return problems


def write(root: Path, page: str, text: str) -> None:
    path = root / page
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


GLOSSARY_TABLE = """\
| Term | Meaning |
|---|---|
| theatre | A project directory with troupe config |
| system | troupe acting by itself, recorded as an actor of kind `system` |
| stage | Where an actor runs |
| rehearsal | A dry run of a performance |
| cue | An open request to a role. The name is provisional |
"""


# The docs as they are.


def test_the_scan_reads_every_page_including_the_glossary() -> None:
    scanned = [path.relative_to(DOCS).as_posix() for path in pages()]
    assert GLOSSARY in scanned
    assert HOUSE_PAGE in scanned


def test_every_project_or_repo_in_the_docs_is_recorded_with_a_reason() -> None:
    assert unrecorded(DOCS, USES) == [], (
        'Where "project" or "repo" means a theatre, say "theatre", or "project directory" when '
        "explaining one (brand guide §7). Otherwise add the line to USES in "
        "packages/troupe/tests/test_user_docs_vocabulary.py, with why it isn't a theatre."
    )


def test_every_recorded_use_is_still_in_the_docs() -> None:
    assert stale(DOCS, USES) == [], "Remove the stale entries from USES."


def test_the_glossary_has_plain_terms_and_the_terms_it_must() -> None:
    assert glossary_problems((DOCS / GLOSSARY).read_text(encoding="utf-8")) == []


def test_neither_the_glossary_nor_the_house_page_calls_the_house_unconfirmed() -> None:
    lines = [
        f"{page}:{number}: {text.strip()}"
        for page in (GLOSSARY, HOUSE_PAGE)
        for number, text in enumerate((DOCS / page).read_text(encoding="utf-8").splitlines(), 1)
        if UNCONFIRMED.search(text)
    ]
    assert lines == []


# Each rule fails when it should.


def test_a_new_project_is_named_with_its_page_and_line(tmp_path: Path) -> None:
    write(
        tmp_path, "the-company/theatres.md", "---\ntitle: T\n---\n\nRun troupe in your project.\n"
    )
    assert unrecorded(tmp_path, ()) == ["the-company/theatres.md:5: Run troupe in your project."]


def test_repo_for_a_theatre_is_named_with_its_page_and_line(tmp_path: Path) -> None:
    write(tmp_path, "opening-night/first-theatre.md", "Set up troupe in an existing repo.\n")
    assert unrecorded(tmp_path, ()) == [
        "opening-night/first-theatre.md:1: Set up troupe in an existing repo."
    ]


def test_a_recorded_use_that_was_edited_away_is_stale(tmp_path: Path) -> None:
    write(tmp_path, "the-company/theatres.md", "A theatre is where troupe works.\n")
    use = Use("the-company/theatres.md", "A theatre is your project directory", "explains it")
    assert stale(tmp_path, (use,)) == [
        'the-company/theatres.md: "A theatre is your project directory"'
    ]


def test_a_recorded_use_on_another_page_doesnt_cover_this_one(tmp_path: Path) -> None:
    write(tmp_path, "a.md", "your project directory\n")
    use = Use("b.md", "your project directory", "explains it")
    assert unrecorded(tmp_path, (use,)) == ["a.md:1: your project directory"]


def test_a_term_in_code_font_is_named(tmp_path: Path) -> None:
    # The website's system row before the owner's fix (#123, 2026-10-19).
    table = GLOSSARY_TABLE.replace(
        "| system | troupe acting by itself, recorded as an actor of kind `system` |",
        "| `system` | troupe acting by itself, recorded as an actor |",
    )
    assert glossary_problems(table) == [
        "the term '`system`' is in code font: write it plainly, and name any literal value in its "
        "meaning",
        "the glossary has no row for system",
    ]


def test_a_missing_term_is_named() -> None:
    table = GLOSSARY_TABLE.replace("| rehearsal | A dry run of a performance |\n", "")
    assert glossary_problems(table) == ["the glossary has no row for rehearsal"]


def test_a_cue_that_isnt_marked_provisional_is_named() -> None:
    table = GLOSSARY_TABLE.replace(". The name is provisional", "")
    assert glossary_problems(table) == [
        "the glossary's cue row doesn't say the name is provisional"
    ]


def test_the_sample_glossary_passes() -> None:
    assert glossary_problems(GLOSSARY_TABLE) == []
