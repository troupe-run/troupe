"""A process catching interrupts through troupe.platform.interrupts (test_platform_interrupts).

With the argument ``self``, it sends the interrupts itself, as Ctrl-C to its own console (Windows
only: the test gives it a console of its own, so nothing else receives them).

With the argument ``busy``, it writes a line of PADDING continuously after READY, so the interrupts
arrive while it is writing, and waits for BUSY_INTERRUPTS of them rather than two.

Prints READY, then INTERRUPTED <n> for each interrupt caught, and after the last, RESTORED <bool>
saying whether the previous handler came back once the block ended. The callback only counts; the
main loop prints INTERRUPTED <n>, because the handler can run inside one of the child's own prints
(#96)."""

import os
import signal
import sys
import time

from troupe.platform.interrupts import INTERRUPTS, on_interrupt

BUSY_INTERRUPTS = 10
"""How many interrupts the ``busy`` child waits for; the test sends exactly this many."""

PADDING = "." * 200


def main() -> None:
    previous = signal.getsignal(INTERRUPTS[-1])
    count = 0
    reported = 0

    def caught() -> None:
        # In the signal handler, which can run inside this process's own print: count, don't print.
        nonlocal count
        count += 1

    def report() -> None:
        nonlocal reported
        while reported < count:
            reported += 1
            print(f"INTERRUPTED {reported}", flush=True)

    sends_itself = sys.argv[1:] == ["self"]
    busy = sys.argv[1:] == ["busy"]
    target = BUSY_INTERRUPTS if busy else 2
    with on_interrupt(caught):
        print("READY", flush=True)
        deadline = time.monotonic() + 30
        while count < target and time.monotonic() < deadline:
            if sends_itself and sys.platform == "win32":
                expected = count + 1
                # Ctrl-C to every process attached to this console: only this one.
                os.kill(0, signal.CTRL_C_EVENT)
                while count < expected and time.monotonic() < deadline:
                    time.sleep(0.05)
            report()
            if busy:
                print(PADDING, flush=True)
            else:
                time.sleep(0.05)
    report()
    print(f"RESTORED {signal.getsignal(INTERRUPTS[-1]) is previous}", flush=True)
    sys.exit(0 if count == target else 1)


if __name__ == "__main__":
    main()
