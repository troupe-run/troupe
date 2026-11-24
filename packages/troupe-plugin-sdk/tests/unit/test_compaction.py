"""The SDK's shared compaction rules (spec: plugin-sdk; compaction-opt-in design D4, D6, D7)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from troupe_plugin_sdk.compaction import Candidate, Estimate, choose, saving, stub
from troupe_plugin_sdk.defaults import BYTES_PER_TOKEN
from troupe_plugin_sdk.events import utf8_size

KB = 1024

# Requirement: The SDK chooses which tool results a runner removes


def test_the_oldest_results_are_chosen_in_order_to_the_target_never_the_latest_turns() -> None:
    candidates = [Candidate(i, "Read", 10 * KB, latest=i == 4) for i in range(5)]
    assert choose(candidates, estimate_bytes=125 * KB, target_bytes=100 * KB) == [0, 1, 2]


def test_nothing_is_chosen_when_every_result_is_in_the_latest_turn() -> None:
    candidates = [Candidate(i, "Read", 10 * KB, latest=True) for i in range(3)]
    assert choose(candidates, estimate_bytes=100 * KB, target_bytes=1) == []


def test_nothing_is_chosen_when_the_estimate_is_already_at_the_target() -> None:
    candidates = [Candidate(i, "Read", 10 * KB) for i in range(3)]
    assert choose(candidates, estimate_bytes=50 * KB, target_bytes=50 * KB) == []


def test_a_result_already_stubbed_or_no_larger_than_its_stub_is_skipped() -> None:
    small = utf8_size(stub("Grep"))
    candidates = [
        Candidate(0, "Read", 10 * KB, stubbed=True),
        Candidate(1, "Grep", small),
        Candidate(2, "Read", 10 * KB),
    ]
    assert choose(candidates, estimate_bytes=100 * KB, target_bytes=95 * KB) == [2]


def test_every_result_that_saves_something_is_chosen_when_the_target_is_out_of_reach() -> None:
    candidates = [Candidate(i, "Read", 10 * KB) for i in range(3)]
    assert choose(candidates, estimate_bytes=1000 * KB, target_bytes=1) == [0, 1, 2]


_candidates = st.lists(
    st.builds(
        Candidate,
        index=st.integers(0, 1000),
        tool=st.sampled_from(["Read", "Grep", "Glob", "Write"]),
        size=st.integers(0, 50 * KB),
        latest=st.booleans(),
        stubbed=st.booleans(),
    ),
    max_size=30,
).map(
    lambda found: [Candidate(i, c.tool, c.size, c.latest, c.stubbed) for i, c in enumerate(found)]
)


@given(_candidates, st.integers(0, 2000 * KB), st.integers(0, 2000 * KB))
def test_any_offer_never_chooses_a_protected_result_and_stops_at_the_target(
    candidates: list[Candidate], estimate: int, target: int
) -> None:
    chosen = choose(candidates, estimate, target)
    by_index = {c.index: c for c in candidates}
    remaining = estimate
    for index in chosen:
        candidate = by_index[index]
        assert not candidate.latest
        assert not candidate.stubbed
        assert saving(candidate) > 0
        # Each choice was made while the estimate was still over the target.
        assert remaining > target
        remaining -= saving(candidate)
    assert chosen == sorted(chosen)


@given(_candidates, st.integers(0, 2000 * KB), st.integers(0, 2000 * KB))
def test_any_offer_reaches_the_target_unless_every_helpful_result_was_chosen(
    candidates: list[Candidate], estimate: int, target: int
) -> None:
    chosen = choose(candidates, estimate, target)
    after = estimate - sum(saving(c) for c in candidates if c.index in chosen)
    helpful = [c.index for c in candidates if not c.latest and not c.stubbed and saving(c) > 0]
    assert after <= target or chosen == helpful


# Requirement: The SDK words the stub that replaces a tool result


def test_the_stub_of_a_read_names_read_says_why_and_how_to_get_it_back() -> None:
    text = stub("Read")
    assert "Read result" in text
    assert "to make room in the context window" in text
    assert "Call Read again if you still need it" in text


# Requirement: The SDK estimates a conversation's tokens from its bytes


def test_before_any_reported_count_the_estimate_uses_the_named_default() -> None:
    estimate = Estimate()
    assert estimate.tokens(BYTES_PER_TOKEN * 1000) == 1000


def test_after_a_reported_count_the_estimate_uses_that_requests_rate() -> None:
    estimate = Estimate()
    estimate.calibrate(request_bytes=4000, input_tokens=1000)
    assert estimate.tokens(8000) == 2000
    assert estimate.bytes(2000) == 8000


@pytest.mark.parametrize(("size", "tokens"), [(0, 1000), (4000, 0), (-1, 5)])
def test_a_count_that_tells_nothing_leaves_the_rate_unchanged(size: int, tokens: int) -> None:
    estimate = Estimate()
    estimate.calibrate(size, tokens)
    assert estimate.bytes_per_token == BYTES_PER_TOKEN


def test_a_rate_of_zero_is_refused() -> None:
    with pytest.raises(ValueError, match="bytes_per_token"):
        Estimate(0)
