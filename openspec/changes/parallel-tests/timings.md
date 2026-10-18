# Timings (design D7)

The check step's duration (`Check (the same script as local runs)`), in minutes, from GitHub's job API for each
successful job. The query is `gh api repos/troupe-run/troupe/actions/runs/<id>/jobs`, taking each job's check step
`completed_at - started_at`, grouped by platform across every Python version.

## Before

The 10 most recent successful CI runs on `main` (2026-10-14 to 2026-10-17): 38985041837, 38869091350,
38743365895, 38738730424, 38723920804, 38702861998, 38701586450, 38570463985, 38567862945, 38544626026.

| Platform | Jobs | Min | Median | Max |
|---|---|---|---|---|
| Ubuntu | 28 | 2.7 | 3.0 | 3.8 |
| macOS | 28 | 4.0 | 5.1 | 6.5 |
| Windows | 28 | 4.1 | 5.2 | 8.0 |

Local, macOS, one run of `uv run scripts/check.py` at 3839355: the tests gate took 293 s (1,792 passed, 7 skipped).

## After

Filled in from the five verification runs (task 6.2).
