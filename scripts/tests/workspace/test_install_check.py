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
import release_config
from install_check import InstallCheckError, Tools


def test_the_documented_command_installs_the_bundle_from_the_named_ref() -> None:
    assert install_check.command(release_config.REPOSITORY, "main") == (
        'uv tool install "git+https://github.com/troupe-run/troupe@main'
        '#subdirectory=packages/troupe-run"'
    )


def test_a_bundle_tags_command_installs_each_component_from_its_pin() -> None:
    """--no-sources, so uv reads the bundle's pins rather than the tag's workspace (design D3)."""
    assert install_check.command(release_config.REPOSITORY, "troupe-run-v0.1.0") == (
        'uv tool install --no-sources "git+https://github.com/troupe-run/troupe@troupe-run-v0.1.0'
        '#subdirectory=packages/troupe-run"'
    )
    assert "--no-sources" not in install_check.command(release_config.REPOSITORY, "<commit>")
    assert "--no-sources" not in install_check.command(release_config.REPOSITORY, "troupe-v0.1.0")


def test_a_bundle_tag_installed_from_the_checkout_still_uses_its_pins() -> None:
    """From the checkout the ref is the resolved commit, but the form is still the tag's."""
    url = "git+file:///checkout@abc#subdirectory=packages/troupe-run"
    assert install_check.install_arguments("file:///checkout", "abc", None, pinned=True) == [
        "tool",
        "install",
        "--no-sources",
        url,
    ]


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
    arguments = install_check.install_arguments(repository, ref, None, pinned=True)
    assert f"uv {' '.join(arguments)}" == (
        install_check.command(release_config.REPOSITORY, "troupe-run-v0.1.0").replace('"', "")
    )


def test_without_hosted_the_checkout_is_installed_from_by_its_resolved_commit() -> None:
    assert install_check.source(REPO, "HEAD", "abc", hosted=False) == (
        install_check.repository_url(REPO),
        "abc",
    )


def bundle(version: str, *dependencies: str) -> str:
    """A bundle pyproject.toml as a tag would hold it."""
    listed = "".join(f'    "{d}",\n' for d in dependencies)
    return f'[project]\nname = "troupe-run"\nversion = "{version}"\ndependencies = [\n{listed}]\n'


def pinned(name: str, version: str) -> str:
    path = "packages/" + name if not name.startswith("troupe-runner") else "plugins/" + name[7:]
    return release_config.pin(name, version, path)


def test_a_bundle_tag_expects_the_version_core_is_pinned_at() -> None:
    """The bundle and core version on their own: the spec's 0.2.0 bundle shipping core 0.1.3."""
    text = bundle("0.2.0", pinned("troupe", "0.1.3"), pinned("troupe-vcs-git", "0.1.1"))
    assert install_check.expected_version("troupe-run-v0.2.0", "0.1.4", text, "abc") == "0.1.3"


def test_any_other_ref_expects_the_version_core_declares() -> None:
    text = bundle("0.2.0", pinned("troupe", "0.1.3"))
    assert install_check.expected_version("main", "0.1.4", text, "abc") == "0.1.4"


def test_a_tag_whose_bundle_declares_another_version_is_refused_naming_both() -> None:
    text = bundle("0.1.0", pinned("troupe", "0.1.0"))
    with pytest.raises(InstallCheckError) as caught:
        install_check.expected_version("troupe-run-v0.2.0", "0.1.0", text, "abc")
    assert str(caught.value) == (
        "--ref troupe-run-v0.2.0: the tag names version 0.2.0, but troupe-run declares 0.1.0 at "
        "abc, so the tag isn't the bundle's release."
    )


def test_a_tag_with_a_component_that_isnt_pinned_is_refused_before_installing() -> None:
    text = bundle("0.2.0", pinned("troupe", "0.1.0"), "troupe-stage-local", "troupe-vcs-git")
    with pytest.raises(InstallCheckError) as caught:
        install_check.expected_version("troupe-run-v0.2.0", "0.1.0", text, "abc")
    assert str(caught.value) == (
        "--ref troupe-run-v0.2.0: troupe-run doesn't pin troupe-stage-local, troupe-vcs-git at "
        "abc, so --no-sources would look for them on a package index. A pinning pull request pins "
        "them, and the bundle's next release ships them."
    )


def test_a_tag_that_doesnt_pin_core_is_refused() -> None:
    text = bundle("0.2.0", pinned("troupe-vcs-git", "0.1.0"))
    with pytest.raises(InstallCheckError, match="doesn't pin troupe at abc"):
        install_check.expected_version("troupe-run-v0.2.0", "0.1.0", text, "abc")


def test_an_install_that_prints_another_version_than_its_tag_is_refused_naming_the_tag() -> None:
    with pytest.raises(InstallCheckError) as caught:
        install_check.confirm_printed(
            "troupe 0.0.0 (protocol 0.1.0)\n", "0.1.0", "troupe-run-v0.1.0", "abc"
        )
    assert str(caught.value) == (
        "troupe --version: printed 'troupe 0.0.0 (protocol 0.1.0)', not troupe 0.1.0, "
        "the version troupe-run-v0.1.0 pins troupe at."
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
