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
            "plugins/runner-example",
            "troupe-runner-example",
            ["troupe-plugin-sdk", *dependencies],
        )

    def lock(self, name: str, dependencies: list[str], source: str = PYPI) -> None:
        # "name; marker" locks an edge that holds only where the marker does, as uv.lock writes it.
        edges = []
        for dependency in dependencies:
            named, _, marker = (part.strip() for part in dependency.partition(";"))
            held = f", marker = {json.dumps(marker)}" if marker else ""
            edges.append(f'{{ name = "{named}"{held} }}')
        deps = ", ".join(edges)
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
    tree.runner("example-sdk")
    tree.package("example-sdk", "example-codec", expression="MIT")
    tree.package("example-codec", expression="BSD-3-Clause")
    assert tree.problems() == []


def test_a_licence_on_neither_tier_is_named_with_the_package_runner_and_list(tree: Tree) -> None:
    tree.runner("example-sdk")
    tree.package("example-sdk", "gpl-thing", expression="MIT")
    tree.package("gpl-thing", expression="GPL-3.0-only")
    assert tree.problems() == [
        "gpl-thing, which troupe-runner-example depends on, is licensed GPL-3.0-only, which "
        f"isn't on either tier of {LIST}: replace the dependency, or, if the licence is compatible "
        f"with Apache-2.0, add it to {LIST} in a reviewed change."
    ]


def test_no_declared_licence_is_named(tree: Tree) -> None:
    tree.runner("example-sdk")
    tree.package("example-sdk")
    assert tree.problems() == [
        "example-sdk, which troupe-runner-example depends on, declares no licence in its metadata "
        f"(License-Expression, License or a licence classifier): no licence was found, so it can't "
        f"be checked against {LIST}. Replace it, or find its licence and raise it with the owner."
    ]


def test_a_package_that_isnt_installed_is_named(tree: Tree) -> None:
    tree.runner("example-sdk")
    tree.lock("example-sdk", [])
    assert tree.problems() == [
        "example-sdk, which troupe-runner-example depends on, isn't installed, so its licence "
        "can't be read: run uv sync, which installs every runner's dependencies."
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


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("GPL-3.0-only AND (MIT OR Apache-2.0)", None),
        ("(MIT OR Apache-2.0) AND GPL-3.0-only", None),
        ("MIT AND (BSD-3-Clause OR GPL-3.0-only)", "permissive"),
        ("(MIT OR GPL-3.0-only) AND (MPL-2.0 OR GPL-3.0-only)", "weak-copyleft"),
        ("((MIT))", "permissive"),
        ("MIT OR (GPL-3.0-only AND ISC)", "permissive"),
        ("Apache-2.0 WITH LLVM-exception", None),
        ("MIT AND (ISC", None),
        ("MIT OR", None),
    ],
)
def test_grouped_expressions_are_read_with_and_binding_tighter_than_or(
    expression: str, expected: str | None
) -> None:
    """A grouped AND can't pass on one branch of its group (review of #338). A WITH exception, or
    an expression this can't parse, reaches no tier: it fails safe, for a reviewed addition."""
    assert runner_licences.tier(expression, runner_licences.load_list(REPO)) == expected


def test_a_package_locked_only_for_another_platform_is_skipped_where_it_isnt_installed(
    tree: Tree,
) -> None:
    """tqdm needs colorama only on Windows: a leg elsewhere hasn't installed it, and the Windows
    leg checks it (review of #338)."""
    tree.runner("tqdm")
    tree.package("tqdm", "colorama; sys_platform == 'win32'", expression="MIT")
    tree.lock("colorama", [])
    assert tree.problems() == []


def test_a_package_locked_only_for_another_platform_is_still_checked_where_it_is_installed(
    tree: Tree,
) -> None:
    tree.runner("tqdm")
    tree.package("tqdm", "colorama; sys_platform == 'win32'", expression="MIT")
    tree.package("colorama", expression="GPL-3.0-only")
    [problem] = tree.problems()
    assert problem.startswith("colorama, which troupe-runner-example depends on, is licensed GPL")


def test_a_package_reached_unconditionally_too_isnt_skipped_when_missing(tree: Tree) -> None:
    tree.runner("tqdm", "colorama")
    tree.package("tqdm", "colorama; sys_platform == 'win32'", expression="MIT")
    tree.lock("colorama", [])
    assert tree.problems() == [
        "colorama, which troupe-runner-example depends on, isn't installed, so its licence can't "
        "be read: run uv sync, which installs every runner's dependencies."
    ]


def test_an_unmapped_licence_classifier_beside_a_mapped_one_fails(tree: Tree) -> None:
    """A classifier this can't read isn't dropped because another one maps (review of #338)."""
    tree.runner("both")
    tree.package(
        "both",
        classifiers=(
            "License :: OSI Approved :: MIT License",
            "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        ),
    )
    [problem] = tree.problems()
    assert "declares no licence in its metadata" in problem


def test_the_bare_osi_approved_classifier_says_nothing_and_is_ignored(tree: Tree) -> None:
    tree.runner("plain")
    tree.package(
        "plain",
        classifiers=("License :: OSI Approved", "License :: OSI Approved :: MIT License"),
    )
    assert tree.problems() == []


def test_a_classifier_is_mapped_to_spdx(tree: Tree) -> None:
    tree.runner("old")
    tree.package("old", classifiers=("License :: OSI Approved :: MIT License",))
    assert tree.problems() == []


def test_an_unmapped_classifier_fails(tree: Tree) -> None:
    tree.runner("odd")
    tree.package("odd", classifiers=("License :: Other/Proprietary License",))
    assert tree.problems() == [
        "odd, which troupe-runner-example depends on, declares no licence in its metadata "
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
        "certifi, which troupe-runner-example depends on, is licensed MPL-2.0, in the "
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
        "certifi, which troupe-runner-example depends on, is licensed MPL-2.0, in the "
        f"weak-copyleft tier of {LIST}, so it's used only unmodified, installed from a package "
        "index as its own package, but the root pyproject.toml's [tool.uv.sources] overrides it: "
        "remove the override."
    ]


def test_a_tracked_file_carrying_a_weak_copyleft_notice_is_named(tree: Tree) -> None:
    tree.runner()
    copied = f"# {NOTICE} v. 2.0.\nVALUE = 1\n"
    assert tree.problems({"plugins/runner-example/src/vendored.py": copied}) == [
        "plugins/runner-example/src/vendored.py carries the MPL-2.0 notice: weak-copyleft code "
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
