"""Turn structured results and errors into text for a terminal."""

from troupe.core.errors import TroupeError
from troupe.platform.paths import friendly


def render_error(error: TroupeError) -> str:
    """The text written to standard error for ``error``: problem, then path, then fix."""
    lines = [f"troupe: {error.problem}"]
    if error.path is not None:
        lines.append(f"  path: {friendly(error.path)}")
    lines.append(f"  fix: {error.fix}")
    return "\n".join(lines)
