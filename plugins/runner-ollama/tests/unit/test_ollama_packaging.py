"""What the plugin depends on (spec: ollama-runner, "The Ollama runner is a self-contained plugin";
ollama-library design D2)."""

import tomllib
from pathlib import Path

TESTS_ROOT = next(p for p in Path(__file__).resolve().parents if p.name == "tests")
"""This suite's tests directory, found by name so the file can sit at any depth under it."""

PYPROJECT = TESTS_ROOT.parent / "pyproject.toml"


def test_the_plugin_depends_on_the_sdk_and_on_httpx2_and_httpcore2_pinned_and_nothing_else() -> (
    None
):
    dependencies = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["dependencies"]
    assert dependencies[0] == "troupe-plugin-sdk"
    pinned = {name: version for name, _, version in (d.partition("==") for d in dependencies[1:])}
    assert sorted(pinned) == ["httpcore2", "httpx2"]
    assert all(version and "," not in version for version in pinned.values()), pinned
    assert len(dependencies) == 3
