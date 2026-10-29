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
