"""The install check builds the documented command and keeps to its own directories.

Spec: installation. Design: install-with-uv D3 and D4. What needs troupe installed (the install
itself, and performing with it) is run by CI's install step on every platform and Python, not here.
The network tests install a one-file probe package from an index on 127.0.0.1 instead, through the
check's own steps and environment (install-check-network-retries design D5)."""

import json
import os
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path

import local_index
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
        "UV_HTTP_RETRIES": str(install_check.HTTP_RETRIES),
        "PATH": "/usr/bin",
    }


def test_without_a_retry_count_of_the_callers_uv_gets_the_checks() -> None:
    tools = Tools(directory=Path("/scratch/tools"), bin=Path("/scratch/bin"))
    assert tools.environment({})["UV_HTTP_RETRIES"] == str(install_check.HTTP_RETRIES)


@pytest.mark.parametrize("value", ["1", "0", "abc", " 7"])
def test_a_retry_count_the_caller_set_reaches_uv_unchanged(value: str) -> None:
    """Even one uv can't read: uv refuses it, naming it, rather than the check replacing it."""
    tools = Tools(directory=Path("/scratch/tools"), bin=Path("/scratch/bin"))
    env = tools.environment({"UV_HTTP_RETRIES": value})
    assert env["UV_HTTP_RETRIES"] == value
    assert env["UV_TOOL_DIR"] == str(Path("/scratch/tools"))


def test_an_empty_retry_count_counts_as_unset_as_uv_reads_it() -> None:
    """uv reads an empty UV_HTTP_RETRIES as unset and uses its default, so the check's applies."""
    tools = Tools(directory=Path("/scratch/tools"), bin=Path("/scratch/bin"))
    assert tools.environment({"UV_HTTP_RETRIES": ""})["UV_HTTP_RETRIES"] == str(
        install_check.HTTP_RETRIES
    )


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


# The extras (spec: installation; runner-extras design D9, D10). Each case gives a runner table of
# its own, naming example, a fixture runner in troupe-run's example extra (remove-lm-studio
# design D1).


def test_the_extras_form_names_the_extras_before_the_url_in_both_ref_forms() -> None:
    assert install_check.command(release_config.REPOSITORY, "main", ("all",)) == (
        'uv tool install "troupe-run[all] @ git+https://github.com/troupe-run/troupe@main'
        '#subdirectory=packages/troupe-run"'
    )
    assert install_check.command(release_config.REPOSITORY, "troupe-run-v0.1.0", ("all",)) == (
        'uv tool install --no-sources "troupe-run[all] @ git+https://github.com/troupe-run/troupe'
        '@troupe-run-v0.1.0#subdirectory=packages/troupe-run"'
    )


def test_the_install_arguments_with_extras_name_them_before_the_url() -> None:
    assert install_check.install_arguments("file:///checkout", "abc", "3.12", extras=("all",)) == [
        "tool",
        "install",
        "troupe-run[all] @ git+file:///checkout@abc#subdirectory=packages/troupe-run",
        "--python",
        "3.12",
    ]


def with_extras(text: str, extras: dict[str, list[str]]) -> str:
    """A bundle pyproject.toml's text with these extras added."""
    block = "\n[project.optional-dependencies]\n" + "".join(
        f"{name} = {json.dumps(requirements)}\n" for name, requirements in extras.items()
    )
    return text + block


def test_a_tag_with_a_runner_bare_in_an_extra_is_refused_naming_the_extra() -> None:
    text = with_extras(
        bundle("0.2.0", pinned("troupe", "0.1.0")),
        {"example": ["troupe-runner-example"], "all": ["troupe-runner-example"]},
    )
    with pytest.raises(InstallCheckError) as caught:
        install_check.expected_version("troupe-run-v0.2.0", "0.1.0", text, "abc")
    assert str(caught.value) == (
        "--ref troupe-run-v0.2.0: troupe-run doesn't pin troupe-runner-example (in its "
        "'example' extra) at abc, so --no-sources would look for them on a package index. A "
        "pinning pull request pins them, and the bundle's next release ships them."
    )


TABLE = """
RUNNERS: dict[str, Runner] = {
    "scripted": Runner(command=("python",), package="troupe_runner_scripted"),
    "example": Runner(command=("python",), package="troupe_runner_example", in_extra=True),
}
"""


def test_the_runners_are_read_from_cores_table_as_text() -> None:
    runners = install_check.runners_in(TABLE, "abc")
    assert [(r.name, r.in_extra) for r in runners] == [("scripted", False), ("example", True)]


def test_a_commit_without_a_runner_table_is_refused_naming_it() -> None:
    with pytest.raises(InstallCheckError) as caught:
        install_check.runners_in("RUNNERS = 1\n", "abc")
    assert str(caught.value) == (
        "read core's runners: packages/troupe/src/troupe/core/interim.py at abc has no RUNNERS "
        "table to read."
    )


def test_the_base_refuses_each_runner_in_an_extra_and_all_rehearses_every_runner() -> None:
    runners = install_check.runners_in(TABLE, "abc")
    assert install_check.refused_in_the_base(runners) == ["example"]
    assert install_check.rehearsed_with_all(runners) == ["scripted", "example"]


def test_only_a_bundle_with_an_all_extra_is_installed_with_it() -> None:
    plain = bundle("0.2.0", pinned("troupe", "0.1.0"))
    assert not install_check.has_all(plain)
    assert install_check.has_all(with_extras(plain, {"all": []}))


def test_a_refusal_naming_the_extra_passes() -> None:
    install_check.confirm_refused("example", 1, "", "  fix: Install troupe-run[example] with ...")


@pytest.mark.parametrize(
    ("code", "stderr"),
    [(3, ""), (0, ""), (1, "troupe: something else\n  fix: something")],
    ids=["rehearsed", "made", "another refusal"],
)
def test_anything_but_a_refusal_naming_the_extra_fails_naming_the_runner(
    code: int, stderr: str
) -> None:
    with pytest.raises(InstallCheckError) as caught:
        install_check.confirm_refused("example", code, "out", stderr)
    message = str(caught.value)
    assert message.startswith(
        "base install: rehearsing an audition on example should be refused, naming "
        f"troupe-run[example], but it exited {code}."
    )
    assert "out" in message


def test_a_rehearsal_that_would_change_passes_and_anything_else_fails() -> None:
    install_check.confirm_rehearsed("example", install_check.WOULD_CHANGE, "", "")
    with pytest.raises(InstallCheckError) as caught:
        install_check.confirm_rehearsed("example", 1, "", "troupe: not installed")
    assert str(caught.value).startswith(
        "all install: rehearsing an audition on example should succeed with the would-change "
        f"code ({install_check.WOULD_CHANGE}), but it exited 1."
    )


def test_the_would_change_code_is_troupes() -> None:
    from troupe.core.exit_codes import ExitCode

    assert install_check.WOULD_CHANGE == ExitCode.WOULD_CHANGE


def _caller(**variables: str) -> dict[str, str]:
    """The environment the check is run with: this one, without a retry count of its own and
    without the developer's uv configuration, plus the given variables."""
    base = {name: value for name, value in os.environ.items() if name != "UV_HTTP_RETRIES"}
    return {**base, "UV_NO_CONFIG": "1", "UV_PYTHON_DOWNLOADS": "never", **variables}


def _install_probe(index: local_index.Index, place: Path, base: Mapping[str, str]) -> Path:
    """Install the probe from the index through the check's install step and environment, into a
    tool directory of the check's own. Returns its bin directory."""
    tools = Tools(directory=place / "tools", bin=place / "bin")
    uv = shutil.which("uv")
    assert uv is not None, "uv isn't on PATH"
    argv = [uv, "--no-cache", "tool", "install", "--index-url", index.url]
    argv += ["--python", sys.executable, local_index.PROJECT]
    env = tools.environment(base)
    install_check.run("install", argv, place, env, install_check.INSTALL_TIMEOUT)
    return tools.bin


def test_the_probe_installs_from_the_local_index_and_its_script_runs(tmp_path: Path) -> None:
    with local_index.serving() as index:
        bin_directory = _install_probe(index, tmp_path, _caller())
    probe = shutil.which(local_index.PROJECT, path=str(bin_directory))
    assert probe is not None
    shown = install_check.run("probe", [probe], tmp_path, os.environ, install_check.COMMAND_TIMEOUT)
    assert shown.strip() == local_index.PRINTED
    assert index.requests[local_index.PAGE] == 1


def test_an_index_that_fails_four_times_is_outlasted_with_the_checks_retries(
    tmp_path: Path,
) -> None:
    """Four failures need a fifth attempt, more than uv's default of three retries makes."""
    with local_index.serving(failures=[503] * 4) as index:
        _install_probe(index, tmp_path, _caller())
    assert index.requests[local_index.PAGE] == 5
    assert shutil.which(local_index.PROJECT, path=str(tmp_path / "bin")) is not None


def test_four_failures_are_more_than_uvs_default_of_three_retries_outlasts(tmp_path: Path) -> None:
    with (
        local_index.serving(failures=[503] * 4) as index,
        pytest.raises(InstallCheckError, match=r"^install: `"),
    ):
        _install_probe(index, tmp_path, _caller(UV_HTTP_RETRIES="3"))
    assert index.requests[local_index.PAGE] == 4


def test_a_package_the_index_doesnt_have_fails_the_install_step_after_one_request(
    tmp_path: Path,
) -> None:
    with local_index.serving(always=404) as index, pytest.raises(InstallCheckError) as caught:
        _install_probe(index, tmp_path, _caller())
    message = str(caught.value)
    assert message.startswith("install: `")
    assert "standard error:\n" in message
    assert local_index.PROJECT in message.split("standard error:", 1)[1]
    assert index.requests[local_index.PAGE] == 1


def test_an_index_that_keeps_failing_fails_the_install_step_after_the_callers_retries(
    tmp_path: Path,
) -> None:
    """The caller's UV_HTTP_RETRIES=1 is what uv used: two requests, not the check's seven."""
    with local_index.serving(always=503) as index, pytest.raises(InstallCheckError) as caught:
        _install_probe(index, tmp_path, _caller(UV_HTTP_RETRIES="1"))
    assert str(caught.value).startswith("install: `")
    assert "503" in str(caught.value)
    assert index.requests[local_index.PAGE] == 2


def test_a_malformed_retry_count_fails_the_install_step_naming_the_variable_and_value(
    tmp_path: Path,
) -> None:
    with local_index.serving() as index, pytest.raises(InstallCheckError) as caught:
        _install_probe(index, tmp_path, _caller(UV_HTTP_RETRIES="abc"))
    message = str(caught.value)
    assert message.startswith("install: `")
    assert "UV_HTTP_RETRIES" in message
    assert "`abc`" in message
    assert sum(index.requests.values()) == 0
