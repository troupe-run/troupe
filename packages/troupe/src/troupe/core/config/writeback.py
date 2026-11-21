"""Surgical write-back: writing config into a file a person formatted, changing only what changed
(spec: config-files, "Write-back changes only what it must"; hand-edit-sweep design D6).

Loading a file with ruamel.yaml's round-trip mode and dumping it again re-indents lists, collapses
spacing and moves comments, so write-back splices text instead: it composes the file (each node
knows where it starts and ends) and, walking it beside the values config holds:

- replaces a changed single-line scalar in place, so a comment after it stays;
- replaces a changed flow collection (``[a, b]``, ``{a: 1}``) in place, in flow style;
- recurses into a changed group written in block style, key by key;
- replaces any other changed value with its whole entry, rendered as troupe renders it, at the
  key's indentation;
- removes a removed key's lines;
- adds a new key after the last sibling that comes before it in the file's order (the schema's at
  the top of a file, sorted inside a group), at the siblings' indentation.

New lines use the file's own line ending. The result is read back before it's used, and must give
exactly the values config holds; otherwise the write is refused with
``config.write-back-failed``, so a wrong file is never written and formatting is never silently
lost.
"""

import io
from collections.abc import Callable, Collection, Mapping, Sequence
from functools import cache
from typing import TYPE_CHECKING, Any

from troupe.core.config.kinds import ACTORS
from troupe.core.config.projection import FIELD_ORDER, RUNTIME_FIELD_ORDER, _sorted, _yaml
from troupe.core.config.reading import SCHEMA_KEY, owner, read_values
from troupe.core.errors import TroupeError
from troupe.core.theatre import THEATRE_DIR

if TYPE_CHECKING:  # loaded where a file is written back: it's slow to load (cli-starts-fast)
    from ruamel.yaml import YAML
    from ruamel.yaml.nodes import MappingNode, Node

Splice = tuple[int, int, str]
"""Replace ``text[start:end]`` with the string."""


def write_back(path: str, data: bytes, values: Mapping[str, Any]) -> bytes:
    """``data``, the config file at ``path`` (relative to .troupe/) as a person left it, with
    ``values`` (the values the file owns, as config holds them) written into it surgically."""
    found = owner(path)
    if found is None:
        raise ValueError(f"{path} is no kind of config file")
    (kind, _), holds = found
    if holds == "character":
        return str(values["character"]).encode("utf-8")
    text = data.decode("utf-8")
    current = read_values(path, data).values
    if current == dict(values):
        return data
    top = FIELD_ORDER if kind == ACTORS else RUNTIME_FIELD_ORDER
    crlf = _crlf(text)
    splices: list[Splice] = []
    _mapping(text, _compose(text), current, dict(values), top, crlf, splices, top_level=True)
    result = _apply(text, splices).encode("utf-8")
    try:
        written = read_values(path, result).values
    except TroupeError:
        written = None
    if written != dict(values):
        raise write_back_failed(path)
    return result


def write_back_failed(path: str) -> TroupeError:
    shown = f"{THEATRE_DIR}/{path}"
    return TroupeError(
        "config.write-back-failed",
        problem=f"troupe couldn't write the change into {shown} without changing what else it "
        "says, so it wrote nothing and recorded nothing.",
        fix="Run troupe sync --force to write the file whole as troupe writes it, keeping a copy "
        "of what it holds now; or make the change by editing the file.",
        details={"file": shown},
    )


def _crlf(text: str) -> bool:
    first = text.find("\n")
    return first > 0 and text[first - 1] == "\r"


def _compose(text: str) -> "MappingNode":
    from ruamel.yaml.nodes import MappingNode

    node = _composer().compose(text)
    if not isinstance(node, MappingNode):
        raise TypeError("a config file's top level is a mapping")  # read_values checked it
    return node


@cache
def _composer() -> "YAML":
    from ruamel.yaml import YAML

    return YAML(typ="rt")


def _line_start(text: str, index: int) -> int:
    return text.rfind("\n", 0, index) + 1


def _line_end(text: str, index: int) -> int:
    """The index just past the end of the line ``index`` is on, its line break included."""
    found = text.find("\n", index)
    return len(text) if found < 0 else found + 1


def _end(text: str, node: "Node") -> int:
    """Where ``node``'s own text ends, leaving out the blank lines and comments a block node's
    end mark takes in after it."""
    from ruamel.yaml.nodes import MappingNode, SequenceNode

    if isinstance(node, MappingNode | SequenceNode) and not node.flow_style and node.value:
        last = node.value[-1]
        return _end(text, last[1] if isinstance(node, MappingNode) else last)
    end: int = node.end_mark.index
    start: int = node.start_mark.index
    while end > start and text[end - 1] in " \t\r\n":
        end -= 1
    return end


def _entry(key: str, value: object, column: int, crlf: bool) -> str:
    """``key: value`` as troupe renders it, every line indented by ``column`` spaces."""
    out = io.StringIO()
    _yaml().dump({key: _sorted(value)}, out)
    lines = out.getvalue().splitlines()
    newline = "\r\n" if crlf else "\n"
    return "".join(" " * column + line + newline for line in lines)


def _scalar(value: object) -> str | None:
    """``value`` rendered as one line, as troupe renders a scalar, or None when it needs more."""
    rendered = _entry("k", value, 0, crlf=False)
    if rendered.count("\n") == 1 and rendered.startswith("k: "):
        return rendered[3:-1]
    return None


def _flow_value(value: object) -> str | None:
    """``value`` rendered in flow style on one line, or None when it can't be."""
    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    def flowing(node: object) -> object:
        if isinstance(node, Mapping):
            mapped = CommentedMap((k, flowing(v)) for k, v in sorted(node.items()))
            mapped.fa.set_flow_style()
            return mapped
        if isinstance(node, list):
            seq = CommentedSeq(flowing(v) for v in node)
            seq.fa.set_flow_style()
            return seq
        return node

    out = io.StringIO()
    _yaml().dump({"k": flowing(value)}, out)
    rendered = out.getvalue()
    if rendered.count("\n") == 1 and rendered.startswith("k: "):
        return rendered[3:-1]
    return None


def _mapping(
    text: str,
    node: "MappingNode",
    current: Mapping[str, Any],
    wanted: Mapping[str, Any],
    order: Sequence[str] | None,
    crlf: bool,
    splices: list[Splice],
    *,
    top_level: bool = False,
) -> None:
    """Splices that make the mapping ``node``, holding ``current``, hold ``wanted``. ``order`` is
    the keys' order (the schema's), or None for sorted order."""
    entries = [(key.value, key, value) for key, value in node.value]
    present = [e for e in entries if not (top_level and e[0] == SCHEMA_KEY)]
    for name, key, value in present:
        if name not in wanted:
            start = _line_start(text, key.start_mark.index)
            splices.append((start, _line_end(text, _end(text, value)), ""))
        elif current.get(name) != wanted[name]:
            _changed(text, key, value, current.get(name), wanted[name], crlf, splices)
    names = [name for name, _, _ in entries]
    missing = [name for name in wanted if name not in names]
    if missing:
        column = (present or entries)[0][1].start_mark.column
        _inserts(
            text, entries, missing, wanted, _ranks(order, [*names, *missing]), column, crlf, splices
        )


def _changed(
    text: str,
    key: "Node",
    value: "Node",
    old: object,
    new: object,
    crlf: bool,
    splices: list[Splice],
) -> None:
    """The splice that changes one key's value from ``old`` to ``new``: in place where it can be
    (a single-line scalar, a flow collection), key by key inside a block group, else the whole
    entry rendered again."""
    from ruamel.yaml.nodes import MappingNode, ScalarNode, SequenceNode

    if isinstance(value, MappingNode) and not value.flow_style and isinstance(new, Mapping):
        _mapping(text, value, old if isinstance(old, Mapping) else {}, new, None, crlf, splices)
        return
    rendered: str | None = None
    if isinstance(value, ScalarNode) and value.style not in ("|", ">"):
        rendered = _scalar(new)
    elif isinstance(value, SequenceNode | MappingNode) and value.flow_style:
        rendered = _flow_value(new)
    if rendered is not None:
        splices.append((value.start_mark.index, _end(text, value), rendered))
        return
    start = _line_start(text, key.start_mark.index)
    end = _line_end(text, _end(text, value))
    splices.append((start, end, _entry(str(key.value), new, key.start_mark.column, crlf)))


def _inserts(
    text: str,
    entries: Sequence[tuple[str, Any, Any]],
    missing: Sequence[str],
    wanted: Mapping[str, Any],
    rank: "Callable[[str], int]",
    column: int,
    crlf: bool,
    splices: list[Splice],
) -> None:
    """Splices that add each ``missing`` key after the last entry that comes before it in order,
    or before the first entry when none does."""
    inserts: dict[int, list[str]] = {}
    for name in sorted(missing, key=rank):
        before = [e for e in entries if rank(e[0]) < rank(name)]
        if before:
            at = _line_end(text, _end(text, before[-1][2]))
        else:
            at = _line_start(text, entries[0][1].start_mark.index)
        inserts.setdefault(at, []).append(_entry(name, wanted[name], column, crlf))
    for at, blocks in inserts.items():
        lead = "" if at == 0 or text[at - 1] == "\n" else ("\r\n" if crlf else "\n")
        splices.append((at, at, lead + "".join(blocks)))


def _ranks(order: Sequence[str] | None, names: Sequence[str]) -> "Callable[[str], int]":
    """A sort key for keys in ``order``, or in sorted order when it's None. A key the order
    doesn't name goes last."""
    listed = list(order) if order is not None else sorted(names)

    def rank(name: str) -> int:
        return listed.index(name) if name in listed else len(listed)

    return rank


def _apply(text: str, splices: list[Splice]) -> str:
    """``text`` with ``splices`` applied. Splices never overlap: each is one key's own text."""
    result = text
    # Applied from the end of the text back. Two inserts at one place, an inner group's last new
    # key and a new key after the group, keep the order they were made in: the later is applied
    # first, so the earlier ends up in front of it.
    ordered = sorted(enumerate(splices), key=lambda s: (s[1][0], s[1][1], s[0]), reverse=True)
    for _, (start, end, replacement) in ordered:
        result = result[:start] + replacement + result[end:]
    return result


def targets(
    config: Mapping[str, Any], seen: Mapping[str, bytes | None], read: Collection[str]
) -> dict[str, bytes]:
    """Every config file ``config`` makes, by its path: the files the sweep ``read`` (a person's)
    written back surgically from the bytes it saw, and every other one rendered whole, as troupe
    renders it (design D6)."""
    from troupe.core.config.projection import render
    from troupe.core.config.reading import owned

    files = render(config)
    for path in read:
        data = seen.get(path)
        located = owner(path)
        if data is None or path not in files or located is None:
            continue
        (kind, name), _ = located
        group = config.get(kind, {}).get(name, {})
        files[path] = write_back(path, data, owned(path, group))
    return files
