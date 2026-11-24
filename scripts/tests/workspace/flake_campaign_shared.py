"""What test_flake_campaign.py and test_flake_campaign_integration.py share."""

import sys

import flake_campaign

ROOT = flake_campaign.ROOT
WINDOWS = sys.platform == "win32"


def options(*argv: str) -> flake_campaign.Options:
    return flake_campaign.parse_options(list(argv))
