"""The install check's steps run for real: a ref resolves to its full commit or is refused by name,
a failing or timed-out step is named with its command and output, and installs from a local index
show the check's retry count outlasting failures that uv's default wouldn't (spec: installation;
install-with-uv design D3 and D4).

Its tests that stay in their own process are in unit/test_install_check.py."""

import os
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path

import local_index
import pytest
from conftest import REPO

import install_check
from install_check import InstallCheckError, Tools


def test_a_ref_is_resolved_to_its_full_commit() -> None:
    sha = install_check.resolve(REPO, "HEAD")
    assert len(sha) == 40
    assert install_check.resolve(REPO, sha) == sha


def test_a_ref_that_names_no_commit_is_refused_by_name() -> None:
    refused = r"--ref 'no-such-ref-for-the-install-check' isn't a commit"
    with pytest.raises(InstallCheckError, match=refused):
        install_check.resolve(REPO, "no-such-ref-for-the-install-check")


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
