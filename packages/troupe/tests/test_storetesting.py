"""The sampling the watched-delivery tests share (listener-bound-on-windows design D1, D3): five
deliveries, then one at a time while none is under BOUND, until the slow-stretch budget runs out.
Driven by scripted delays and a clock that advances by each one, so no machine is measured."""

from collections.abc import Callable

from storetesting import BOUND, watched_delays

FAST = BOUND / 2
SLOW = BOUND * 4


class Scripted:
    """A ``measure`` that returns the scripted delays in turn, and a clock that each measurement
    advances by the delay it returns."""

    def __init__(self, delays: Callable[[int], float]) -> None:
        self._delays = delays
        self.now = 0.0
        self.started: list[float] = []

    def clock(self) -> float:
        return self.now

    def measure(self) -> float:
        self.started.append(self.now)
        delay = self._delays(len(self.started) - 1)
        self.now += delay
        return delay


def test_a_fast_first_delivery_measures_exactly_five() -> None:
    script = Scripted(lambda index: FAST)
    assert watched_delays(script.measure, clock=script.clock, slow_stretch=60) == [FAST] * 5


def test_five_slow_then_a_fast_delivery_stops_at_the_fast_one() -> None:
    script = Scripted(lambda index: FAST if index == 5 else SLOW)
    delays = watched_delays(script.measure, clock=script.clock, slow_stretch=60)
    assert delays == [SLOW] * 5 + [FAST]


def test_always_slow_stops_once_the_budget_has_passed_returning_every_delay() -> None:
    script = Scripted(lambda index: SLOW)
    delays = watched_delays(script.measure, clock=script.clock, slow_stretch=10)
    # Each measurement takes 1 s, from 0 s: the one started at 9 s is the last inside the budget.
    assert delays == [SLOW] * 10, delays
    assert all(started < 10 for started in script.started), script.started
    assert script.now >= 10


def test_a_fast_delivery_within_the_first_five_still_measures_five() -> None:
    script = Scripted(lambda index: FAST if index == 2 else SLOW)
    delays = watched_delays(script.measure, clock=script.clock, slow_stretch=60)
    assert delays == [SLOW, SLOW, FAST, SLOW, SLOW]


def test_five_are_measured_even_when_they_outlast_the_budget() -> None:
    script = Scripted(lambda index: SLOW)
    assert watched_delays(script.measure, clock=script.clock, slow_stretch=2) == [SLOW] * 5
