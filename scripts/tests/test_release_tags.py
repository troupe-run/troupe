"""Every version the manifest records has its release tag, and a missing one fails the release run,
naming the tag and the repair route (spec: releases; release-missing-components design D1, D2).

The config and manifest are this checkout's own files, copied to a scratch root, so the tests read
the real shapes; the tag refs are what `gh api .../git/matching-refs/tags --jq '.[].ref'` prints."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from conftest import REPO, SCRIPTS

import release_tags
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


def test_every_version_tagged_passes(tmp_path: Path) -> None:
    root = write_root(tmp_path)
    assert release_tags.missing(root, every_tag(read(MANIFEST), read(CONFIG))) == []


def test_the_0_2_0_release_without_ollama_and_protocol_names_both_tags(tmp_path: Path) -> None:
    manifest = released_0_2_0()
    root = write_root(tmp_path, manifest)
    gone = {"refs/tags/troupe-runner-ollama-v0.1.0", "refs/tags/protocol-v0.2.0"}
    refs = [ref for ref in every_tag(manifest, read(CONFIG)) if ref not in gone]
    assert release_tags.missing(root, refs) == ["troupe-runner-ollama-v0.1.0", "protocol-v0.2.0"]


def test_an_unreleased_member_at_0_0_0_needs_no_tag(tmp_path: Path) -> None:
    manifest = read(MANIFEST)
    manifest[path_of("runner-openai")] = "0.0.0"
    root = write_root(tmp_path, manifest)
    refs = every_tag(manifest, read(CONFIG))
    assert not any("troupe-runner-openai-v0.0.0" in ref for ref in refs)
    assert release_tags.missing(root, refs) == []


def test_a_ref_that_isnt_a_tag_doesnt_count_as_one(tmp_path: Path) -> None:
    root = write_root(tmp_path)
    tags = every_tag(read(MANIFEST), read(CONFIG))
    refs = [ref.replace("refs/tags/", "refs/heads/") for ref in tags]
    assert len(release_tags.missing(root, refs)) == len(refs)


def test_a_manifest_path_the_config_doesnt_configure_is_an_error(tmp_path: Path) -> None:
    manifest = read(MANIFEST) | {UNCONFIGURED: "0.1.0"}
    root = write_root(tmp_path, manifest)
    pattern = rf"{UNCONFIGURED}.*release-please-config\.json"
    with pytest.raises(release_tags.UnreadableError, match=pattern):
        release_tags.missing(root, every_tag(read(MANIFEST), read(CONFIG)))


def test_a_package_without_a_component_is_an_error(tmp_path: Path) -> None:
    config = read(CONFIG)
    del config["packages"]["protocol"]["component"]
    root = write_root(tmp_path, config=config)
    with pytest.raises(release_tags.UnreadableError, match=r"'protocol'.*component"):
        release_tags.missing(root, every_tag(read(MANIFEST), read(CONFIG)))


@pytest.mark.parametrize("setting", [False, None, "true"])
def test_tags_without_their_component_are_an_error(tmp_path: Path, setting: object) -> None:
    config = read(CONFIG)
    if setting is None:
        del config["include-component-in-tag"]
    else:
        config["include-component-in-tag"] = setting
    root = write_root(tmp_path, config=config)
    with pytest.raises(release_tags.UnreadableError, match="include-component-in-tag"):
        release_tags.missing(root, every_tag(read(MANIFEST), read(CONFIG)))


@pytest.mark.parametrize("version", ["0.2", "v0.2.0", "0.2.0-rc.1", ""])
def test_a_version_that_isnt_x_y_z_is_an_error(tmp_path: Path, version: str) -> None:
    manifest = read(MANIFEST) | {"protocol": version}
    root = write_root(tmp_path, manifest)
    with pytest.raises(release_tags.UnreadableError, match=rf"'protocol'.*{json.dumps(version)}"):
        release_tags.missing(root, every_tag(read(MANIFEST), read(CONFIG)))


def run(root: Path, refs: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "release_tags.py"), "--root", str(root)],
        input="".join(f"{ref}\n" for ref in refs),
        capture_output=True,
        text=True,
        check=False,
    )


def test_run_as_the_workflow_runs_it_exits_0_when_every_tag_exists(tmp_path: Path) -> None:
    root = write_root(tmp_path)
    result = run(root, every_tag(read(MANIFEST), read(CONFIG)))
    assert (result.returncode, result.stderr) == (0, "")


def test_run_as_the_workflow_runs_it_exits_1_naming_the_tags_and_the_repair(tmp_path: Path) -> None:
    manifest = released_0_2_0()
    root = write_root(tmp_path, manifest)
    gone = ("troupe-runner-ollama-v0.1.0", "protocol-v0.2.0")
    refs = [ref for ref in every_tag(manifest, read(CONFIG)) if not ref.endswith(gone)]
    result = run(root, refs)
    assert result.returncode == 1
    assert "troupe-runner-ollama-v0.1.0" in result.stderr
    assert "protocol-v0.2.0" in result.stderr
    assert REPAIR in result.stderr


def test_run_as_the_workflow_runs_it_exits_1_naming_an_unreadable_input(tmp_path: Path) -> None:
    root = write_root(tmp_path, read(MANIFEST) | {UNCONFIGURED: "0.1.0"})
    result = run(root, every_tag(read(MANIFEST), read(CONFIG)))
    assert result.returncode == 1
    assert UNCONFIGURED in result.stderr


@pytest.mark.docs
def test_the_repair_section_the_failure_points_to_exists() -> None:
    guide = (REPO / "contributing" / "releasing.md").read_text(encoding="utf-8")
    assert "\n## Repairing a missing release\n" in guide
    assert release_tags.REPAIR == REPAIR
