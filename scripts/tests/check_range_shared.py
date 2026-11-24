"""What test_check_range.py and test_check_range_integration.py share."""

BEFORE, BASE, HEAD = "a" * 40, "b" * 40, "c" * 40
WHOLE = f"{BASE}...{HEAD}"


def check_run(conclusion: str | None, started_at: str | None) -> dict[str, str | None]:
    return {"status": "completed", "conclusion": conclusion, "started_at": started_at}


EARLY, LATE = "2026-10-30T13:27:32Z", "2026-10-30T13:40:05Z"
