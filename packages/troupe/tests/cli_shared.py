"""What test_cli.py and test_cli_integration.py share."""

from importlib.metadata import version

from troupe.core import schemas

# Requirement: Version reporting

VERSION_LINE = f"troupe {version('troupe')} (protocol {schemas.protocol_version()})\n"
