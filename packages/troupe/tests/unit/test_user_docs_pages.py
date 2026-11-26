"""What single user docs pages say about troupe, checked against troupe (spec: user-docs; user-docs
design D6).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_user_docs_pages_integration.py."""

import dataclasses
import json
import re
import tomllib
from typing import get_args

import pytest

from troupe.core import defaults, interim, settings
from troupe.core.audition import (
    ANTHROPIC_AUDITION_LIMITS,
    ANTHROPIC_AUDITION_MODEL,
    MISTRALRS_AUDITION_LIMITS,
    OPENAI_AUDITION_LIMITS,
)
from troupe.core.client.messages import State
from troupe.core.policy import ALLOW_UNENFORCED_LOCAL_STAGE, Policy, env_name
from troupe.core.runs.aggregate import TOPICS
from user_docs_pages_shared import (
    ANTHROPIC,
    LOCAL,
    MISTRALRS,
    OPENAI,
    PAGE,
    ROOT,
    RUNTIMES_PAGE,
    blocks_in,
    section,
    sh_lines,
)
from userdocs import DOCS, pages, read

pytestmark = pytest.mark.docs  # reads docs/ (scripts/check-paths.toml)


def blocks(page: str) -> list[tuple[str, str, str]]:
    """Each fenced block in a page."""
    return blocks_in((DOCS / page).read_text(encoding="utf-8"))


def test_the_anthropic_section_states_the_auditions_model_and_limits_as_the_code_does() -> None:
    text = " ".join(section(PAGE, ANTHROPIC).split())
    limits = ANTHROPIC_AUDITION_LIMITS
    assert f"`{ANTHROPIC_AUDITION_MODEL}`" in text
    assert (
        f"a run stops after {limits['maxTurns']} requests, or once it has used "
        f"{limits['maxTotalTokens']:,} tokens" in text
    )
    assert "ANTHROPIC_API_KEY" in text


def test_the_mistralrs_section_states_the_auditions_limit_as_the_code_does() -> None:
    text = " ".join(section(PAGE, MISTRALRS).split())
    assert f"A run stops after {MISTRALRS_AUDITION_LIMITS['maxTurns']} requests" in text
    assert "--managed-python" in (DOCS / "opening-night" / "install.md").read_text(encoding="utf-8")


AUDITION_RUNNER = re.compile(r"^troupe init --audition(?: --runner (?P<runner>\S+))?$")


def test_the_first_run_page_has_a_path_for_every_runner_troupe_has() -> None:
    # Spec: user-docs, "The first run has a path for every runner". Each path auditions an actor
    # on its runner; one with no --runner auditions the default, claude-code.
    lines = sh_lines((DOCS / PAGE).read_text(encoding="utf-8"))
    shown = {
        match.group("runner") or "claude-code"
        for line in lines
        if (match := AUDITION_RUNNER.match(line))
    }
    missing = sorted(set(interim.RUNNERS) - shown)
    assert not missing, f"{PAGE} has no path for the runner(s) {', '.join(missing)}"


NAMED_RUNNER = re.compile(r"(?:--runner[ =]|\brunner=)(?P<runner>[a-z0-9][a-z0-9._-]*)")
INLINE_CODE = re.compile(r"`([^`\n]+)`")


def code_on_each_line(text: str) -> list[tuple[int, str]]:
    """Each line's code, by line number: the whole line inside a fenced block, else its inline code
    spans. Commands and config lines are code; prose that says "--runner says" isn't."""
    found, fenced = [], False
    for number, line in enumerate(text.splitlines(), 1):
        if line.startswith("```"):
            fenced = not fenced
        elif fenced:
            found.append((number, line))
        else:
            found.extend((number, span) for span in INLINE_CODE.findall(line))
    return found


def unknown_runners(text: str) -> list[tuple[int, str]]:
    """Each runner a page's text names in its code (``--runner x``, ``runner=x``) that troupe
    doesn't have, with its line number."""
    return [
        (number, match.group("runner"))
        for number, code in code_on_each_line(text)
        for match in NAMED_RUNNER.finditer(code)
        if match.group("runner") not in interim.RUNNERS
    ]


def test_no_page_offers_a_runner_troupe_doesnt_have() -> None:
    # Spec: user-docs, "No page offers a runner troupe doesn't have".
    found = [
        f"{path.relative_to(DOCS).as_posix()}:{number}: {runner}"
        for path in pages()
        for number, runner in unknown_runners(path.read_text(encoding="utf-8"))
    ]
    assert not found, f"runners troupe doesn't have ({', '.join(sorted(interim.RUNNERS))}): {found}"


def test_the_check_finds_a_removed_runner_but_not_prose_or_a_runner_troupe_has() -> None:
    # The check above, falsified: the removed LM Studio runner, in a command and in config, beside
    # prose that says "--runner" and a runner troupe has.
    text = (
        "Unless --runner says:\n\n```sh\ntroupe init --audition --runner lm-studio\n"
        "troupe init --audition --runner ollama\n```\n\nOr `actors.a.runner=lm-studio`.\n"
    )
    assert unknown_runners(text) == [(4, "lm-studio"), (8, "lm-studio")]


def test_the_openai_section_states_the_auditions_limits_as_the_code_does() -> None:
    text = section(PAGE, OPENAI)
    limits = OPENAI_AUDITION_LIMITS
    assert (
        f"a run stops after {limits['maxTurns']} requests, or once it has used "
        f"{limits['maxTotalTokens']:,} tokens" in " ".join(text.split())
    )
    assert "OPENAI_API_KEY" in text


def test_the_local_model_section_states_the_ollama_the_runner_requires() -> None:
    text = section(PAGE, LOCAL)
    assert "Ollama 0.12.6 or later" in text
    assert "16384 tokens" in text


RUNS = "the-company/performances-and-runs.md"


def test_the_runs_page_lists_exactly_the_states_a_run_can_be_in() -> None:
    rows = re.findall(r"^\| `([a-z-]+)` \|", section(RUNS, "A run's state"), re.MULTILINE)
    assert set(rows) == set(get_args(State))


def test_the_runs_page_lists_exactly_the_events_a_run_records() -> None:
    named = re.findall(
        r"^- \*\*`(Run\.[A-Za-z]+)`:", section(RUNS, "What a run records"), re.MULTILINE
    )
    assert {f"Run.{name.split('.')[-1]}" for name in TOPICS} == set(named)


def test_the_runs_page_gives_each_policy_settings_default_and_variable_as_the_code_does() -> None:
    policy = section(RUNS, "Policy")
    rows = dict(re.findall(r"^\| `([a-z_]+)` \| `([a-z]+)` \|", policy, re.MULTILINE))
    assert rows == _defaults(Policy)
    assert env_name(ALLOW_UNENFORCED_LOCAL_STAGE) in policy


def _defaults(seam: type) -> dict[str, str]:
    """Each setting a seam's dataclass reads, and its default as the docs write it."""
    return {
        field.name: str(getattr(defaults, field.name.upper())).lower()
        for field in dataclasses.fields(seam)
    }


def test_the_runs_page_gives_each_settings_default_and_variable_as_the_code_does() -> None:
    page = section(RUNS, "Settings")
    rows = dict(re.findall(r"^\| `([a-z_]+)` \| `([a-z]+)` \|", page, re.MULTILINE))
    assert rows == _defaults(settings.Settings)
    assert settings.env_name(settings.MARK_MERGES_RESOLVED) in page
    assert "`settings.invalid-value`" in page


# Lineage.


def test_every_field_the_lineage_page_describes_is_one_the_lineage_schema_defines() -> None:
    schema = json.loads((ROOT / "protocol/schemas/lineage.schema.json").read_text(encoding="utf-8"))
    named = re.findall(
        r"^- \*\*`([a-z]+)`:\*\*",
        section("the-company/lineage.md", "What lineage says"),
        re.MULTILINE,
    )
    assert set(named) == set(schema["properties"])


# Install.


def test_the_install_page_gives_the_python_versions_troupe_declares() -> None:
    declared = tomllib.loads((ROOT / "packages/troupe/pyproject.toml").read_text(encoding="utf-8"))
    bound = re.fullmatch(r">=3\.(\d+),<3\.(\d+)", declared["project"]["requires-python"])
    assert bound is not None
    low, high = int(bound.group(1)), int(bound.group(2)) - 1
    text = (DOCS / "opening-night/install.md").read_text(encoding="utf-8")
    assert f"Python 3.{low} to 3.{high}" in text


# Every page.


def test_no_page_is_still_planned() -> None:
    planned = [
        path.relative_to(DOCS).as_posix()
        for path in pages()
        if read(path).front["status"] == "planned"
    ]
    assert planned == []


def test_the_runtimes_page_gives_the_built_in_runtimes_as_the_code_does() -> None:
    text = section(RUNTIMES_PAGE, "The runtimes troupe knows")
    rows = re.findall(
        r"^\| `([a-z-]+)` \| `?(none: in-process|[^`]+)`? \| (?:`([A-Z_]+)`|none) "
        r"\| (?:`([a-z.-]+)`|none) \|$",
        text,
        re.M,
    )
    documented = {
        name: (endpoint, env or None, engine or None) for name, endpoint, env, engine in rows
    }
    built_in: dict[str, tuple[str, object, object]] = {}
    for name, runtime in defaults.RUNTIMES.items():
        credential = runtime.get("credential")
        env = credential.get("env") if isinstance(credential, dict) else None
        built_in[name] = (
            str(runtime.get("endpoint", "none: in-process")),
            env,
            runtime.get("engine"),
        )
    assert documented == built_in


def test_the_runtimes_page_gives_the_shortest_key_as_the_code_does() -> None:
    assert f"a key under {defaults.CREDENTIAL_MIN_BYTES} bytes is refused" in (
        DOCS / RUNTIMES_PAGE
    ).read_text(encoding="utf-8")


# Requirement: The first run answers its gate and says how to drop the wait (spec: user-docs)


def test_the_first_runs_keep_section_approves_names_reject_and_gives_no_accept() -> None:
    text = section(PAGE, "Keep it, or not")
    assert sh_lines(text) == ["troupe diff <run>", "troupe approve <run>"]
    assert "`troupe reject <run>`" in text
    assert "troupe accept" not in text


def test_the_first_run_says_clean_work_is_kept_without_asking_and_how_to_drop_the_wait() -> None:
    text = section(PAGE, "Keep clean work without asking")
    assert sh_lines(text) == ["troupe config unset actors.lead.approvers"]
    assert "troupe approves them itself" in text
