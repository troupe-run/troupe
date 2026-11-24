"""What test_cli_startup.py and test_cli_startup_unit.py share."""

FAMILIES = {
    "runs": "troupe.core.runs",
    "config": "troupe.core.config.commands",
    "init": "troupe.core.init",
}
"""Each family of the core's commands, by the module its handlers live in."""
