"""Config's models, generated from protocol/schemas/ by scripts/generate_models.py.

Don't edit this file: change the schemas, then run `uv run scripts/generate_models.py`.
Validate with ``parse``, which is strict (config-model design D11).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import ConfigDict, Field, RootModel

from troupe.core.config.base import StrictModel


class ExpectItem(RootModel[str]):
    model_config = ConfigDict(
        regex_engine="python-re",
    )
    root: Annotated[
        str,
        Field(
            min_length=1,
            pattern="^(?![/\\\\])(?![A-Za-z]:)(?!.*\\\\)(?!(.*/)?\\.\\.(/|$)).+$",
            title="Theatre-relative path",
        ),
    ]
    """
    A path relative to the theatre's root, with / separators. Never a host path, a drive, or a path that leaves the theatre with ..
    """


class Actor(StrictModel):
    """
    One actor's config file, .troupe/actors/<name>.yaml. The file's name is the actor's name. Its character, when it has one, is the whole of .troupe/actors/<name>.md. troupe writes this file from the theatre's config events, and every field is set with troupe config set.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    field_schema: Annotated[
        str | None,
        Field(
            alias="$schema",
            pattern="(^|/)config/actor\\.schema\\.json$",
            title="Schema",
        ),
    ] = None
    """
    Where this file's schema is, relative to the file, so editors can check it. troupe writes it.
    """
    runner: Annotated[str, Field(pattern="^[a-z][a-z0-9-]{0,63}$", title="Runner")]
    """
    The runner that runs this actor, by name.
    """
    options: Annotated[dict[str, Any] | None, Field(title="Runner options")] = None
    """
    The runner's own options, passed to it unchanged. Absent means {}. An extension point: the runner's published options schema fills it, and without one only {} validates.
    """
    expect: Annotated[list[ExpectItem], Field(title="Effect check")]
    """
    Files, relative to the theatre's root, that a run must create or change: each must exist after the run, and differ from before it. A file named twice is checked once. An empty list means no effect check, and has to be written.
    """
    workspace: Annotated[Literal["worktree", "theatre"] | None, Field(title="Workspace")] = None
    """
    Where a run works. worktree, the default when absent: the run's own git worktree at HEAD, under .troupe/local/worktrees/, whose changes reach the theatre only through troupe accept. theatre: the theatre itself, so what the run writes lands among your files at once.
    """


class PathItem(RootModel[str]):
    root: Annotated[str, Field(min_length=1)]


class ConfigChangedJson(
    RootModel[Union[str, float, bool, list["ConfigChangedJson"], dict[str, "ConfigChangedJson"]]]
):
    root: Annotated[
        Union[str, float, bool, list[ConfigChangedJson], dict[str, ConfigChangedJson]],
        Field(title="JSON value"),
    ]
    """
    Any JSON value but null.
    """


class ConfigChangedFile(StrictModel):
    """
    A config file, relative to .troupe/, and the hash of the bytes troupe wrote. A missing hash means the change removed it.
    """

    model_config = ConfigDict(
        extra="forbid",
        regex_engine="python-re",
    )
    path: Annotated[
        str,
        Field(
            min_length=1,
            pattern="^(?![/\\\\])(?![A-Za-z]:)(?!.*\\\\)(?!(.*/)?\\.\\.(/|$)).+$",
            title="Theatre-relative path",
        ),
    ]
    """
    The file, relative to the theatre's .troupe/ directory, with / separators.
    """
    hash: Annotated[str | None, Field(pattern="^sha256:[0-9a-f]{64}$", title="Content hash")] = None
    """
    The SHA-256 of the file's bytes as troupe wrote them.
    """


class ConfigChangedValue(RootModel[str | float | bool | list[ConfigChangedJson]]):
    """
    A config value: a string, number, boolean or list. A list's items may be any JSON value but null.
    """

    root: Annotated[str | float | bool | list[ConfigChangedJson], Field(title="Value")]
    """
    A config value: a string, number, boolean or list. A list's items may be any JSON value but null.
    """


class ConfigChangedEntry1(StrictModel):
    """
    One value's change. A missing before means the value didn't exist; a missing after means it was removed. An entry for a group (an object) only ever removes it.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    path: Annotated[list[PathItem], Field(min_length=1)]
    """
    The value's logical path, as keys from the top of config, such as ["actors", "tester", "runner"].
    """
    before: Annotated[str, Field(pattern="^sha256:[0-9a-f]{64}$", title="Content hash")]
    """
    The SHA-256 of the old value's canonical JSON (sorted keys, no spaces, UTF-8), the same form event ids hash. For a group, the hash of the whole group.
    """
    after: ConfigChangedValue | None = None
    """
    The new value. Never an object: an object is a group of values, each changed by its own entry.
    """


class ConfigChangedEntry2(StrictModel):
    """
    One value's change. A missing before means the value didn't exist; a missing after means it was removed. An entry for a group (an object) only ever removes it.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    path: Annotated[list[PathItem], Field(min_length=1)]
    """
    The value's logical path, as keys from the top of config, such as ["actors", "tester", "runner"].
    """
    before: Annotated[str | None, Field(pattern="^sha256:[0-9a-f]{64}$", title="Content hash")] = (
        None
    )
    """
    The SHA-256 of the old value's canonical JSON (sorted keys, no spaces, UTF-8), the same form event ids hash. For a group, the hash of the whole group.
    """
    after: ConfigChangedValue
    """
    The new value. Never an object: an object is a group of values, each changed by its own entry.
    """


class ConfigChangedEntry(RootModel[ConfigChangedEntry1 | ConfigChangedEntry2]):
    root: Annotated[ConfigChangedEntry1 | ConfigChangedEntry2, Field(title="Change entry")]
    """
    One value's change. A missing before means the value didn't exist; a missing after means it was removed. An entry for a group (an object) only ever removes it.
    """


class ConfigChanged(StrictModel):
    """
    The payload of one config change (topic troupe.core.config.aggregate:Config.Changed): every value one command changed, and every config file it wrote or removed. One command records exactly one. Field names are as recorded.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    changes: Annotated[list[ConfigChangedEntry], Field(min_length=1)]
    """
    Each value the command changed, at most once each. A change that would change nothing isn't recorded.
    """
    files: list[ConfigChangedFile]
    """
    Each config file the change wrote or removed, so troupe can tell its own files from a person's.
    """


ConfigChangedJson.model_rebuild()
