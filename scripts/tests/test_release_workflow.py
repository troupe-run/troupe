"""The release workflow pins the bundle after each release (spec: releases; release-each-package
design D6). A workflow can't import pin_bundle.py or read the release config, so these tests keep
its copies of the branch and the bot's identity the same as theirs, and pin what the job may do."""

import json
from typing import Any

import yaml
from conftest import REPO

import guard
import pin_bundle

WORKFLOW = ".github/workflows/release.yml"


def jobs() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load((REPO / WORKFLOW).read_text(encoding="utf-8"))
    found: dict[str, Any] = loaded["jobs"]
    return found


def step(job: str, name: str) -> dict[str, Any]:
    steps: list[dict[str, Any]] = jobs()[job]["steps"]
    [found] = [s for s in steps if s.get("name") == name]
    return found


def test_release_please_exposes_whether_it_released() -> None:
    job = jobs()["release-please"]
    assert job["outputs"]["releases_created"] == (
        "${{ steps.release-please.outputs.releases_created }}"
    )
    named = "Open or update the release pull request, or release a merged one"
    assert step("release-please", named)["id"] == "release-please"


def test_the_pins_move_only_after_a_release() -> None:
    job = jobs()["pin-bundle"]
    assert job["needs"] == "release-please"
    assert job["if"] == "${{ needs.release-please.outputs.releases_created == 'true' }}"


def test_the_job_runs_in_the_release_environment_with_only_contents_and_pull_requests() -> None:
    job = jobs()["pin-bundle"]
    assert job["environment"] == "release"
    token = step("pin-bundle", "Mint the release App's token")["with"]
    assert {k for k in token if k.startswith("permission-")} == {
        "permission-contents",
        "permission-pull-requests",
    }
    assert token["permission-contents"] == token["permission-pull-requests"] == "write"


def test_it_runs_the_pinning_step_and_opens_a_pull_request_only_when_a_pin_moved() -> None:
    moved = step("pin-bundle", "Move the pins")
    assert "uv run scripts/pin_bundle.py --message" in moved["run"]
    assert moved["id"] == "pin"
    assert step("pin-bundle", "Open or update the pinning pull request")["if"] == (
        "${{ steps.pin.outputs.moved == 'true' }}"
    )


def test_the_branch_is_pin_bundles_and_the_guard_exempts_it_by_name() -> None:
    env = step("pin-bundle", "Open or update the pinning pull request")["env"]
    assert env["BRANCH"] == pin_bundle.BRANCH
    assert pin_bundle.BRANCH.startswith(guard.RELEASE_BRANCH_PREFIX)
    assert guard.reserved_release_branch(pin_bundle.BRANCH, "troupe-run/troupe")


def test_it_commits_as_the_bot_the_config_signs_off_as() -> None:
    """DCO needs the author to match the message's sign-off, which pin_bundle.py takes from the
    config's signoff."""
    env = step("pin-bundle", "Open or update the pinning pull request")["env"]
    signoff = json.loads((REPO / "release-please-config.json").read_text(encoding="utf-8"))[
        "signoff"
    ]
    assert f"{env['BOT_NAME']} <{env['BOT_EMAIL']}>" == signoff


def test_the_token_isnt_left_in_the_checkout_while_the_script_runs() -> None:
    [checkout] = [
        s for s in jobs()["pin-bundle"]["steps"] if s.get("uses", "").startswith("actions/checkout")
    ]
    assert checkout["with"]["persist-credentials"] is False
