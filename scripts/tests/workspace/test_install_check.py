"""The install check builds the documented command and keeps to its own directories.

Spec: installation. Design: install-with-uv D3 and D4. What needs an install (the install itself,
and performing with it) is run by CI's install step on every platform and Python, not here: each
test here checks what the check does without installing anything."""

import os
import sys
from pathlib import Path

import pytest
from conftest import REPO

import install_check
from install_check import InstallCheckError, Tools


def test_the_documented_command_installs_the_bundle_from_the_named_ref() -> None:
    assert install_check.command(install_check.REPOSITORY, "main") == (
        'uv tool install "git+https://github.com/troupe-run/troupe@main'
        '#subdirectory=packages/troupe-run"'
    )


def test_the_install_arguments_are_the_documented_command_with_python_only_when_given() -> None:
    repository = "file:///checkout"
    url = "git+file:///checkout@abc#subdirectory=packages/troupe-run"
    assert install_check.install_arguments(repository, "abc", None) == ["tool", "install", url]
    assert install_check.install_arguments(repository, "abc", "3.13") == [
        "tool",
        "install",
        url,
        "--python",
        "3.13",
    ]
    assert f"uv {' '.join(install_check.install_arguments(repository, 'abc', None))}" == (
        install_check.command(repository, "abc").replace('"', "")
    )


def test_the_checkout_is_installed_from_as_a_file_url(tmp_path: Path) -> None:
    assert install_check.repository_url(tmp_path) == tmp_path.resolve().as_uri()
    assert install_check.repository_url(tmp_path).startswith("file:///")


def test_a_ref_is_resolved_to_its_full_commit() -> None:
    sha = install_check.resolve(REPO, "HEAD")
    assert len(sha) == 40
    assert install_check.resolve(REPO, sha) == sha


def test_a_ref_that_names_no_commit_is_refused_by_name() -> None:
    refused = r"--ref 'no-such-ref-for-the-install-check' isn't a commit"
    with pytest.raises(InstallCheckError, match=refused):
        install_check.resolve(REPO, "no-such-ref-for-the-install-check")


def test_the_tool_directories_are_the_checks_own_and_override_the_persons() -> None:
    tools = Tools(directory=Path("/scratch/tools"), bin=Path("/scratch/bin"))
    env = tools.environment({"UV_TOOL_DIR": "/home/me/tools", "PATH": "/usr/bin"})
    assert env == {
        "UV_TOOL_DIR": str(Path("/scratch/tools")),
        "UV_TOOL_BIN_DIR": str(Path("/scratch/bin")),
        "PATH": "/usr/bin",
    }


def test_the_scratch_directory_is_removed_afterwards_even_when_a_step_fails() -> None:
    kept: list[Path] = []

    def a_step_that_fails() -> None:
        with install_check.scratch() as place:
            kept.append(place)
            (place / "tools").mkdir()
            (place / "tools" / "left.txt").write_text("x", encoding="utf-8")
            raise InstallCheckError("a step failed")

    with pytest.raises(InstallCheckError):
        a_step_that_fails()
    assert not kept[0].exists()


def test_a_failing_step_names_the_step_the_command_and_its_output(tmp_path: Path) -> None:
    script = "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"
    argv = [sys.executable, "-c", script]
    with pytest.raises(InstallCheckError) as caught:
        install_check.run("perform", argv, tmp_path, os.environ, 30)
    message = str(caught.value)
    assert message.startswith(f"perform: `{' '.join(argv)}` exited 3.")
    assert "standard output:\nout\n" in message
    assert "standard error:\nerr\n" in message


def test_a_step_that_outlives_its_timeout_is_stopped_and_named(tmp_path: Path) -> None:
    argv = [sys.executable, "-c", "import time; time.sleep(30)"]
    with pytest.raises(InstallCheckError, match=r"^install: `.*` didn't finish within 0.5s\.$"):
        install_check.run("install", argv, tmp_path, os.environ, 0.5)


@pytest.mark.parametrize(
    ("ref", "version"),
    [
        ("troupe-run-v0.1.0", "0.1.0"),
        ("troupe-run-v1.2.3-rc.1", "1.2.3-rc.1"),
        ("troupe-v0.1.0", None),
        ("main", None),
        ("0123456789abcdef0123456789abcdef01234567", None),
        ("troupe-run-v", None),
        ("troupe-run-vnext", None),
    ],
)
def test_only_the_bundles_release_tag_names_a_version(ref: str, version: str | None) -> None:
    assert install_check.tagged_version(ref) == version


def test_hosted_installs_from_github_with_the_ref_exactly_as_given() -> None:
    repository, ref = install_check.source(REPO, "troupe-run-v0.1.0", "abc", hosted=True)
    assert f"uv {' '.join(install_check.install_arguments(repository, ref, None))}" == (
        install_check.command(install_check.REPOSITORY, "troupe-run-v0.1.0").replace('"', "")
    )


def test_without_hosted_the_checkout_is_installed_from_by_its_resolved_commit() -> None:
    assert install_check.source(REPO, "HEAD", "abc", hosted=False) == (
        install_check.repository_url(REPO),
        "abc",
    )


def test_a_tag_whose_version_core_doesnt_declare_is_refused_naming_both() -> None:
    with pytest.raises(InstallCheckError) as caught:
        install_check.expected_version("troupe-run-v0.2.0", "0.1.0", "abc")
    assert str(caught.value) == (
        "--ref troupe-run-v0.2.0: the tag names version 0.2.0, but core declares 0.1.0 at abc. "
        "The bundle and core are released at one version, so the tag or the linked group is wrong."
    )


def test_a_tag_whose_version_core_declares_expects_that_version() -> None:
    assert install_check.expected_version("troupe-run-v0.1.0", "0.1.0", "abc") == "0.1.0"
    assert install_check.expected_version("main", "0.0.0", "abc") == "0.0.0"


def test_an_install_that_prints_another_version_than_its_tag_is_refused_naming_the_tag() -> None:
    with pytest.raises(InstallCheckError) as caught:
        install_check.confirm_printed(
            "troupe 0.0.0 (protocol 0.1.0)\n", "0.1.0", "troupe-run-v0.1.0", "abc"
        )
    assert str(caught.value) == (
        "troupe --version: printed 'troupe 0.0.0 (protocol 0.1.0)', not troupe 0.1.0, "
        "the version troupe-run-v0.1.0 names."
    )


def test_an_install_from_a_commit_that_prints_another_version_names_the_commit() -> None:
    with pytest.raises(InstallCheckError) as caught:
        install_check.confirm_printed("troupe 0.0.1 (protocol 0.1.0)\n", "0.0.0", "HEAD", "abc")
    assert str(caught.value) == (
        "troupe --version: printed 'troupe 0.0.1 (protocol 0.1.0)', not troupe 0.0.0, "
        "the version core declares at abc."
    )


def test_an_install_that_prints_the_expected_version_passes() -> None:
    install_check.confirm_printed(
        "troupe 0.1.0 (protocol 0.1.0)\n", "0.1.0", "troupe-run-v0.1.0", "abc"
    )
