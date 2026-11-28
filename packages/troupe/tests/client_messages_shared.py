"""Helpers that test_client_messages.py shares with other test modules."""

from typing import Any

# A run summary carries what its state knows (spec: client-protocol; omit-nulls design D3).

ENDED_SUMMARY: dict[str, Any] = {
    "runId": "0f8fad5b-d9cb-469f-a165-70867728950e",
    "performanceId": "7a1c0d2e-0000-4000-8000-00000000000a",
    "step": 1,
    "actor": "tester",
    "startedBy": {"kind": "unknown"},
    "runner": {"requested": "scripted", "reported": {"name": "scripted", "version": "0"}},
    "stage": {"name": "docker", "effects": "enforced"},
    "effectCheck": {"kind": "none"},
    "workspace": {"kind": "theatre"},
    "state": "ended",
    "outcome": "failed",
    "error": {
        "code": "run.error-result",
        "problem": "p",
        "fix": "f",
        "details": {"reason": "other", "message": "m"},
    },
    "events": 1,
    "startedAt": "2026-10-13T00:00:00.000Z",
    "endedAt": "2026-10-13T00:00:01.000Z",
    "transcript": "sha256:" + "a" * 64,
    "transcriptFormat": "native",
    "stderr": "sha256:" + "b" * 64,
    "audit": {"outside": []},
    "recording": {
        "failedAt": 0,
        "error": {
            "code": "run.error-result",
            "problem": "p",
            "fix": "f",
            "details": {"reason": "other", "message": "m"},
        },
    },
}
