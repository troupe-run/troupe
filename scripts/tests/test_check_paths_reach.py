"""Each suite's reach is worked out from the source, and a scope's `tests` must equal it.

Spec: quality-check. Design: package-check-scopes D3 and D4. Each rule is shown on a small
temporary workspace with a core, `troupe`, and packages such as `alpha` and `beta`. The tests
marked @reads_every_package run the analysis on the real tree instead, and carry every package
scope's tag."""

import textwrap
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import REPO

import check_paths_reach
import guard
from check_paths_reach import ReachError, Workspace, disagreements, expected_tests, reach

DECLARATION = guard.check_paths((REPO / guard.CHECK_PATHS).read_text(encoding="utf-8"))
READS_EVERY_PACKAGE = [
    getattr(pytest.mark, name) for name, _ in DECLARATION.scopes if name != "docs"
]
"""The tests that run the analysis on the real tree read every package's sources and tests, and a
change to any package can change its reach, so they carry every package scope's tag (design D4).
Built from the declaration, so a new scope needs no edit here."""


def reads_every_package[F: Callable[..., object]](test: F) -> F:
    for mark in READS_EVERY_PACKAGE:
        test = mark(test)
    return test


class Tree:
    """A workspace on disk: a root pyproject, members under packages/ and plugins/, suites."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.suites: list[str] = []
        self.write(
            "packages/troupe/pyproject.toml",
            '[project]\nname = "troupe"\ndependencies = []\n',
        )
        self.write("packages/troupe/src/troupe/__init__.py", "")
        self.write("packages/troupe/tests/helper.py", "")

    def write(self, relative: str, text: str) -> None:
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(text), encoding="utf-8")

    def package(
        self,
        name: str,
        under: str = "packages",
        dependencies: tuple[str, ...] = ("troupe",),
        entry_points: str = "",
        scripts: str = "",
    ) -> str:
        module = name.replace("-", "_")
        listed = ", ".join(f'"{dependency}"' for dependency in dependencies)
        self.write(
            f"{under}/{name}/pyproject.toml",
            f'[project]\nname = "{name}"\ndependencies = [{listed}]\n{scripts}{entry_points}',
        )
        self.write(f"{under}/{name}/src/{module}/__init__.py", "")
        return module

    def test(self, suite: str, name: str, text: str) -> None:
        if suite not in self.suites:
            self.suites.append(suite)
        self.write(f"{suite}/{name}.py", text)

    def workspace(self) -> Workspace:
        listed = ", ".join(f'"{suite}"' for suite in self.suites)
        self.write(
            "pyproject.toml",
            f"""\
            [tool.uv.workspace]
            members = ["packages/*", "plugins/*"]

            [tool.pytest.ini_options]
            testpaths = [{listed}]
            pythonpath = ["packages/troupe/tests", "scripts"]
            """,
        )
        return check_paths_reach.load_workspace(self.root)

    def reach(self, suite: str) -> frozenset[str]:
        return reach(self.workspace())[suite]


@pytest.fixture
def tree(tmp_path: Path) -> Tree:
    return Tree(tmp_path)


SUITE = "packages/troupe/tests"


# Rule 1 and 2: imports.


def test_a_suite_reaches_its_own_package(tree: Tree) -> None:
    tree.package("alpha")
    tree.test("packages/alpha/tests", "test_own", "def test(): pass\n")
    assert tree.reach("packages/alpha/tests") == {"alpha"}


def test_core_has_no_scope_and_a_scope_drops_troupe_and_uses_underscores(tree: Tree) -> None:
    tree.package("troupe-store-text")
    tree.test(SUITE, "test_core", "import troupe\nimport troupe_store_text\n")
    assert tree.reach(SUITE) == {"store_text"}


def test_an_import_inside_a_function_counts(tree: Tree) -> None:
    tree.package("alpha")
    tree.test(SUITE, "test_late", "def test():\n    import alpha\n")
    assert tree.reach(SUITE) == {"alpha"}


def test_an_import_only_for_type_checking_counts(tree: Tree) -> None:
    tree.package("alpha")
    tree.test(
        SUITE,
        "test_typed",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from alpha import Thing\n",
    )
    assert tree.reach(SUITE) == {"alpha"}


def test_a_declared_dependency_counts_transitively(tree: Tree) -> None:
    tree.package("alpha", dependencies=("troupe", "beta"))
    tree.package("beta", dependencies=("gamma",))
    tree.package("gamma")
    tree.test(SUITE, "test_deps", "import alpha\n")
    assert tree.reach(SUITE) == {"alpha", "beta", "gamma"}


def test_a_helpers_import_counts_for_the_suite_that_imports_the_helper(tree: Tree) -> None:
    tree.package("alpha")
    tree.write("packages/troupe/tests/helper.py", "import alpha\n")
    tree.test("packages/beta/tests", "test_helped", "from helper import thing\n")
    tree.package("beta")
    assert tree.reach("packages/beta/tests") == {"alpha", "beta"}


def test_a_package_sources_imports_count_relative_ones_included(tree: Tree) -> None:
    tree.package("alpha")
    tree.package("beta")
    tree.write("packages/alpha/src/alpha/__init__.py", "from .inner import thing\n")
    tree.write("packages/alpha/src/alpha/inner.py", "from beta import other\n")
    tree.test(SUITE, "test_chain", "import alpha\n")
    assert tree.reach(SUITE) == {"alpha", "beta"}


def test_import_module_with_a_literal_name_counts(tree: Tree) -> None:
    tree.package("alpha")
    tree.package("beta")
    tree.test(SUITE, "test_dynamic", "import importlib\nimportlib.import_module('alpha')\n")
    assert tree.reach(SUITE) == {"alpha"}


def test_import_module_with_a_computed_name_reaches_every_package(tree: Tree) -> None:
    tree.package("alpha")
    tree.package("beta", under="plugins")
    tree.test(
        SUITE, "test_dynamic", "import importlib\ndef f(n):\n    importlib.import_module(n)\n"
    )
    assert tree.reach(SUITE) == {"alpha", "beta"}


def test_a_nested_suites_modules_belong_to_it_and_not_to_the_suite_around_it(tree: Tree) -> None:
    tree.package("alpha")
    tree.test("scripts/tests", "test_plain", "def test(): pass\n")
    tree.test("scripts/tests/workspace", "test_named", "import alpha\n")
    reached = reach(tree.workspace())
    assert reached["scripts/tests"] == {"scripts"}
    assert reached["scripts/tests/workspace"] == {"scripts", "alpha"}


def test_a_conftest_above_a_suite_counts_for_it(tree: Tree) -> None:
    tree.package("alpha")
    tree.write("scripts/tests/conftest.py", "import alpha\n")
    tree.test("scripts/tests", "test_plain", "def test(): pass\n")
    tree.test("scripts/tests/workspace", "test_inner", "def test(): pass\n")
    reached = reach(tree.workspace())
    assert reached["scripts/tests/workspace"] == {"scripts", "alpha"}


# Rule 3: entry points.

LOADER = """\
import importlib.metadata
ENTRY_POINT_GROUP = "troupe.things"
def installed():
    return importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)
"""
REGISTERS = '\n[project.entry-points."troupe.things"]\nmine = "{module}:Thing"\n'


def test_reaching_a_loader_reaches_every_package_registered_in_its_group(tree: Tree) -> None:
    tree.write("packages/troupe/src/troupe/things.py", LOADER)
    tree.package("alpha", entry_points=REGISTERS.format(module="alpha"))
    tree.package("beta", entry_points=REGISTERS.format(module="beta"))
    tree.package("gamma")
    tree.test(SUITE, "test_things", "from troupe.things import installed\n")
    assert tree.reach(SUITE) == {"alpha", "beta"}


def test_a_suite_that_never_imports_the_loader_doesnt_reach_the_group(tree: Tree) -> None:
    tree.write("packages/troupe/src/troupe/things.py", LOADER)
    tree.package("alpha", entry_points=REGISTERS.format(module="alpha"))
    tree.test(SUITE, "test_other", "import troupe\n")
    assert tree.reach(SUITE) == frozenset()


def test_a_group_constant_imported_from_another_module_is_read(tree: Tree) -> None:
    tree.write("packages/troupe/src/troupe/names.py", 'GROUP = "troupe.things"\n')
    tree.package("alpha", entry_points=REGISTERS.format(module="alpha"))
    tree.test(
        SUITE,
        "test_listing",
        "from importlib.metadata import entry_points\nfrom troupe.names import GROUP\n"
        "entry_points(group=GROUP)\n",
    )
    assert tree.reach(SUITE) == {"alpha"}


def test_a_group_passed_as_a_parameter_is_read_from_the_names_in_the_module(tree: Tree) -> None:
    tree.package("alpha", entry_points=REGISTERS.format(module="alpha"))
    tree.test(
        SUITE,
        "test_registered",
        "import importlib.metadata\nGROUPS = [('troupe.things', 'mine')]\n"
        "def test(group):\n    importlib.metadata.entry_points(group=group)\n",
    )
    assert tree.reach(SUITE) == {"alpha"}


def test_an_unreadable_group_is_an_error_naming_the_file_and_line(tree: Tree) -> None:
    tree.package("alpha", entry_points=REGISTERS.format(module="alpha"))
    tree.test(
        SUITE,
        "test_hidden",
        "import importlib.metadata\n\n"
        "def test(group):\n    importlib.metadata.entry_points(group=group)\n",
    )
    with pytest.raises(ReachError, match=r"packages/troupe/tests/test_hidden\.py:4 .*group="):
        tree.reach(SUITE)


@reads_every_package
def test_the_real_trees_loaders_are_the_five_core_groups() -> None:
    analysis = check_paths_reach._Analysis(check_paths_reach.load_workspace(REPO))
    found = {group for file in analysis.names for group in analysis.groups(file)}
    assert found == {
        "troupe.artifacts",
        "troupe.identity",
        "troupe.stages",
        "troupe.store",
        "troupe.vcs",
    }


# Rule 4: packages named by test-side code.


def test_a_subprocess_running_a_packages_module_reaches_it(tree: Tree) -> None:
    tree.package("runner", under="plugins")
    tree.test(SUITE, "test_spawn", "import sys\nCOMMAND = [sys.executable, '-m', 'runner']\n")
    assert tree.reach(SUITE) == {"runner"}


def test_a_packages_console_script_reaches_it(tree: Tree) -> None:
    tree.package("runner", under="plugins", scripts='[project.scripts]\nrun-it = "runner:main"\n')
    tree.test(SUITE, "test_spawn", "COMMAND = ['run-it', '--once']\n")
    assert tree.reach(SUITE) == {"runner"}


def test_a_path_into_a_root_with_no_package_after_it_reaches_every_package_there(
    tree: Tree,
) -> None:
    tree.package("alpha", under="plugins")
    tree.package("beta", under="plugins")
    tree.package("gamma")
    tree.test(
        SUITE,
        "test_schemas",
        "from pathlib import Path\nPLUGINS = Path(__file__).parents[3] / 'plugins'\n",
    )
    assert tree.reach(SUITE) == {"alpha", "beta"}


def test_a_path_that_names_a_package_after_the_root_reaches_only_that_package(tree: Tree) -> None:
    tree.package("alpha", under="plugins")
    tree.package("beta", under="plugins")
    tree.test(
        SUITE,
        "test_fixtures",
        "from pathlib import Path\n"
        "FIXTURES = Path(__file__).parents[3] / 'plugins' / 'alpha' / 'fixtures'\n",
    )
    assert tree.reach(SUITE) == {"alpha"}


def test_a_glob_after_the_root_reaches_every_package_there(tree: Tree) -> None:
    tree.package("alpha", under="plugins")
    tree.package("beta", under="plugins")
    tree.test(SUITE, "test_glob", "from pathlib import Path\nFILES = Path('plugins/*/schemas')\n")
    assert tree.reach(SUITE) == {"alpha", "beta"}


def test_a_bare_root_or_distribution_name_isnt_a_path_and_reaches_nothing(tree: Tree) -> None:
    tree.package("troupe-alpha")
    tree.test(
        "scripts/tests",
        "test_config",
        "NAME = 'troupe-alpha'\ndef test(c):\n    c['packages'].clear()\n",
    )
    assert tree.reach("scripts/tests") == {"scripts"}


def test_a_path_written_as_one_string_reaches_the_package_it_names_even_as_a_key(
    tree: Tree,
) -> None:
    tree.package("troupe-alpha")
    tree.package("troupe-beta")
    tree.test(
        "scripts/tests",
        "test_config",
        "SELECTION = ('packages/troupe-alpha/tests',)\n"
        "def test(c):\n    c['packages'].pop('packages/troupe-beta')\n",
    )
    assert tree.reach("scripts/tests") == {"scripts", "alpha", "beta"}


def test_a_string_that_globs_after_the_root_reaches_every_package_there(tree: Tree) -> None:
    tree.package("alpha", under="plugins")
    tree.package("beta", under="plugins")
    tree.package("gamma")
    tree.test("scripts/tests", "test_glob", "PATTERN = 'plugins/*/schemas/*.json'\n")
    assert tree.reach("scripts/tests") == {"scripts", "alpha", "beta"}


@pytest.mark.parametrize("text", ["packages/", "packages/gone", "packages/gone/tests"])
def test_a_string_that_stops_at_the_root_or_names_no_package_reaches_nothing(
    tree: Tree, text: str
) -> None:
    tree.package("alpha")
    tree.test(
        "scripts/tests", "test_prefix", f"def f(path):\n    return path.startswith({text!r})\n"
    )
    assert tree.reach("scripts/tests") == {"scripts"}


def test_a_name_in_a_packages_own_source_doesnt_reach_another_package(tree: Tree) -> None:
    tree.package("runner", under="plugins")
    tree.write("packages/troupe/src/troupe/__init__.py", "DEFAULT = ['runner']\n")
    tree.test(SUITE, "test_core", "import troupe\n")
    assert tree.reach(SUITE) == frozenset()


# Rule 5: scripts.


def test_importing_a_script_reaches_the_scripts_scope(tree: Tree) -> None:
    tree.write("scripts/tool.py", "")
    tree.test(SUITE, "test_tool", "import tool\n")
    assert tree.reach(SUITE) == {"scripts"}


@pytest.mark.parametrize("module", sorted(check_paths_reach.FULL_CHECK_SCRIPTS))
def test_importing_a_full_check_script_reaches_no_scope(tree: Tree, module: str) -> None:
    tree.write(f"scripts/{module}.py", "")
    tree.test(SUITE, "test_tool", f"import {module}\n")
    assert tree.reach(SUITE) == frozenset()


def test_the_scripts_suite_reaches_the_scripts_scope(tree: Tree) -> None:
    tree.test("scripts/tests", "test_x", "def test(): pass\n")
    assert tree.reach("scripts/tests") == {"scripts"}


# The comparison with a declaration.


def test_expected_tests_name_every_suite_that_reaches_a_scope_in_testpaths_order(
    tree: Tree,
) -> None:
    tree.package("alpha")
    tree.test(SUITE, "test_core", "import alpha\n")
    tree.test("packages/alpha/tests", "test_alpha", "")
    tree.test("scripts/tests", "test_scripts", "")
    assert expected_tests(tree.workspace()) == {
        "alpha": ("packages/troupe/tests/**", "packages/alpha/tests/**"),
        "scripts": ("scripts/tests/**",),
    }


EXPECTED = {"alpha": ("a/tests/**", "b/tests/**"), "scripts": ("scripts/tests/**",)}


def test_a_declaration_that_matches_has_no_disagreements() -> None:
    declared = {"alpha": ["b/tests/**", "a/tests/**"], "scripts": ["scripts/tests/**"]}
    assert disagreements(declared, EXPECTED) == []


def test_a_missing_suite_is_named_with_the_line_to_declare() -> None:
    (problem,) = disagreements({"alpha": ["a/tests/**"]}, EXPECTED)
    assert problem == (
        "scopes.alpha in scripts/check-paths.toml leaves out `b/tests/**`, which reach it. Fix: "
        'declare `tests = ["a/tests/**", "b/tests/**"]` (package-check-scopes design D3).'
    )


def test_an_extra_suite_is_named_with_the_line_to_declare() -> None:
    (problem,) = disagreements({"scripts": ["scripts/tests/**", "a/tests/**"]}, EXPECTED)
    assert problem == (
        "scopes.scripts in scripts/check-paths.toml names `a/tests/**`, which don't. Fix: "
        'declare `tests = ["scripts/tests/**"]` (package-check-scopes design D3).'
    )


def test_a_missing_and_an_extra_suite_are_named_together() -> None:
    (problem,) = disagreements({"alpha": ["a/tests/**", "c/tests/**"]}, EXPECTED)
    assert "leaves out `b/tests/**`, which reach it and names `c/tests/**`, which don't" in problem


def test_a_scope_with_no_tests_is_named() -> None:
    (problem,) = disagreements({"alpha": None}, EXPECTED)
    assert problem.startswith("scopes.alpha in scripts/check-paths.toml declares no `tests`.")


def test_scopes_the_analysis_doesnt_cover_and_scopes_not_declared_are_left_alone() -> None:
    assert disagreements({"docs": ["docs/**"]}, EXPECTED) == []


# The real tree.


@reads_every_package
def test_on_the_real_tree_every_suite_reaches_its_own_package() -> None:
    workspace = check_paths_reach.load_workspace(REPO)
    reached = reach(workspace)
    for package in workspace.packages:
        suite = f"{package.path}/tests"
        if package.scope is not None and suite in reached:
            assert package.scope in reached[suite], suite
    assert "scripts" in reached["scripts/tests"]


@reads_every_package
def test_every_declared_scopes_tests_are_the_suites_that_reach_it() -> None:
    tests = dict(DECLARATION.tests)
    declared = {name: tests.get(name) for name, _ in DECLARATION.scopes}
    expected = expected_tests(check_paths_reach.load_workspace(REPO))
    problems = disagreements(declared, expected)
    assert not problems, "\n".join(problems)
