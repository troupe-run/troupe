"""Helpers that test_anthropic_live.py shares with other test modules."""

TEST_LIMITS = {"maxTurns": 5, "maxTotalTokens": 20_000}
"""The plugin's test limits: a few cents on Claude's API."""
