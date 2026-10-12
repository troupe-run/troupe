"""The local identity sources and the default chain, end to end (spec: identity)."""

from pathlib import Path

import pytest

from gitrepo import Repo, make_repo
from troupe.core.errors import TroupeError
from troupe.core.identity import Identity, IdentityContext, resolve_identity
from troupe.core.vcs import load_vcs
from troupe_identity_local import EnvSource, OsLoginSource, VcsSource
from troupe_vcs_git import GitAdapter

LOGIN = OsLoginSource(lookup=lambda: "ada-login")


def chain(login: OsLoginSource = LOGIN) -> list[tuple[str, EnvSource | VcsSource | OsLoginSource]]:
    """The default chain, with the OS login fixed so tests don't depend on who runs them."""
    return [("env", EnvSource()), ("vcs", VcsSource()), ("os-login", login)]


def in_git(repo: Repo, **env: str) -> IdentityContext:
    return IdentityContext(env=env, vcs=GitAdapter(repo.path, source=repo.env))


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return make_repo(tmp_path)


def test_the_override_wins_over_git(repo: Repo) -> None:
    repo.git("config", "user.email", "git@example.com")
    found = resolve_identity(in_git(repo, TROUPE_ACTOR="human:ada@example.com"), sources=chain())
    assert found == Identity(kind="human", id="ada@example.com", source="env")


def test_the_override_can_name_an_agent(repo: Repo) -> None:
    found = resolve_identity(in_git(repo, TROUPE_ACTOR="agent:tester"), sources=chain())
    assert found == Identity(kind="agent", id="tester", source="env")


def test_without_the_override_the_git_user_email_is_used(repo: Repo) -> None:
    repo.git("config", "user.email", "ada@example.com")
    found = resolve_identity(in_git(repo), sources=chain())
    assert found == Identity(kind="human", id="ada@example.com", source="vcs")


def test_a_user_email_only_in_the_global_config_resolves_through_git_not_the_os_login(
    repo: Repo,
) -> None:
    repo.git("config", "--global", "user.email", "global@example.com")
    found = resolve_identity(in_git(repo), sources=chain())
    assert found == Identity(kind="human", id="global@example.com", source="vcs")


def test_with_no_override_and_no_git_email_the_os_login_is_used(repo: Repo) -> None:
    found = resolve_identity(in_git(repo), sources=chain())
    assert found == Identity(kind="human", id="ada-login", source="os-login")


def test_the_filesystem_adapter_has_no_vcs_identity_so_the_os_login_is_used(
    tmp_path: Path,
) -> None:
    context = IdentityContext(env={}, vcs=load_vcs("files", tmp_path))
    assert resolve_identity(context, sources=chain()).source == "os-login"


@pytest.mark.parametrize(
    "value", ["ada", "human:", "robot:ada", "human: ada", "Human:ada", "human:ada ", "agent"]
)
def test_a_malformed_override_fails_naming_the_value_and_both_forms(repo: Repo, value: str) -> None:
    repo.git("config", "user.email", "git@example.com")
    with pytest.raises(TroupeError) as caught:
        resolve_identity(in_git(repo, TROUPE_ACTOR=value), sources=chain())
    assert caught.value.code == "identity.invalid-override"
    assert repr(value) in caught.value.problem
    assert "human:<id>" in caught.value.fix
    assert "agent:<id>" in caught.value.fix


def test_an_empty_override_is_unset_and_passes_on(repo: Repo) -> None:
    repo.git("config", "user.email", "git@example.com")
    assert resolve_identity(in_git(repo, TROUPE_ACTOR=""), sources=chain()).source == "vcs"


def test_two_git_emails_fail_as_ambiguous_and_the_os_login_is_not_used(repo: Repo) -> None:
    repo.git("config", "user.email", "ada@example.com")
    repo.git("config", "--add", "user.email", "grace@example.com")
    asked: list[str] = []

    def lookup() -> str:
        asked.append("os-login")
        return "ada-login"

    login = OsLoginSource(lookup=lookup)
    with pytest.raises(TroupeError) as caught:
        resolve_identity(in_git(repo), sources=chain(login))
    assert caught.value.code == "identity.ambiguous"
    assert caught.value.details["source"] == "vcs"
    assert caught.value.details["values"] == ["ada@example.com", "grace@example.com"]
    assert asked == []


def test_an_unset_git_email_passes_on_to_the_next_source(repo: Repo) -> None:
    assert resolve_identity(in_git(repo), sources=chain()).source == "os-login"


def test_the_os_login_failing_is_no_answer_so_nothing_resolves(repo: Repo) -> None:
    def no_login() -> str:
        raise OSError("no login name")

    with pytest.raises(TroupeError) as caught:
        resolve_identity(in_git(repo), sources=chain(OsLoginSource(lookup=no_login)))
    assert caught.value.code == "identity.unresolved"
    assert caught.value.details["tried"] == ["env", "vcs", "os-login"]
    assert "TROUPE_ACTOR" in caught.value.fix


def test_the_installed_sources_are_the_default_chain(repo: Repo) -> None:
    repo.git("config", "user.email", "ada@example.com")
    found = resolve_identity(in_git(repo))
    assert found == Identity(kind="human", id="ada@example.com", source="vcs")
