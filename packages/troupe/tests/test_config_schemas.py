"""Config's schemas accept what they should, and its generated models accept exactly what the
schemas accept (spec: config; config-model design D2, D6, D11)."""

import copy
import importlib.util
import io
import json
import re
import shutil
from contextlib import redirect_stderr
from pathlib import Path
from types import ModuleType
from typing import Any

import jsonschema
import pytest
from hypothesis import example, given
from hypothesis import strategies as st
from pydantic import ValidationError

from event_schemas import HASH, LINEAGE, ULID
from protocol_schemas import PROTOCOL_BASE, ROOT, SCHEMAS, SCRIPTED, validator_for
from runtesting import INIT, OK, script
from troupe.core.config.base import StrictModel
from troupe.core.config.models import Actor, ConfigChanged


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "generate_models", ROOT / "scripts" / "generate_models.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


generator = _load()

ACTOR_URI = PROTOCOL_BASE + "config/actor.schema.json"
ACTOR = validator_for(ACTOR_URI, SCRIPTED)
RECORD = validator_for(PROTOCOL_BASE + "event-record.schema.json", SCRIPTED)

SCRIPT = script(INIT, OK)
ACTOR_FILE: dict[str, Any] = {
    "$schema": "https://troupe.run/protocol/0/config/actor.schema.json",
    "runner": "scripted",
    "options": SCRIPT,
    "expect": ["out/hello.txt"],
}

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


# Requirement: An actor is defined by its runner, options, effect check and character (the file)


def _changed(data: dict[str, Any], **changes: object) -> dict[str, Any]:
    result = copy.deepcopy(data)
    for key, value in changes.items():
        if value is ...:
            result.pop(key, None)
        else:
            result[key] = value
    return result


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(ACTOR_FILE, id="a whole actor file"),
        pytest.param(_changed(ACTOR_FILE, options=...), id="no options"),
        pytest.param(_changed(ACTOR_FILE, expect=[]), id="an explicit empty effect check"),
        pytest.param(_changed(ACTOR_FILE, **{"$schema": ...}), id="no schema key"),
    ],
)
def test_the_actor_schema_accepts(value: dict[str, Any]) -> None:
    ACTOR.validate(value)


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(_changed(ACTOR_FILE, runnr="scripted"), id="an unknown key"),
        pytest.param(_changed(ACTOR_FILE, expect=...), id="no effect check written"),
        pytest.param(_changed(ACTOR_FILE, runner=...), id="no runner"),
        pytest.param(_changed(ACTOR_FILE, expect=["/etc/passwd"]), id="an absolute path"),
        pytest.param(_changed(ACTOR_FILE, expect=["C:/x"]), id="a drive"),
        pytest.param(_changed(ACTOR_FILE, expect=["../elsewhere.txt"]), id="a path leaving it"),
        pytest.param(_changed(ACTOR_FILE, runner="Scripted"), id="a runner name that doesn't fit"),
        pytest.param(
            _changed(ACTOR_FILE, options={"script": SCRIPT["script"], "speed": 2}),
            id="an option the runner doesn't define",
        ),
        pytest.param(
            _changed(ACTOR_FILE, **{"$schema": "../local/schemas/config/other.schema.json"}),
            id="a schema path naming another kind",
        ),
    ],
)
def test_the_actor_schema_refuses(value: dict[str, Any]) -> None:
    assert not ACTOR.is_valid(value)


def test_without_a_runner_bound_only_empty_options_validate() -> None:
    unbound = validator_for(ACTOR_URI)
    assert unbound.is_valid(_changed(ACTOR_FILE, options={}))
    assert not unbound.is_valid(ACTOR_FILE)


# Requirement: A change entry holds the path, the old value's hash and the new value


def _record(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "format": 1,
        "id": HASH,
        "stream": "6c1e2a3b-0000-5000-8000-000000000001",
        "stream_type": "uuid",
        "version": 2,
        "topic": "troupe.core.config.aggregate:Config.Changed",
        "parents": [HASH],
        "state": {
            "lineage": LINEAGE,
            "timestamp": {"_type_": "datetime_iso", "_data_": "2026-10-21T03:04:05.678000+00:00"},
            **state,
        },
        "batch": {"id": ULID, "index": 0, "size": 1},
    }


CHANGE: dict[str, Any] = {
    "changes": [
        {"path": ["actors", "tester", "runner"], "before": HASH, "after": "claude-code"},
        {"path": ["actors", "tester", "expect"], "after": ["out/hello.txt"]},
        {"path": ["actors", "old"], "before": HASH},
        {"path": ["actors", "tester", "options", "script"], "after": [{"steps": []}]},
    ],
    "files": [{"path": "actors/tester.yaml", "hash": HASH}, {"path": "actors/old.yaml"}],
}


def _entry(**changes: object) -> dict[str, Any]:
    return {"changes": [_changed(CHANGE["changes"][0], **changes)], "files": []}


def test_a_config_change_record_validates_by_its_topic() -> None:
    RECORD.validate(_record(CHANGE))


@pytest.mark.parametrize(
    "state",
    [
        pytest.param(_entry(before=None), id="a null before"),
        pytest.param(_entry(after=None), id="a null after"),
        pytest.param(_entry(after={"model": "opus"}), id="an object after"),
        pytest.param(_entry(path=["actors", "", "runner"]), id="a path with an empty key"),
        pytest.param(_entry(path=[]), id="an empty path"),
        pytest.param(_entry(before="41ab"), id="a before that isn't a hash"),
        pytest.param(_entry(before=..., after=...), id="an entry that changes nothing"),
        pytest.param({"changes": [], "files": []}, id="no changes"),
        pytest.param(_entry(why="because"), id="an unknown entry field"),
        pytest.param({**CHANGE, "files": [{"path": "/etc/passwd"}]}, id="a file outside"),
    ],
)
def test_a_config_change_record_refuses(state: dict[str, Any]) -> None:
    assert not RECORD.is_valid(_record(state))


def test_a_config_change_held_as_opaque_bytes_is_refused() -> None:
    record = _record(CHANGE)
    del record["state"]
    record["state_b64"] = "e30="
    assert not RECORD.is_valid(record)


# Requirement: Config's types are generated from its schemas (types and schemas agree)

BUNDLE = generator.bundle()


def _bundled(name: str) -> jsonschema.Draft202012Validator:
    """The schema the generator was given for ``name``'s model, with its bundle's definitions."""
    schema = BUNDLE if name == "Actor" else {"$ref": f"#/$defs/{name}", "$defs": BUNDLE["$defs"]}
    return jsonschema.Draft202012Validator({**schema, "$defs": BUNDLE["$defs"]})


JSON = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False) | st.text(max_size=8),
    lambda inner: st.lists(inner, max_size=3) | st.dictionaries(st.text(max_size=5), inner),
    max_leaves=6,
)
NAMES = st.from_regex(re.compile(r"[a-z][a-z0-9-]{0,8}"), fullmatch=True)
PATHS = st.one_of(
    st.lists(st.from_regex(re.compile(r"[a-z0-9._-]{1,6}"), fullmatch=True), min_size=1, max_size=3)
    .map("/".join)
    .filter(lambda p: ".." not in p.split("/")),
    st.sampled_from(["/abs", "C:/x", "a\\b", "../x", "a/../b", "", "a\n", ".", "a/./b", "a/"]),
)
HASHES = st.one_of(
    st.binary(min_size=32, max_size=32).map(lambda b: "sha256:" + b.hex()),
    st.sampled_from(["sha256:", "sha256:AB" + "0" * 62, "md5:" + "0" * 32, HASH + "\n"]),
)
VALUES = st.one_of(
    st.text(max_size=8), st.integers(), st.floats(allow_nan=False), st.booleans(), st.lists(JSON)
)


def _near_miss(draw: st.DrawFn, data: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    """``data``, or ``data`` with one field dropped, replaced by any JSON, or a key added."""
    choice = draw(st.sampled_from(["as is", "drop", "replace", "add"]))
    result = dict(data)
    if choice == "drop" and keys:
        result.pop(draw(st.sampled_from(keys)), None)
    elif choice == "replace" and keys:
        result[draw(st.sampled_from(keys))] = draw(JSON)
    elif choice == "add":
        result[draw(st.text(min_size=1, max_size=6))] = draw(JSON)
    return result


@st.composite
def actors(draw: st.DrawFn) -> dict[str, Any]:
    data: dict[str, Any] = {
        "runner": draw(st.one_of(NAMES, st.text(max_size=6))),
        "expect": draw(st.lists(PATHS, max_size=3)),
    }
    if draw(st.booleans()):
        data["options"] = draw(st.dictionaries(st.text(max_size=5), JSON, max_size=3))
    if draw(st.booleans()):
        data["$schema"] = draw(
            st.sampled_from(["../local/schemas/config/actor.schema.json", "actor.json", ""])
        )
    return _near_miss(draw, data, list(data))


@st.composite
def entries(draw: st.DrawFn) -> dict[str, Any]:
    data: dict[str, Any] = {
        "path": draw(st.lists(st.text(max_size=5), max_size=4)),
    }
    if draw(st.booleans()):
        data["before"] = draw(HASHES)
    if draw(st.booleans()):
        data["after"] = draw(st.one_of(VALUES, JSON))
    return _near_miss(draw, data, list(data))


@st.composite
def changes(draw: st.DrawFn) -> dict[str, Any]:
    files = st.fixed_dictionaries({"path": PATHS}, optional={"hash": HASHES})
    data = {
        "changes": draw(st.lists(entries(), max_size=3)),
        "files": draw(st.lists(files, max_size=2)),
    }
    return _near_miss(draw, data, list(data))


def _accepts(model: type[StrictModel], value: object) -> bool:
    try:
        model.parse(value)
    except ValidationError:
        return False
    return True


def _value(after: object) -> dict[str, Any]:
    return {"changes": [{"path": ["a"], "after": after}], "files": []}


@given(actors())
@example({"runner": "scripted\n", "expect": []})
@example({"runner": "s" * 65, "expect": []})
@example({"runner": "scripted", "expect": ["a\n"]})
@example({"runner": "scripted", "expect": ["a\\b"]})
@example({"runner": "scripted", "expect": [], "options": {"a": None}})
def test_the_actor_model_accepts_exactly_what_its_schema_accepts(value: dict[str, Any]) -> None:
    assert _accepts(Actor, value) == _bundled("Actor").is_valid(value)


@given(changes())
@example(_value([{"a": None}]))
@example(_value([{"a": [None]}]))
@example(_value([{"a": {"b": None}}]))
@example(_value([None]))
@example(_value([1.5, True]))
@example(_value(True))
@example(_value(3))
@example(_value({"a": 1}))
def test_the_change_model_accepts_exactly_what_its_schema_accepts(value: dict[str, Any]) -> None:
    assert _accepts(ConfigChanged, value) == _bundled("ConfigChanged").is_valid(value)


@given(actors().filter(lambda value: "options" not in value))
def test_the_bundle_agrees_with_the_actor_schema_wherever_options_are_absent(
    value: dict[str, Any],
) -> None:
    assert _bundled("Actor").is_valid(value) == validator_for(ACTOR_URI).is_valid(value)
