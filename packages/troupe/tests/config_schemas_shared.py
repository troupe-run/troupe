"""What test_config_schemas.py and test_config_schemas_integration.py share."""

import importlib.util
from types import ModuleType

from protocol_schemas import ROOT


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "generate_models", ROOT / "scripts" / "generate_models.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


generator = _load()
