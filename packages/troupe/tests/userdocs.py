"""The user docs in docs/, read for tests (spec: user-docs; user-docs design D2).

Front matter is read as a strict subset of YAML: one ``key: value`` per line, each value a
double-quoted or single-quoted string, ``true`` or ``false``, or a plain scalar that YAML reads as
the same string. Anything else is refused with a fix rather than read loosely, so a page that
parses here means the same to the site's YAML loader.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DOCS = ROOT / "docs"

FRONT_MATTER_KEYS = {
    "title": str,
    "description": str,
    "status": str,
    "prerelease": bool,
    "purpose": str,
}
"""Every key a page may set, with its type. website#23's content schema must allow exactly these:
change both together (user-docs design D2)."""

STATUSES = ("written", "planned")

_KEY = re.compile(r"[a-z][a-z0-9_]*")
# A plain scalar YAML reads as a string: no indicator first, and no ": " or " #" inside.
_PLAIN = re.compile(r"[^\s\-?:,\[\]{}#&*!|>'\"%@`](?:(?!: | #).)*")
_RESERVED = {"true", "false", "null", "~", "yes", "no", "on", "off"}


class FrontMatterError(ValueError):
    """A page's front matter isn't in the subset troupe's docs use."""


@dataclass(frozen=True)
class Page:
    name: str  # the page's path under docs/, with ``/``
    front: dict[str, str | bool]
    body: str


def _value(raw: str) -> str | bool:
    if raw in ("true", "false"):
        return raw == "true"
    if raw.startswith('"'):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            raise FrontMatterError(
                f"{raw} isn't a double-quoted string with JSON's escapes"
            ) from None
        if isinstance(value, str):
            return value
    if raw.startswith("'") and raw.endswith("'") and len(raw) >= 2:
        inner = raw[1:-1]
        if "'" not in inner.replace("''", ""):
            return inner.replace("''", "'")
    if (
        _PLAIN.fullmatch(raw)
        and raw.lower() not in _RESERVED
        and not re.fullmatch(r"[-+.\d]+", raw)
    ):
        return raw
    raise FrontMatterError(
        f"{raw} isn't a string, true or false; quote it with double quotes, as in "
        f'"Flows: fork, join, swarm, loop"'
    )


def parse(text: str) -> tuple[dict[str, str | bool], str]:
    """A page's front matter and its body, refusing what the subset doesn't allow."""
    lines = text.replace("\r\n", "\n").split("\n")
    if lines[0] != "---":
        raise FrontMatterError(
            "the page doesn't start with front matter: put `---` on its first line"
        )
    try:
        end = lines.index("---", 1)
    except ValueError:
        raise FrontMatterError("the front matter has no closing `---` line") from None
    front: dict[str, str | bool] = {}
    for number, line in enumerate(lines[1:end], start=2):
        key, separator, raw = line.partition(": ")
        if not separator or not _KEY.fullmatch(key) or raw != raw.strip() or not raw:
            raise FrontMatterError(f"line {number} isn't `key: value`: {line!r}")
        if key in front:
            raise FrontMatterError(f"`{key}` is set twice; keep one")
        try:
            front[key] = _value(raw)
        except FrontMatterError as error:
            raise FrontMatterError(f"`{key}` on line {number}: {error}") from None
    return front, "\n".join(lines[end + 1 :])


def read(path: Path, root: Path = DOCS) -> Page:
    """The page at ``path``, named by its path under ``root``."""
    name = path.relative_to(root).as_posix()
    try:
        front, body = parse(path.read_text(encoding="utf-8"))
    except FrontMatterError as error:
        raise FrontMatterError(f"{name}: {error}") from None
    return Page(name=name, front=front, body=body)


def pages(root: Path = DOCS) -> list[Path]:
    """Every page under ``root``, sorted."""
    return sorted(root.rglob("*.md"))


def problems(page: Page) -> list[str]:
    """What's wrong with a page's front matter against the site's schema, as the spec has it."""
    front = page.front
    found = []
    for key, value in front.items():
        if key not in FRONT_MATTER_KEYS:
            allowed = ", ".join(FRONT_MATTER_KEYS)
            found.append(f"`{key}` isn't a front-matter key; the keys allowed are {allowed}")
        elif not isinstance(value, FRONT_MATTER_KEYS[key]):
            kind = "true or false" if FRONT_MATTER_KEYS[key] is bool else "a string"
            found.append(f"`{key}` must be {kind}")
    for key in ("title", "description"):
        if not isinstance(front.get(key), str) or not str(front.get(key)).strip():
            found.append(f"`{key}` is missing or empty; give the page a {key}")
    status = front.get("status")
    if status not in STATUSES:
        found.append(f"`status` must be `written` or `planned`, not {status!r}")
    has_body = bool(page.body.strip())
    if status == "planned":
        if not isinstance(front.get("purpose"), str) or not str(front.get("purpose")).strip():
            found.append("a planned page needs a `purpose`: the line its placeholder shows")
        if has_body:
            found.append("a planned page has no body: set `status: written`, or remove the body")
    if status == "written":
        if not has_body:
            found.append("a written page needs a body, or `status: planned` and a `purpose`")
        if "prerelease" not in front:
            found.append(
                "a written page sets `prerelease`: `true` if it describes behaviour troupe "
                "doesn't have yet, `false` otherwise"
            )
    return found
