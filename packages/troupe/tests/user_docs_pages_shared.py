"""What test_user_docs_pages.py and test_user_docs_pages_integration.py share."""

import re
from pathlib import Path

from userdocs import DOCS

ROOT = Path(__file__).resolve().parents[3]
BLOCK = re.compile(
    r"^```(?P<lang>\w+)(?P<meta>[^\n]*)\n(?P<body>.*?)^```", re.MULTILINE | re.DOTALL
)


def blocks_in(text: str) -> list[tuple[str, str, str]]:
    """Each fenced block in ``text``: its language, its meta (such as ``title="x"``) and text."""
    return [
        (m.group("lang"), m.group("meta").strip(), m.group("body")) for m in BLOCK.finditer(text)
    ]


# Your first performance (first-run-walkthrough design D1-D5).

PAGE = "opening-night/first-performance.md"
LOCAL = "Try it with a model on your own machine"
OPENAI = "Try it on OpenAI"
ANTHROPIC = "Try it on Claude's API"
MISTRALRS = "Try it in-process with mistral.rs"


def sh_lines(text: str) -> list[str]:
    """Every line of every sh block in ``text``, in order: the commands a reader runs."""
    return [line for lang, _, body in blocks_in(text) if lang == "sh" for line in body.splitlines()]


# Performances and runs.


def section(page: str, heading: str) -> str:
    text = (DOCS / page).read_text(encoding="utf-8")
    match = re.search(
        rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL
    )
    assert match is not None, f"{page} has no section {heading!r}"
    return match.group(1)


# Point actors at a service (runtimes design; spec: runtimes).

RUNTIMES_PAGE = "stagecraft/runtimes.md"
