"""Check that every file naming a Python version agrees with the supported range.

Spec: python-support.

The root pyproject.toml's requires-python is the one place the supported versions are decided
(python-version-bounds design D1). Every workspace member must declare the same bound, CI's matrix
must test exactly the versions it allows, and .python-version, ruff's target and mypy's version
must name the lowest of them. It runs as a test, inside scripts/check.py; each problem names the
file to fix. scripts/on.py reads the supported versions from here too.

Standard library only, like check.py.
"""

import re
import tomllib
from pathlib import Path
from typing import Any

import release_config

PYPROJECT = "pyproject.toml"
CI = ".github/workflows/ci.yml"
PIN = ".python-version"

_MINOR = r"3\.(0|[1-9][0-9]*)"
_BOUND = re.compile(rf"\s*>=\s*{_MINOR}\s*,\s*<\s*{_MINOR}\s*")
"""The only form a bound may take (design D2): with no packaging library, nothing is guessed."""
_MATRIX = re.compile(r"^\s*python:\s*\[(.*)\]\s*$", re.MULTILINE)
_ENTRY = re.compile(rf"([\"']){_MINOR}\1")
_FORM = 'it must be ">=3.X,<3.Y" with X below Y, for example ">=3.12,<3.14".'


class BoundError(ValueError):
    """The root's requires-python isn't of the one accepted form."""


def parse_bound(bound: str) -> list[str]:
    """The minor versions a bound of the form >=3.X,<3.Y allows, lowest first."""
    match = _BOUND.fullmatch(bound)
    if match is None or int(match[1]) >= int(match[2]):
        raise BoundError(f'{PYPROJECT} has requires-python = "{bound}": {_FORM}')
    return [f"3.{minor}" for minor in range(int(match[1]), int(match[2]))]


def bound(root: Path) -> str:
    """The root's requires-python, exactly as written."""
    value = _requires_python(_toml(root / PYPROJECT))
    if value is None:
        raise BoundError(f"{PYPROJECT} has no requires-python: {_FORM}")
    return value


def supported(root: Path) -> list[str]:
    """The supported minor versions, lowest first, as the root's bound declares them."""
    return parse_bound(bound(root))


def problems(root: Path) -> list[str]:
    """Every way a file disagrees with the supported versions. A malformed root bound is the only
    problem reported, since nothing else can be checked against it."""
    try:
        declared = bound(root)
        versions = parse_bound(declared)
    except BoundError as error:
        return [str(error)]
    lowest = versions[0]
    found: list[str] = []
    for path in release_config.members(root):
        value = _requires_python(_toml(root / path / PYPROJECT))
        if value != declared:
            has = "no requires-python" if value is None else f'requires-python = "{value}"'
            found.append(
                f'{path}/{PYPROJECT} has {has}, not the root\'s "{declared}": set it to '
                f'"{declared}".'
            )
    found.extend(_ci_problems(root, declared, versions))
    found.extend(_pin_problems(root, lowest))
    found.extend(_tool_problems(_toml(root / PYPROJECT), lowest))
    return found


def _toml(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _requires_python(pyproject: dict[str, Any]) -> str | None:
    value = pyproject.get("project", {}).get("requires-python")
    return value if isinstance(value, str) else None


def _ci_problems(root: Path, declared: str, versions: list[str]) -> list[str]:
    lines = _MATRIX.findall((root / CI).read_text(encoding="utf-8"))
    if len(lines) != 1:
        return [
            f"{CI} has {len(lines)} 'python: [...]' lines: keep exactly one, in the check job's "
            'matrix, listing the supported versions as quoted strings, like python: ["3.12", '
            '"3.13"].'
        ]
    tested: list[str] = []
    found: list[str] = []
    for entry in (part.strip() for part in lines[0].split(",") if part.strip()):
        match = _ENTRY.fullmatch(entry)
        if match is None:
            found.append(
                f"{CI} lists {entry} in its Python matrix: each entry must be a quoted minor "
                'version, like "3.13" (unquoted, YAML reads 3.10 as the number 3.1).'
            )
        else:
            tested.append(f"3.{match[2]}")
    if found:
        return found
    found.extend(
        f'{CI} doesn\'t test {version}, which requires-python "{declared}" in {PYPROJECT} '
        "supports: add it to the matrix, or narrow the bound."
        for version in versions
        if version not in tested
    )
    found.extend(
        f'{CI} tests {version}, which requires-python "{declared}" in {PYPROJECT} doesn\'t '
        "allow: widen the bound, or remove it from the matrix."
        for version in tested
        if version not in versions
    )
    return found


def _pin_problems(root: Path, lowest: str) -> list[str]:
    pin = root / PIN
    if not pin.is_file():
        return [f"{PIN} is missing: create it holding {lowest}, the lowest supported version."]
    value = pin.read_text(encoding="utf-8").strip()
    if value != lowest:
        return [
            f"{PIN} says {value}, not {lowest}, the lowest supported version: set it to {lowest}."
        ]
    return []


def _tool_problems(pyproject: dict[str, Any], lowest: str) -> list[str]:
    tool = pyproject.get("tool", {})
    found: list[str] = []
    target = "py" + lowest.replace(".", "")
    ruff = tool.get("ruff", {}).get("target-version")
    if ruff != target:
        found.append(
            f'{PYPROJECT} has [tool.ruff] target-version = "{ruff}", not "{target}" for {lowest}, '
            f'the lowest supported version: set it to "{target}".'
        )
    mypy = tool.get("mypy", {}).get("python_version")
    if mypy != lowest:
        found.append(
            f'{PYPROJECT} has [tool.mypy] python_version = "{mypy}", not "{lowest}", the lowest '
            f'supported version: set it to "{lowest}".'
        )
    return found
