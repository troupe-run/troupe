"""A runner's options schema is read from the installed runner's published files without importing
the runner, checked in a fresh interpreter (spec: protocol, scripted-runner; config-model design
D13, D17).

Its tests that stay in their own process are in unit/test_schemas.py."""

import subprocess
import sys

# Requirement: A plugin's published schemas are installed with it


def test_a_runners_options_schema_is_read_from_the_installed_runner_without_importing_it() -> None:
    probe = (
        "import sys\n"
        "from troupe.core import interim\n"
        "schema = interim.options_schema('scripted')\n"
        "assert schema['$id'].endswith('/runner-scripted/options.schema.json'), schema['$id']\n"
        "assert 'troupe_runner_scripted' not in sys.modules\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=False, timeout=60
    )
    assert result.returncode == 0, result.stderr
