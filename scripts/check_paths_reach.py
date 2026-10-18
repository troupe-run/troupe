"""Which test suites reach which scope in scripts/check-paths.toml, worked out from the source.

Spec: quality-check. A package scope runs the test suites its `tests` key names, and they must be
exactly the suites that reach the package (package-check-scopes design D3). guard_pytest can't
prove that: it sees a module's first import, not later ones, nor entry-point loads of modules
already imported, nor subprocesses. So the reach is computed here, statically, with `ast`:

1. A suite is a `testpaths` directory. Its code is every module in it, plus each module those
   import, followed transitively: helpers on pytest's `pythonpath`, and workspace packages'
   sources. Every import counts, including those inside functions and `TYPE_CHECKING` blocks, and
   `importlib.import_module` with a literal name. One with a computed name reaches every package.
2. A suite reaches each package that owns a module in its closure, and each package's workspace
   `dependencies`, transitively.
3. A module that calls `entry_points(group=...)` reaches every package registered in that group.
   The group is read from a string, a module-level string constant (here or imported), or, failing
   those, the group names written in the same module. A call with none of those is an error, so a
   new loader can't go unseen.
4. Test-side code (anything outside a package's `src/`) also reaches a package it names: a string
   equal to the package's module or console-script name (a subprocess's `-m` module or command),
   or a path into a workspace root. A path that names a package right after the root reaches it,
   whether it's built in code (`ROOT / "plugins" / "runner-scripted"`) or written as one string
   (`"packages/troupe-vcs-git/tests"`, even as a configuration key: how a string is used can't be
   told from the source, so it counts). A path that globs after the root reaches every package
   there, and so does a path expression that stops at the root (`ROOT / "plugins"`, globbed in
   another call). A bare word doesn't count: not `"packages"` alone (a key, in this repository),
   nor a bare directory or distribution name (`"troupe-vcs-git"`, which names a package in
   metadata or configuration but isn't a path to its files).
5. A module under scripts/, other than the four files that run the full check, reaches the
   `scripts` scope.

Rules 1, 3 and 4 err wide: an unneeded suite costs time, a missing one costs a missed failure.
What this can't see: a path or command built at run time from non-literal parts (a variable
holding "plugins", a directory listed from data, such as the workspace members python_versions.py
and release_config.py read). The members they read are each package's pyproject.toml, which is in
no scope, so those reads need nothing here. guard_pytest's read check still catches a scope's file
opened untagged, and a case found later is fixed here, with a test.

Run it to print each suite's reach and the `tests` each scope should declare:

    uv run scripts/check_paths_reach.py

Standard library only, like check.py.
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECK_PATHS = "scripts/check-paths.toml"
CORE = "troupe"
"""The core distribution. It has no scope: a change to it runs the full check."""
SCRIPTS = "scripts"
"""The directory, and the scope, of the repository's own scripts."""
FULL_CHECK_SCRIPTS = frozenset({"check", "guard", "guard_pytest"})
"""Modules under scripts/ that every check runs, so a change to them runs the full check and
importing them reaches no scope. (check-paths.toml is the fourth such file; it isn't a module.)"""
_REQUIREMENT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_GLOB = re.compile(r"[*?\[]")


class ReachError(ValueError):
    """The source holds something the analysis can't classify, so no answer would be safe."""


@dataclass(frozen=True)
class Package:
    """A workspace member, as its pyproject.toml and its src/ directory describe it."""

    name: str
    path: str
    """Relative to the repository root, POSIX: packages/troupe-store-text."""
    modules: frozenset[str]
    """Its top-level import names: troupe_store_text."""
    dependencies: frozenset[str]
    """The workspace members it depends on, by distribution name."""
    groups: frozenset[str]
    """The entry-point groups it registers in: troupe.store."""
    commands: frozenset[str] = frozenset()
    """Its console scripts, from [project.scripts]."""

    @property
    def scope(self) -> str | None:
        """Its scope's name: the distribution name without `troupe-`, with `_` for `-`."""
        if self.name == CORE:
            return None
        return self.name.removeprefix("troupe-").replace("-", "_")

    @property
    def directory(self) -> str:
        return self.path.rsplit("/", 1)[-1]


@dataclass(frozen=True)
class Workspace:
    root: Path
    packages: tuple[Package, ...]
    suites: tuple[str, ...]
    """pytest's testpaths, in order."""
    pythonpath: tuple[str, ...]
    roots: frozenset[str]
    """The directories workspace members live in: packages, plugins."""

    def scopes(self) -> tuple[str, ...]:
        """Every scope this analysis has an answer for, sorted."""
        named = {package.scope for package in self.packages if package.scope is not None}
        return tuple(sorted(named | {SCRIPTS}))


def _toml(path: Path) -> dict[str, object]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _table(data: Mapping[str, object], *keys: str) -> dict[str, object]:
    for key in keys:
        value = data.get(key, {})
        data = value if isinstance(value, dict) else {}
    return dict(data)


def _strings(value: object) -> tuple[str, ...]:
    return tuple(item for item in value if isinstance(item, str)) if isinstance(value, list) else ()


def load_workspace(root: Path = ROOT) -> Workspace:
    """The workspace's members, test suites and pythonpath, from its pyproject.toml files."""
    pyproject = _toml(root / "pyproject.toml")
    members = _strings(_table(pyproject, "tool", "uv", "workspace").get("members"))
    pytest = _table(pyproject, "tool", "pytest", "ini_options")
    found: list[tuple[Path, dict[str, object]]] = []
    for pattern in members:
        for member in sorted(root.glob(pattern)):
            if (member / "pyproject.toml").is_file():
                found.append((member, _table(_toml(member / "pyproject.toml"), "project")))
    names = {str(project.get("name")) for _, project in found}
    packages = []
    for member, project in found:
        requirements = (_REQUIREMENT_NAME.match(r) for r in _strings(project.get("dependencies")))
        source = member / "src"
        modules = (
            {
                child.stem
                for child in source.iterdir()
                if child.suffix == ".py" or (child / "__init__.py").is_file()
            }
            if source.is_dir()
            else set()
        )
        packages.append(
            Package(
                name=str(project.get("name")),
                path=member.relative_to(root).as_posix(),
                modules=frozenset(modules),
                dependencies=frozenset(m[0] for m in requirements if m and m[0] in names),
                groups=frozenset(_table(project, "entry-points")),
                commands=frozenset(_table(project, "scripts")),
            )
        )
    return Workspace(
        root=root,
        packages=tuple(packages),
        suites=_strings(pytest.get("testpaths")),
        pythonpath=_strings(pytest.get("pythonpath")),
        roots=frozenset(pattern.split("/", 1)[0] for pattern in members),
    )


@dataclass
class _Module:
    """What one file says about its reach, before any of it is resolved."""

    imports: list[tuple[int, str, tuple[str, ...]]] = field(default_factory=list)
    """(level, module, names): `import a.b` is (0, "a.b", ()), and `from .c import d` is
    (1, "c", ("d",))."""
    strings: set[str] = field(default_factory=set)
    paths: list[list[str | None]] = field(default_factory=list)
    """Path expressions as segments, None for a part that isn't a literal."""
    constants: dict[str, str] = field(default_factory=dict)
    imported: dict[str, tuple[int, str, str]] = field(default_factory=dict)
    """Names bound by `from m import x [as y]`: y -> (level, m, x)."""
    groups: list[tuple[int, ast.expr | None]] = field(default_factory=list)
    """Each entry_points() call: its line, and its group argument."""
    dynamic: list[int] = field(default_factory=list)
    """Lines that import a module whose name is computed."""


def _segments(text: str) -> list[str | None]:
    return list(text.split("/"))


def _div_operands(node: ast.expr) -> list[ast.expr]:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _div_operands(node.left) + _div_operands(node.right)
    return [node]


def _path_segments(parts: Iterable[ast.expr]) -> list[str | None]:
    segments: list[str | None] = []
    for part in parts:
        if isinstance(part, ast.Constant) and isinstance(part.value, str):
            segments += _segments(part.value)
        else:
            segments.append(None)
    return segments


def _called(node: ast.Call) -> str:
    function = node.func
    if isinstance(function, ast.Attribute):
        return function.attr
    return function.id if isinstance(function, ast.Name) else ""


def _parse(path: Path) -> _Module:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    module = _Module()
    for statement in tree.body:
        if isinstance(statement, ast.Assign | ast.AnnAssign):
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            value = statement.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                for target in targets:
                    if isinstance(target, ast.Name):
                        module.constants[target.id] = value.value
    chained = {
        id(child)
        for node in ast.walk(tree)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
        for child in (node.left, node.right)
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            module.imports += [(0, alias.name, ()) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = tuple(alias.name for alias in node.names)
            module.imports.append((node.level, node.module or "", names))
            for alias in node.names:
                module.imported[alias.asname or alias.name] = (
                    node.level,
                    node.module or "",
                    alias.name,
                )
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            module.strings.add(node.value)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            if id(node) not in chained:
                module.paths.append(_path_segments(_div_operands(node)))
        elif isinstance(node, ast.Call):
            called = _called(node)
            if called in ("Path", "PurePath", "PurePosixPath", "join"):
                module.paths.append(_path_segments(node.args))
            elif called == "entry_points":
                group = next((k.value for k in node.keywords if k.arg == "group"), None)
                module.groups.append((node.lineno, group))
            elif called in ("import_module", "__import__"):
                first = node.args[0] if node.args else None
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    module.imports.append((0, first.value, ()))
                else:
                    module.dynamic.append(node.lineno)
    return module


class _Analysis:
    """One workspace's module graph, parsed once and shared by every suite."""

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self.root = workspace.root
        self.dotted: dict[str, str] = {}
        """Every module in a package's src/, by dotted name, to its file."""
        self.names: dict[str, str] = {}
        """The reverse: a src/ file to its dotted name."""
        for package in workspace.packages:
            source = self.root / package.path / "src"
            for file in sorted(source.rglob("*.py")) if source.is_dir() else ():
                parts = list(file.relative_to(source).with_suffix("").parts)
                if parts[-1] == "__init__":
                    parts.pop()
                relative = file.relative_to(self.root).as_posix()
                self.dotted[".".join(parts)] = relative
                self.names[relative] = ".".join(parts)
        self.known_groups = frozenset(g for p in workspace.packages for g in p.groups)

    @cache  # noqa: B019  (one analysis per run; the cache dies with it)
    def parsed(self, file: str) -> _Module:
        return _parse(self.root / file)

    def owner(self, file: str) -> Package | None:
        return next((p for p in self.workspace.packages if file.startswith(p.path + "/")), None)

    def _flat(self, importer: str, name: str) -> str | None:
        """A module found as `<name>.py` in the importer's directory or on pytest's pythonpath."""
        here = importer.rsplit("/", 1)[0] if "/" in importer else ""
        for directory in (here, *self.workspace.pythonpath):
            candidate = f"{directory}/{name}.py" if directory else f"{name}.py"
            if (self.root / candidate).is_file():
                return candidate
        return None

    def _absolute(self, importer: str, level: int, name: str) -> str:
        if level == 0:
            return name
        dotted = self.names.get(importer)
        if dotted is None:
            raise ReachError(f"{importer}: a relative import outside a package's src/.")
        package = dotted.split(".")
        if not importer.endswith("/__init__.py"):
            package.pop()
        base = package[: len(package) - (level - 1)]
        return ".".join([*base, name] if name else base)

    def resolve(self, importer: str, level: int, name: str, names: Sequence[str] = ()) -> set[str]:
        """The workspace files an import loads: each package on the way, the module, and any
        submodules named in a `from` import."""
        if level == 0 and importer not in self.names:
            flat = self._flat(importer, name.split(".")[0])
            if flat is not None:
                return {flat}
        dotted = self._absolute(importer, level, name)
        parts = dotted.split(".")
        prefixes = [".".join(parts[:n]) for n in range(1, len(parts) + 1)]
        prefixes += [f"{dotted}.{submodule}" for submodule in names]
        return {self.dotted[prefix] for prefix in prefixes if prefix in self.dotted}

    def target(self, importer: str, level: int, name: str) -> str | None:
        """The one file an import names, without the packages on the way."""
        if level == 0 and importer not in self.names:
            flat = self._flat(importer, name.split(".")[0])
            if flat is not None:
                return flat if "." not in name else None
        return self.dotted.get(self._absolute(importer, level, name))

    def closure(self, suite: str) -> set[str]:
        """Every workspace file a suite's modules load, its own included."""
        directory = self.root / suite
        pending = [f.relative_to(self.root).as_posix() for f in sorted(directory.rglob("*.py"))]
        seen = set(pending)
        while pending:
            file = pending.pop()
            for level, name, names in self.parsed(file).imports:
                for found in self.resolve(file, level, name, names) - seen:
                    seen.add(found)
                    pending.append(found)
        return seen

    def _constant(self, file: str, name: str) -> str | None:
        module = self.parsed(file)
        if name in module.constants:
            return module.constants[name]
        if name in module.imported:
            level, source, attribute = module.imported[name]
            found = self.target(file, level, source)
            if found is not None:
                return self.parsed(found).constants.get(attribute)
        return None

    def groups(self, file: str) -> set[str]:
        """The entry-point groups a module lists."""
        module = self.parsed(file)
        found: set[str] = set()
        for line, argument in module.groups:
            group = None
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                group = argument.value
            elif isinstance(argument, ast.Name):
                group = self._constant(file, argument.id)
            if group is not None:
                found.add(group)
                continue
            named = module.strings & self.known_groups
            if not named:
                raise ReachError(
                    f"{file}:{line} calls entry_points() with a group this analysis can't read. "
                    "Fix: pass group= a string or a module-level constant, or name the group in a "
                    f"string in the same module, so {Path(__file__).name} can see which packages "
                    "it loads."
                )
            found |= named
        return found

    def named(self, file: str) -> set[Package]:
        """The packages a test-side module names, as a string or a path (rule 4)."""
        module = self.parsed(file)
        packages = self.workspace.packages
        found = {p for p in packages if module.strings & (p.modules | p.commands)}
        for segments in module.paths:
            found |= self._into_root(segments, ends_everywhere=True)
        for text in module.strings:
            if "/" in text:
                found |= self._into_root(_segments(text), ends_everywhere=False)
        return found

    def _into_root(self, segments: list[str | None], ends_everywhere: bool) -> set[Package]:
        """The packages a path reaches through a workspace root: the one it names after the root,
        or every one there when it globs. A path expression that stops at the root (`ROOT /
        "plugins"`, then a glob in another call) reaches every one too; a single string that
        stops there (`"packages/"`, a prefix to match) or names no package (`"packages/gone"`)
        reaches none."""
        found: set[Package] = set()
        for index, segment in enumerate(segments):
            if segment not in self.workspace.roots:
                continue
            after = next((s for s in segments[index + 1 :] if s != ""), None)
            under = [p for p in self.workspace.packages if p.path.startswith(f"{segment}/")]
            if (after is None and ends_everywhere) or (after is not None and _GLOB.search(after)):
                found.update(under)
            else:
                found.update(p for p in under if p.directory == after)
        return found

    def reach(self, suite: str) -> frozenset[str]:
        """The scopes a suite reaches."""
        packages: set[Package] = set()
        scopes: set[str] = set()
        for file in self.closure(suite):
            owner = self.owner(file)
            if owner is not None:
                packages.add(owner)
            if file.startswith(f"{SCRIPTS}/") and Path(file).stem not in FULL_CHECK_SCRIPTS:
                scopes.add(SCRIPTS)
            module = self.parsed(file)
            if module.dynamic:
                packages.update(self.workspace.packages)
            groups = self.groups(file)
            packages.update(p for p in self.workspace.packages if p.groups & groups)
            if file not in self.names:
                packages |= self.named(file)
        by_name = {p.name: p for p in self.workspace.packages}
        pending = list(packages)
        while pending:
            for dependency in pending.pop().dependencies:
                if by_name[dependency] not in packages:
                    packages.add(by_name[dependency])
                    pending.append(by_name[dependency])
        return frozenset(scopes | {p.scope for p in packages if p.scope is not None})


def reach(workspace: Workspace) -> dict[str, frozenset[str]]:
    """Each suite (a testpaths directory) and the scopes it reaches."""
    analysis = _Analysis(workspace)
    return {suite: analysis.reach(suite) for suite in workspace.suites}


def expected_tests(workspace: Workspace) -> dict[str, tuple[str, ...]]:
    """Each scope and the `tests` entries it should declare: the suites that reach it."""
    reached = reach(workspace)
    return {
        scope: tuple(f"{suite}/**" for suite in workspace.suites if scope in reached[suite])
        for scope in workspace.scopes()
    }


def _listed(entries: Iterable[str]) -> str:
    return ", ".join(f"`{entry}`" for entry in entries)


def disagreements(
    declared: Mapping[str, Sequence[str] | None], expected: Mapping[str, Sequence[str]]
) -> list[str]:
    """Each declared scope this analysis covers whose `tests` aren't the suites that reach it.

    Scopes the analysis doesn't cover (`docs`) and scopes not declared are left alone: a path in
    no scope runs the full check, which is always safe.
    """
    found = []
    for scope, tests in sorted(declared.items()):
        if scope not in expected:
            continue
        want = list(expected[scope])
        have = list(tests or ())
        missing = [entry for entry in want if entry not in have]
        extra = [entry for entry in have if entry not in want]
        if tests is None:
            problem = "declares no `tests`"
        elif missing or extra:
            parts = []
            if missing:
                parts.append(f"leaves out {_listed(missing)}, which reach it")
            if extra:
                parts.append(f"names {_listed(extra)}, which don't")
            problem = " and ".join(parts)
        else:
            continue
        line = "tests = [" + ", ".join(f'"{entry}"' for entry in want) + "]"
        found.append(
            f"scopes.{scope} in {CHECK_PATHS} {problem}. Fix: declare `{line}` "
            f"(package-check-scopes design D3)."
        )
    return found


def _table_lines(workspace: Workspace) -> Iterator[str]:
    reached = reach(workspace)
    for suite in workspace.suites:
        yield f"{suite}: {', '.join(sorted(reached[suite])) or '(no scope)'}"
    yield ""
    for scope, tests in expected_tests(workspace).items():
        yield f"[scopes.{scope}]"
        yield "tests = [" + ", ".join(f'"{entry}"' for entry in tests) + "]"


def main() -> int:
    try:
        lines = list(_table_lines(load_workspace()))
    except ReachError as error:
        print(f"check_paths_reach: {error}", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
