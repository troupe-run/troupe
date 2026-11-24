"""Every version the manifest records has its release tag, and a missing one fails the release run,
naming the tag and the repair route (spec: releases; release-missing-components design D1, D2).

The config and manifest are this checkout's own files, copied to a scratch root, so the tests read
the real shapes; the tag refs are what `gh api .../git/matching-refs/tags --jq '.[].ref'` prints.

Its tests that start a process, open a socket or use a git theatre are in
integration/test_release_tags_integration.py."""

import json
from pathlib import Path

import pytest
from conftest import REPO
from release_tags_shared import (
    REPAIR,
    UNCONFIGURED,
    every_tag,
    path_of,
    read,
    released_0_2_0,
    write_root,
)

import release_tags
from release_config import CONFIG, MANIFEST


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


@pytest.mark.docs
def test_the_repair_section_the_failure_points_to_exists() -> None:
    guide = (REPO / "contributing" / "releasing.md").read_text(encoding="utf-8")
    assert "\n## Repairing a missing release\n" in guide
    assert release_tags.REPAIR == REPAIR
