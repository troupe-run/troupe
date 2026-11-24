"""Split each test file that holds both kinds into its two halves, in place (test-split design D3).

Run from the repository root, on a tree where the files are still in each suite's `tests/`:

    uv run python openspec/changes/test-split/split_tests.py

It reads `test-kinds.json` beside it. For each file with a `split`, the named top-level tests (functions or
classes) move to a new file `<stem>_<kind>.py` beside it; the rest stay. Module-level definitions go with the
tests that use them, transitively: used by one half only, they go to that half; used by both, they go to a new
helper module `<topic>_shared.py` (the stem without `test_`), and both halves import them from it. Each output
keeps the module's docstring, every import (ruff then drops the unused ones) and `pytestmark`. The comments
since the previous statement travel with the next one, as does a string just below an assignment (its docstring).

It's deterministic, so after a rebase it's re-run on the new tree rather than conflicts resolved by hand. A test
added since the survey stays in the file it's in; the kinds check then says if it belongs in the other half.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import textwrap
from dataclasses import dataclass, field
from collections.abc import Callable
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLAN = HERE / "test-kinds.json"
DOCSTRINGS = HERE / "test-docstrings.json"


@dataclass
class Piece:
    """One top-level statement with the comments above it and the docstring below it."""

    text: str
    node: ast.stmt
    bound: set[str] = field(default_factory=set)
    used: set[str] = field(default_factory=set)
    kind: str = "helper"  # docstring, import, pytestmark, test, helper


def _bound(node: ast.stmt) -> set[str]:
    names: set[str] = set()
    for inner in [node, *(ast.walk(node) if isinstance(node, ast.If | ast.Try) else [])]:
        if isinstance(inner, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(inner.name)
        elif isinstance(inner, ast.Assign):
            for target in inner.targets:
                names.update(n.id for n in ast.walk(target) if isinstance(n, ast.Name))
        elif isinstance(inner, ast.AnnAssign | ast.AugAssign) and isinstance(inner.target, ast.Name):
            names.add(inner.target.id)
        elif isinstance(inner, ast.Import | ast.ImportFrom) and inner is not node:
            names.update((a.asname or a.name).split(".")[0] for a in inner.names)
    return names


def _used(node: ast.stmt) -> set[str]:
    names: set[str] = set()
    for inner in ast.walk(node):
        if isinstance(inner, ast.Name):
            names.add(inner.id)
        elif isinstance(inner, ast.arg):
            names.add(inner.arg)  # a fixture, by its parameter name
        elif isinstance(inner, ast.Call) and _names_fixtures_by_string(inner):
            # usefixtures("name"), and an indirect parametrize's argument names
            for argument in inner.args[:1] if _call_name(inner) == "parametrize" else inner.args:
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    names.update(argument.value.replace(",", " ").split())
    return names


def _requested(node: ast.stmt) -> set[str]:
    """The fixtures a statement asks for: its functions' parameters and usefixtures' names."""
    names = {a.arg for a in ast.walk(node) if isinstance(a, ast.arg)}
    for call in (c for c in ast.walk(node) if isinstance(c, ast.Call)):
        if _names_fixtures_by_string(call):
            for argument in call.args:
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    names.update(argument.value.replace(",", " ").split())
    return names


def _call_name(call: ast.Call) -> str:
    func = call.func
    return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")


def _names_fixtures_by_string(call: ast.Call) -> bool:
    """A call whose string arguments name fixtures: usefixtures, or an indirect parametrize. Any
    other string is text, not a use (a docstring's word "record" isn't the fixture)."""
    name = _call_name(call)
    indirect = any(k.arg == "indirect" for k in call.keywords)
    return name == "usefixtures" or (name == "parametrize" and indirect)


def _autouse(node: ast.stmt) -> bool:
    if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        return False
    return any(
        isinstance(k, ast.keyword) and k.arg == "autouse"
        for d in node.decorator_list
        if isinstance(d, ast.Call)
        for k in d.keywords
    )


def _fixture(node: ast.stmt) -> bool:
    return isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and any(
        "fixture" in ast.unparse(d) for d in node.decorator_list
    )


def pieces(source: str) -> list[Piece]:
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)
    body = tree.body
    out: list[Piece] = []
    start = 0  # the first line (0-based) not yet given to a piece
    i = 0
    while i < len(body):
        node = body[i]
        # Every comment since the previous statement travels with this one, blank lines between
        # included: a section's comment explains the tests below it (#510's review).
        top = start
        end = node.end_lineno or node.lineno
        group = [node]
        # A string statement right after an assignment is its docstring.
        while (
            i + 1 < len(body)
            and isinstance(node, ast.Assign | ast.AnnAssign)
            and isinstance(body[i + 1], ast.Expr)
            and isinstance(body[i + 1].value, ast.Constant)  # type: ignore[attr-defined]
            and isinstance(body[i + 1].value.value, str)  # type: ignore[attr-defined]
        ):
            i += 1
            group.append(body[i])
            end = body[i].end_lineno or body[i].lineno
        piece = Piece("".join(lines[top:end]), node)
        for member in group:
            piece.used |= _used(member)
        piece.bound = _bound(node)
        if i == 0 and isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            piece.kind = "docstring"
        elif isinstance(node, ast.Import | ast.ImportFrom):
            piece.kind = "import"
            piece.bound = {(a.asname or a.name).split(".")[0] for a in node.names}
        elif piece.bound == {"pytestmark"}:
            piece.kind = "pytestmark"
        elif any(n.startswith(("test", "Test")) for n in piece.bound):
            piece.kind = "test"
        out.append(piece)
        start = end
        i += 1
    return out


def _reach(start: list[Piece], by_name: dict[str, Piece]) -> list[Piece]:
    """The helper pieces the start pieces use, through the helpers that use other helpers."""
    seen: dict[int, Piece] = {}
    stack = [by_name[n] for p in start for n in p.used if n in by_name]
    while stack:
        piece = stack.pop()
        if id(piece) in seen:
            continue
        seen[id(piece)] = piece
        stack.extend(by_name[n] for n in piece.used if n in by_name and id(by_name[n]) not in seen)
    return list(seen.values())


def _named(piece: Piece) -> str:
    """A fixture's text as <name>_fixture, registered under its own name; other pieces as they are."""
    if not _fixture(piece.node):
        return piece.text
    text = piece.text
    node = ast.parse(text).body[0]  # positions within the piece's own text
    assert isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    name = node.name
    for decorator in node.decorator_list:
        before = ast.get_source_segment(text, decorator) or ast.unparse(decorator)
        if "fixture" not in before:
            continue
        if isinstance(decorator, ast.Call):
            after = before.replace("fixture(", f'fixture(name="{name}", ', 1).replace(", )", ")")
        else:
            after = f'{before}(name="{name}")'
        text = text.replace(f"@{before}", f"@{after}", 1)
    return re.sub(rf"\bdef {name}\(", f"def {name}_fixture(", text, count=1)


class Made(str):
    """Text the script writes itself (a docstring, an import line), not a statement from the
    source: it's set apart by a blank line. A statement keeps the blank lines it had above it."""


def _module(parts: list[str]) -> str:
    """Parts in order. A statement from the source keeps its own gap above it, so a group of
    constants stays together; made text, and the statement after it, get one blank line."""
    out = ""
    after_made = False
    for part in (p for p in parts if p.strip()):
        made = isinstance(part, Made)
        if not out:
            out = part.lstrip("\n")
        elif made or after_made or part.startswith("\n"):
            out = out.rstrip("\n") + "\n\n" + part.lstrip("\n")
        else:
            out = out.rstrip("\n") + "\n" + part
        after_made = made
    return out.rstrip("\n") + "\n"


@dataclass
class Partition:
    """Where each piece of a split module goes, by id: the kept half, the moved half, or shared."""

    all_pieces: list[Piece]
    by_name: dict[str, Piece]
    kept: list[Piece]
    moved: list[Piece]
    autouse: list[Piece]
    keep_ids: set[int]
    move_ids: set[int]
    shared_ids: set[int]

    @property
    def shared_names(self) -> set[str]:
        return {n for p in self.all_pieces if id(p) in self.shared_ids for n in p.bound}


def partition(all_pieces: list[Piece], moving: set[str]) -> Partition:
    by_name = {n: p for p in all_pieces if p.kind == "helper" for n in p.bound}
    tests = [p for p in all_pieces if p.kind == "test"]
    loose = [p for p in all_pieces if p.kind == "helper" and not p.bound]
    moved = [p for p in tests if p.bound & moving]
    kept = [p for p in tests if not p.bound & moving]
    autouse = [p for p in all_pieces if p.kind == "helper" and _autouse(p.node)]
    autouse_ids = {id(p) for p in autouse}
    # A statement that binds nothing (an attribute set on a helper) stays, with what it uses.
    keep_reach = {id(p) for p in _reach([*kept, *loose, *autouse], by_name)} | autouse_ids
    move_reach = {id(p) for p in _reach([*moved, *autouse], by_name)} | autouse_ids
    both = [p for p in all_pieces if id(p) in keep_reach & move_reach]
    shared_ids = {id(p) for p in both} | {id(p) for p in _reach(both, by_name)}
    move_ids = move_reach - shared_ids
    # What the kept half reaches, and whatever neither reaches: it stays where it was.
    keep_ids = {id(p) for p in all_pieces if p.kind == "helper"} - shared_ids - move_ids
    return Partition(all_pieces, by_name, kept, moved, autouse, keep_ids, move_ids, shared_ids)


def _from_shared(part: Partition, topic: str, ids: set[int], test_pieces: list[Piece]) -> list[str]:
    """The imports a half needs from the shared module: only what its own code names, so a name the shared
    helpers reach for themselves (one bound on one OS only, say) isn't imported."""
    own = [p for p in part.all_pieces if id(p) in ids] + test_pieces
    used = set().union(set(), *(p.used for p in own)) | {n for p in part.autouse for n in p.bound}
    names = used & part.shared_names
    # A fixture is used by asking for it (a parameter, or usefixtures), never by its bare name: a
    # local variable called `record` isn't the `record` fixture.
    requested = {n for p in own for n in _requested(p.node)} | {n for p in part.autouse for n in p.bound}
    names -= {n for n in names if _fixture(part.by_name[n].node) and n not in requested}
    fixtures = sorted(n for n in names if _fixture(part.by_name[n].node))
    plain = sorted(names - set(fixtures))
    lines = [Made(f"from {topic} import {', '.join(plain)}\n")] if plain else []
    # pytest finds a fixture by its name in the module, which ruff can't see as a use; and a test's
    # parameter of the fixture's own name would redefine the import (F811), so the shared fixture is
    # defined as <name>_fixture with name="<name>".
    renamed = ", ".join(f"{n}_fixture" for n in fixtures)
    lines += [Made(f"from {topic} import {renamed}  # noqa: F401\n")] if fixtures else []
    return lines


POINTERS = {
    "unit": "Its tests that start a process, open a socket or use a git theatre are in {other}.",
    "integration": "Its tests that stay in their own process are in {other}.",
}
"""What each half's docstring says about the other (design D3)."""


def _docstring(kept: str, added: str = "") -> str:
    """A module docstring: `kept` as it is (it may hold commands or lists), then `added` wrapped to
    the line length."""
    parts = [kept.strip()] if kept.strip() else []
    if added:
        width = 97 if not parts else 100  # the opening quotes share the first line
        text = " ".join(added.split())
        parts.append(textwrap.fill(text, width=width, break_on_hyphens=False))
    body = "\n\n".join(parts)
    closing = '"""' if len(body.splitlines()[-1]) + 3 <= 100 else '\n"""'
    return Made(f'"""{body}{closing}\n')


def half_docstring(
    original: str | None, own_path: str, kind: str, other: str, overrides: dict[str, str]
) -> str | None:
    """A split half's docstring: the plan's, when it gives one (the original's first paragraph
    is wrong for this half); otherwise the original, the split-off half keeping only its first
    paragraph, and each saying where the other half is."""
    pointer = POINTERS[kind].format(other=other)
    if own_path in overrides:
        paragraphs = overrides[own_path].split("\n\n")
        given = "\n\n".join(
            textwrap.fill(" ".join(p.split()), 97 if i == 0 else 100, break_on_hyphens=False)
            for i, p in enumerate(paragraphs)
        )
        return _docstring(given, pointer)
    if original is None:
        return None
    keep = original if not own_path.endswith(f"_{kind}.py") else original.split("\n\n")[0]
    return _docstring(keep, pointer)


def _half(
    part: Partition, topic: str, ids: set[int], test_pieces: list[Piece], docstring: str | None
) -> str:
    """One half's text: its docstring, the module's imports and pytestmark, then its own pieces in
    order."""
    head = [docstring] if docstring else []
    head += [p.text for p in part.all_pieces if p.kind == "import"]
    mark = [p.text for p in part.all_pieces if p.kind == "pytestmark"]
    chosen = {id(p) for p in test_pieces} | ids
    body = [p.text for p in part.all_pieces if id(p) in chosen]
    return _module([*head, *_from_shared(part, topic, ids, test_pieces), *mark, *body])


def split(
    path: Path, kind: str, minor: str, moving: set[str], overrides: dict[str, str]
) -> list[Path]:
    source = path.read_text(encoding="utf-8")
    all_pieces = pieces(source)
    original = ast.get_docstring(ast.parse(source), clean=True)
    part = partition(all_pieces, moving)
    found = set().union(set(), *(p.bound for p in part.kept + part.moved))
    if moving - found:
        print(f"{path}: not found (since the survey?): {sorted(moving - found)}", file=sys.stderr)
    if not part.moved:
        return []
    topic = path.stem.removeprefix("test_") + "_shared"
    new = path.with_name(f"{path.stem}_{minor}.py")
    shared = path.with_name(f"{topic}.py")
    for target in (new, shared):
        if target.exists():
            raise SystemExit(f"{target} exists already; the split would overwrite it")
    kept_doc = half_docstring(original, str(path), kind, f"{minor}/{new.name}", overrides)
    new_doc = half_docstring(original, str(new), minor, f"{kind}/{path.name}", overrides)
    path.write_text(_half(part, topic, part.keep_ids, part.kept, kept_doc), encoding="utf-8")
    new.write_text(_half(part, topic, part.move_ids, part.moved, new_doc), encoding="utf-8")
    if not part.shared_ids:
        return [path, new]
    imports = [p.text for p in all_pieces if p.kind == "import"]
    body = [_named(p) for p in all_pieces if id(p) in part.shared_ids]
    doc = Made(f'"""What {path.name} and {new.name} share."""\n')
    shared.write_text(_module([doc, *imports, *body]), encoding="utf-8")
    return [path, new, shared]


def _import_lines(module: str, names: list[str], fixtures: set[str]) -> list[str]:
    """`from module import ...` lines: fixtures as <name>_fixture, which ruff can't see used (design D3)."""
    plain = sorted(n for n in names if n not in fixtures)
    lines = [Made(f"from {module} import {', '.join(plain)}\n")] if plain else []
    if fixtures & set(names):
        renamed = ", ".join(f"{n}_fixture" for n in sorted(fixtures & set(names)))
        lines.append(Made(f"from {module} import {renamed}  # noqa: F401\n"))
    return lines


def extract(source: Path, helper: Path, names: set[str]) -> list[Path]:
    """Move the top-level definitions of `names`, and the helpers they reach, from a test module into a
    helper module (made if it doesn't exist), so no test module imports another: once the tests move, one
    is found only from its own directory, and mypy doesn't find it at all (design D3a)."""
    all_pieces = pieces(source.read_text(encoding="utf-8"))
    by_name = {n: p for p in all_pieces if p.kind == "helper" for n in p.bound}
    seeds = [p for p in all_pieces if p.kind == "helper" and p.bound & names]
    if not seeds:
        print(f"{source}: none of {sorted(names)} found to extract", file=sys.stderr)
        return []
    taking_ids = {id(p) for p in seeds} | {id(p) for p in _reach(seeds, by_name)}
    taking = [p for p in all_pieces if id(p) in taking_ids]
    rest = [p for p in all_pieces if id(p) not in taking_ids]
    _keep_in_source(source, helper.stem, rest, taking)
    _add_to_helper(helper, source.name, [p for p in all_pieces if p.kind == "import"], taking)
    return [source, helper]


def _keep_in_source(source: Path, helper: str, rest: list[Piece], taking: list[Piece]) -> None:
    """Rewrite the source without the taken pieces, importing back what it still uses."""
    taken = {n for p in taking for n in p.bound}
    fixtures = {n for p in taking if _fixture(p.node) for n in p.bound}
    still = sorted(set().union(set(), *(p.used for p in rest if p.kind != "import")) & taken)
    head = [p.text for p in rest if p.kind in ("docstring", "import")]
    body = [p.text for p in rest if p.kind not in ("docstring", "import")]
    text = _module([*head, *_import_lines(helper, still, fixtures), *body])
    source.write_text(text, encoding="utf-8")


def _add_to_helper(helper: Path, source: str, imports: list[Piece], taking: list[Piece]) -> None:
    """Append the taken pieces to the helper, with the source's imports (never one of the helper itself)."""
    own = [
        p.text
        for p in imports
        if not (isinstance(p.node, ast.ImportFrom) and p.node.module == helper.stem)
    ]
    if helper.exists():
        old = pieces(helper.read_text(encoding="utf-8"))
        last = max((i for i, p in enumerate(old) if p.kind in ("docstring", "import")), default=-1)
        parts = [p.text for p in old[: last + 1]] + own + [p.text for p in old[last + 1 :]]
    else:
        parts = [Made(f'"""Helpers that {source} shares with other test modules."""\n'), *own]
    helper.write_text(_module([*parts, *(_named(p) for p in taking)]), encoding="utf-8")


def _definitions(path: Path) -> dict[str, bool]:
    """The names a module defines itself (not those it imports), each with whether it's a fixture renamed
    to <name>_fixture, under its fixture name."""
    found: dict[str, bool] = {}
    for piece in pieces(path.read_text(encoding="utf-8")):
        if piece.kind == "import":
            continue
        for name in piece.bound:
            renamed = _fixture(piece.node) and name.endswith("_fixture")
            found[name.removesuffix("_fixture") if renamed else name] = renamed
    return found


def _test_imports(path: Path) -> list[ast.ImportFrom]:
    """Every `from test_... import` in a module, nested ones included."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and n.level == 0 and (n.module or "").startswith("test_")
    ]


def redirect(roots: list[Path], moved_to: dict[str, list[str]]) -> list[Path]:
    """Point each `from <module> import name` at the module that now defines the name, for the modules the
    splits and extractions took names out of, looking only where each could have put them."""
    modules = {p.stem: p for root in roots for p in root.glob("*.py")}
    defined: dict[str, dict[str, bool]] = {}

    def defines(stem: str) -> dict[str, bool]:
        if stem not in defined:
            defined[stem] = _definitions(modules[stem]) if stem in modules else {}
        return defined[stem]

    changed = []
    for path in sorted(p for root in roots for p in root.glob("*.py")):
        edits = [_rewritten(node, moved_to, defines) for node in _imports_from(path, moved_to)]
        edits = [e for e in edits if e is not None]
        if edits:
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
            for start, end, statement in sorted(edits, reverse=True):
                lines[start:end] = [statement]
            path.write_text("".join(lines), encoding="utf-8")
            changed.append(path)
    return changed


def _imports_from(path: Path, moved_to: dict[str, list[str]]) -> list[ast.ImportFrom]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.level == 0 and n.module in moved_to
    ]


def _rewritten(
    node: ast.ImportFrom,
    moved_to: dict[str, list[str]],
    defines: Callable[[str], dict[str, bool]],
) -> tuple[int, int, str] | None:
    """The lines to put in place of one import, or None when every name is still where it's imported from."""
    module = str(node.module)
    homes: dict[str, list[str]] = {}
    fixtures: set[str] = set()
    for alias in node.names:
        home = module
        if alias.name not in defines(module):
            # Only where the split or extraction could have put it, never a namesake elsewhere.
            found = [s for s in moved_to[module] if alias.name in defines(s)]
            home = (found or [module])[0]
            if defines(home).get(alias.name):
                fixtures.add(alias.name)
        homes.setdefault(home, []).append(alias.name)
    if list(homes) == [module]:
        return None
    indent = " " * node.col_offset
    lines = [line for home, names in homes.items() for line in _import_lines(home, names, fixtures)]
    statement = "".join(indent + line for line in lines)
    return node.lineno - 1, node.end_lineno or node.lineno, statement


def untangle(directories: list[Path]) -> tuple[list[Path], dict[str, list[str]]]:
    """Extract every name one test module imports from another into the source's `<topic>_shared.py`, until
    no test module imports another (a name the source only re-exports is redirected, not extracted)."""
    written: list[Path] = []
    moved_to: dict[str, list[str]] = {}
    modules = {p.stem: p for d in directories for p in d.glob("*.py")}
    wanted: dict[str, set[str]] = {}
    for path in sorted(p for d in directories for p in d.glob("test_*.py")):
        for node in _test_imports(path):
            if node.module in modules:
                wanted.setdefault(str(node.module), set()).update(a.name for a in node.names)
    plain = _plain_imports(directories, modules)
    for (path, module), names in plain.items():
        wanted.setdefault(module, set()).update(names)
    for module, names in sorted(wanted.items()):
        source = modules[module]
        own = set(_definitions(source)) & names
        helper = source.with_name(module.removeprefix("test_") + "_shared.py")
        if own:
            written += extract(source, helper, own)
        moved_to.setdefault(module, []).append(helper.stem)
    for (path, module), _ in plain.items():
        # `import test_x` then `test_x.NAME`: import the helper module under its own name instead.
        topic = module.removeprefix("test_") + "_shared"
        text = path.read_text(encoding="utf-8")
        text = re.sub(rf"\bimport {module}\b", f"import {topic}", text)
        path.write_text(re.sub(rf"\b{module}\.", f"{topic}.", text), encoding="utf-8")
        written.append(path)
    return written, moved_to


def _plain_imports(directories: list[Path], modules: dict[str, Path]) -> dict[tuple[Path, str], set[str]]:
    """Each `import test_x` in a test module, with the attributes it reads from it (`test_x.NAME`)."""
    found: dict[tuple[Path, str], set[str]] = {}
    for path in sorted(p for d in directories for p in d.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {
            a.name
            for n in ast.walk(tree)
            if isinstance(n, ast.Import)
            for a in n.names
            if a.name.startswith("test_") and a.name in modules and a.asname is None
        }
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in imported:
                found.setdefault((path, n.value.id), set()).add(n.attr)
    return found


def _mypy_finds(directories: list[str]) -> None:
    """Add each directory holding a new shared module to mypy's path, as its tests import it by name."""
    pyproject = Path("pyproject.toml")
    text = pyproject.read_text(encoding="utf-8")
    start = text.index("mypy_path = [")
    end = text.index("]", start)
    listed = re.findall(r'"([^"]+)"', text[start:end])
    missing = [d for d in directories if d not in listed]
    if missing:
        added = "".join(f'    "{d}",\n' for d in missing)
        text = text[:end] + added + text[end:]
        pyproject.write_text(text, encoding="utf-8")


def main() -> int:
    document = json.loads(PLAN.read_text(encoding="utf-8"))
    plan = document["files"]
    # The unit halves whose first paragraph described the integration tests (#510's review).
    docstrings: dict[str, str] = json.loads(DOCSTRINGS.read_text(encoding="utf-8"))
    written: list[Path] = []
    moved_to: dict[str, list[str]] = {}
    # Extractions first, so a split sees the extracted helpers as imports.
    for name, entry in document.get("extract", {}).items():
        written += extract(Path(name), Path(entry["to"]), set(entry["names"]))
        moved_to.setdefault(Path(name).stem, []).append(Path(entry["to"]).stem)
    for name, entry in plan.items():
        for minor, moving in entry.get("split", {}).items():
            path = Path(name)
            if not path.exists():
                print(f"{path}: missing, skipped", file=sys.stderr)
                continue
            written += split(path, entry["kind"], minor, set(moving), docstrings)
            topic = path.stem.removeprefix("test_") + "_shared"
            moved_to.setdefault(path.stem, []).extend([f"{path.stem}_{minor}", topic])
    directories = sorted({Path(n).parent for n in plan})
    untangled, untangle_moved = untangle(directories)
    written += untangled
    for module, homes in untangle_moved.items():
        moved_to.setdefault(module, []).extend(homes)
    _mypy_finds(sorted({str(p.parent) for p in written if p.stem.endswith("_shared")}))
    roots = sorted({p.parent for p in written} | {Path(n).parent for n in plan})
    written += redirect(roots, moved_to)
    files = sorted({str(p) for p in written})
    if files:
        # The halves carry every import; drop what each doesn't use, then sort and format.
        subprocess.run(["ruff", "check", "--fix", "--select", "F401,I001", "--quiet", *files], check=False)
        subprocess.run(["ruff", "format", "--quiet", *files], check=True)
    print(f"wrote {len(files)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
