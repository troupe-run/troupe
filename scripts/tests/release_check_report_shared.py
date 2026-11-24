"""What test_release_check_report.py and test_release_check_report_integration.py share."""

import copy
from typing import Any

RUN = "https://github.com/troupe-run/troupe/actions/runs/41181494838"
RELEASE = "https://github.com/troupe-run/troupe/releases/tag/troupe-run-v0.1.0"
TAG = "troupe-run-v0.1.0"


def job(
    name: str, conclusion: str, database_id: int, started: str, completed: str
) -> dict[str, Any]:
    return {
        "completedAt": completed,
        "conclusion": conclusion,
        "databaseId": database_id,
        "name": name,
        "startedAt": started,
        "status": "completed",
        "steps": [
            {
                "completedAt": started,
                "conclusion": "success",
                "name": "Set up job",
                "number": 1,
                "startedAt": started,
                "status": "completed",
            }
        ],
        "url": f"{RUN}/job/{database_id}",
    }


JOBS: dict[str, Any] = {
    "jobs": [
        job(
            "What does it need?",
            "success",
            124479654360,
            "2026-10-31T07:40:01Z",
            "2026-10-31T07:40:08Z",
        ),
        job(
            "install (ubuntu-latest, Python 3.12)",
            "success",
            124479681699,
            "2026-10-31T07:40:09Z",
            "2026-10-31T07:43:10Z",
        ),
        job(
            "install (windows-latest, Python 3.15)",
            "success",
            124479681805,
            "2026-10-31T07:40:09Z",
            "2026-10-31T07:52:41Z",
        ),
        job(
            "install (macos-latest, Python 3.13)",
            "success",
            124479681743,
            "2026-10-31T07:40:09Z",
            "2026-10-31T07:45:02Z",
        ),
        job(
            "install (windows-latest, Python 3.12)",
            "success",
            124479681847,
            "2026-10-31T07:40:09Z",
            "2026-10-31T07:51:30Z",
        ),
        job("report", "success", 124481487575, "2026-10-31T07:52:45Z", "2026-10-31T07:52:52Z"),
    ]
}


def failing(*legs: tuple[str, str, str]) -> dict[str, Any]:
    """The jobs, with each (runner, python, conclusion) leg concluding as given."""
    jobs = copy.deepcopy(JOBS)
    for runner, python, conclusion in legs:
        [entry] = [j for j in jobs["jobs"] if j["name"] == f"install ({runner}, Python {python})"]
        entry["conclusion"] = conclusion
    return jobs
