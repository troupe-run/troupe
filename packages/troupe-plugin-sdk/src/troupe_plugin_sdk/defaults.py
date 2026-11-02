"""Every limit the SDK applies, with its default, in one place (spec: runner-tools, "Results are
capped by named limits"; runner-sdk design D10).

A runner passes ``ToolLimits`` to lower any of them. None can be raised above its default here, so
a runner can tighten what a model gets back, never loosen it.
"""

from dataclasses import dataclass, fields

READ_MAX_BYTES = 256 * 1024
"""The UTF-8 bytes of file text ``Read`` returns in one call. The model reads on with ``offset``."""

READ_MAX_LINES = 2000
"""The lines ``Read`` returns in one call when the model gives no ``limit``, and the most it may ask
for."""

FILE_MAX_BYTES = 16 * 1024 * 1024
"""The largest file ``Read`` and ``Edit`` load. Both read a whole file, so a larger one is an error
result rather than a runner holding it all in memory."""

GLOB_MAX_PATHS = 1000
"""The paths ``Glob`` returns in one call."""

GREP_MAX_MATCHES = 500
"""The matching lines ``Grep`` returns in one call."""

GREP_FILE_MAX_BYTES = 1024 * 1024
"""The largest file ``Grep`` searches. A larger one is skipped and counted, which also bounds how
long one search of a file can take."""

SUMMARY_MAX_BYTES = 4096
"""The UTF-8 bytes one summary field of a run event keeps (``inputSummary``, ``outputSummary``),
before run/start's ``eventMaxBytes`` cuts it further. The Claude Code runner's limit too."""


@dataclass(frozen=True)
class ToolLimits:
    """The limits one ``Tools`` applies. Each defaults to its named default, and may be lowered."""

    read_max_bytes: int = READ_MAX_BYTES
    read_max_lines: int = READ_MAX_LINES
    file_max_bytes: int = FILE_MAX_BYTES
    glob_max_paths: int = GLOB_MAX_PATHS
    grep_max_matches: int = GREP_MAX_MATCHES
    grep_file_max_bytes: int = GREP_FILE_MAX_BYTES
    summary_max_bytes: int = SUMMARY_MAX_BYTES

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            default = field.default
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"ToolLimits.{field.name} must be a whole number of at least 1")
            if isinstance(default, int) and value > default:
                raise ValueError(
                    f"ToolLimits.{field.name} is {value}, above its default {default}: a runner "
                    "can lower a limit, never raise it"
                )
