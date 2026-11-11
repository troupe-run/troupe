"""troupe starts fast: what a fresh interpreter loads to read a command line, and to run one
command (spec: cli; cli-starts-fast design D6).

Each test runs a fresh interpreter, since this one has loaded everything already, and reads the
names in its ``sys.modules`` from a file, so the command's own output is left as it is. The tests
count modules, never time: a slow or loaded machine can't change their outcome.
"""

import asyncio
import importlib
import io
import json
import os
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pytest

from gitrepo import Repo
from runtesting import ADA, ALLOW, theatre
from troupe.cli import main
from troupe.core.client import dispatch
from troupe.core.client.session import Session
from troupe.core.errors import TroupeError

HEAVY = (
    "importlib.metadata",  # package metadata, with the email parsing it reads it with
    "email",
    "jsonschema",  # schema checking, and its schema registry
    "jsonschema_specifications",
    "referencing",
    "ruamel.yaml",  # YAML
    "asyncio",  # the async runtime
    "troupe.core.runs",  # the core's command handlers, by family
    "troupe.core.config.commands",
    "troupe.core.init",
    "troupe.core.interim",  # the runner table, which checks options against schemas
    "troupe.core.runners.effects",  # the runner effects module
)
"""The modules that commands use to do their work, which reading a command line never needs.
A name covers its submodules too."""

METADATA = ("importlib.metadata", "email")
"""What ``--version`` may load of HEAVY: the installed package's metadata."""

FAMILIES = {
    "runs": "troupe.core.runs",
    "config": "troupe.core.config.commands",
    "init": "troupe.core.init",
}
"""Each family of the core's commands, by the module its handlers live in."""

PROBE = """\
import json, sys
out, mode = sys.argv[1], sys.argv[2]
try:
    if mode == "import":
        import troupe.cli
        code = 0
    else:
        from troupe.cli import main
        code = main(json.loads(mode))
finally:
    with open(out, "w", encoding="utf-8") as file:
        json.dump(sorted(sys.modules), file)
sys.exit(code)
"""


@dataclass(frozen=True)
class Probed:
    """What a fresh interpreter printed and loaded."""

    code: int
    stdout: str
    stderr: str
    modules: frozenset[str]


def probe(
    tmp_path: Path,
    argv: list[str] | None,
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> Probed:
    """Run a fresh interpreter that imports troupe's command line (``argv`` None) or runs it with
    ``argv``, and return its output and the modules it loaded."""
    out = tmp_path / "modules.json"
    result = subprocess.run(
        [sys.executable, "-c", PROBE, str(out), "import" if argv is None else json.dumps(argv)],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=120,
    )
    assert out.exists(), f"the probe wrote no module list:\n{result.stderr}"
    modules = frozenset(json.loads(out.read_text(encoding="utf-8")))
    return Probed(result.returncode, result.stdout, result.stderr, modules)


def loaded(modules: Iterable[str], names: Iterable[str]) -> list[str]:
    """The ``names`` that are loaded, a name counting as loaded when it or a submodule is."""
    found = set(modules)
    return sorted(
        name for name in names if name in found or any(m.startswith(f"{name}.") for m in found)
    )


def assert_none_loaded(modules: Iterable[str], names: Iterable[str]) -> None:
    heavy = loaded(modules, names)
    assert not heavy, (
        f"these were loaded but aren't needed here: {', '.join(heavy)}. To see what imports one, "
        "run `python -X importtime -c 'import troupe.cli'` and read the lines above its name."
    )


def in_process(argv: list[str]) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(argv, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


# The probe itself


def test_the_probe_reports_a_module_only_when_the_interpreter_loaded_it(tmp_path: Path) -> None:
    imported = probe(tmp_path, None).modules
    assert "troupe.cli" in imported
    assert loaded(["jsonschema.validators"], ["jsonschema"]) == ["jsonschema"]
    assert loaded(["jsonschemas"], ["jsonschema"]) == []  # a longer name isn't a submodule


# Requirement: Starting troupe loads only what parsing needs


def test_importing_the_command_line_loads_none_of_the_heavy_modules(tmp_path: Path) -> None:
    assert_none_loaded(probe(tmp_path, None).modules, HEAVY)


@pytest.mark.parametrize(
    "argv",
    [["--help"], [], ["config", "--help"], ["perform", "--help"]],
    ids=["--help", "no command", "a group's help", "a command's help"],
)
def test_help_is_printed_as_before_and_loads_none_of_the_heavy_modules(
    tmp_path: Path, argv: list[str]
) -> None:
    probed = probe(tmp_path, argv, cwd=tmp_path)
    assert (probed.code, probed.stdout, probed.stderr) == in_process(argv)
    assert_none_loaded(probed.modules, HEAVY)


@pytest.mark.parametrize(
    "argv",
    [["frobnicate"], ["status", "--frob"], ["perform"], ["status", "--limit", "many"]],
    ids=["an unknown command", "an unknown flag", "a missing argument", "a refused value"],
)
def test_a_usage_error_is_reported_as_before_and_loads_none_of_the_heavy_modules(
    tmp_path: Path, argv: list[str]
) -> None:
    probed = probe(tmp_path, argv, cwd=tmp_path)
    assert probed.code != 0
    assert (probed.code, probed.stdout, probed.stderr) == in_process(argv)
    assert_none_loaded(probed.modules, HEAVY)


def test_the_version_is_printed_as_before_and_loads_only_package_metadata(tmp_path: Path) -> None:
    probed = probe(tmp_path, ["--version"], cwd=tmp_path)
    assert (probed.code, probed.stdout, probed.stderr) == in_process(["--version"])
    assert_none_loaded(probed.modules, [name for name in HEAVY if name not in METADATA])


# Requirement: A command loads only its own handlers


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return theatre(tmp_path / "theatre")


def theatre_env(repo: Repo) -> dict[str, str]:
    return {**os.environ, **repo.env, **ADA, **ALLOW}


def test_status_shows_the_runs_and_loads_neither_configs_nor_inits_handlers(
    tmp_path: Path, repo: Repo
) -> None:
    probed = probe(tmp_path, ["status"], cwd=repo.path, env=theatre_env(repo))
    assert (probed.code, probed.stdout) == (0, "No runs yet.\n"), probed.stderr
    assert_none_loaded(probed.modules, [FAMILIES["config"], FAMILIES["init"]])


def test_config_get_shows_config_and_loads_neither_runs_nor_inits_handlers(
    tmp_path: Path, repo: Repo
) -> None:
    probed = probe(tmp_path, ["config", "get", "--json"], cwd=repo.path, env=theatre_env(repo))
    assert probed.code == 0, probed.stderr
    json.loads(probed.stdout)
    assert_none_loaded(probed.modules, [FAMILIES["runs"], FAMILIES["init"]])


def test_the_dispatchers_table_names_every_method_the_families_offer() -> None:
    every: set[str] = set()
    for module in FAMILIES.values():
        every |= set(importlib.import_module(module).methods())
    assert set(dispatch.FAMILIES) == every
    assert set(dispatch.handlers()) == every


def test_an_unknown_method_is_refused_listing_every_method_troupe_offers() -> None:
    with pytest.raises(TroupeError) as caught:
        asyncio.run(dispatch.call("deploy", {}, Session(theatre=Path())))
    assert caught.value.code == "client.unknown-method"
    assert caught.value.details["known"] == sorted(dispatch.handlers())
