"""The identity chain's mechanics (spec: identity; event-store design D9)."""

from pathlib import Path

import pytest

from troupe.core import defaults
from troupe.core.errors import TroupeError
from troupe.core.identity import Identity, IdentityContext, IdentitySource, resolve_identity
from troupe.core.vcs import load_vcs


class Fixed:
    """A source that always gives the same answer (None: nothing found)."""

    def __init__(self, name: str, answer: Identity | None) -> None:
        self.hint = f"configure {name}"
        self.answer = answer
        self.asked = 0

    def resolve(self, context: IdentityContext) -> Identity | None:
        self.asked += 1
        return self.answer


class Refusing:
    hint = "fix it"

    def resolve(self, context: IdentityContext) -> Identity | None:
        raise TroupeError(
            "identity.ambiguous",
            problem="two answers",
            fix="keep one",
            details={
                "source": "vcs",
                "adapter": "git",
                "values": ["a@example.com", "b@example.com"],
            },
        )


@pytest.fixture
def context(tmp_path: Path) -> IdentityContext:
    return IdentityContext(env={}, vcs=load_vcs("files", tmp_path))


def ada(source: str) -> Identity:
    return Identity(kind="human", id="ada@example.com", source=source)


def test_the_default_chain_is_the_override_then_the_vcs_then_the_os_login() -> None:
    assert defaults.IDENTITY_CHAIN == ("env", "vcs", "os-login")


def test_the_first_source_that_answers_wins(context: IdentityContext) -> None:
    first, second, third = Fixed("a", None), Fixed("b", ada("b")), Fixed("c", ada("c"))
    sources: list[tuple[str, IdentitySource]] = [("a", first), ("b", second), ("c", third)]
    assert resolve_identity(context, sources=sources) == ada("b")
    assert (first.asked, second.asked, third.asked) == (1, 1, 0)


def test_reordering_the_chain_changes_which_source_wins(context: IdentityContext) -> None:
    vcs, login = Fixed("vcs", ada("vcs")), Fixed("os-login", ada("os-login"))
    assert resolve_identity(context, sources=[("os-login", login), ("vcs", vcs)]) == ada("os-login")
    assert resolve_identity(context, sources=[("vcs", vcs), ("os-login", login)]) == ada("vcs")


def test_a_source_that_refuses_stops_the_chain_and_later_sources_are_not_asked(
    context: IdentityContext,
) -> None:
    later = Fixed("later", ada("later"))
    with pytest.raises(TroupeError) as caught:
        resolve_identity(context, sources=[("refusing", Refusing()), ("later", later)])
    assert caught.value.code == "identity.ambiguous"
    assert later.asked == 0


def test_nothing_resolving_fails_naming_each_source_tried_and_how_to_fix_it(
    context: IdentityContext,
) -> None:
    sources: list[tuple[str, IdentitySource]] = [("a", Fixed("a", None)), ("b", Fixed("b", None))]
    with pytest.raises(TroupeError) as caught:
        resolve_identity(context, sources=sources)
    assert caught.value.code == "identity.unresolved"
    assert caught.value.details["tried"] == ["a", "b"]
    assert "configure a" in caught.value.fix
    assert "configure b" in caught.value.fix


def test_a_chain_naming_an_uninstalled_source_fails_naming_it_and_the_installed_ones(
    context: IdentityContext,
) -> None:
    with pytest.raises(TroupeError) as caught:
        resolve_identity(context, chain=("env", "oidc", "os-login"))
    assert caught.value.code == "identity.unknown-source"
    assert caught.value.details["unknown"] == ["oidc"]
    assert {"env", "vcs", "os-login"} <= set(caught.value.details["installed"])


@pytest.mark.parametrize("bad", ["", " ada", "ada "])
def test_an_identity_never_has_an_empty_or_padded_id(bad: str) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        Identity(kind="human", id=bad, source="env")
