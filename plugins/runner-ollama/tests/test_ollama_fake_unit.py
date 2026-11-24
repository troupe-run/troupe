"""The fake Ollama's done line holds a cached prompt count only when a test gives one, so the
runner's tests can trust it (local-model-runner design D12).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_ollama_fake.py."""

from fake_ollama import done


def test_a_done_line_holds_a_cached_count_only_when_given_one() -> None:
    assert done(cached=4)["prompt_eval_cached_count"] == 4
    assert "prompt_eval_cached_count" not in done()
