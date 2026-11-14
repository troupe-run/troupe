"""The mistralrs runner with the engine stand-in: a test-only entry point, so production code has
no hook for it (in-process-runner design D10). The stand-in's script is the JSON file
TROUPE_MISTRALRS_STAND_IN names; without one, it serves one short successful run, as the
conformance suite needs.

Run it as ``python stand_in_runner.py``.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from stand_in import StandIn, response
from troupe_runner_mistralrs.runner import main

DEFAULT = {"responses": [response("Done.", prompt=120, completion=5)]}

if __name__ == "__main__":
    named = os.environ.get("TROUPE_MISTRALRS_STAND_IN")
    script = json.loads(Path(named).read_text(encoding="utf-8")) if named else DEFAULT
    stand_in = StandIn(script)
    main(loader=stand_in.load, check=stand_in.check)
