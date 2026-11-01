"""The bundle's state before and after its first pin, built in a copy of the repository
(pin-tests-any-state design D1).

The tests that copy the real files can't assume which of the two the repository is in: main is
unpinned until the first pinning pull request merges, and pinned for good after it (#229). So each
test builds the state it needs in its copy. Both work on bytes, like the pinning step, and find
dependencies by name, never by an expected line."""

import json
import re
from pathlib import Path

import pin_bundle
import release_config
from release_config import BUNDLE, CONFIG, MANIFEST

_DEPENDENCY = re.compile(r'^(?P<indent>\s*)"(?P<requirement>[^"]+)"(?P<rest>,?\s*)$')


def bundle_pyproject(root: Path) -> Path:
    path = release_config.bundle_member(root)
    assert path is not None, f"{BUNDLE} isn't a workspace member in {root}"
    return root / path / "pyproject.toml"


def dependency_lines(text: str) -> list[tuple[int, str]]:
    """Each line of the bundle's dependencies array, by index in text.splitlines(keepends=True),
    with the requirement it holds."""
    lines = text.splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines) if line.startswith("dependencies = ["))
    found: list[tuple[int, str]] = []
    for index in range(start + 1, len(lines)):
        if lines[index].strip() == "]":
            return found
        matched = _DEPENDENCY.match(lines[index])
        assert matched is not None, f"the bundle's dependency {lines[index]!r} isn't one string"
        found.append((index, matched["requirement"]))
    raise AssertionError("the bundle's dependencies array isn't closed")


def set_dependency(root: Path, name: str, requirement: str | None) -> None:
    """Make the bundle's dependency on name requirement, whatever it was, or drop its line when
    requirement is None."""
    pyproject = bundle_pyproject(root)
    text = pyproject.read_bytes().decode("utf-8")
    lines = text.splitlines(keepends=True)
    [index] = [
        i
        for i, held in dependency_lines(text)
        if release_config.requirement_name(held) == release_config.normalise(name)
    ]
    if requirement is None:
        del lines[index]
    else:
        matched = _DEPENDENCY.match(lines[index])
        assert matched is not None
        lines[index] = f'{matched["indent"]}"{requirement}"{matched["rest"]}'
    pyproject.write_bytes("".join(lines).encode("utf-8"))


def unpinned(root: Path) -> None:
    """As before the first pin: every dependency on a workspace member bare, the bundle's
    bootstrap 'exclude-paths' in the config, and the bundle unreleased in the manifest. The three
    go together: the check fails an exclusion kept after the bundle released."""
    pyproject = bundle_pyproject(root)
    bundle = pyproject.parent.relative_to(root).as_posix()
    names = {release_config.normalise(name): name for name in release_config.members(root).values()}
    text = pyproject.read_bytes().decode("utf-8")
    for _, requirement in dependency_lines(text):
        name = names.get(release_config.requirement_name(requirement))
        if name is not None:
            set_dependency(root, name, name)
    config = root / CONFIG
    entry = json.loads(config.read_bytes())["packages"][bundle] if config.exists() else {}
    if config.exists() and "exclude-paths" not in entry:
        _exclude(config, bundle)
    manifest = root / MANIFEST
    if manifest.exists():
        versions = json.loads(manifest.read_bytes())
        if versions.get(bundle) != "0.0.0":
            versions[bundle] = "0.0.0"
            manifest.write_bytes((json.dumps(versions, indent=2) + "\n").encode("utf-8"))


def pinned(root: Path) -> None:
    """As the pinning step leaves it, by running the step: every member the manifest gives a
    release pinned at it, unreleased ones bare, and the bootstrap exclusion gone. A copy with
    nothing to pin fails rather than quietly staying unpinned."""
    moved = pin_bundle.moves(root)
    assert moved, f"nothing in {root / MANIFEST} has released, so the bundle can't be pinned"
    pin_bundle.apply(root, moved)


def _exclude(config: Path, bundle: str) -> None:
    """Put the bootstrap line back on its own after the entry's "component" line: the one form
    the pinning step can remove."""
    text = config.read_bytes().decode("utf-8")
    lines = text.splitlines(keepends=True)
    component = [i for i, line in enumerate(lines) if line.strip() == f'"component": "{BUNDLE}",']
    assert len(component) == 1, f'{CONFIG} has {len(component)} "component": "{BUNDLE}" lines'
    line = lines[component[0]]
    indent = line[: len(line) - len(line.lstrip())]
    ending = line[len(line.rstrip("\r\n")) :]
    lines.insert(component[0] + 1, f'{indent}"exclude-paths": ["{bundle}"],{ending}')
    config.write_bytes("".join(lines).encode("utf-8"))
