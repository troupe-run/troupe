"""Move every test file into its suite's unit/ or integration/ directory (test-split design D7, step 3).

Run from the repository root, after split_tests.py and anchor_paths.py:

    uv run python openspec/changes/test-split/move_tests.py

It reads `test-kinds.json` beside it for each file's kind (a split file's new half has the split's kind), refuses
a test file the plan doesn't name (classify it in the plan first), and refuses a move that would leave a test
module importing another test module of the other kind (pytest finds that one only from the same directory).
Then it `git mv`s each file, and rewrites every repository-relative path naming a moved file in the tracked text
files that aren't delivered from troupe-run/infrastructure (.github/guard-delivery.json) or under openspec/, plus the few path patterns that
name test files by glob (the flake campaign's selection). Finally pytest's `pythonpath` gains each suite's
`tests/`, where the helpers stay.

Deterministic, so after a rebase it's re-run rather than conflicts resolved by hand.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLAN = HERE / "test-kinds.json"
KINDS = ("unit", "integration")
DELIVERED = "Source: troupe-run/infrastructure"
GLOBS = {
    # The flake campaign's selection names test files by pattern, so a file moving between the kinds stays
    # hunted (flake-hunt delta): each entry matches both kinds' directories. Applied before the exact paths.
    "scripts/flake_campaign.py": ('"packages/troupe/tests/test_', '"packages/troupe/tests/*/test_'),
}


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def suites() -> list[str]:
    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    return list(config["tool"]["pytest"]["ini_options"]["testpaths"])


def suite_of(path: str, all_suites: list[str]) -> str:
    holding = [s for s in all_suites if path.startswith(s + "/")]
    return max(holding, key=len)


def kinds(plan: dict[str, dict[str, object]]) -> dict[str, str]:
    """Every test file's kind, the split halves included."""
    found: dict[str, str] = {}
    for name, entry in plan.items():
        found[name] = str(entry["kind"])
        for minor in dict(entry.get("split", {})):  # type: ignore[call-overload]
            found[name.removesuffix(".py") + f"_{minor}.py"] = minor
    return found


def test_files(all_suites: list[str]) -> list[str]:
    tracked = git("ls-files", "--cached", "--others", "--exclude-standard", *all_suites).split()
    files = []
    for path in tracked:
        name = path.rsplit("/", 1)[-1]
        if not (name.startswith("test_") and name.endswith(".py")):
            continue
        rest = path[len(suite_of(path, all_suites)) + 1 :]
        if "/" not in rest:  # directly in the suite: not moved yet
            files.append(path)
    return files


def destination(path: str, kind: str, all_suites: list[str]) -> str:
    suite = suite_of(path, all_suites)
    return f"{suite}/{kind}/{path[len(suite) + 1 :]}"


def imports_of(path: str) -> set[str]:
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    names = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("test_"):
            names.add(node.module)
        elif isinstance(node, ast.Import):
            names.update(a.name for a in node.names if a.name.startswith("test_"))
    return names


def crossing(files: list[str], moves: dict[str, str], kind_of: dict[str, str]) -> list[str]:
    """Each test module that would import a test module now in another directory."""
    by_module = {Path(p).stem: p for p in files}
    found = []
    for path in files:
        for module in imports_of(path):
            target = by_module.get(module)
            if target and Path(moves[target]).parent != Path(moves[path]).parent:
                found.append(f"{path} ({kind_of[path]}) imports {module} ({kind_of[target]})")
    return found


def rewrite_references(moves: dict[str, str]) -> None:
    """Rewrite the paths that name moved files, longest first so no path rewrites part of another."""
    rewrites = sorted(moves.items(), key=lambda item: -len(item[0]))
    pattern = re.compile("|".join(re.escape(old) + r"(?![A-Za-z0-9_])" for old, _ in rewrites))
    lookup = dict(rewrites)
    delivered = set(json.loads(Path(".github/guard-delivery.json").read_text(encoding="utf-8"))["files"])
    for path in git("ls-files").split():
        # The specs change through the change's deltas, at archive.
        if path.startswith("openspec/") or path in moves.values():
            continue
        file = Path(path)
        try:
            text = file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, IsADirectoryError, FileNotFoundError):
            continue
        if path in delivered or DELIVERED in text[:400]:
            continue  # infrastructure's to change: delivered here, overwritten on the next delivery
        changed = text
        if path in GLOBS:
            changed = changed.replace(*GLOBS[path])
        changed = pattern.sub(lambda m: lookup[m.group(0)], changed)
        if changed != text:
            file.write_text(changed, encoding="utf-8")
            print(f"rewrote paths in {path}", file=sys.stderr)


def find_helpers(all_suites: list[str]) -> None:
    """Helpers stay in each suite's tests/, which pytest no longer puts on sys.path by itself."""
    pyproject = Path("pyproject.toml")
    text = pyproject.read_text(encoding="utf-8")
    old_line = re.search(r"^pythonpath = \[.*\]$", text, re.M)
    if old_line is None:
        raise SystemExit("pyproject.toml's pytest pythonpath isn't on one line; update it by hand")
    lines = ["pythonpath = ["] + [f'    "{e}",' for e in [*all_suites, "scripts"]] + ["]"]
    pyproject.write_text(text.replace(old_line.group(0), "\n".join(lines)), encoding="utf-8")


def main() -> int:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))["files"]
    all_suites = suites()
    kind_of = kinds(plan)
    files = test_files(all_suites)
    unplanned = sorted(set(files) - set(kind_of))
    if unplanned:
        print("not in the plan; add each to test-kinds.json with its kind:", *unplanned, sep="\n  ")
        return 1
    moves = {path: destination(path, kind_of[path], all_suites) for path in files}
    crossed = crossing(files, moves, kind_of)
    if crossed:
        print("imports between test modules of different kinds:", *crossed, sep="\n  ")
        return 1
    for old, new in moves.items():
        Path(new).parent.mkdir(exist_ok=True)
        git("mv", old, new)
    rewrite_references(moves)
    find_helpers(all_suites)
    print(f"moved {len(moves)} files", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
