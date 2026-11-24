"""What test_anthropic_service.py and test_anthropic_service_unit.py share."""

import os

import pytest

KEY = "sk-ant-canary-0123456789"


@pytest.fixture(name="clean_environment", autouse=True)
def clean_environment_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    """No ANTHROPIC_* variable of the machine's own reaches a test; each test sets its own, and
    monkeypatch restores them, whatever the runner removed."""
    for name in [n for n in os.environ if n.upper().startswith("ANTHROPIC_")]:
        monkeypatch.delenv(name)
