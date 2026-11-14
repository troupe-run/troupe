"""The runner keeps the protocol channel to itself: nothing imports mistralrs before the entry
point has moved file descriptor 1 to standard error (in-process-runner design D3)."""

import subprocess
import sys


def test_importing_the_runner_does_not_import_the_engine() -> None:
    code = (
        "import sys, troupe_runner_mistralrs.runner, troupe_runner_mistralrs.conversation; "
        "print('mistralrs' in sys.modules)"
    )
    found = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, timeout=60
    )
    assert found.stdout.strip() == "False"
