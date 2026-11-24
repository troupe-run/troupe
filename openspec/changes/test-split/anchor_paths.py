"""Make each test file's paths independent of how deep it sits (test-split design D7, step 2).

Run from the repository root, after split_tests.py and before move_tests.py:

    uv run python openspec/changes/test-split/anchor_paths.py

A test file that finds a file from its own location by a fixed depth (`Path(__file__).resolve().parents[3]`,
`Path(__file__).with_name("record_child.py")`) would find the wrong one once it moves a level down into `unit/` or
`integration/`. Each such expression is rewritten from `TESTS_ROOT`, the nearest directory named `tests` above the file,
found by name, which is the same before and after the move. Only code is rewritten, never a string's contents (a
test that writes Python source into a temporary file keeps it).

Deterministic, so after a rebase it's re-run rather than conflicts resolved by hand.
"""

from __future__ import annotations

import ast
import io
import os
import re
import sys
import tokenize
from pathlib import Path

ANCHOR = 'TESTS_ROOT = next(p for p in Path(__file__).resolve().parents if p.name == "tests")\n'
ANCHOR_DOC = '"""This suite\'s tests directory, found by name so the file can sit at any depth under it."""\n'
PATTERN = re.compile(
    r"Path\(__file__\)(?:\.resolve\(\))?"
    r"(?:\.parents\[(?P<k>\d+)\]|\.parent(?!s)|\.with_name\((?P<name>[^)]*)\))"
)


def _string_spans(source: str) -> list[tuple[int, int]]:
    """The character spans of string tokens (f-strings' pieces included)."""
    offsets = [0]
    for line in source.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    spans = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.STRING or token.type == getattr(tokenize, "FSTRING_MIDDLE", -1):
            start = offsets[token.start[0] - 1] + token.start[1]
            end = offsets[token.end[0] - 1] + token.end[1]
            spans.append((start, end))
    return spans


def _expression(target: Path, tests: Path) -> str:
    """`target` written from TESTS."""
    try:
        inside = target.relative_to(tests)
    except ValueError:
        up = len(tests.relative_to(os.path.commonpath([tests, target])).parts)
        rest = target.relative_to(os.path.commonpath([tests, target]))
        base = "TESTS_ROOT.parent" if up == 1 else f"TESTS_ROOT.parents[{up - 1}]"
        return base + "".join(f' / "{part}"' for part in rest.parts)
    return "TESTS_ROOT" + "".join(f' / "{part}"' for part in inside.parts)


def anchor(path: Path) -> bool:
    source = path.read_text(encoding="utf-8")
    here = path.resolve().parent
    tests = next(p for p in path.resolve().parents if p.name == "tests")
    spans = _string_spans(source)

    def replace(match: re.Match[str]) -> str:
        if any(start <= match.start() < end for start, end in spans):
            return match.group(0)
        if match.group("k") is not None:
            target = here.parents[int(match.group("k")) - 1] if int(match.group("k")) else here
            return _expression(target, tests)
        if match.group("name") is not None:
            joined = f"{_expression(here, tests)} / {match.group('name')}"
            chained = source[match.end() : match.end() + 1] == "."
            return f"({joined})" if chained else joined
        return _expression(here, tests)

    changed = PATTERN.sub(replace, source)
    if changed == source:
        return False
    if re.search(r"^TESTS_ROOT\b", changed, re.M):
        raise SystemExit(f"{path} already defines TESTS_ROOT; rename it by hand")
    changed = _insert_anchor(changed)
    path.write_text(changed, encoding="utf-8")
    return True


def _insert_anchor(source: str) -> str:
    """The anchor goes after the last top-level import, with Path imported if it isn't."""
    tree = ast.parse(source)
    imports = [n for n in tree.body if isinstance(n, ast.Import | ast.ImportFrom)]
    lines = source.splitlines(keepends=True)
    after = imports[-1].end_lineno if imports else 0
    assert after is not None
    has_path = any(
        isinstance(n, ast.ImportFrom) and n.module == "pathlib" and any(a.name == "Path" for a in n.names)
        for n in imports
    )
    added = [] if has_path else ["from pathlib import Path\n"]
    return "".join([*lines[:after], *added, "\n", ANCHOR, ANCHOR_DOC, *lines[after:]])


def main() -> int:
    roots = [Path(p) for p in ("packages", "plugins", "scripts/tests")]
    changed = []
    for root in roots:
        for path in sorted(root.rglob("test_*.py")):
            if "tests" in path.parts and anchor(path):
                changed.append(str(path))
    if changed:
        import subprocess

        subprocess.run(["ruff", "check", "--fix", "--select", "I001", "--quiet", *changed], check=False)
        subprocess.run(["ruff", "format", "--quiet", *changed], check=True)
    print(f"anchored {len(changed)} files", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
