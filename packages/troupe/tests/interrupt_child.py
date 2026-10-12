"""A process catching interrupts through troupe.platform.interrupts (test_platform_interrupts).

Prints READY, then INTERRUPTED <n> for each interrupt caught, and after the second, RESTORED <bool>
saying whether the previous handler came back once the block ended."""

import signal
import sys
import time

from troupe.platform.interrupts import INTERRUPTS, on_interrupt


def main() -> None:
    previous = signal.getsignal(INTERRUPTS[-1])
    count = 0

    def caught() -> None:
        nonlocal count
        count += 1
        print(f"INTERRUPTED {count}", flush=True)

    with on_interrupt(caught):
        print("READY", flush=True)
        deadline = time.monotonic() + 30
        while count < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
    print(f"RESTORED {signal.getsignal(INTERRUPTS[-1]) is previous}", flush=True)
    sys.exit(0 if count == 2 else 1)


if __name__ == "__main__":
    main()
