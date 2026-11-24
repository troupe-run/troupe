"""Helpers that test_mistralrs_fixtures.py shares with other test modules."""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CASES = sorted(path.name for path in FIXTURES.iterdir() if path.is_dir())
CAPTURE = Path(__file__).resolve().parents[1] / "tools" / "capture_mistralrs.py"


def _capture() -> ModuleType:
    spec = importlib.util.spec_from_file_location("capture_mistralrs", CAPTURE)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["capture_mistralrs"] = module
    spec.loader.exec_module(module)
    return module


def _load(case: str, name: str) -> Any:  # noqa: ANN401 - JSON
    return json.loads((FIXTURES / case / name).read_text(encoding="utf-8"))


def _filled(value: Any, workspace: str, scratch: str) -> Any:  # noqa: ANN401 - JSON
    """``value`` with the placeholders put back as this replay's paths."""
    text = json.dumps(value)
    for placeholder, path in (("<workspace>", workspace), ("<scratch>", scratch)):
        text = text.replace(placeholder, json.dumps(path)[1:-1])
    return json.loads(text)
