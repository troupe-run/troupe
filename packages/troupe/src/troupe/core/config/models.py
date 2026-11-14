"""Config's models, generated from protocol/schemas/ by scripts/generate_models.py.

Don't edit this file: change the schemas, then run `uv run scripts/generate_models.py`.
Validate with ``parse``, which is strict (config-model design D11).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import ConfigDict, Field, RootModel, StringConstraints

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


class WriteItem(RootModel[str]):
    model_config = ConfigDict(
        regex_engine="python-re",
    )
    root: Annotated[
        str,
        Field(
            min_length=1,
            pattern="^(?![\\s\\S]*[\\x00-\\x1f\\x7f])(?!\\.git(?:/|$))(?!\\.troupe(?:/|$))(?!\\.\\.?(?:/|$))(?:\\*\\*(?=/|$)|(?:(?!\\*\\*)[^/\\\\:\\x00-\\x1f\\x7f])+)(?:/(?!\\.\\.?(?:/|$))(?:\\*\\*(?=/|$)|(?:(?!\\*\\*)[^/\\\\:\\x00-\\x1f\\x7f])+))*$",
            title="Effect pattern",
        ),
    ]
    """
    A path pattern relative to the theatre's root, with / between its parts: * matches within one part, ** as a whole part matches any number of parts, ? matches one character, and anything else matches itself. Never absolute, never with .., \\, :, a control character, an empty part or ** inside a part, and never starting with .git or .troupe, which no effect can allow changing.
    """


class DeleteItem(RootModel[str]):
    model_config = ConfigDict(
        regex_engine="python-re",
    )
    root: Annotated[
        str,
        Field(
            min_length=1,
            pattern="^(?![\\s\\S]*[\\x00-\\x1f\\x7f])(?!\\.git(?:/|$))(?!\\.troupe(?:/|$))(?!\\.\\.?(?:/|$))(?:\\*\\*(?=/|$)|(?:(?!\\*\\*)[^/\\\\:\\x00-\\x1f\\x7f])+)(?:/(?!\\.\\.?(?:/|$))(?:\\*\\*(?=/|$)|(?:(?!\\*\\*)[^/\\\\:\\x00-\\x1f\\x7f])+))*$",
            title="Effect pattern",
        ),
    ]
    """
    A path pattern relative to the theatre's root, with / between its parts: * matches within one part, ** as a whole part matches any number of parts, ? matches one character, and anything else matches itself. Never absolute, never with .., \\, :, a control character, an empty part or ** inside a part, and never starting with .git or .troupe, which no effect can allow changing.
    """


class MoveItem(RootModel[str]):
    model_config = ConfigDict(
        regex_engine="python-re",
    )
    root: Annotated[
        str,
        Field(
            min_length=1,
            pattern="^(?![\\s\\S]*[\\x00-\\x1f\\x7f])(?!\\.git(?:/|$))(?!\\.troupe(?:/|$))(?!\\.\\.?(?:/|$))(?:\\*\\*(?=/|$)|(?:(?!\\*\\*)[^/\\\\:\\x00-\\x1f\\x7f])+)(?:/(?!\\.\\.?(?:/|$))(?:\\*\\*(?=/|$)|(?:(?!\\*\\*)[^/\\\\:\\x00-\\x1f\\x7f])+))*$",
            title="Effect pattern",
        ),
    ]
    """
    A path pattern relative to the theatre's root, with / between its parts: * matches within one part, ** as a whole part matches any number of parts, ? matches one character, and anything else matches itself. Never absolute, never with .., \\, :, a control character, an empty part or ** inside a part, and never starting with .git or .troupe, which no effect can allow changing.
    """


class Effects(StrictModel):
    """
    What this actor's runs may change: write, delete and move, each a list of patterns relative to the theatre's root. Absent declares nothing, so the actor is read-only. Every path in expect must match a write or move pattern. After each run, troupe audits every change in the workspace against it. Not enforcement: only a stage that enforces effects contains a run.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    write: Annotated[list[WriteItem] | None, Field(title="Write")] = None
    """
    Where a run may create or change files (Write and Edit).
    """
    delete: Annotated[list[DeleteItem] | None, Field(title="Delete")] = None
    """
    Where a run may remove files. Declared apart from write, because it's more destructive.
    """
    move: Annotated[list[MoveItem] | None, Field(title="Move")] = None
    """
    Where a run may move or rename files: both the source and the destination must match.
    """


class Actor(StrictModel):
    """
    One actor's config file, .troupe/actors/<name>.yaml. The file's name is the actor's name. Its character, when it has one, is the whole of .troupe/actors/<name>.md. troupe writes this file from the theatre's config events, and every field is set with troupe config set.
    """

    model_config = ConfigDict(
        extra="forbid",
        regex_engine="python-re",
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
    Files, relative to the theatre's root, that a run must create or change: each must exist after the run, and differ from before it, and each must match a write or move pattern in effects. A file named twice is checked once. An empty list means no file has to change; the run's changes are still audited against its effects. It has to be written.
    """
    effects: Annotated[Effects | None, Field(title="Effects")] = None
    """
    What this actor's runs may change: write, delete and move, each a list of patterns relative to the theatre's root. Absent declares nothing, so the actor is read-only. Every path in expect must match a write or move pattern. After each run, troupe audits every change in the workspace against it. Not enforcement: only a stage that enforces effects contains a run.
    """
    workspace: Annotated[Literal["worktree", "theatre"] | None, Field(title="Workspace")] = None
    """
    Where a run works. worktree, the default when absent: the run's own git worktree at HEAD, under .troupe/local/worktrees/, whose changes reach the theatre only through troupe accept. theatre: the theatre itself, so what the run writes lands among your files at once.
    """
    onContextFull: Annotated[
        Literal["fail", "compact"] | None, Field(title="When the context fills")
    ] = None
    """
    What this actor's runs do when their engine's context fills. fail, the default when absent: the run ends with reason context-length, and nothing it was told is lost. compact: the run compacts its conversation and carries on, which changes what the model sees; each compaction is recorded with the run's events. Policy can turn compaction on for every actor that doesn't say fail (TROUPE_POLICY_COMPACTION=all), or forbid it (none).
    """
    runtime: Annotated[str | None, Field(pattern="^[a-z][a-z0-9-]{0,63}$", title="Runtime")] = None
    """
    The runtime this actor's runs talk to, by name: one of troupe's built-in runtimes or one in config. Only for a runner that takes a runtime; required by one that needs it.
    """
    model: Annotated[
        str | None,
        Field(
            max_length=256,
            min_length=1,
            pattern="^(?![\\s\\S]*[\\x00-\\x1f\\x7f])[\\s\\S]+$",
            title="Model",
        ),
    ] = None
    """
    The model this actor's runs use, overriding its runtime's. The person's TROUPE_RUNTIME_<NAME>_MODEL overrides both. Only with a runtime.
    """


class Credential(StrictModel):
    """
    Where the runtime's credential comes from. Never the credential itself: config is committed, so it holds only a reference.
    """

    model_config = ConfigDict(
        extra="forbid",
        regex_engine="python-re",
    )
    env: Annotated[
        str,
        Field(
            max_length=256,
            pattern="^(?![Tt][Rr][Oo][Uu][Pp][Ee]_)(?![\\s\\S]*[\\x00-\\x1f\\x7f])[A-Za-z_][A-Za-z0-9_]*$",
            title="Environment variable",
        ),
    ]
    """
    The name of the environment variable that holds the credential, read from the person's environment when a run starts. It can't be one of troupe's own (TROUPE_...).
    """


class Prices(StrictModel):
    """
    What a model costs at a service, in US dollars per million tokens of each kind, named after the result's usage counters. A rate a price doesn't give is unknown, not zero: an estimate needs a rate for every kind of token the run used.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    input: Annotated[float, Field(ge=0.0)]
    """
    US dollars per million input tokens, cache reads and writes excluded.
    """
    output: Annotated[float, Field(ge=0.0)]
    """
    US dollars per million output tokens.
    """
    cacheRead: Annotated[float | None, Field(ge=0.0)] = None
    """
    US dollars per million input tokens read from the service's prompt cache.
    """
    cacheWrite: Annotated[float | None, Field(ge=0.0)] = None
    """
    US dollars per million input tokens written to the service's prompt cache.
    """


class Runtime(StrictModel):
    """
    One runtime's config file, .troupe/runtimes/<name>.yaml: a service a runner talks to. The file's name is the runtime's name. It holds only what the theatre's config sets: a built-in runtime's other fields are troupe's defaults, and the person's environment overrides any of them (TROUPE_RUNTIME_<NAME>_ENDPOINT, _MODEL, _CREDENTIAL_ENV). troupe writes this file from the theatre's config events, and every field is set with troupe config set.
    """

    model_config = ConfigDict(
        extra="forbid",
        regex_engine="python-re",
    )
    field_schema: Annotated[
        str | None,
        Field(
            alias="$schema",
            pattern="(^|/)config/runtime\\.schema\\.json$",
            title="Schema",
        ),
    ] = None
    """
    Where this file's schema is, so editors can check it. troupe writes it.
    """
    endpoint: Annotated[
        str | None,
        Field(
            max_length=2048,
            pattern="^(?![\\s\\S]*[\\x00-\\x20\\x7f])https?://(?:[A-Za-z0-9._~-]+|\\[[0-9A-Fa-f:.]+\\])(?::[0-9]{1,5})?(?:/[^?#\\\\]*)?$",
            title="Endpoint",
        ),
    ] = None
    """
    The base URL the runner's API is served under: http or https, a host and an optional port and path, with no user info, query or fragment. The runner adds its own paths. Required for a runtime that isn't built in, and refused for an in-process built-in (mistralrs), which loads its model in the runner's own process.
    """
    model: Annotated[
        str | None,
        Field(
            max_length=256,
            min_length=1,
            pattern="^(?![\\s\\S]*[\\x00-\\x1f\\x7f])[\\s\\S]+$",
            title="Model",
        ),
    ] = None
    """
    The model a run uses when its actor sets none, as the service names it.
    """
    credential: Annotated[Credential | None, Field(title="Credential")] = None
    """
    Where the runtime's credential comes from. Never the credential itself: config is committed, so it holds only a reference.
    """
    prices: Annotated[
        dict[
            Annotated[
                str,
                StringConstraints(
                    pattern=r"^(?![\s\S]*[\x00-\x1f\x7f])[\s\S]+$", min_length=1, max_length=256
                ),
            ],
            Prices,
        ]
        | None,
        Field(title="Prices"),
    ] = None
    """
    What each model costs at this service, by the model's name exactly as a run names it, in US dollars per million tokens. A runner whose service reports no cost estimates one from the run's model's price, marked as an estimate; a model with no price gets none. Set a rate for every kind of token the service's runs use, cacheRead and cacheWrite included (0 for a kind it doesn't charge for), or runs that use it get no estimate. In a config set path, a model's name that holds a dot goes in brackets: runtimes.openai.prices[gpt-4.1].
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
