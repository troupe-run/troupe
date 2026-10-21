"""Config's values and the changes between them (spec: config; config-model design D2; #135).

Config is a tree: an object is a group of values, and anything else (a string, number, boolean or
list) is one value, replaced and compared whole, never merged inside (#135). A path is the list of
keys from the top, such as ``["actors", "tester", "runner"]``.

A change is a list of entries, one per value it changes:

- ``{"path": [...], "before": "sha256:...", "after": value}``: ``before`` is the hash of the old
  value's canonical JSON, absent when there was none; ``after`` is the new value, absent when it's
  removed, and never an object.
- A group is removed as one entry addressed to the group: its ``before`` hashes the whole group.

Entries are sorted by path, so the same change is always written the same way, and an entry that
changes nothing is never written.
"""

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from troupe.core import strict_json
from troupe.core.errors import TroupeError

Tree = dict[str, Any]
Path = tuple[str, ...]
Entry = dict[str, Any]


def value_hash(value: object) -> str:
    """``sha256:`` and the SHA-256 of ``value``'s canonical JSON, the form event ids hash."""
    return "sha256:" + hashlib.sha256(strict_json.dumps(value).encode("utf-8")).hexdigest()


def dotted(path: Sequence[str]) -> str:
    """A path as people read it: ``actors.tester.runner``."""
    return ".".join(path)


def get(tree: Mapping[str, Any], path: Sequence[str]) -> object:
    """The value or group at ``path``, or None when there's nothing there."""
    node: object = tree
    for key in path:
        if not isinstance(node, Mapping) or key not in node:
            return None
        node = node[key]
    return node


def leaves(tree: Mapping[str, Any], prefix: Path = ()) -> dict[Path, object]:
    """Every value in ``tree``, by its path. An empty group holds no value, so it has none."""
    found: dict[Path, object] = {}
    for key, node in tree.items():
        path = (*prefix, key)
        if isinstance(node, Mapping):
            found.update(leaves(node, path))
        else:
            found[path] = node
    return found


def _entry(path: Path, old: object, new: object) -> Entry | None:
    entry: Entry = {"path": list(path)}
    if old is not None:
        entry["before"] = value_hash(old)
    if new is not None:
        entry["after"] = new
    if old is not None and new is not None and value_hash(old) == value_hash(new):
        return None
    if old is None and new is None:
        return None
    return entry


def set_value(tree: Mapping[str, Any], path: Sequence[str], value: object) -> list[Entry]:
    """The entries that set ``path`` to ``value``. An object is set as a whole group: each value
    under the path that it adds, changes or removes gets its own entry."""
    path = tuple(path)
    _refuse_null(path, value)
    if isinstance(value, Mapping):
        old = get(tree, path)
        before = leaves(old, path) if isinstance(old, Mapping) else {}
        entries = [_removal_of_value_ancestor(tree, path)]
        if old is not None and not isinstance(old, Mapping):
            entries.append(_entry(path, old, None))
        after = leaves(value, path)
        for leaf in sorted(before.keys() | after.keys()):
            entries.append(_entry(leaf, before.get(leaf), after.get(leaf)))
        return _sorted(entries)
    return _sorted([_removal_of_value_ancestor(tree, path), _entry(path, get(tree, path), value)])


def unset(tree: Mapping[str, Any], path: Sequence[str]) -> list[Entry]:
    """The entry that removes the value or group at ``path``, or none when there's nothing there."""
    return _sorted([_entry(tuple(path), get(tree, path), None)])


UNSET = object()
"""In ``change``'s operations, the value that removes a path."""


def change(
    tree: Mapping[str, Any], operations: Sequence[tuple[Sequence[str], object]]
) -> list[Entry]:
    """The entries of one command that sets each path to its value, or unsets it (``UNSET``), in
    order. A path changed twice keeps its first ``before`` and its last ``after``, and an entry
    that ends where it began is left out, so the command records its net change."""
    current: Tree = _copy(tree)
    net: dict[Path, Entry] = {}
    for path, value in operations:
        entries = unset(current, path) if value is UNSET else set_value(current, path, value)
        for entry in entries:
            key = tuple(entry["path"])
            first = net.get(key)
            merged: Entry = {"path": entry["path"]}
            before = first.get("before") if first is not None else entry.get("before")
            if before is not None:
                merged["before"] = before
            if "after" in entry:
                merged["after"] = entry["after"]
            net[key] = merged
        current = apply(current, entries)
    kept = [
        entry
        for entry in net.values()
        if not ("after" in entry and entry.get("before") == value_hash(entry["after"]))
        and ("before" in entry or "after" in entry)
    ]
    return _sorted(kept)


def apply(tree: Mapping[str, Any], entries: Sequence[Mapping[str, Any]]) -> Tree:
    """``tree`` after ``entries``, as a new tree. Empty groups are left out."""
    result: Tree = _copy(tree)
    for entry in sorted(entries, key=lambda e: tuple(e["path"])):
        path = tuple(entry["path"])
        if "after" in entry:
            _put(result, path, entry["after"])
        else:
            _remove(result, path)
    return _prune(result)


def _removal_of_value_ancestor(tree: Mapping[str, Any], path: Path) -> Entry | None:
    """When a value sits where ``path`` needs a group (``actors.tester`` is a string, and
    ``actors.tester.runner`` is set), the entry that removes it."""
    for depth in range(1, len(path)):
        node = get(tree, path[:depth])
        if node is not None and not isinstance(node, Mapping):
            return _entry(path[:depth], node, None)
    return None


def _sorted(entries: Sequence[Entry | None]) -> list[Entry]:
    return sorted((e for e in entries if e is not None), key=lambda e: tuple(e["path"]))


def _refuse_null(path: Path, value: object) -> None:
    for leaf, node in (
        {path: value} if not isinstance(value, Mapping) else leaves(value, path)
    ).items():
        if node is None or _holds_null(node):
            raise TroupeError(
                "config.invalid",
                problem=f"{dotted(leaf)} is null: config has no null values.",
                fix=f"To remove {dotted(leaf)}, unset it (troupe config unset {dotted(leaf)}).",
                details={"path": list(leaf), "rule": "config has no null values"},
            )


def _holds_null(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, list):
        return any(_holds_null(item) for item in value)
    if isinstance(value, Mapping):
        return any(_holds_null(item) for item in value.values())
    return False


def _copy(tree: Mapping[str, Any]) -> Tree:
    return {k: _copy(v) if isinstance(v, Mapping) else v for k, v in tree.items()}


def _put(tree: Tree, path: Path, value: object) -> None:
    node = tree
    for key in path[:-1]:
        child = node.get(key)
        if not isinstance(child, dict):
            child = {}
            node[key] = child
        node = child
    node[path[-1]] = value


def _remove(tree: Tree, path: Path) -> None:
    node: object = tree
    for key in path[:-1]:
        if not isinstance(node, dict) or key not in node:
            return
        node = node[key]
    if isinstance(node, dict):
        node.pop(path[-1], None)


def _prune(tree: Tree) -> Tree:
    pruned: Tree = {}
    for key, node in tree.items():
        if isinstance(node, dict):
            node = _prune(node)
            if not node:
                continue
        pruned[key] = node
    return pruned
