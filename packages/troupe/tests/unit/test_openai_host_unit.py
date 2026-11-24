"""Checks that the test limits the OpenAI stand-in service, the plugin's harness and the live tests
each hold are the same (spec: openai-runner; openai-style-runner design D13).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_openai_host.py."""

import openai_stand_in


def test_the_three_copies_of_the_test_limits_agree() -> None:
    import importlib.util

    import openai_live_shared

    harness = openai_stand_in.PLUGIN / "tests" / "openai_harness.py"
    spec = importlib.util.spec_from_file_location("openai_harness_for_limits", harness)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert openai_stand_in.TEST_LIMITS == module.TEST_LIMITS == openai_live_shared.TEST_LIMITS
