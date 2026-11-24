"""What test_openai_capture.py and test_openai_capture_integration.py share."""

import importlib.util
import sys
from functools import cache
from pathlib import Path
from types import ModuleType

TOOL = Path(__file__).resolve().parents[1] / "tools" / "capture_openai.py"
KEY = "sk-proj-capture0123456789abcd"


@cache
def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("capture_openai", TOOL)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
