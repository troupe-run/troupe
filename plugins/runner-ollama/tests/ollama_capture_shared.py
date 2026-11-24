"""What test_ollama_capture.py and test_ollama_capture_unit.py share."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

TOOL = Path(__file__).resolve().parents[1] / "tools" / "capture_ollama.py"


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("capture_ollama", TOOL)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["capture_ollama"] = module
    spec.loader.exec_module(module)
    return module
