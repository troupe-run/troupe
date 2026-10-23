"""troupe carries the schemas it was built with, and reads a plugin's published schemas from the
installed plugin (spec: protocol, scripted-runner; config-model design D13, D17)."""

import importlib.util
import io
import json
import shutil
import subprocess
import sys
from contextlib import redirect_stderr
from pathlib import Path
from types import ModuleType

import pytest

from protocol_schemas import ROOT, SCHEMAS
from runtesting import INIT, OK, script
from troupe.core import interim, schemas
from troupe.core.errors import TroupeError


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "package_schemas", ROOT / "scripts" / "package_schemas.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


packager = _load()

# Requirement: troupe carries the schemas it was built with


def test_the_packages_copy_is_what_protocol_schemas_holds() -> None:
    err = io.StringIO()
    with redirect_stderr(err):
        code = packager.main(["--check"])
    assert code == 0, err.getvalue()


def test_a_schema_changed_without_its_copy_fails_the_check_naming_it_and_the_fix(
    tmp_path: Path,
) -> None:
    source, copy = tmp_path / "source", tmp_path / "copy"
    shutil.copytree(SCHEMAS, source)
    shutil.copytree(schemas.PROTOCOL, copy)
    actor = source / "config" / "actor.schema.json"
    actor.write_text(actor.read_text(encoding="utf-8").replace("Runner", "Runner!"), "utf-8")
    (copy / "client" / "stray.schema.json").write_text("{}", encoding="utf-8")
    err = io.StringIO()
    with redirect_stderr(err):
        code = packager.main(["--check"], source=source, copy=copy)
    assert code == 1
    message = err.getvalue()
    assert "config/actor.schema.json: differs" in message
    assert "client/stray.schema.json: not in protocol/schemas/" in message
    assert "uv run scripts/package_schemas.py" in message
    assert packager.main([], source=source, copy=copy) == 0
    assert packager.main(["--check"], source=source, copy=copy) == 0


def test_regenerating_and_checking_the_copy_leave_the_recorded_protocol_version_alone(
    tmp_path: Path,
) -> None:
    # version.json sits beside the copy but is written only by a protocol release
    # (protocol-own-release design D2), so the packager must neither delete nor report it.
    source, copy = tmp_path / "source", tmp_path / "copy"
    shutil.copytree(SCHEMAS, source)
    shutil.copytree(schemas.PROTOCOL, copy)
    record = copy / "version.json"
    before = record.read_bytes()
    (source / "error.schema.json").unlink()
    assert packager.main([], source=source, copy=copy) == 0
    assert record.read_bytes() == before
    err = io.StringIO()
    with redirect_stderr(err):
        code = packager.main(["--check"], source=source, copy=copy)
    assert code == 0, err.getvalue()


def test_every_protocol_schema_is_found_by_its_id_from_the_packages_copy() -> None:
    registry = schemas.registry()
    for path in sorted(SCHEMAS.rglob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        assert registry.contents(schema["$id"]) == schema


# Requirement: A plugin's published schemas are installed with it


def test_a_runners_options_schema_is_read_from_the_installed_runner_without_importing_it() -> None:
    probe = (
        "import sys\n"
        "from troupe.core import interim\n"
        "schema = interim.options_schema('scripted')\n"
        "assert schema['$id'].endswith('/runner-scripted/options.schema.json'), schema['$id']\n"
        "assert 'troupe_runner_scripted' not in sys.modules\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=False, timeout=60
    )
    assert result.returncode == 0, result.stderr


def test_options_are_checked_against_the_runners_schema_and_the_contract_it_refers_to() -> None:
    validator = interim.options_validator("scripted")
    assert validator.is_valid(script(INIT, OK))
    assert not validator.is_valid({**script(INIT, OK), "speed": 2})
    bad_event = {"event": {"type": "result", "status": "maybe", "message": "?"}}
    assert not validator.is_valid(script(INIT, bad_event))  # a status the contract doesn't define


def test_a_plugin_that_isnt_installed_is_refused_naming_it() -> None:
    with pytest.raises(TroupeError) as caught:
        schemas.plugin_schemas_directory("troupe_runner_nobody")
    assert caught.value.code == "schemas.plugin-missing"
    assert caught.value.details == {"package": "troupe_runner_nobody"}
