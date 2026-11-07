"""Config and an actor whose runner troupe knows but isn't installed here (spec: config, "A change
to an actor on a runner that isn't installed is refused" and "Another actor's uninstalled runner
doesn't block config"; runner-extras design D7).

The runner is ``lm-studio``, an extra's runner as #291 will add. While it's "installed" its entry
starts the scripted runner, so its options are the scripted runner's; ``uninstall`` points it at a
package that doesn't exist, as an install without ``troupe-run[lm-studio]`` would be."""

import dataclasses
from pathlib import Path

import pytest

from configtesting import TESTER, branched, config_of, merged_feature, on, set_config
from gitrepo import Repo
from runtesting import theatre
from storetesting import git_service
from troupe.core import interim
from troupe.core.config import aggregate, kinds
from troupe.core.config.changes import UNSET
from troupe.core.errors import TroupeError

LEAD = ["actors", "lead"]
ON_LM_STUDIO = {**TESTER, "runner": "lm-studio"}


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return theatre(tmp_path)


@pytest.fixture
def lm_studio(monkeypatch: pytest.MonkeyPatch) -> None:
    """The lm-studio runner, installed for now."""
    entry = dataclasses.replace(interim.RUNNERS["scripted"], in_extra=True)
    monkeypatch.setitem(interim.RUNNERS, "lm-studio", entry)


def uninstall(monkeypatch: pytest.MonkeyPatch) -> None:
    gone = dataclasses.replace(interim.RUNNERS["lm-studio"], package="troupe_runner_lm_studio")
    monkeypatch.setitem(interim.RUNNERS, "lm-studio", gone)


def events(repo: Repo) -> int:
    return len(git_service(repo).history(aggregate.STREAM))


def refused(caught: pytest.ExceptionInfo[TroupeError], path: str) -> None:
    assert caught.value.code == "runner.not-installed"
    # The actor's config path is in the details, as config.invalid's is: the error's own path is a
    # file's (error.schema.json; review of #338).
    assert caught.value.details["path"] == path.split(".")
    assert caught.value.path is None
    assert caught.value.problem.startswith(f"{path}: ")
    assert caught.value.details["extra"] == "lm-studio"
    assert "troupe-run[lm-studio]" in caught.value.fix


@pytest.mark.usefixtures("lm_studio")
def test_defining_an_actor_on_an_uninstalled_runner_is_refused_and_records_nothing(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    uninstall(monkeypatch)
    with pytest.raises(TroupeError) as caught:
        set_config(repo, [(LEAD, ON_LM_STUDIO)])
    refused(caught, "actors.lead.runner")
    assert events(repo) == 0


@pytest.mark.usefixtures("lm_studio")
def test_changing_an_existing_actors_character_on_an_uninstalled_runner_is_refused(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_config(repo, [(LEAD, ON_LM_STUDIO)])
    uninstall(monkeypatch)
    with pytest.raises(TroupeError) as caught:
        set_config(repo, [([*LEAD, "character"], "You lead.")])
    refused(caught, "actors.lead.runner")
    assert events(repo) == 1


@pytest.mark.usefixtures("lm_studio")
def test_removing_an_actor_on_an_uninstalled_runner_is_recorded(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_config(repo, [(LEAD, ON_LM_STUDIO)])
    uninstall(monkeypatch)
    set_config(repo, [(LEAD, UNSET)])
    assert "lead" not in config_of(repo).config.get("actors", {})


@pytest.mark.usefixtures("lm_studio")
def test_moving_an_actor_to_an_installed_runner_checks_it_against_that_runner(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_config(repo, [(LEAD, ON_LM_STUDIO)])
    uninstall(monkeypatch)
    with pytest.raises(TroupeError) as caught:
        set_config(repo, [([*LEAD, "runner"], "scripted"), ([*LEAD, "options", "speed"], 2)])
    assert caught.value.code == "config.invalid"
    assert "scripted runner's options schema" in caught.value.problem
    set_config(repo, [([*LEAD, "runner"], "scripted")])
    assert config_of(repo).config["actors"]["lead"]["runner"] == "scripted"


@pytest.mark.usefixtures("lm_studio")
def test_changing_another_actor_is_recorded(repo: Repo, monkeypatch: pytest.MonkeyPatch) -> None:
    set_config(repo, [(LEAD, ON_LM_STUDIO)])
    uninstall(monkeypatch)
    set_config(repo, [(["actors", "tester"], TESTER)])
    assert config_of(repo).config["actors"]["tester"]["runner"] == "scripted"


@pytest.mark.usefixtures("lm_studio")
def test_a_merge_without_the_runner_leaves_its_options_unchecked_and_performing_it_is_refused(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    branched(repo, [(LEAD, ON_LM_STUDIO), (["actors", "tester"], TESTER)])
    on(repo, "feature", [([*LEAD, "options"], {"script": {"steps": []}})])
    on(repo, "main", [(["actors", "tester", "character"], "You test.")])
    uninstall(monkeypatch)
    merged = merged_feature(repo)
    assert merged.conflicts == ()
    with pytest.raises(TroupeError) as caught:
        kinds.check_actor("lead", merged.config)  # what perform checks for the actor it runs
    refused(caught, "actors.lead.runner")


@pytest.mark.usefixtures("lm_studio")
def test_a_merge_without_the_runner_still_checks_the_actors_effects(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    covered = {**ON_LM_STUDIO, "effects": {"write": ["out/**", "docs/**"]}}
    branched(repo, [(LEAD, covered)])
    on(repo, "feature", [([*LEAD, "expect"], ["out/hello.txt", "docs/a.md"])])
    on(repo, "main", [([*LEAD, "effects", "write"], ["out/**"])])
    uninstall(monkeypatch)
    merged = merged_feature(repo)
    [conflict] = merged.conflicts
    assert conflict.paths == (("actors", "lead"),)
    assert conflict.rule is not None
    assert "'docs/a.md' is expected" in conflict.rule


@pytest.mark.parametrize("value", [5, True, "lead"], ids=["a number", "a boolean", "a string"])
def test_actors_set_to_a_value_is_config_invalid_not_a_crash(repo: Repo, value: object) -> None:
    """Working out the touched actors mustn't assume actors is a group (review of #338)."""
    with pytest.raises(TroupeError) as caught:
        set_config(repo, [(["actors"], value)])
    assert caught.value.code == "config.invalid"
    assert events(repo) == 0
