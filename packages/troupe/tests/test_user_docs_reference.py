"""The user docs' generated regions match their sources, and regenerating them touches nothing else
(spec: user-docs; user-docs design D3)."""

import argparse
import importlib.util
import io
import json
import shutil
from contextlib import redirect_stderr
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from troupe.cli import COMMANDS
from troupe.cli.parser import Command
from troupe.core.exit_codes import ExitCode

pytestmark = pytest.mark.docs  # reads docs/ (scripts/check-paths.toml)

ROOT = Path(__file__).resolve().parents[3]
PAGES = ("cli.md", "events.md", "config-schema.md")
EXIT_CODES = "packages/troupe/src/troupe/core/exit_codes.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "docs_reference", ROOT / "scripts" / "docs_reference.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


reference = _load()


@pytest.fixture
def copy(tmp_path: Path) -> Path:
    """A root with copies of the pages that hold regions, the exit codes and the schemas."""
    (tmp_path / "docs" / "prompt-book").mkdir(parents=True)
    for page in PAGES:
        shutil.copy(ROOT / "docs" / "prompt-book" / page, tmp_path / "docs" / "prompt-book" / page)
    (tmp_path / EXIT_CODES).parent.mkdir(parents=True)
    shutil.copy(ROOT / EXIT_CODES, tmp_path / EXIT_CODES)
    shutil.copytree(ROOT / "protocol" / "schemas", tmp_path / "protocol" / "schemas")
    return tmp_path


def sources(root: Path, **changes: object) -> Any:  # noqa: ANN401
    return replace(reference.Sources(root=root, protocol=root / "protocol" / "schemas"), **changes)


def check(root: Path, **changes: object) -> tuple[int, str]:
    err = io.StringIO()
    with redirect_stderr(err):
        code = reference.main(["--check"], sources=sources(root, **changes))
    return code, err.getvalue()


# The docs as they are.


def test_every_generated_region_matches_its_source() -> None:
    stale = reference.run(True, reference.Sources())
    assert stale == [], "Run `uv run scripts/docs_reference.py`, then commit the regenerated pages."


def test_the_events_page_lists_every_event_schema_with_every_field() -> None:
    page = (ROOT / "docs" / "prompt-book" / "events.md").read_text(encoding="utf-8")
    for path in sorted((ROOT / "protocol" / "schemas" / "events").glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        assert f"### {schema['title']}" in page
        for name in schema["properties"]:
            assert f"| `{name}` |" in page


def test_the_cli_page_lists_every_command_and_option() -> None:
    page = (ROOT / "docs" / "prompt-book" / "cli.md").read_text(encoding="utf-8")
    for command in COMMANDS:
        parser = argparse.ArgumentParser(add_help=False)
        command.configure(parser)
        assert f"### `troupe {command.name}`" in page
        for action in parser._actions:
            for name in action.option_strings:
                assert f"`{name}" in page


# Each spec scenario.


def _with_since(parser: argparse.ArgumentParser) -> None:
    next(command for command in COMMANDS if command.name == "status").configure(parser)
    parser.add_argument("--since", help="only runs started since this time")


def test_a_new_cli_option_fails_the_check_naming_the_page_region_and_command(copy: Path) -> None:
    commands = tuple(
        replace(command, configure=_with_since) if command.name == "status" else command
        for command in COMMANDS
    )
    code, err = check(copy, commands=commands)
    assert code == 1
    assert "docs_reference: docs/prompt-book/cli.md: cli is stale" in err
    assert "run `uv run scripts/docs_reference.py`" in err


def test_an_edit_inside_a_region_fails_until_regenerated_and_says_to_change_the_source(
    copy: Path,
) -> None:
    page = copy / "docs" / "prompt-book" / "events.md"
    page.write_text(
        page.read_text(encoding="utf-8").replace("Why, in the actor's words.", "Why, as told."),
        encoding="utf-8",
    )
    code, err = check(copy)
    assert code == 1
    assert "docs/prompt-book/events.md: events is stale" in err
    assert "change its source" in err
    assert "never the region" in err
    assert reference.main([], sources=sources(copy)) == 0
    assert check(copy) == (0, "")


def test_with_no_config_schema_the_region_says_so_and_a_new_schema_makes_it_stale(
    copy: Path,
) -> None:
    page = copy / "docs" / "prompt-book" / "config-schema.md"
    config = copy / "protocol" / "schemas" / "config"
    shutil.rmtree(config)
    assert reference.main([], sources=sources(copy)) == 0
    assert "There is no config schema yet" in page.read_text(encoding="utf-8")
    assert check(copy) == (0, "")
    config.mkdir()
    (config / "actor.schema.json").write_text(
        json.dumps(
            {
                "title": "Actor",
                "description": "An actor's config.",
                "type": "object",
                "additionalProperties": False,
                "required": ["runner"],
                "properties": {"runner": {"description": "The runner, by name.", "type": "string"}},
            }
        ),
        encoding="utf-8",
    )
    code, err = check(copy)
    assert code == 1
    assert "docs/prompt-book/config-schema.md: config is stale" in err
    assert reference.main([], sources=sources(copy)) == 0
    text = page.read_text(encoding="utf-8")
    assert "### Actor" in text
    assert "| `runner` | string | Yes | The runner, by name. |" in text
    assert "There is no config schema yet" not in text


# Regenerating touches only the regions.

PROSE_BEFORE = "---\ntitle: Config schema\n---\n\nIntro, with `code` and a | pipe.\n\n"
PROSE_AFTER = "\n\nClosing prose.\n"


def _stale_page() -> str:
    return (
        PROSE_BEFORE
        + "<!-- generated: config -->\nwhatever was here\n<!-- end generated: config -->"
        + PROSE_AFTER
    )


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_regenerating_keeps_the_prose_around_a_region_byte_for_byte(
    copy: Path, newline: str
) -> None:
    text = _stale_page().replace("\n", newline)
    result, stale = reference.regenerate(text, "prompt-book/config-schema.md", sources(copy))
    assert stale == ["config"]
    assert result.startswith(PROSE_BEFORE.replace("\n", newline))
    assert result.endswith(PROSE_AFTER.replace("\n", newline))
    assert "whatever was here" not in result
    if newline == "\r\n":
        assert "\n" not in result.replace("\r\n", "")


def test_lf_and_crlf_pages_regenerate_to_the_same_text(copy: Path) -> None:
    page = "prompt-book/config-schema.md"
    lf, _ = reference.regenerate(_stale_page(), page, sources(copy))
    crlf, _ = reference.regenerate(_stale_page().replace("\n", "\r\n"), page, sources(copy))
    assert crlf.replace("\r\n", "\n") == lf


def test_a_second_run_changes_nothing(copy: Path) -> None:
    page = copy / "docs" / "prompt-book" / "cli.md"
    page.write_text(
        page.read_text(encoding="utf-8").replace("Show the version", "x"), encoding="utf-8"
    )
    assert reference.run(False, sources(copy)) == ["docs/prompt-book/cli.md: cli"]
    before = page.read_bytes()
    assert reference.run(False, sources(copy)) == []
    assert page.read_bytes() == before


# What the generator refuses.


def test_a_page_missing_its_region_is_refused_naming_the_markers_to_add(copy: Path) -> None:
    page = copy / "docs" / "prompt-book" / "events.md"
    text = page.read_text(encoding="utf-8")
    start = text.index("<!-- generated: events")
    end = text.index("<!-- end generated: events -->") + len("<!-- end generated: events -->")
    page.write_text(text[:start] + text[end:], encoding="utf-8")
    code, err = check(copy)
    assert code == 2
    assert "prompt-book/events.md has no generated region `events`" in err
    assert "<!-- end generated: events -->" in err


def test_a_region_on_the_wrong_page_is_refused(copy: Path) -> None:
    page = copy / "docs" / "prompt-book" / "events.md"
    page.write_text(
        page.read_text(encoding="utf-8")
        + "\n<!-- generated: cli -->\n<!-- end generated: cli -->\n",
        encoding="utf-8",
    )
    code, err = check(copy)
    assert code == 2
    assert "has a generated region `cli` that isn't prompt-book/events.md's to hold" in err


def test_a_field_without_a_description_is_refused_naming_the_schema_and_field(copy: Path) -> None:
    path = copy / "protocol" / "schemas" / "events" / "run-reported.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    del schema["properties"]["seq"]["description"]
    path.write_text(json.dumps(schema), encoding="utf-8")
    code, err = check(copy)
    assert code == 2
    assert "schemas/events/run-reported.schema.json: the field `seq` has no description" in err


def test_an_exit_code_without_a_docstring_is_refused(copy: Path) -> None:
    path = copy / EXIT_CODES
    path.write_text(
        path.read_text(encoding="utf-8").replace('    """The command completed."""\n', ""),
        encoding="utf-8",
    )
    code, err = check(copy)
    assert code == 2
    assert "ExitCode.OK has no docstring" in err


def test_the_usage_line_shows_required_groups_and_optional_values() -> None:
    perform = next(command for command in COMMANDS if command.name == "perform")
    assert reference._usage(perform) == (
        "troupe perform <actor> --runner <runner> [--runner-options <file>] "
        "[--instructions <instructions>] (--expect <path> | --no-effect-check)"
    )


def test_a_command_is_rendered_from_its_definition_alone() -> None:
    def configure(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("thing", help="the thing")
        parser.add_argument("--many", action="append", metavar="X", help="one of many (repeatable)")

    command = Command("demo", "do a demo.", configure, lambda arguments, out, err: ExitCode.OK)
    text = reference.render_cli(reference.Sources(commands=(command,)))
    assert "### `troupe demo`\n\nDo a demo.\n" in text
    assert "troupe demo <thing> [--many <x>]" in text
    assert "| `<thing>` | Yes | The thing |" in text
    assert "| `--many <x>` | No | One of many. Repeatable |" in text
