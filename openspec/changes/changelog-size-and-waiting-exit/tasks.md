## 1. Size gate

- [ ] 1.1 Add `**/CHANGELOG.md` to `[size] exclude` in `quality-gates.toml`, with the reason in its comment. Verify:
  a changelog grown past 49,152 bytes in a scratch commit passes `uv run scripts/check.py`'s size gate, and a
  Markdown file grown past it still fails (run `scripts/quality_gates.py size` against a base).

## 2. Perform's waiting message

- [ ] 2.1 Change `_settle_hint`'s waiting branch to D2's text. Update the two unit tests in
  `packages/troupe/tests/unit/test_cli_perform_unit.py`, so the exact string covers the conflict case and the no-conflict case
  checks "succeeded", the role and "exit 4 means waiting for director, not failure". Verify: the tests fail on the old
  text and pass on the new.
- [ ] 2.2 Verify: the integration tests that match "waits at its gate for director" still pass
  (`test_cli_init.py`, `test_user_docs_pages_integration.py`).

## 3. Walkthrough

- [ ] 3.1 Rewrite the exit-4 sentence in `docs/opening-night/first-performance.md` (D3), and check
  `docs/the-company/gates-and-decisions.md` and `docs/prompt-book/cli.md` agree.
- [ ] 3.2 Add a docs unit test: the walkthrough says exit 4 means the run succeeded and waits, not failure, and the
  exit-code table gives 4 as `WAITING`. Verify: it fails on the old page.

## 4. Check

- [ ] 4.1 `uv run scripts/check.py` passes. `openspec validate changelog-size-and-waiting-exit --strict` passes.
