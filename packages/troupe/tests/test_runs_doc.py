"""contributing/runs.md describes runs, stages and policy as the code defines them."""

import re
from collections.abc import Iterable
from pathlib import Path
from typing import get_args

import pytest

from troupe.core import defaults
from troupe.core.client.messages import State
from troupe.core.errors import CODES
from troupe.core.notices import CODES as NOTICE_CODES
from troupe.core.policy import ALLOW_UNENFORCED_LOCAL_STAGE, env_name
from troupe.core.runs.aggregate import TOPICS

pytestmark = pytest.mark.docs  # reads docs/ (scripts/check-paths.toml)

DOC = Path(__file__).resolve().parents[3] / "contributing" / "runs.md"
TEXT = DOC.read_text(encoding="utf-8")
RUNNERS_DOC = (DOC.parent / "runners.md").read_text(encoding="utf-8")
PREFIXES = {"client", "perform", "policy", "stage", "theatre", "workspace"}
"""Codes only runs use. run. and runner. codes are shared with the run host, whose own are in
contributing/runners.md; every other one is documented here."""


def _section(heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", TEXT, re.M | re.S)
    assert match is not None, f"contributing/runs.md has no section {heading!r}"
    return match.group(1)


def test_the_policy_table_gives_each_settings_default_as_the_code_does() -> None:
    rows = dict(re.findall(r"^\| `([a-z_]+)` \| `([a-z]+)` \|", _section("Policy"), re.M))
    assert rows == {
        ALLOW_UNENFORCED_LOCAL_STAGE: str(defaults.ALLOW_UNENFORCED_LOCAL_STAGE).lower()
    }


def test_the_policy_section_names_the_variable_the_code_reads() -> None:
    assert env_name(ALLOW_UNENFORCED_LOCAL_STAGE) in _section("Policy")


def test_every_relative_link_resolves() -> None:
    for target in re.findall(r"\]\(((?:\.\./|[a-z])[^)#:]*)(?:#[^)]*)?\)", TEXT):
        assert (DOC.parent / target).exists(), target


def test_the_stages_section_names_the_local_stages_refusal_and_its_setting() -> None:
    section = _section("Stages")
    assert "`stage.effects-unenforced`" in section
    assert f"`{ALLOW_UNENFORCED_LOCAL_STAGE}`" in section
    assert "including an actor that declares none" in section


def _run_host_codes() -> set[str]:
    return set(re.findall(r"`([a-z]+\.[a-z.-]+)`", RUNNERS_DOC))


def _ours(codes: Iterable[str]) -> set[str]:
    return {
        code
        for code in codes
        if code.split(".")[0] in PREFIXES
        or (code.split(".")[0] in {"run", "runner"} and code not in _run_host_codes())
    }


def test_the_tables_list_exactly_the_errors_and_notices_runs_add() -> None:
    listed = set(re.findall(r"^\| `([a-z-]+\.[a-z.-]+)` \|", _section("Notices and errors"), re.M))
    assert listed == _ours(CODES) | _ours(NOTICE_CODES)


def test_the_states_table_lists_exactly_the_states_a_run_can_be_in() -> None:
    section = TEXT.split("### States", 1)[1].split("\n## ", 1)[0]
    assert set(re.findall(r"^\| `([a-z-]+)` \|", section, re.M)) == set(get_args(State))


def test_the_run_events_table_lists_exactly_the_topics_a_run_records() -> None:
    section = TEXT.split("### Run events", 1)[1].split("\n### ", 1)[0]
    listed = set(re.findall(r"^\| `(Run\.[A-Za-z]+)` \|", section, re.M))
    assert listed == {topic.split(":")[1] for topic in TOPICS}
