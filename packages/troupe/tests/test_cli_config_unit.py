"""The config command group on the command line: config with no command is refused naming the
commands it takes, and a flag a config command doesn't take is refused as an unknown flag (spec:
cli, config; config-model design D10).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_cli_config.py."""

import pytest

from troupe.cli import COMMANDS
from troupe.cli.parser import parse
from troupe.core.errors import TroupeError

# The config group on the command line


def test_config_alone_needs_one_of_its_commands() -> None:
    with pytest.raises(TroupeError) as caught:
        parse(["config"], COMMANDS)
    assert caught.value.code == "usage.missing-argument"
    assert "set, unset, mv, get, drop or keep" in caught.value.problem


def test_a_config_commands_unknown_flag_is_refused_naming_it() -> None:
    with pytest.raises(TroupeError) as caught:
        parse(["config", "get", "--force"], COMMANDS)
    assert caught.value.code == "usage.unknown-flag"
