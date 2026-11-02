# Tasks

## 1. The docs check requires an audition row (design D1)

- [ ] 1.1 In `packages/troupe/tests/test_user_docs_vocabulary.py`, add audition to the sample `GLOSSARY_TABLE` and a
  case for the spec's "No audition row" scenario that removes it and asserts
  `glossary_problems(table) == ["the glossary has no row for audition"]`, before changing `REQUIRED_TERMS`. Verify
  with `uv run pytest packages/troupe/tests/test_user_docs_vocabulary.py` that the new case fails (the check says
  nothing) and every other case passes, and record the result here.
- [ ] 1.2 Add audition to `REQUIRED_TERMS`, after rehearsal. Verify the new case passes and
  `test_the_glossary_has_plain_terms_and_the_terms_it_must` now fails on the real glossary, naming audition, and
  record it here.

## 2. The glossary has the row (design D2)

- [ ] 2.1 In `docs/prompt-book/glossary.md`, add the audition row from design D2 straight after the rehearsal row.
  Verify `uv run pytest packages/troupe/tests/test_user_docs_vocabulary.py` passes in full, and read the row against
  the brand guide's status quoted in the proposal.
- [ ] 2.2 Run `uv run scripts/check.py` and verify it passes; record the result here.

## Workflow follow-up

- Open the draft pull request with `Closes #257`, and say on troupe-run/website#85 that the row is on its way.
- After the merge, comment on #257 with the pull request and the archived change, check its card on the roadmap board
  says Done, and tell website#85 to re-sync so its vocabulary check can run against `main`.
