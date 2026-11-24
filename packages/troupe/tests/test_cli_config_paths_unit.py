"""A config change entry or conflict at a key that holds a dot is shown with that key in brackets,
the form it is typed in (spec: config, "A config path is shown in the form it is typed";
config-path-dotted-keys design D3, D4).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_cli_config_paths.py."""

import io

from cli_config_paths_shared import PRICE
from troupe.cli import config as cli_config


def test_an_entry_at_a_key_that_holds_a_dot_is_shown_in_brackets() -> None:
    shown = io.StringIO()
    cli_config._render_change(
        {"entries": [{"path": PRICE, "after": 2}, {"path": PRICE[:4]}], "files": [], "notices": []},
        shown,
        rehearse=False,
    )
    assert shown.getvalue().splitlines() == [
        "set runtimes.openai.prices[gpt-4.1].input",
        "unset runtimes.openai.prices[gpt-4.1]",
    ]


def test_a_conflict_at_a_key_that_holds_a_dot_is_shown_in_brackets() -> None:
    lines = cli_config._conflict_lines({"paths": [PRICE], "changes": []})
    assert lines == [
        "conflict at runtimes.openai.prices[gpt-4.1].input: these changes set it differently"
    ]
