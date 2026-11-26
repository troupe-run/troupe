"""troupe init, and troupe init --audition, in the core (spec: cli, config, client-protocol;
init-and-audition design D1, D2, D6, D8).

Its tests that start a process, open a socket or use a git theatre are in integration/test_init.py.
"""

from importlib.metadata import version

import pytest

from troupe.core import audition as auditions
from troupe.core import interim
from troupe.core.config.changes import apply, change
from troupe.core.config.kinds import check


def test_the_anthropic_audition_model_is_claude_haiku_5_5() -> None:
    # Claude's cheapest current model (anthropic-runner design D15); this pins the name only.
    assert auditions.ANTHROPIC_AUDITION_MODEL == "claude-haiku-5-5"


def test_the_scripted_init_event_reports_the_installed_runners_version() -> None:
    lead = auditions.audition("scripted").actor
    init_event = lead["options"]["script"]["steps"][0]["event"]
    assert init_event["runner"] == {
        "name": "scripted",
        "version": version("troupe-runner-scripted"),
    }


# Requirement: The audition's config is valid; every runner has one (design D6)


@pytest.mark.parametrize("runner", sorted(interim.RUNNERS))
def test_every_runner_troupe_knows_has_an_audition_whose_config_is_valid(runner: str) -> None:
    chosen = auditions.audition(runner)
    assert chosen.runner == runner
    check(apply({}, change({}, chosen.operations())))


def test_no_runner_named_means_claude_code() -> None:
    assert auditions.audition(None).runner == "claude-code"


# Requirement: Every audition's actor waits for a person (spec: config; manual-gates decision 8)


@pytest.mark.parametrize("runner", sorted(interim.RUNNERS))
def test_every_auditions_actor_waits_at_a_gate_for_director(runner: str) -> None:
    assert auditions.audition(runner).actor["approvers"] == ["director"]
