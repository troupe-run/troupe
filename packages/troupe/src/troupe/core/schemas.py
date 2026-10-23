"""The one place core finds a schema (spec: protocol; config-model design D17).

troupe carries the schemas it was built with: ``troupe/protocol/`` in the package is a generated
copy of the repository's ``protocol/schemas/`` (``scripts/package_schemas.py``), so an installed
troupe never fetches one. Every schema is found by its ``$id``. A plugin's published schemas are
installed with it, in its package's ``schemas/`` directory, and are found without importing the
plugin (troupe never imports one): ``importlib.util.find_spec`` locates a top-level package
without running it.

Beside the copy, ``version.json`` records which protocol release the copy is. Only a protocol
release pull request writes it (protocol-own-release design D2), and everything that reports or
writes the protocol version reads it through ``protocol_version`` (design D4).
"""

import importlib.util
import json
import re
from functools import cache
from pathlib import Path
from typing import Any

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from troupe.core import strict_json
from troupe.core.errors import TroupeError

PROTOCOL = Path(__file__).resolve().parents[1] / "protocol"
"""The schemas this troupe was built with."""

PATTERN = "*.schema.json"

PROTOCOL_RECORD = PROTOCOL / "version.json"
"""Which protocol release the copy is: ``{"version": "<major>.<minor>.<patch>"}``."""

_VERSION = re.compile(r"\A(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")


def _load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


@cache
def _protocol() -> tuple[dict[str, Any], ...]:
    return tuple(_load(path) for path in sorted(PROTOCOL.rglob(PATTERN)))


def plugin_schemas_directory(package: str) -> Path:
    """Where the installed plugin ``package`` keeps its published schemas, found without importing
    it. Refused when the plugin isn't installed, or ships none."""
    spec = importlib.util.find_spec(package)
    locations = list(spec.submodule_search_locations or []) if spec is not None else []
    for location in locations:
        directory = Path(location) / "schemas"
        if directory.is_dir():
            return directory
    raise TroupeError(
        "schemas.plugin-missing",
        problem=f"The plugin package {package!r} isn't installed, or ships no schemas/ directory.",
        fix="Install the plugin (uv sync, in a checkout of troupe). A plugin publishes its schemas "
        "in its package's schemas/ directory, installed with it.",
        details={"package": package},
    )


@cache
def _plugin(package: str) -> tuple[dict[str, Any], ...]:
    directory = plugin_schemas_directory(package)
    return tuple(_load(path) for path in sorted(directory.glob(PATTERN)))


def plugin_schema(package: str, name: str) -> dict[str, Any]:
    """The installed plugin ``package``'s published schema ``name`` (such as
    ``options.schema.json``)."""
    path = plugin_schemas_directory(package) / name
    if not path.is_file():
        raise TroupeError(
            "schemas.plugin-missing",
            problem=f"The plugin package {package!r} publishes no {name}.",
            fix="A runner publishes options.schema.json and errors.schema.json in its package's "
            "schemas/ directory (contributing/runners.md).",
            details={"package": package},
        )
    return _load(path)


def registry(*plugins: str) -> Registry[Any]:
    """Every schema troupe carries, and each named plugin's, by ``$id``."""
    schemas = [*_protocol(), *(schema for package in plugins for schema in _plugin(package))]
    return Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema, default_specification=DRAFT202012))
        for schema in schemas
    )


def validator(uri: str, *plugins: str) -> jsonschema.Draft202012Validator:
    """A validator for the schema at ``uri`` (an ``$id``, optionally with a fragment), which may
    refer to any schema troupe carries or the named plugins publish."""
    return jsonschema.Draft202012Validator({"$ref": uri}, registry=registry(*plugins))


def protocol_version() -> str:
    """The protocol version this troupe carries, as its record says. A record that is missing or
    holds anything but a version is refused, never read as a default (spec: protocol)."""
    path = PROTOCOL_RECORD
    try:
        record = strict_json.loads(path.read_bytes())
    except FileNotFoundError:
        found = "is missing"
    except (OSError, strict_json.StrictJSONError) as error:
        found = f"isn't readable JSON ({error})"
    else:
        only_a_version = isinstance(record, dict) and set(record) == {"version"}
        version = record.get("version") if isinstance(record, dict) and only_a_version else None
        if isinstance(version, str) and _VERSION.match(version):
            return version
        found = f"holds {strict_json.dumps(record)}"
    raise TroupeError(
        "schemas.protocol-version-invalid",
        problem=f"troupe's record of the protocol version it carries {found}. It must hold only "
        '{"version": "<major>.<minor>.<patch>"}, such as 0.2.0.',
        fix="Reinstall troupe. In a checkout of troupe, restore the file with "
        "`git restore packages/troupe/src/troupe/protocol/version.json`: only a protocol release "
        "pull request changes it.",
        path=str(path),
    )


def protocol_major() -> int:
    """The major version of the protocol this troupe carries: the troupe.run path that config files
    name their schemas by (design D7)."""
    return int(protocol_version().split(".", 1)[0])
