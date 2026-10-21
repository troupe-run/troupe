"""Regenerate the user docs' generated regions from their sources (spec: user-docs; user-docs
design D3).

    uv run scripts/docs_reference.py            rewrite every stale region
    uv run scripts/docs_reference.py --check    change nothing; exit 1 naming each stale region

A region sits between two HTML comments, which Markdown doesn't render:

    <!-- generated: cli (from ...; regenerate with `uv run scripts/docs_reference.py`) -->
    ...
    <!-- end generated: cli -->

Only the text between the markers is rewritten, so the prose around a region is never touched. A
region's text is built from the code and the schemas, never from argparse's own help formatting,
which changes between Python versions.
"""

import argparse
import ast
import json
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from troupe.cli import COMMANDS
from troupe.cli.parser import Command, _global_options

ROOT = Path(__file__).resolve().parents[1]
DOCS = "docs"
PROTOCOL = "protocol/schemas"
EXIT_CODES = "packages/troupe/src/troupe/core/exit_codes.py"
COMMAND = "uv run scripts/docs_reference.py"
ISSUES = "https://github.com/troupe-run/troupe/issues"

MARKED = re.compile(
    r"<!-- generated: (?P<name>[a-z-]+) [^\n]*-->\n(?P<body>.*?)<!-- end generated: (?P=name) -->",
    re.DOTALL,
)
START = re.compile(r"<!-- generated: (?P<name>[a-z-]+)[ \n]")


class ReferenceError(Exception):
    """A page or a source isn't as the generator needs it. The message names it and the fix."""


@dataclass(frozen=True)
class Sources:
    """Where each region is generated from. Tests replace them to show a region going stale."""

    root: Path = ROOT
    commands: Sequence[Command] = COMMANDS
    protocol: Path = field(default_factory=lambda: ROOT / PROTOCOL)


@dataclass(frozen=True)
class Region:
    name: str
    page: str  # its path under docs/
    source: str  # what it's generated from, as its start marker says
    render: Callable[[Sources], str]


def _cell(text: str) -> str:
    """Text for one Markdown table cell: whitespace collapsed, pipes escaped."""
    return " ".join(text.split()).replace("|", "\\|")


def _sentence(text: str) -> str:
    text = " ".join(text.split())
    return text[:1].upper() + text[1:] if text else text


# The CLI.


def _metavar(action: argparse.Action) -> str:
    name = action.metavar if isinstance(action.metavar, str) else action.dest
    return f"<{name.lower().replace('_', '-')}>"


def _takes_value(action: argparse.Action) -> bool:
    return action.nargs != 0


def _spelling(action: argparse.Action) -> str:
    """How an argument is written: ``<run>``, ``--limit <limit>`` or ``--json``."""
    if not action.option_strings:
        return _metavar(action)
    value = f" {_metavar(action)}" if _takes_value(action) else ""
    return ", ".join(f"`{name}{value}`" for name in action.option_strings)


def _usage_part(action: argparse.Action) -> str:
    if not action.option_strings:
        return _metavar(action)
    longest = max(action.option_strings, key=len)
    return f"{longest} {_metavar(action)}" if _takes_value(action) else longest


def _parser(command: Command) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"troupe {command.name}", add_help=False)
    command.configure(parser)
    return parser


def _groups(parser: argparse.ArgumentParser) -> list[argparse._MutuallyExclusiveGroup]:
    return list(parser._mutually_exclusive_groups)


def _usage(command: Command) -> str:
    parser = _parser(command)
    grouped = {id(action): group for group in _groups(parser) for action in group._group_actions}
    parts: list[str] = []
    done: set[int] = set()
    for action in parser._actions:
        group = grouped.get(id(action))
        if group is not None:
            if id(group) in done:
                continue
            done.add(id(group))
            joined = " | ".join(_usage_part(each) for each in group._group_actions)
            parts.append(f"({joined})" if group.required else f"[{joined}]")
        elif (action.option_strings and not action.required) or (
            not action.option_strings and action.nargs == "?"
        ):
            parts.append(f"[{_usage_part(action)}]")
        else:
            parts.append(_usage_part(action))
    return " ".join([f"troupe {command.name}", *parts])


def _needed(action: argparse.Action, groups: list[argparse._MutuallyExclusiveGroup]) -> str:
    for group in groups:
        if action in group._group_actions:
            names = ", ".join(f"`{each.option_strings[-1]}`" for each in group._group_actions)
            return f"One of {names}" if group.required else f"At most one of {names}"
    if action.option_strings:
        return "Yes" if action.required else "No"
    return "No" if action.nargs in ("?", "*") else "Yes"


def _help(action: argparse.Action) -> str:
    text = _sentence(action.help or "")
    if isinstance(action, argparse._AppendAction):
        text = re.sub(r"\s*\(repeatable\)", "", text).rstrip(".") + ". Repeatable"
    return _cell(text.rstrip("."))


def render_cli(sources: Sources) -> str:
    out = []
    for command in sources.commands:
        parser = _parser(command)
        groups = _groups(parser)
        out += [
            f"### `troupe {command.name}`",
            "",
            _sentence(command.help),
            "",
            "```text",
            _usage(command),
            "```",
            "",
            "| Argument | Required | What it is |",
            "|---|---|---|",
        ]
        out += [
            f"| {_spelling(action) if action.option_strings else f'`{_spelling(action)}`'} "
            f"| {_needed(action, groups)} | {_help(action)} |"
            for action in parser._actions
        ]
        out.append("")
    out += ["### Global flags", "", "| Flag | What it does |", "|---|---|"]
    out += [f"| {_spelling(action)} | {_help(action)} |" for action in _global_options()._actions]
    return "\n".join(out) + "\n"


# The exit codes.


def render_exit_codes(sources: Sources) -> str:
    path = sources.root / EXIT_CODES
    tree = ast.parse(path.read_text(encoding="utf-8"))
    enum = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ExitCode"
    )
    rows = ["| Code | Name | Meaning |", "|---|---|---|"]
    body = enum.body
    for index, node in enumerate(body):
        if not (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, int)
        ):
            continue
        name = node.targets[0].id if isinstance(node.targets[0], ast.Name) else "?"
        after = body[index + 1] if index + 1 < len(body) else None
        if not (
            isinstance(after, ast.Expr)
            and isinstance(after.value, ast.Constant)
            and isinstance(after.value.value, str)
        ):
            raise ReferenceError(
                f"{EXIT_CODES}: ExitCode.{name} has no docstring. Give it one: the docs' exit-code "
                "table is generated from them."
            )
        rows.append(f"| {node.value.value} | `{name}` | {_cell(after.value.value)} |")
    return "\n".join(rows) + "\n"


# The schemas: events and config.


class _Schemas:
    """The protocol's schemas, with ``$ref`` followed across files."""

    def __init__(self, protocol: Path) -> None:
        self.protocol = protocol
        self.loaded: dict[Path, Any] = {}

    def load(self, path: Path) -> Any:  # noqa: ANN401
        path = path.resolve()
        if path not in self.loaded:
            self.loaded[path] = json.loads(path.read_text(encoding="utf-8"))
        return self.loaded[path]

    def resolve(self, node: Any, base: Path) -> tuple[Any, Path]:  # noqa: ANN401
        """``node``, with each ``$ref`` followed, and the file the result came from."""
        while isinstance(node, dict) and "$ref" in node:
            target, _, pointer = node["$ref"].partition("#")
            path = (base.parent / target).resolve() if target else base
            found = self.load(path)
            for part in [part for part in pointer.split("/") if part]:
                found = found[part.replace("~1", "/").replace("~0", "~")]
            node, base = found, path
        return node, base

    def describe(self, node: Any, base: Path) -> str:  # noqa: ANN401
        """A property's description: its own, or the one where its reference leads."""
        while isinstance(node, dict):
            if "description" in node:
                return str(node["description"])
            if "$ref" not in node:
                return ""
            target, _, pointer = node["$ref"].partition("#")
            path = (base.parent / target).resolve() if target else base
            found = self.load(path)
            for part in [part for part in pointer.split("/") if part]:
                found = found[part]
            node, base = found, path
        return ""

    def kind(self, node: Any, base: Path) -> str:  # noqa: ANN401
        """A short name for what a property holds."""
        resolved, where = self.resolve(node, base)
        if not isinstance(resolved, dict):
            return "any"
        if "$dynamicRef" in resolved:
            return "object (an extension point, filled by the runner's options schema)"
        if "const" in resolved:
            return f"`{json.dumps(resolved['const'])}`"
        if "enum" in resolved:
            return "one of " + ", ".join(f"`{json.dumps(value)}`" for value in resolved["enum"])
        for combinator in ("oneOf", "anyOf"):
            if combinator in resolved:
                kinds = dict.fromkeys(self.kind(each, where) for each in resolved[combinator])
                return " or ".join(kinds)
        kind = resolved.get("type")
        if kind == "array":
            return f"list of {self.kind(resolved.get('items', {}), where)}"
        if kind == "object" and "title" in resolved:
            return f"object ({resolved['title']})"
        if isinstance(kind, list):
            return " or ".join(str(each) for each in kind)
        return str(kind or resolved.get("title", "any"))

    def fields(self, schema: Any, base: Path) -> list[str]:  # noqa: ANN401
        required = set(schema.get("required", []))
        rows = ["| Field | Holds | Always there | What it is |", "|---|---|---|---|"]
        for name, node in schema.get("properties", {}).items():
            always = "Yes" if name in required else "No"
            what = _cell(self.describe(node, base))
            if not what:
                where = base.relative_to(self.protocol.parent).as_posix()
                raise ReferenceError(
                    f"{where}: the field `{name}` has no description. Give it one in the schema "
                    "(or where its $ref leads): the docs' field tables are generated from them."
                )
            rows.append(f"| `{name}` | {_cell(self.kind(node, base))} | {always} | {what} |")
        return rows


def _schema_section(schemas: _Schemas, path: Path, heading: str) -> list[str]:
    schema = schemas.load(path)
    title = schema.get("title", path.name)
    return [
        f"{heading} {title}",
        "",
        _cell(schema.get("description", "")),
        "",
        *schemas.fields(schema, path),
        "",
    ]


def render_events(sources: Sources) -> str:
    schemas = _Schemas(sources.protocol)
    out: list[str] = []
    for path in sorted((sources.protocol / "events").glob("*.schema.json")):
        out += _schema_section(schemas, path, "###")
    out += _schema_section(schemas, sources.protocol / "lineage.schema.json", "###")
    return "\n".join(out).rstrip("\n") + "\n"


def render_config(sources: Sources) -> str:
    directory = sources.protocol / "config"
    found = sorted(directory.glob("*.schema.json")) if directory.is_dir() else []
    if not found:
        return (
            "There is no config schema yet: config arrives with "
            f"[#60]({ISSUES}/60), and this section is generated from its schemas when it does.\n"
        )
    schemas = _Schemas(sources.protocol)
    out: list[str] = []
    for path in found:
        out += _schema_section(schemas, path, "###")
    return "\n".join(out).rstrip("\n") + "\n"


REGIONS = (
    Region("cli", "prompt-book/cli.md", "troupe.cli.COMMANDS and the global options", render_cli),
    Region(
        "exit-codes", "prompt-book/cli.md", "troupe.core.exit_codes.ExitCode", render_exit_codes
    ),
    Region(
        "events", "prompt-book/events.md", "protocol/schemas/events/ and lineage", render_events
    ),
    Region("config", "prompt-book/config-schema.md", "protocol/schemas/config/", render_config),
)


def start_marker(region: Region) -> str:
    return f"<!-- generated: {region.name} (from {region.source}; regenerate with `{COMMAND}`) -->"


def regenerate(text: str, page: str, sources: Sources) -> tuple[str, list[str]]:
    """``text`` with every region of ``page`` regenerated, and the names of those that changed.

    Line endings are kept as the page has them. A page missing a region it must hold, or holding
    one this page doesn't, is refused.
    """
    newline = "\r\n" if "\r\n" in text else "\n"
    text = text.replace("\r\n", "\n")
    expected = {region.name: region for region in REGIONS if region.page == page}
    starts = [match.group("name") for match in START.finditer(text)]
    marked = {match.group("name"): match for match in MARKED.finditer(text)}
    for name in starts:
        if name not in expected:
            raise ReferenceError(
                f"{page} has a generated region `{name}` that isn't {page}'s to hold."
            )
        if name not in marked:
            raise ReferenceError(
                f"{page}'s generated region `{name}` has no `<!-- end generated: {name} -->` line."
            )
    for name in expected:
        if name not in marked:
            raise ReferenceError(
                f"{page} has no generated region `{name}`. Add the two marker lines where it goes:"
                f" {start_marker(expected[name])} and <!-- end generated: {name} -->, then run "
                f"`{COMMAND}`."
            )
    stale = []

    def fresh(match: re.Match[str]) -> str:
        region = expected[match.group("name")]
        body = region.render(sources)
        whole = f"{start_marker(region)}\n{body}<!-- end generated: {region.name} -->"
        if whole != match.group(0):
            stale.append(region.name)
        return whole

    result = MARKED.sub(fresh, text)
    return result.replace("\n", newline), stale


def run(check: bool, sources: Sources) -> list[str]:
    """Regenerate (or, with ``check``, only compare) every page that holds a region. Returns each
    stale region as ``page: name``."""
    stale = []
    for page in dict.fromkeys(region.page for region in REGIONS):
        path = sources.root / DOCS / page
        if not path.is_file():
            raise ReferenceError(f"{DOCS}/{page} doesn't exist; it holds generated regions.")
        text = path.read_bytes().decode("utf-8")
        result, changed = regenerate(text, page, sources)
        stale += [f"{DOCS}/{page}: {name}" for name in changed]
        if changed and not check:
            path.write_bytes(result.encode("utf-8"))
    return stale


def main(argv: Sequence[str] | None = None, sources: Sources | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="docs_reference.py", description="Regenerate the user docs' generated regions."
    )
    parser.add_argument("--check", action="store_true", help="change nothing; report stale regions")
    args = parser.parse_args(argv)
    try:
        stale = run(args.check, sources or Sources())
    except ReferenceError as error:
        print(f"docs_reference: {error}", file=sys.stderr)
        return 2
    if args.check and stale:
        for each in stale:
            print(f"docs_reference: {each} is stale", file=sys.stderr)
        print(
            f"  fix: run `{COMMAND}`. To change what a region says, change its source (the CLI's "
            "definitions, ExitCode's docstrings or the schema), never the region.",
            file=sys.stderr,
        )
        return 1
    for each in stale:
        print(f"docs_reference: regenerated {each}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
