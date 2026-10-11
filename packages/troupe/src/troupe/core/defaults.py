"""Default values for troupe's limits, in one named place (design D6).

Every timeout, size or other limit troupe uses has its default here. Callers can override each one;
the ``settings`` capability will later let configuration override them too, bounded by policy.
"""

LOCK_TIMEOUT_SECONDS = 30.0
"""How long to wait for another process's lock before giving up."""

LOCK_ANNOUNCE_AFTER_SECONDS = 1.0
"""How long a lock wait lasts before troupe says what it is waiting for."""

REPLACE_TIMEOUT_SECONDS = 10.0
"""How long to keep retrying a file replacement that another program is blocking (Windows)."""

REPLACE_ANNOUNCE_AFTER_SECONDS = 1.0
"""How long a blocked replacement lasts before troupe says which file it is waiting for."""
