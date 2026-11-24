"""What test_claude_code_capture.py and test_claude_code_capture_integration.py share."""

import importlib.util
from pathlib import Path
from types import ModuleType

TOOL = Path(__file__).resolve().parents[1] / "tools" / "capture_claude.py"


def _tool() -> ModuleType:
    """The capture tool, a script rather than a package module, loaded from its path."""
    spec = importlib.util.spec_from_file_location("capture_claude", TOOL)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
