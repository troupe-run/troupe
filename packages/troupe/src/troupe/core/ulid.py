"""ULIDs that sort in the order this process made them (event-store design D4, D8).

A ULID is 48 bits of milliseconds and 80 random bits, written as 26 characters of Crockford
base32, so ULIDs sort by time. Two made in the same millisecond would sort by chance, so within a
process the random part is incremented instead: every ULID sorts after the one before it, even when
the clock stands still or steps back (cladus finding: same-millisecond files otherwise sort
wrongly).
"""

import os
import threading
import time

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_RANDOM_BITS = 80

_lock = threading.Lock()
_last_time = -1
_last_random = 0


def new_ulid() -> str:
    """A new ULID, greater than every ULID this process made before."""
    global _last_time, _last_random
    with _lock:
        now = time.time_ns() // 1_000_000
        if now > _last_time:
            _last_time = now
            _last_random = int.from_bytes(os.urandom(10), "big")
        else:
            _last_random += 1
            if _last_random >> _RANDOM_BITS:
                _last_time += 1  # the random part overflowed: borrow the next millisecond
                _last_random = 0
        value = (_last_time << _RANDOM_BITS) | _last_random
    return "".join(ALPHABET[(value >> shift) & 31] for shift in range(125, -1, -5))
