"""What test_release_tags.py and test_release_tags_integration.py share."""

import json
from pathlib import Path
from typing import Any

from conftest import REPO

from release_config import CONFIG, MANIFEST

REPAIR = "contributing/releasing.md#repairing-a-missing-release"


def read(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((REPO / name).read_text(encoding="utf-8"))
    return loaded


def write_root(
    tmp_path: Path,
    manifest: dict[str, str] | None = None,
    config: dict[str, Any] | None = None,
) -> Path:
    (tmp_path / CONFIG).write_text(json.dumps(config or read(CONFIG)), encoding="utf-8")
    (tmp_path / MANIFEST).write_text(json.dumps(manifest or read(MANIFEST)), encoding="utf-8")
    return tmp_path


def every_tag(manifest: dict[str, str], config: dict[str, Any]) -> list[str]:
    packages = config["packages"]
    return [
        f"refs/tags/{packages[path]['component']}-v{version}"
        for path, version in manifest.items()
        if version != "0.0.0"
    ]


def path_of(directory: str) -> str:
    """A configured path, found by its last segment. Neither the path nor the component's name is
    written out: either would make this suite reach that package (scripts/check_paths_reach.py,
    rule 4), since a component's name is also its console script's."""
    paths: list[str] = list(read(CONFIG)["packages"])
    [path] = [p for p in paths if p.rsplit("/", 1)[-1] == directory]
    return path


UNCONFIGURED = "unconfigured/member"
"""A manifest path release-please-config.json doesn't configure."""


def released_0_2_0() -> dict[str, str]:
    """The manifest as #263's merge left it: troupe-runner-ollama at 0.1.0 and protocol at 0.2.0."""
    manifest: dict[str, str] = read(MANIFEST)
    manifest[path_of("runner-ollama")] = "0.1.0"
    manifest[path_of("protocol")] = "0.2.0"
    return manifest
