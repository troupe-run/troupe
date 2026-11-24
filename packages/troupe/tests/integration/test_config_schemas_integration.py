"""Config's generated models are what its schemas generate: a schema changed without its models
fails the check naming the fix, and regenerating writes models the check then accepts (spec:
config; config-model design D2, D6, D11).

Its tests that stay in their own process are in unit/test_config_schemas.py."""

import io
import json
import shutil
from contextlib import redirect_stderr
from pathlib import Path

from config_schemas_shared import generator
from protocol_schemas import SCHEMAS

# Requirement: Config's types are generated from its schemas


def test_the_models_are_what_the_schemas_generate() -> None:
    err = io.StringIO()
    with redirect_stderr(err):
        code = generator.main(["--check"])
    assert code == 0, err.getvalue()


def test_a_schema_changed_without_its_models_fails_the_check_naming_the_fix(
    tmp_path: Path,
) -> None:
    schemas = tmp_path / "schemas"
    shutil.copytree(SCHEMAS, schemas)
    actor = schemas / "config" / "actor.schema.json"
    schema = json.loads(actor.read_text(encoding="utf-8"))
    schema["properties"]["note"] = {"description": "A new field.", "type": "string"}
    actor.write_text(json.dumps(schema, indent=2), encoding="utf-8")
    err = io.StringIO()
    with redirect_stderr(err):
        code = generator.main(["--check"], schemas=schemas)
    assert code == 1
    message = err.getvalue()
    assert "packages/troupe/src/troupe/core/config/models.py" in message
    assert "uv run scripts/generate_models.py" in message


def test_regenerating_writes_the_models_the_check_then_accepts(tmp_path: Path) -> None:
    output = tmp_path / "models.py"
    assert generator.main([], output=output) == 0
    assert generator.main(["--check"], output=output) == 0
    assert output.read_text(encoding="utf-8") == generator.generate()
