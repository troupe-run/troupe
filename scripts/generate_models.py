"""Generate config's pydantic models from its JSON Schemas (spec: config; config-model design D11).

    uv run scripts/generate_models.py            rewrite the models
    uv run scripts/generate_models.py --check    change nothing; exit 1 if they're stale

The schemas in protocol/schemas/ are the source of truth (decision #7), and
packages/troupe/src/troupe/core/config/models.py is generated from them, never edited by hand. A
test runs ``--check``, so a schema can't change without its models.

The generator is given one bundled schema, not the files themselves, for two reasons. A config
schema refers to a few definitions in other files (a theatre path, a hash), and the generator
would otherwise follow each file's every reference, through schemas config doesn't use. And the
runner's options are an extension point (``$dynamicRef``), which only a runner's own options
schema fills, so the model types them as a JSON object, and troupe checks them against the
runner's schema separately (design D6). Each source schema becomes a top-level definition named
by ``SOURCES``, its own definitions are prefixed with that name, and each reference to another
file is replaced by a copy of what it refers to.
"""

import argparse
import json
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "protocol" / "schemas"
OUTPUT = ROOT / "packages" / "troupe" / "src" / "troupe" / "core" / "config" / "models.py"
COMMAND = "uv run scripts/generate_models.py"

SOURCES: dict[str, str] = {
    "Actor": "config/actor.schema.json",
    "ConfigChanged": "events/config-changed.schema.json",
}
"""Each schema the models are generated from, by the name of its model. The first is the bundle's
root; the others are its definitions."""

RECORDED_BY_THE_STORE = ("lineage", "timestamp")
"""Payload fields the event store adds to every event, which config's models leave out: config
builds a change, and the store records it with its lineage (spec: lineage)."""

RUNNER_OPTIONS = "#runnerOptions"
"""The extension point a runner's published options schema fills (spec: runner-protocol)."""

HEADER = f'''"""Config's models, generated from protocol/schemas/ by scripts/generate_models.py.

Don't edit this file: change the schemas, then run `{COMMAND}`.
Validate with ``parse``, which is strict (config-model design D11).
"""
'''

GENERATOR_ARGS = [
    "--input-file-type",
    "jsonschema",
    "--output-model-type",
    "pydantic_v2.BaseModel",
    "--base-class",
    "troupe.core.config.base.StrictModel",
    "--target-python-version",
    "3.12",
    "--use-annotated",
    "--field-constraints",
    "--enum-field-as-literal",
    "all",
    "--use-double-quotes",
    "--use-schema-description",
    "--use-field-description",
    "--disable-timestamp",
    "--formatters",
    "builtin",
]


class BundleError(Exception):
    """A schema the bundle can't be made from. The message names it and what's wrong."""


def _load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _pointer(document: dict[str, Any], fragment: str, where: str) -> Any:  # noqa: ANN401 - JSON
    node: Any = document
    for part in [p for p in fragment.lstrip("/").split("/") if p]:
        key = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or key not in node:
            msg = f"{where}: the reference #{fragment} doesn't resolve"
            raise BundleError(msg)
        node = node[key]
    return node


def _inline(node: Any, path: Path, prefix: str, seen: tuple[str, ...]) -> Any:  # noqa: ANN401
    """``node`` from the schema at ``path``, with references to other files copied in, and its own
    definitions' references renamed with ``prefix``. ``prefix`` is None inside a copy from another
    file, where every reference is copied in."""
    if isinstance(node, list):
        return [_inline(item, path, prefix, seen) for item in node]
    if not isinstance(node, dict):
        return node
    if node.get("$dynamicRef") == RUNNER_OPTIONS:
        rest = {k: v for k, v in node.items() if k != "$dynamicRef"}
        return {**rest, "type": "object"}
    ref = node.get("$ref")
    if isinstance(ref, str):
        target, _, fragment = ref.partition("#")
        rest = {k: _inline(v, path, prefix, seen) for k, v in node.items() if k != "$ref"}
        if not target and prefix:
            name = fragment.removeprefix("/$defs/")
            return {**rest, "$ref": f"#/$defs/{prefix}{name[0].upper()}{name[1:]}"}
        source = (path.parent / target).resolve() if target else path
        key = f"{source.as_posix()}#{fragment}"
        if key in seen:
            msg = f"{key}: a reference cycle in another file can't be copied in"
            raise BundleError(msg)
        copied = _inline(_pointer(_load(source), fragment, key), source, "", (*seen, key))
        return {**copied, **rest}
    return {k: _inline(v, path, prefix, seen) for k, v in node.items()}


def _leave_out_store_fields(schema: dict[str, Any]) -> None:
    properties = schema.get("properties", {})
    for key in RECORDED_BY_THE_STORE:
        properties.pop(key, None)
    if "required" in schema:
        schema["required"] = [k for k in schema["required"] if k not in RECORDED_BY_THE_STORE]


def bundle(schemas: Path = SCHEMAS) -> dict[str, Any]:
    """One schema holding every source, as the generator is given it: the first source at its
    root, and every other source, and every source's own definitions, in its ``$defs``."""
    root: dict[str, Any] = {}
    definitions: dict[str, Any] = {}
    for index, (name, relative) in enumerate(SOURCES.items()):
        path = (schemas / relative).resolve()
        schema = _load(path)
        own = schema.pop("$defs", {})
        own.pop(RUNNER_OPTIONS.removeprefix("#"), None)
        for key in ("$schema", "$id"):
            schema.pop(key, None)
        _leave_out_store_fields(schema)
        if index == 0:
            root = _inline(schema, path, name, ())
        else:
            definitions[name] = _inline(schema, path, name, ())
        for key, value in own.items():
            definitions[f"{name}{key[0].upper()}{key[1:]}"] = _inline(value, path, name, ())
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", **root, "$defs": definitions}


def _ruff(*args: str) -> list[str]:
    return [str(Path(sys.executable).parent / "ruff"), *args]


def generate(schemas: Path = SCHEMAS) -> str:
    """The models module's text, generated from ``schemas``."""
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "config.schema.json"
        target = Path(directory) / "models.py"
        source.write_text(json.dumps(bundle(schemas), indent=2), encoding="utf-8")
        generator = Path(sys.executable).parent / "datamodel-codegen"
        subprocess.run(
            [
                str(generator),
                *("--input", str(source), "--output", str(target)),
                *("--class-name", next(iter(SOURCES))),
                *GENERATOR_ARGS,
            ],
            check=True,
            capture_output=True,
        )
        body = target.read_text(encoding="utf-8").split("\n\n", 1)[1]
    text = HEADER + "\n" + body
    # Read through stdin as the output's own path, so the project's ruff settings apply.
    name = str(OUTPUT.relative_to(ROOT))
    for args in (("check", "--fix", "--exit-zero", "--quiet"), ("format",)):
        command = _ruff(*args, "--stdin-filename", name, "-")
        text = subprocess.run(
            command, input=text, check=True, capture_output=True, text=True, cwd=ROOT
        ).stdout
    return text


def main(argv: Sequence[str] | None = None, schemas: Path = SCHEMAS, output: Path = OUTPUT) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="change nothing; fail if stale")
    args = parser.parse_args(argv)
    text = generate(schemas)
    current = output.read_text(encoding="utf-8") if output.exists() else None
    if args.check:
        if current != text:
            relative = OUTPUT.relative_to(ROOT).as_posix()  # the file the fix regenerates
            print(
                f"generate_models: {relative} isn't what the schemas generate. "
                f"Fix: run `{COMMAND}`, then commit it.",
                file=sys.stderr,
            )
            return 1
        return 0
    if current != text:
        output.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
