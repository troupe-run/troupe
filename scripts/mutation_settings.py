"""Mutation testing's settings and baselines, read strictly (spec: mutation-testing; lint-mutation
design D3, D6, D7).

scripts/mutation.json declares every number the runs judge by and what each repository mutates.
Each repository's quality-gates.toml holds, in its [mutation] table, the baseline each module's
score may not fall below. Both are read as closed schemas: an unknown key, a missing one or a value
out of range is an error naming it, never a default (a malformed input is an error, not a
fall-through).

Standard library only, Python 3.12+: it's delivered with the pull request report (design D9).
"""

import json
import re
from dataclasses import dataclass
from typing import Any

TOOLS = ("mutmut", "stryker")
SHA = re.compile(r"[0-9a-f]{40}")
MAX_JOB_MINUTES = 360
"""GitHub's limit on one job. A budget leaves 30 minutes of it for setup and the report."""
RUNNER_CPUS = 4
"""GitHub's ubuntu-latest runner for a public repository: more mutants at once than CPUs only
oversubscribes it (#337)."""


class SettingsError(Exception):
    """The settings or a mutation table isn't well formed."""


@dataclass(frozen=True)
class Unit:
    """One mutmut run: a package's source and the tests that exercise it."""

    name: str
    source: str
    tests: str
    also_copy: tuple[str, ...] = ()  # what the tests read beside the source, copied in with it
    deselect: tuple[tuple[str, str], ...] = ()  # (test node id, why mutmut's hooks can't run it)


@dataclass(frozen=True)
class Repository:
    name: str
    tool: str
    units: tuple[Unit, ...] = ()  # mutmut
    mutate: tuple[str, ...] = ()  # stryker: globs of files to mutate
    tests: str = ""  # stryker: the unit tests' directory


@dataclass(frozen=True)
class Settings:
    threshold: float
    tolerance: float
    min_mutants: int
    budget_minutes: int
    pr_budget_minutes: int
    max_new_issues: int
    max_children: int
    """How many mutants mutmut runs at once (#337: four starved the hosted runner)."""
    mutant_memory_mb: int | None
    """The address space each mutant's test process may use, or None for no cap (#366). A runaway
    mutant then fails on its own instead of taking the run's cgroup down. Set from a measured run's
    peaks, never by arithmetic: it caps virtual size, which runs well above resident size."""
    full_refresh_days: int
    """How old a unit's kept mutmut state may grow before the scheduled run discards it and fills
    afresh, clearing what incremental runs can't see: edited tests, changed callees (#378)."""
    tools: dict[str, str]
    repositories: dict[str, Repository]


@dataclass(frozen=True)
class Baseline:
    score: float
    mutants: int
    judged_at: str


SETTINGS_KEYS = {
    "threshold",
    "tolerance",
    "min_mutants",
    "budget_minutes",
    "pr_budget_minutes",
    "max_new_issues",
    "max_children",
    "mutant_memory_mb",
    "full_refresh_days",
    "tools",
    "repositories",
}


def closed(
    value: object, keys: set[str], where: str, required: set[str] | None = None
) -> dict[str, Any]:
    """`value` as an object holding only `keys`, and every key in `required` (all by default)."""
    if not isinstance(value, dict):
        raise SettingsError(f"{where} isn't an object")
    for key in sorted(set(value) - keys):
        raise SettingsError(f"{where} has the key {key!r}, which isn't one of {sorted(keys)}")
    for key in sorted((keys if required is None else required) - set(value)):
        raise SettingsError(f"{where} has no {key!r}")
    return value


def number(value: object, where: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not low <= value <= high:
        raise SettingsError(f"{where} is {value!r}; it must be a number from {low:g} to {high:g}")
    return float(value)


def whole(value: object, where: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise SettingsError(f"{where} is {value!r}; it must be a whole number from {low} to {high}")
    return value


MUTANT_MEMORY_MB = (256, 12_288)
"""From a quarter of a gigabyte to the run's whole cgroup (MemoryMax 12G, #345)."""


def optional_whole(value: object, where: str, low: int, high: int) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise SettingsError(
            f"{where} is {value!r}; it must be null or a whole number from {low} to {high}"
        )
    return value


def text(value: object, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise SettingsError(f"{where} is {value!r}; it must be a non-empty string")
    return value


def load_repository(name: str, value: object) -> Repository:
    where = f"repositories.{name}"
    raw = closed(value, {"tool", "units", "mutate", "tests"}, where, required={"tool"})
    tool = raw["tool"]
    if tool not in TOOLS:
        raise SettingsError(f"{where}.tool is {tool!r}; it must be one of {list(TOOLS)}")
    if tool == "mutmut":
        closed(raw, {"tool", "units"}, where)
        units = raw["units"]
        if not isinstance(units, list) or not units:
            raise SettingsError(f"{where}.units must be a non-empty list")
        loaded = []
        for index, unit in enumerate(units):
            at = f"{where}.units[{index}]"
            fields = closed(
                unit,
                {"name", "source", "tests", "also_copy", "deselect"},
                at,
                required={"name", "source", "tests"},
            )
            also_copy = fields.get("also_copy", [])
            if not isinstance(also_copy, list):
                raise SettingsError(f"{at}.also_copy must be a list of paths")
            deselect = fields.get("deselect", [])
            if not isinstance(deselect, list):
                raise SettingsError(f"{at}.deselect must be a list of {{test, why}}")
            skipped = []
            for number, entry in enumerate(deselect):
                item = closed(entry, {"test", "why"}, f"{at}.deselect[{number}]")
                test = text(item["test"], f"{at}.deselect[{number}].test")
                if not test.startswith(fields["tests"].rstrip("/") + "/") or "::" not in test:
                    raise SettingsError(
                        f"{at}.deselect[{number}].test is {test!r}; it must be a test node id "
                        f"under {fields['tests']}, such as {fields['tests']}/test_x.py::test_y"
                    )
                skipped.append((test, text(item["why"], f"{at}.deselect[{number}].why")))
            loaded.append(
                Unit(
                    name=text(fields["name"], f"{at}.name"),
                    source=text(fields["source"], f"{at}.source"),
                    tests=text(fields["tests"], f"{at}.tests"),
                    also_copy=tuple(text(path, f"{at}.also_copy") for path in also_copy),
                    deselect=tuple(skipped),
                )
            )
        return Repository(name, tool, units=tuple(loaded))
    closed(raw, {"tool", "mutate", "tests"}, where)
    mutate = raw["mutate"]
    if not isinstance(mutate, list) or not mutate:
        raise SettingsError(f"{where}.mutate must be a non-empty list of globs")
    globs = tuple(text(glob, f"{where}.mutate") for glob in mutate)
    return Repository(name, tool, mutate=globs, tests=text(raw["tests"], f"{where}.tests"))


def load_settings(source: str) -> Settings:
    """The settings in scripts/mutation.json, or SettingsError naming the first thing wrong."""
    try:
        loaded = json.loads(source)
    except json.JSONDecodeError as error:
        raise SettingsError(f"the settings aren't JSON: {error}") from None
    raw = closed(loaded, SETTINGS_KEYS, "the settings")
    tools = closed(raw["tools"], set(TOOLS), "tools")
    repositories = raw["repositories"]
    if not isinstance(repositories, dict) or not repositories:
        raise SettingsError("repositories must be a non-empty object")
    return Settings(
        threshold=number(raw["threshold"], "threshold", 0, 100),
        tolerance=number(raw["tolerance"], "tolerance", 0, 100),
        min_mutants=whole(raw["min_mutants"], "min_mutants", 1, 10_000),
        budget_minutes=whole(raw["budget_minutes"], "budget_minutes", 1, MAX_JOB_MINUTES - 30),
        pr_budget_minutes=whole(
            raw["pr_budget_minutes"], "pr_budget_minutes", 1, MAX_JOB_MINUTES - 30
        ),
        max_new_issues=whole(raw["max_new_issues"], "max_new_issues", 0, 100),
        max_children=whole(raw["max_children"], "max_children", 1, RUNNER_CPUS),
        full_refresh_days=whole(raw["full_refresh_days"], "full_refresh_days", 1, 365),
        mutant_memory_mb=optional_whole(
            raw["mutant_memory_mb"], "mutant_memory_mb", *MUTANT_MEMORY_MB
        ),
        tools={name: text(tools[name], f"tools.{name}") for name in TOOLS},
        repositories={name: load_repository(name, value) for name, value in repositories.items()},
    )


def load_baselines(table: dict[str, Any], path: str) -> dict[str, Baseline]:
    """The baselines in a repository's [mutation] table, as #322's loader hands it over (design D7).

    An absent table is no baselines. A table that is there but malformed is an error naming the
    file, the module and the key: it's never read as having none.
    """
    raw = closed(table, {"baselines"}, f"{path} [mutation]", required=set())
    baselines = raw.get("baselines", {})
    if not isinstance(baselines, dict):
        raise SettingsError(f"{path} [mutation] baselines isn't a table")
    loaded = {}
    for module, entry in baselines.items():
        where = f"{path} [mutation.baselines.{module!r}]"
        fields = closed(entry, {"score", "mutants", "judged_at"}, where)
        judged_at = fields["judged_at"]
        if not isinstance(judged_at, str) or not SHA.fullmatch(judged_at):
            raise SettingsError(f"{where} judged_at is {judged_at!r}; it must be a full commit SHA")
        loaded[module] = Baseline(
            score=number(fields["score"], f"{where} score", 0, 100),
            mutants=whole(fields["mutants"], f"{where} mutants", 1, 1_000_000),
            judged_at=judged_at,
        )
    return loaded


def read_mutation_table(source: str, path: str) -> dict[str, Any]:
    """The [mutation] table of a repository's quality-gates.toml, untouched, or {} without one.

    The file is read by quality_gates.py's own strict parser (#322), which hands this table over
    as it is; load_baselines validates it. Anything that parser refuses is an error naming the file.
    """
    import quality_gates

    try:
        config = quality_gates.parse_config(source)
    except quality_gates.GateError as error:
        raise SettingsError(f"{path}: {error}") from None
    return dict(config.mutation)
