"""Checks that the test limits the Anthropic stand-in service, the plugin's harness and the live
tests each hold are the same (spec: anthropic-runner; anthropic-runner design D14).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_anthropic_host.py."""

import anthropic_stand_in


def test_the_three_copies_of_the_test_limits_agree() -> None:
    import importlib.util

    import anthropic_live_shared

    harness = anthropic_stand_in.PLUGIN / "tests" / "anthropic_harness.py"
    spec = importlib.util.spec_from_file_location("anthropic_harness_for_limits", harness)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert anthropic_stand_in.TEST_LIMITS == module.TEST_LIMITS == anthropic_live_shared.TEST_LIMITS
