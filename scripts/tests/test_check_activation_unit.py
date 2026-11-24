"""Task 7.1: running the check turns the git hooks on by default.

Its tests that start a process, open a socket or use a git theatre are in
integration/test_check_activation.py."""

from pathlib import Path

import check


def test_a_directory_that_isn_t_a_git_checkout_is_left_alone(tmp_path: Path) -> None:
    assert check.activate_git_hooks(tmp_path) is None
