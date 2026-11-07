"""Every package a runner plugin depends on is pinned in the lock and licensed compatibly with
Apache-2.0, and a weak-copyleft one is only used unmodified, as its own package (spec:
runner-protocol; runner-extras design D11, D13; owner, #333).

Each case builds a small workspace with a lock and fake installed metadata; the last test runs the
check on the real repository. The weak-copyleft notice is read from the list, never written here,
so this file can't trip the copied-notice rule itself."""

import json
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest
from conftest import REPO

import guard
import runner_licences
from runner_licences import LIST

NOTICE = runner_licences.load_list(REPO).weak["MPL-2.0"]
PYPI = 'source = { registry = "https://pypi.org/simple" }'


class Tree:
    """A workspace: a root pyproject, an SDK, one runner plugin, a lock and installed metadata."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.locked: list[str] = []
        self.metadata: dict[str, dict[str, list[str]]] = {}
        self.sources = ""
        (root / "scripts").mkdir()
        (root / LIST).write_bytes((REPO / LIST).read_bytes())
        self.member("packages/troupe-plugin-sdk", "troupe-plugin-sdk", [])

    def member(self, path: str, name: str, dependencies: list[str]) -> None:
        (self.root / path).mkdir(parents=True, exist_ok=True)
        listed = ", ".join(json.dumps(d) for d in dependencies)
        (self.root / path / "pyproject.toml").write_text(
            f'[project]\nname = "{name}"\nversion = "0.0.0"\ndependencies = [{listed}]\n',
            encoding="utf-8",
        )
        self.lock(name, dependencies, f'source = {{ editable = "{path}" }}')

    def runner(self, *dependencies: str) -> None:
        self.member(
            "plugins/runner-lm-studio",
            "troupe-runner-lm-studio",
            ["troupe-plugin-sdk", *dependencies],
        )

    def lock(self, name: str, dependencies: list[str], source: str = PYPI) -> None:
        deps = ", ".join(f'{{ name = "{d}" }}' for d in dependencies)
        self.locked.append(
            f'[[package]]\nname = "{name}"\nversion = "1.0.0"\n{source}\ndependencies = [{deps}]\n'
        )

    def package(
        self,
        name: str,
        *dependencies: str,
        expression: str | None = None,
        licence: str | None = None,
        classifiers: tuple[str, ...] = (),
        source: str = PYPI,
    ) -> None:
        self.lock(name, list(dependencies), source)
        meta: dict[str, list[str]] = {"Classifier": list(classifiers)}
        if expression is not None:
            meta["License-Expression"] = [expression]
        if licence is not None:
            meta["License"] = [licence]
        self.metadata[name] = meta

    def problems(self, files: Mapping[str, str] | None = None) -> list[str]:
        (self.root / "pyproject.toml").write_text(
            '[tool.uv.workspace]\nmembers = ["packages/*", "plugins/*"]\n' + self.sources,
            encoding="utf-8",
        )
        (self.root / "uv.lock").write_text("version = 1\n\n" + "\n".join(self.locked), "utf-8")
        for path, text in (files or {}).items():
            (self.root / path).parent.mkdir(parents=True, exist_ok=True)
            (self.root / path).write_text(text, encoding="utf-8")
        return runner_licences.problems(
            self.root,
            metadata=lambda name: self.metadata.get(name),
            files=sorted(files or {}),
        )


@pytest.fixture
def tree(tmp_path: Path) -> Tree:
    return Tree(tmp_path)


def test_permissive_licences_pass(tree: Tree) -> None:
    tree.runner("lmstudio")
    tree.package("lmstudio", "msgspec", expression="MIT")
    tree.package("msgspec", expression="BSD-3-Clause")
    assert tree.problems() == []


def test_a_licence_on_neither_tier_is_named_with_the_package_runner_and_list(tree: Tree) -> None:
    tree.runner("lmstudio")
    tree.package("lmstudio", "gpl-thing", expression="MIT")
    tree.package("gpl-thing", expression="GPL-3.0-only")
    assert tree.problems() == [
        "gpl-thing, which troupe-runner-lm-studio depends on, is licensed GPL-3.0-only, which "
        f"isn't on either tier of {LIST}: replace the dependency, or, if the licence is compatible "
        f"with Apache-2.0, add it to {LIST} in a reviewed change."
    ]


def test_no_declared_licence_is_named(tree: Tree) -> None:
    tree.runner("lmstudio")
    tree.package("lmstudio")
    assert tree.problems() == [
        "lmstudio, which troupe-runner-lm-studio depends on, declares no licence in its metadata "
        f"(License-Expression, License or a licence classifier): no licence was found, so it can't "
        f"be checked against {LIST}. Replace it, or find its licence and raise it with the owner."
    ]


def test_a_package_that_isnt_installed_is_named(tree: Tree) -> None:
    tree.runner("lmstudio")
    tree.lock("lmstudio", [])
    assert tree.problems() == [
        "lmstudio, which troupe-runner-lm-studio depends on, isn't installed, so its licence can't "
        "be read: run uv sync, which installs every runner's dependencies."
    ]


def test_an_or_expression_with_one_branch_on_the_list_passes(tree: Tree) -> None:
    tree.runner("sniffio")
    tree.package("sniffio", expression="MIT OR Apache-2.0")
    assert tree.problems() == []


def test_an_and_expression_needs_every_part_on_the_list(tree: Tree) -> None:
    tree.runner("mixed")
    tree.package("mixed", expression="MIT AND GPL-3.0-only")
    [problem] = tree.problems()
    assert "licensed MIT AND GPL-3.0-only" in problem


def test_a_classifier_is_mapped_to_spdx(tree: Tree) -> None:
    tree.runner("old")
    tree.package("old", classifiers=("License :: OSI Approved :: MIT License",))
    assert tree.problems() == []


def test_an_unmapped_classifier_fails(tree: Tree) -> None:
    tree.runner("odd")
    tree.package("odd", classifiers=("License :: Other/Proprietary License",))
    assert tree.problems() == [
        "odd, which troupe-runner-lm-studio depends on, declares no licence in its metadata "
        f"(License-Expression, License or a licence classifier): no licence was found, so it can't "
        f"be checked against {LIST}. Replace it, or find its licence and raise it with the owner."
    ]


def test_a_single_spdx_license_field_counts(tree: Tree) -> None:
    tree.runner("plain")
    tree.package("plain", licence="ISC")
    assert tree.problems() == []


def test_workspace_members_are_skipped(tree: Tree) -> None:
    tree.runner()
    assert tree.problems() == []


def test_runners_with_no_dependency_beyond_the_sdk_check_no_package(tree: Tree) -> None:
    tree.runner()
    assert tree.problems() == []
    assert runner_licences.dependencies_of_runners(tree.root) == {}


# The weak-copyleft tier (runner-protocol: "A weak-copyleft dependency is used only unmodified, as
# its own package"; owner, #333 comment 6707703235).


def test_certifi_through_an_http_library_from_pypi_passes(tree: Tree) -> None:
    tree.runner("httpx")
    tree.package("httpx", "certifi", expression="BSD-3-Clause")
    tree.package("certifi", expression="MPL-2.0")
    assert tree.problems() == []


def test_a_weak_copyleft_package_from_a_git_source_is_named(tree: Tree) -> None:
    tree.runner("httpx")
    tree.package("httpx", "certifi", expression="BSD-3-Clause")
    git = 'source = { git = "https://github.com/certifi/python-certifi?rev=abc#abc" }'
    tree.package("certifi", expression="MPL-2.0", source=git)
    assert tree.problems() == [
        "certifi, which troupe-runner-lm-studio depends on, is licensed MPL-2.0, in the "
        f"weak-copyleft tier of {LIST}, so it's used only unmodified, installed from a package "
        "index as its own package, but uv.lock takes it from a git source: lock it from the "
        "package index."
    ]


def test_a_weak_copyleft_package_overridden_in_the_workspace_sources_is_named(tree: Tree) -> None:
    tree.runner("httpx")
    tree.package("httpx", "certifi", expression="BSD-3-Clause")
    tree.package("certifi", expression="MPL-2.0")
    tree.sources = '\n[tool.uv.sources]\ncertifi = { path = "vendor/certifi" }\n'
    assert tree.problems() == [
        "certifi, which troupe-runner-lm-studio depends on, is licensed MPL-2.0, in the "
        f"weak-copyleft tier of {LIST}, so it's used only unmodified, installed from a package "
        "index as its own package, but the root pyproject.toml's [tool.uv.sources] overrides it: "
        "remove the override."
    ]


def test_a_tracked_file_carrying_a_weak_copyleft_notice_is_named(tree: Tree) -> None:
    tree.runner()
    copied = f"# {NOTICE} v. 2.0.\nVALUE = 1\n"
    assert tree.problems({"plugins/runner-lm-studio/src/vendored.py": copied}) == [
        "plugins/runner-lm-studio/src/vendored.py carries the MPL-2.0 notice: weak-copyleft code "
        "is used only as an unmodified dependency, installed as its own package, never copied, "
        "vendored or patched into troupe's source. Remove the file, and depend on its package."
    ]


def test_a_file_outside_packages_plugins_and_scripts_isnt_scanned(tree: Tree) -> None:
    tree.runner()
    assert tree.problems({"docs/licences.md": f"{NOTICE}\n"}) == []


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
