"""A run's declaration, read from run start, and its normalised view (spec: plugin-sdk, "The SDK
reads the declaration from run start" and "Runners plug in their own way of applying the
declaration"; declared-effects design D7)."""

from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from typing import Any

import pytest

from troupe_plugin_sdk import runner as p
from troupe_plugin_sdk.declaration import (
    Declaration,
    EffectsTranslation,
    Mode,
    posix_absolute,
)
from troupe_plugin_sdk.effects import Effects
from troupe_plugin_sdk.tools import Tools

RUN = "0f8fad5b-d9cb-469f-a165-70867728950e"


def _start(effects: dict[str, Any]) -> dict[str, Any]:
    return {
        "runId": RUN,
        "direction": "go",
        "workspace": "/w/t",
        "options": {},
        "limits": {"eventMaxBytes": 65536},
        "effects": {"write": [], "delete": [], "move": [], **effects},
        "scratch": "/s/run",
    }


def test_a_run_start_with_write_declared_allows_writing_only_there() -> None:
    declaration = Declaration.from_run_start(
        p.RunStartParams.from_data(_start({"write": ["out/**"]}))
    )
    assert declaration.effects.allows("write", "out/a.txt")
    assert not declaration.effects.allows("write", "src/a.txt")
    assert not declaration.effects.allows("delete", "out/a.txt")
    assert not declaration.effects.allows("move", "out/a.txt")


def test_a_malformed_pattern_in_run_start_is_a_protocol_error_naming_the_effect() -> None:
    with pytest.raises(p.ProtocolError, match=r"delete: '\.\./x'"):
        p.RunStartParams.from_data(_start({"delete": ["../x"]}))


def test_a_pattern_on_windows_is_rooted_at_the_drive_in_lowercase() -> None:
    declaration = Declaration(
        Effects(write=("out/**",)), PureWindowsPath("C:\\work\\theatre"), PureWindowsPath("D:\\s")
    )
    assert declaration.absolute("write") == ("/c/work/theatre/out/**",)
    assert declaration.scratch_absolute() == "/d/s"


def test_a_pattern_on_posix_is_rooted_at_the_workspace() -> None:
    declaration = Declaration(Effects(delete=("drafts/*",)), PurePosixPath("/w/t"))
    assert declaration.absolute("delete") == ("/w/t/drafts/*",)
    assert declaration.absolute("write") == ()
    assert declaration.scratch_absolute() is None


@pytest.mark.parametrize(
    "path", [PurePosixPath("relative"), PureWindowsPath("\\\\server\\share\\x")]
)
def test_a_path_that_isnt_an_absolute_drive_path_is_refused(path: PurePath) -> None:
    with pytest.raises(ValueError, match=r"absolute|drive"):
        posix_absolute(path)


class _Rules:
    """A translation of the kind a runner plugs in: rules from the normalised view."""

    @property
    def mode(self) -> Mode:
        return "translated"

    def translate(self, declaration: Declaration) -> tuple[str, ...]:
        return tuple(f"allow-write {pattern}" for pattern in declaration.absolute("write"))


def test_two_runners_see_the_same_normalised_declaration(tmp_path: Path) -> None:
    (tmp_path / "w").mkdir()
    (tmp_path / "s").mkdir()
    declaration = Declaration(Effects(write=("out/**",)), tmp_path / "w", tmp_path / "s")
    rules: EffectsTranslation[tuple[str, ...]] = _Rules()
    root = posix_absolute(tmp_path / "w")
    assert rules.translate(declaration) == (f"allow-write {root}/out/**",)
    assert rules.mode == "translated"
    checked: EffectsTranslation[Tools] = Tools.for_declaration(declaration)
    tools = checked.translate(declaration)
    assert checked.mode == "checked"
    assert tools.effects == declaration.effects
    assert tools.workspace.root == (tmp_path / "w").resolve()
    assert tools.scratch == tmp_path / "s"
