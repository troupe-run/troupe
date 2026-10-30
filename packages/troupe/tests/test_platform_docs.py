import re
from pathlib import Path
from types import ModuleType

import pytest

from troupe.core import defaults
from troupe_vcs_git import defaults as git_defaults

pytestmark = pytest.mark.docs  # reads docs/ (scripts/check-paths.toml)

DOCS = Path(__file__).resolve().parents[3] / "contributing"
DOC = DOCS / "platform.md"
ROW = re.compile(r"^\| `([A-Z_]+)` \| ([0-9.]+|true|false) \|", re.MULTILINE)


def _documented(doc: Path) -> dict[str, float]:
    return {
        name: 1.0 if value == "true" else 0.0 if value == "false" else float(value)
        for name, value in ROW.findall(doc.read_text(encoding="utf-8"))
    }


def _numeric(module: ModuleType) -> dict[str, float]:
    return {
        name: float(value)
        for name, value in vars(module).items()
        if name.isupper() and isinstance(value, int | float)
    }


def test_the_docs_list_exactly_the_defaults_and_their_values_each_in_one_place() -> None:
    platform = _documented(DOC)
    runners = _documented(DOCS / "runners.md")
    events = _documented(DOCS / "event-store.md")
    runs = _documented(DOCS / "runs.md")
    config = _documented(DOCS / "config.md")
    assert platform.keys().isdisjoint(runners)
    assert events.keys().isdisjoint(platform | runners)
    assert runs.keys().isdisjoint(platform | runners | events)
    assert config.keys().isdisjoint(platform | runners | events | runs)
    # Adapters keep their limits in their own package (event-store design D11); the platform doc
    # lists the git adapter's beside troupe's own.
    assert {**platform, **runners, **events, **runs, **config} == _numeric(defaults) | _numeric(
        git_defaults
    )


def test_platform_doc_has_a_row_for_every_platform_module() -> None:
    modules = {
        path.name
        for path in (DOC.parents[1] / "packages" / "troupe" / "src" / "troupe" / "platform").glob(
            "*.py"
        )
        if path.name not in {"__init__.py", "errors.py"}
    }
    documented = set(
        re.findall(r"^\| [^|]+ \| `platform/(\w+\.py)` \|", DOC.read_text(encoding="utf-8"), re.M)
    )
    assert documented == modules
