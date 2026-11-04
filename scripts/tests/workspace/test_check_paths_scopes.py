"""troupe's declaration scopes each runner plugin, and the plugin SDK's scope reaches every runner's
suite (spec: quality-check, "Each package outside core has a scope"). Here, not in scripts/tests,
because naming a package's path makes a suite reach it (package-check-scopes design D6)."""

import tomllib
from pathlib import Path

import guard


def _troupes_declaration() -> guard.CheckPaths:
    return guard.check_paths(
        (Path(__file__).resolve().parents[3] / guard.CHECK_PATHS).read_text(encoding="utf-8")
    )


def test_troupes_declaration_scopes_the_ollama_runners_source_to_runner_ollama() -> None:
    declaration = _troupes_declaration()
    paths = ["plugins/runner-ollama/src/troupe_runner_ollama/runner.py"]
    assert guard.check_scope(paths, declaration).names == ("runner_ollama",)


def test_the_plugin_sdks_scope_reaches_every_runner_plugins_suite() -> None:
    root = Path(__file__).resolve().parents[3]
    text = (root / guard.CHECK_PATHS).read_text(encoding="utf-8")
    sdk_tests = tomllib.loads(text)["scopes"]["plugin_sdk"]["tests"]
    runners = sorted(path.name for path in (root / "plugins").glob("runner-*") if path.is_dir())
    assert "runner-ollama" in runners
    for runner in runners:
        assert f"plugins/{runner}/tests/**" in sdk_tests, runner
