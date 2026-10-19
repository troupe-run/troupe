"""Links between the user docs resolve, with anchors as the site makes them (spec: user-docs;
user-docs design D7).

The site publishes only docs/, so a relative link must stay inside it. A link to the rest of this
repository is an absolute GitHub URL, which isn't fetched here.
"""

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import pytest

from userdocs import DOCS, pages

pytestmark = pytest.mark.docs  # reads docs/ (scripts/check-paths.toml)

FENCE = re.compile(r"^(```|~~~).*?^\1[ \t]*$", re.MULTILINE | re.DOTALL)
GENERATED = re.compile(r"<!-- generated: .*?<!-- end generated: [a-z-]+ -->", re.DOTALL)
INLINE_CODE = re.compile(r"`[^`\n]*`")
INLINE = re.compile(r"\[(?:[^\[\]]|\[[^\]]*\])*\]\(\s*<?([^)\s>]*)>?(?:\s+\"[^\"]*\")?\s*\)")
REFERENCE = re.compile(
    r"^[ \t]*\[[^\]]+\]:[ \t]*<?(\S+?)>?(?:[ \t]+\"[^\"]*\")?[ \t]*$", re.MULTILINE
)
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)


def slug(text: str) -> str:
    """A heading's id as github-slugger makes it, before repeats are numbered."""
    kept = "".join(
        char
        for char in text.lower()
        if char in "- _"
        or unicodedata.category(char)[0] in "LNM"
        or unicodedata.category(char) == "Pc"
    )
    return kept.replace(" ", "-")


def heading_text(markdown: str) -> str:
    """A heading's text as the site reads it: code spans and links keep their text, and emphasis
    markers go. Underscores inside a word or a code span aren't emphasis."""
    parts = re.split(r"(`[^`]*`)", markdown)
    text = ""
    for part in parts:
        if part.startswith("`") and part.endswith("`") and len(part) >= 2:
            text += part[1:-1]
            continue
        part = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", part)
        part = re.sub(r"(\*\*|\*)(\S(?:.*?\S)?)\1", r"\2", part)
        text += re.sub(r"(?<!\w)(__|_)(\S(?:.*?\S)?)\1(?!\w)", r"\2", part)
    return text


def anchors(markdown: str) -> list[str]:
    """Every heading's id in a page, numbered for repeats as github-slugger numbers them."""
    seen: dict[str, int] = {}
    found = []
    for heading in HEADING.findall(FENCE.sub("", markdown)):
        base = slug(heading_text(heading))
        made = base
        while made in seen:
            seen[base] += 1
            made = f"{base}-{seen[base]}"
        seen[made] = 0
        found.append(made)
    return found


@dataclass(frozen=True)
class Link:
    page: str
    line: int
    target: str


def links(path: Path, root: Path) -> list[Link]:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    # Blank out what isn't prose, keeping the newlines so line numbers stay true.
    for pattern in (FENCE, GENERATED, INLINE_CODE):
        text = pattern.sub(lambda match: re.sub(r"[^\n]", " ", match.group(0)), text)
    page = path.relative_to(root).as_posix()
    found = []
    for pattern in (INLINE, REFERENCE):
        for match in pattern.finditer(text):
            found.append(Link(page, text.count("\n", 0, match.start()) + 1, match.group(1)))
    return sorted(found, key=lambda link: (link.line, link.target))


def _inside(page: str, target: str) -> str | None:
    """``target``, linked from ``page``, as a path under docs/, or None when it leaves docs/."""
    parts: list[str] = []
    for part in (PurePosixPath(page).parent / target).parts:
        if part == "..":
            if not parts:
                return None
            parts.pop()
        elif part != ".":
            parts.append(part)
    return "/".join(parts)


def _problem(link: Link, path: Path, root: Path) -> str | None:
    where = f"{link.page}:{link.line}: {link.target}"
    if SCHEME.match(link.target):
        return None
    if link.target.startswith("/"):
        return (
            f"{where} is a path on the site, which this check can't resolve: link a page under "
            "docs/ by its .md path, or a page the website keeps by its full https://troupe.run/ URL"
        )
    target, _, anchor = link.target.partition("#")
    if not target:
        have = anchors(path.read_text(encoding="utf-8"))
        if anchor in have:
            return None
        listed = ", ".join(have) or "none"
        return f"{where}: the page has no heading #{anchor}; its anchors are {listed}"
    name = _inside(link.page, target)
    if name is None:
        return (
            f"{where} leaves docs/, which is all the site publishes: link the file's GitHub URL, "
            "https://github.com/troupe-run/troupe/blob/main/<path>"
        )
    if not name.endswith(".md") or not (root / name).is_file():
        return f"{where} isn't a page under docs/: link a page by its .md path"
    have = anchors((root / name).read_text(encoding="utf-8"))
    if anchor and anchor not in have:
        return (
            f"{where}: {name} has no heading #{anchor}; its anchors are {', '.join(have) or 'none'}"
        )
    return None


def problems(root: Path) -> list[str]:
    """Every link under ``root`` that doesn't resolve, with the page, the line and the fix."""
    found = []
    for path in pages(root):
        for link in links(path, root):
            problem = _problem(link, path, root)
            if problem is not None:
                found.append(problem)
    return found


def write(root: Path, page: str, text: str) -> None:
    path = root / page
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# The docs as they are.


def test_every_link_in_the_user_docs_resolves() -> None:
    assert problems(DOCS) == []


# The slugger, against github-slugger's own cases.


@pytest.mark.parametrize(
    ("heading", "expected"),
    [
        ("foo", "foo"),
        ("foo bar", "foo-bar"),
        ("Foo", "foo"),
        ("Hello, World!", "hello-world"),
        ("Mixed CASE", "mixed-case"),
        ("foo_bar", "foo_bar"),
        ("a  b", "a--b"),
        ("Привет non-ascii", "привет-non-ascii"),
        ("😄 emoji", "-emoji"),
        ("Heading with `code`", "heading-with-code"),
        ("Values that start with `-`", "values-that-start-with--"),
        ("Flows: fork, join, swarm, loop", "flows-fork-join-swarm-loop"),
        ("The git adapter (troupe_vcs_git.defaults)", "the-git-adapter-troupe_vcs_gitdefaults"),
        ("[A link](x.md) in a heading", "a-link-in-a-heading"),
    ],
)
def test_a_heading_slugs_as_github_slugger_slugs_it(heading: str, expected: str) -> None:
    assert slug(heading_text(heading)) == expected


def test_repeated_headings_are_numbered() -> None:
    assert anchors("## foo\n\n## foo\n\n## foo\n") == ["foo", "foo-1", "foo-2"]


def test_a_heading_inside_a_code_block_isnt_an_anchor() -> None:
    assert anchors("## real\n\n```markdown\n## not\n```\n") == ["real"]


# Each failure is named.


def test_a_link_to_a_missing_page_names_the_page_link_and_line(tmp_path: Path) -> None:
    write(
        tmp_path,
        "stagecraft/build-a-flow.md",
        "---\ntitle: T\n---\n\nSee [theatres](../the-company/theater.md).\n",
    )
    assert problems(tmp_path) == [
        "stagecraft/build-a-flow.md:5: ../the-company/theater.md isn't a page under docs/: link a "
        "page by its .md path"
    ]


def test_a_link_to_a_missing_heading_names_the_anchors_the_target_has(tmp_path: Path) -> None:
    write(tmp_path, "prompt-book/cli.md", "## Global flags\n\n## Errors\n")
    write(tmp_path, "prompt-book/events.md", "See [options](cli.md#global-options).\n")
    assert problems(tmp_path) == [
        "prompt-book/events.md:1: cli.md#global-options: prompt-book/cli.md has no heading "
        "#global-options; its anchors are global-flags, errors"
    ]


def test_a_relative_link_out_of_the_docs_says_to_use_the_github_url(tmp_path: Path) -> None:
    write(tmp_path, "prompt-book/events.md", "See [protocol](../../protocol/README.md).\n")
    assert problems(tmp_path) == [
        "prompt-book/events.md:1: ../../protocol/README.md leaves docs/, which is all the site "
        "publishes: link the file's GitHub URL, https://github.com/troupe-run/troupe/blob/main/<path>"
    ]


def test_a_link_to_a_page_in_the_same_section_and_its_anchor_resolves(tmp_path: Path) -> None:
    write(tmp_path, "the-company/lineage.md", "## Who acted\n")
    write(
        tmp_path,
        "the-company/theatres.md",
        "See [who](lineage.md#who-acted) and [here](#top).\n\n## Top\n",
    )
    assert problems(tmp_path) == []


def test_a_link_to_a_missing_heading_on_the_same_page_is_named(tmp_path: Path) -> None:
    write(tmp_path, "a.md", "See [below](#nowhere).\n\n## Somewhere\n")
    assert problems(tmp_path) == [
        "a.md:1: #nowhere: the page has no heading #nowhere; its anchors are somewhere"
    ]


def test_links_in_code_and_generated_regions_arent_read(tmp_path: Path) -> None:
    write(
        tmp_path,
        "a.md",
        "`[x](missing.md)`\n\n```markdown\n[y](missing.md)\n```\n\n"
        "<!-- generated: cli (from x) -->\n[z](missing.md)\n<!-- end generated: cli -->\n",
    )
    assert problems(tmp_path) == []


def test_an_absolute_url_isnt_fetched(tmp_path: Path) -> None:
    write(
        tmp_path,
        "a.md",
        "[gh](https://github.com/troupe-run/troupe/blob/main/contributing/runs.md)\n",
    )
    assert problems(tmp_path) == []


def test_a_reference_style_link_is_read(tmp_path: Path) -> None:
    write(tmp_path, "a.md", "See [the house][house].\n\n[house]: the-house.md\n")
    assert problems(tmp_path) == [
        "a.md:3: the-house.md isn't a page under docs/: link a page by its .md path"
    ]


def test_a_path_on_the_site_says_to_use_the_md_path_or_the_full_url(tmp_path: Path) -> None:
    write(tmp_path, "a.md", "See [status](/docs/programme/status-and-roadmap/).\n")
    assert problems(tmp_path) == [
        "a.md:1: /docs/programme/status-and-roadmap/ is a path on the site, which this check can't "
        "resolve: link a page under docs/ by its .md path, or a page the website keeps by its full "
        "https://troupe.run/ URL"
    ]
