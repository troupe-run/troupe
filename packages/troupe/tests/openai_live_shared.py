"""Helpers that test_openai_live.py shares with other test modules."""

TEST_LIMITS = {"maxTurns": 5, "maxTotalTokens": 20_000}
"""The plugin's test limits (openai-style-runner design D7): a few cents on a real service."""
