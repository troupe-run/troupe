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
from release_config import BUNDLE, CONFIG, LOCK, MANIFEST

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
    """As before the first pin: every dependency on a workspace member bare, in its dependencies and
    its extras, the bundle's 'exclude-paths' in the config, and the bundle unreleased in the
    manifest. The exclusion goes
    with something being bare: the check fails a bare member without it, and an exclusion with
    nothing bare (refuse-bare-bundle-member design D2)."""
    pyproject = bundle_pyproject(root)
    bundle = pyproject.parent.relative_to(root).as_posix()
    names = {release_config.normalise(name): name for name in release_config.members(root).values()}
    text = pyproject.read_bytes().decode("utf-8")
    for _, requirement in dependency_lines(text):
        name = names.get(release_config.requirement_name(requirement))
        if name is not None:
            set_dependency(root, name, name)
    # The extras too: after a real pin, a runner in an extra is pinned there, and in 'all' (#411).
    held = extras(root)
    bare = {
        extra: [names.get(release_config.requirement_name(r), r) for r in requirements]
        for extra, requirements in held.items()
    }
    if bare != held:
        set_extras(root, bare)
    if (root / CONFIG).exists():
        exclude(root)
    manifest = root / MANIFEST
    if manifest.exists():
        versions = json.loads(manifest.read_bytes())
        if versions.get(bundle) != "0.0.0":
            versions[bundle] = "0.0.0"
            manifest.write_bytes((json.dumps(versions, indent=2) + "\n").encode("utf-8"))


def pinned(root: Path) -> None:
    """As the pinning step leaves it, by running the step: every member the manifest gives a
    release pinned at it, unreleased ones bare, and the exclusion gone only when nothing is left
    bare. A copy with nothing to pin fails rather than quietly staying unpinned."""
    moved = pin_bundle.moves(root)
    assert moved, f"nothing in {root / MANIFEST} has released, so the bundle can't be pinned"
    pin_bundle.apply(root, moved)


def exclude(root: Path) -> None:
    """Keep the bundle's commits out of release pull requests, unless they already are: its
    'exclude-paths' line on its own after the entry's "component" line, the one form the pinning
    step can remove."""
    config = root / CONFIG
    bundle = bundle_pyproject(root).parent.relative_to(root).as_posix()
    if "exclude-paths" in json.loads(config.read_bytes())["packages"][bundle]:
        return
    text = config.read_bytes().decode("utf-8")
    lines = text.splitlines(keepends=True)
    component = [i for i, line in enumerate(lines) if line.strip() == f'"component": "{BUNDLE}",']
    assert len(component) == 1, f'{CONFIG} has {len(component)} "component": "{BUNDLE}" lines'
    line = lines[component[0]]
    indent = line[: len(line) - len(line.lstrip())]
    ending = line[len(line.rstrip("\r\n")) :]
    lines.insert(component[0] + 1, f'{indent}"exclude-paths": ["{bundle}"],{ending}')
    config.write_bytes("".join(lines).encode("utf-8"))


def add_member(root: Path, name: str) -> str:
    """Add a new workspace member, packages/<name>, as a commit adding one would: its
    pyproject.toml, its release config entry, the manifest at 0.0.0 (no tag yet), its uv.lock
    package, and a bare dependency in the bundle (spec: releases). The bundle's exclusion is left
    as it was: each test decides. Returns the member's path. Text is inserted, not re-serialised,
    so every other byte stays as it was."""
    path = f"packages/{name}"
    (root / path).mkdir(parents=True)
    (root / path / "pyproject.toml").write_bytes(
        f'[project]\nname = "{name}"\nversion = "0.0.0"\n'.encode()
    )
    entry = {
        "release-type": "python",
        "package-name": name,
        "component": name,
        "extra-files": [
            {"type": "toml", "path": f"/{LOCK}", "jsonpath": release_config.lock_jsonpath(name)}
        ],
    }
    _insert_after(root / CONFIG, '"packages": {', f"{json.dumps(path)}: {json.dumps(entry)},")
    manifest = root / MANIFEST
    versions = json.loads(manifest.read_bytes())
    versions[path] = "0.0.0"
    manifest.write_bytes((json.dumps(versions, indent=2) + "\n").encode("utf-8"))
    lock = root / LOCK
    if lock.exists():
        text = lock.read_bytes().decode("utf-8")
        text += (
            f'\n[[package]]\nname = "{name}"\nversion = "0.0.0"\n'
            f'source = {{ editable = "{path}" }}\n'
        )
        lock.write_bytes(text.encode("utf-8"))
    _insert_after(bundle_pyproject(root), "dependencies = [", f'"{name}",')
    return path


def _insert_after(file: Path, marker: str, line: str) -> None:
    """Insert line after the one line that ends with marker, indented one level deeper."""
    text = file.read_bytes().decode("utf-8")
    lines = text.splitlines(keepends=True)
    [index] = [i for i, held in enumerate(lines) if held.rstrip("\r\n").endswith(marker)]
    held = lines[index]
    indent = held[: len(held) - len(held.lstrip())] + "    "
    ending = held[len(held.rstrip("\r\n")) :]
    lines.insert(index + 1, f"{indent}{line}{ending}")
    file.write_bytes("".join(lines).encode("utf-8"))


RUNNER_TABLE = "packages/troupe/src/troupe/core/interim.py"
"""Core's table of the runners it knows, which the bundle check reads for each runner's name and
whether it's in an extra (runner-extras design D5)."""


def copy_runner_table(source: Path, root: Path) -> None:
    """Copy core's runner table from source to root, where the bundle check reads it."""
    (root / RUNNER_TABLE).parent.mkdir(parents=True, exist_ok=True)
    (root / RUNNER_TABLE).write_bytes((source / RUNNER_TABLE).read_bytes())


def extras(root: Path) -> dict[str, list[str]]:
    """The bundle's extras, by name, in file order."""
    import tomllib

    project = tomllib.loads(bundle_pyproject(root).read_bytes().decode("utf-8"))["project"]
    found: dict[str, list[str]] = project.get("optional-dependencies", {})
    return found


def with_real_extras(
    real: dict[str, list[str]], wanted: dict[str, list[str]]
) -> dict[str, list[str]]:
    """``wanted``, with ``real``, the copy's extras as read before the test changed them, kept as
    they are (whichever runners they hold, bare or pinned, or none), and their entries kept in 'all'
    when ``wanted`` gives 'all'. A test that adds a fixture runner beside them then needs no change
    when a real runner is added to an extra or removed (#411)."""
    kept = {extra: held for extra, held in real.items() if extra != "all"}
    kept.update(wanted)
    if "all" in wanted:
        named = {release_config.requirement_name(r) for r in wanted["all"]}
        kept["all"] = [
            *wanted["all"],
            *(r for r in real.get("all", []) if release_config.requirement_name(r) not in named),
        ]
    return kept


def set_extras(root: Path, wanted: dict[str, list[str]]) -> None:
    """Make the bundle's [project.optional-dependencies] exactly wanted, written as the bundle
    writes it: one requirement a line. An empty wanted removes the table."""
    pyproject = bundle_pyproject(root)
    text = pyproject.read_bytes().decode("utf-8")
    header = "[project.optional-dependencies]\n"
    if header in text:
        start = text.index(header)
        end = text.find("\n[", start + len(header))
        text = text[:start] + text[end + 1 :] if end != -1 else text[:start]
    if wanted:
        block = header
        for extra, requirements in wanted.items():
            if requirements:
                lines = "".join(f'    "{requirement}",\n' for requirement in requirements)
                block += f"{extra} = [\n{lines}]\n"
            else:
                block += f"{extra} = []\n"
        marker = "\n[project.urls]"
        assert marker in text, f"{pyproject} has no [project.urls] to put the extras before"
        text = text.replace(marker, "\n" + block + marker, 1)
    pyproject.write_bytes(text.encode("utf-8"))


def add_runner(
    root: Path,
    runner: str,
    *,
    library: str | None = "example-sdk>=1.5",
    extra: str | None = None,
    in_extra: bool | None = None,
) -> str:
    """Add a runner plugin, plugins/runner-<runner> (distribution troupe-runner-<runner>), as a
    commit adding one would: its pyproject.toml depending on the SDK and, unless library is None,
    on library; its release config, manifest and lock entries; and its entry in core's runner
    table (copy it first). With extra, the bundle names it bare in that extra and in all;
    without, in its dependencies. in_extra is what the table says, by default whether extra is
    given. Returns the distribution's name."""
    name = f"troupe-runner-{runner}"
    package = name.replace("-", "_")
    path = f"plugins/runner-{runner}"
    dependencies = ["troupe-plugin-sdk"] + ([library] if library is not None else [])
    _member_files(root, path, name, dependencies)
    if extra is None:
        _insert_after(bundle_pyproject(root), "dependencies = [", f'"{name}",')
    else:
        held = extras(root)
        held.setdefault(extra, []).append(name)
        held.setdefault("all", [])
        held["all"] = [*held["all"], name]
        set_extras(root, {**{k: v for k, v in held.items() if k != "all"}, "all": held["all"]})
    table = root / RUNNER_TABLE
    assert table.exists(), f"copy core's runner table into {root} first"
    flag = (extra is not None) if in_extra is None else in_extra
    entry = (
        f'    "{runner}": Runner(\n'
        f'        command=(sys.executable, "-m", "{package}"),\n'
        f'        package="{package}",\n'
        f"        in_extra={flag},\n"
        "    ),\n"
    )
    text = table.read_bytes().decode("utf-8")
    start = text.index("RUNNERS: dict[str, Runner] = {")
    end = text.index("\n}\n", start)
    table.write_bytes((text[: end + 1] + entry + text[end + 1 :]).encode("utf-8"))
    return name


def _member_files(root: Path, path: str, name: str, dependencies: list[str]) -> None:
    """A new member's pyproject.toml, release config entry, manifest version (0.0.0, no tag yet)
    and uv.lock package, inserted as text so every other byte stays as it was."""
    (root / path).mkdir(parents=True)
    listed = ", ".join(json.dumps(d) for d in dependencies)
    (root / path / "pyproject.toml").write_bytes(
        f'[project]\nname = "{name}"\nversion = "0.0.0"\ndependencies = [{listed}]\n'.encode()
    )
    entry = {
        "release-type": "python",
        "package-name": name,
        "component": name,
        "extra-files": [
            {"type": "toml", "path": f"/{LOCK}", "jsonpath": release_config.lock_jsonpath(name)}
        ],
    }
    if (root / CONFIG).exists():
        _insert_after(root / CONFIG, '"packages": {', f"{json.dumps(path)}: {json.dumps(entry)},")
    manifest = root / MANIFEST
    if manifest.exists():
        versions = json.loads(manifest.read_bytes())
        versions[path] = "0.0.0"
        manifest.write_bytes((json.dumps(versions, indent=2) + "\n").encode("utf-8"))
    lock = root / LOCK
    if lock.exists():
        text = lock.read_bytes().decode("utf-8")
        text += (
            f'\n[[package]]\nname = "{name}"\nversion = "0.0.0"\n'
            f'source = {{ editable = "{path}" }}\n'
        )
        lock.write_bytes(text.encode("utf-8"))
