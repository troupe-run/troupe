"""The licence check run on the real repository finds no problem: every package a runner plugin
depends on has a listed licence (spec: runner-protocol; runner-extras design D11, D13; owner,
#333).

Its tests that stay in their own process are in unit/test_runner_licences.py."""

from collections.abc import Callable

import pytest
from conftest import REPO

import guard
import runner_licences

DECLARATION = guard.check_paths((REPO / guard.CHECK_PATHS).read_text(encoding="utf-8"))
EVERY_SCOPE = [getattr(pytest.mark, name) for name, _ in DECLARATION.scopes]
"""The run on the real repository reads every tracked file under packages/, plugins/ and scripts/
for a copied notice, so a change in any scope, docs included, can change its answer."""


def reads_every_scope[F: Callable[..., object]](test: F) -> F:
    for mark in EVERY_SCOPE:
        test = mark(test)
    return test


@reads_every_scope
def test_every_runner_dependency_in_the_repository_has_a_listed_licence() -> None:
    assert runner_licences.problems(REPO) == []
