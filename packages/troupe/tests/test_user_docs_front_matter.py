"""Every page in docs/ carries the site's front matter, closed and explicit (spec: user-docs;
user-docs design D2)."""

from pathlib import Path

import pytest

from userdocs import DOCS, FrontMatterError, Page, pages, parse, problems, read

pytestmark = pytest.mark.docs  # reads docs/ (scripts/check-paths.toml)

WRITTEN = (
    "---\ntitle: Theatres\ndescription: What a theatre is.\nstatus: written\n{extra}---\n\n{body}"
)


def page(tmp_path: Path, text: str) -> Page:
    path = tmp_path / "the-company" / "theatres.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return read(path, root=tmp_path)


def test_the_user_docs_have_pages() -> None:
    assert len(pages()) >= 2


@pytest.mark.parametrize("path", pages(), ids=lambda path: path.relative_to(DOCS).as_posix())
def test_every_page_has_front_matter_the_site_accepts(path: Path) -> None:
    assert problems(read(path)) == []


def test_a_page_with_a_missing_description_names_description(tmp_path: Path) -> None:
    found = problems(page(tmp_path, "---\ntitle: Theatres\nstatus: planned\npurpose: What.\n---\n"))
    assert found == ["`description` is missing or empty; give the page a description"]


def test_an_unknown_key_is_named_with_the_keys_allowed(tmp_path: Path) -> None:
    found = problems(
        page(tmp_path, WRITTEN.format(extra="prerelease: false\nstaus: x\n", body="Hi."))
    )
    assert found == [
        "`staus` isn't a front-matter key; the keys allowed are title, description, status, "
        "prerelease, purpose"
    ]


def test_a_planned_page_with_text_says_to_write_it_or_remove_the_body(tmp_path: Path) -> None:
    text = "---\ntitle: T\ndescription: D.\nstatus: planned\npurpose: P.\n---\n\nSome text.\n"
    assert problems(page(tmp_path, text)) == [
        "a planned page has no body: set `status: written`, or remove the body"
    ]


def test_a_written_page_that_leaves_prerelease_out_says_what_to_set(tmp_path: Path) -> None:
    assert problems(page(tmp_path, WRITTEN.format(extra="", body="Hi.\n"))) == [
        "a written page sets `prerelease`: `true` if it describes behaviour troupe doesn't have "
        "yet, `false` otherwise"
    ]


def test_a_planned_page_needs_a_purpose(tmp_path: Path) -> None:
    found = problems(page(tmp_path, "---\ntitle: T\ndescription: D.\nstatus: planned\n---\n"))
    assert found == ["a planned page needs a `purpose`: the line its placeholder shows"]


def test_prerelease_must_be_true_or_false(tmp_path: Path) -> None:
    found = problems(page(tmp_path, WRITTEN.format(extra='prerelease: "no"\n', body="Hi.")))
    assert found == ["`prerelease` must be true or false"]


def test_the_websites_quoted_purpose_reads_as_the_site_reads_it() -> None:
    # As the website's stagecraft/read-the-lineage.md has it (origin/main, 2026-10-19).
    front, body = parse(
        "---\ntitle: Read the lineage\ndescription: Following the record.\nstatus: planned\n"
        'purpose: "Answering \\"who decided this?\\" from the lineage."\n---\n'
    )
    assert front["purpose"] == 'Answering "who decided this?" from the lineage.'
    assert body == ""


def test_a_key_set_twice_is_refused() -> None:
    with pytest.raises(FrontMatterError, match="`title` is set twice; keep one"):
        parse("---\ntitle: A\ntitle: B\n---\n")


@pytest.mark.parametrize(
    "value",
    ["Flows: fork, join", "[a, b]", "yes", "12", "a # comment", "'it's'"],
    ids=["colon", "flow-list", "yaml-bool", "number", "comment", "bad-single-quote"],
)
def test_a_value_yaml_would_read_differently_is_refused_with_how_to_quote_it(value: str) -> None:
    with pytest.raises(FrontMatterError, match="quote it with double quotes"):
        parse(f"---\ntitle: {value}\n---\n")


def test_a_page_without_front_matter_is_refused() -> None:
    with pytest.raises(FrontMatterError, match="put `---` on its first line"):
        parse("# Theatres\n")


def test_crlf_line_endings_read_the_same() -> None:
    text = "---\ntitle: T\ndescription: D.\nstatus: planned\npurpose: P.\n---\n"
    assert parse(text.replace("\n", "\r\n")) == parse(text)
