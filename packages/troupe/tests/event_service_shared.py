"""What test_event_service.py and test_event_service_integration.py share."""

import json
from pathlib import Path
from typing import Any

from storetesting import segments


def recorded_lines(theatre: Path) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    for path in segments(theatre):
        lines.extend(json.loads(raw) for raw in path.read_bytes().splitlines()[1:])
    return lines


def lineage_of(theatre: Path, event_id: str) -> dict[str, Any]:
    [line] = [line for line in recorded_lines(theatre) if line["id"] == event_id]
    lineage: dict[str, Any] = line["state"]["lineage"]
    return lineage
