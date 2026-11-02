# Tasks

## 1. The docs check refuses a duplicate term

- [ ] 1.1 Add the tests first, in `packages/troupe/tests/test_user_docs_vocabulary.py` (spec: "A duplicate term", "A duplicate that differs only in case or spacing"; design D1, D2): `test_a_term_with_two_rows_is_named_once_with_its_count` (an extra audition row placed after cue in `GLOSSARY_TABLE` gives exactly `["the glossary has 2 rows for audition: keep one"]`), `test_a_term_with_three_rows_is_named_once_with_its_count`, and `test_terms_that_differ_only_in_case_or_spacing_are_duplicates` (rows "the house" and "The  House" give one message naming "the house" with 2 rows). Verify: `uv run pytest packages/troupe/tests/test_user_docs_vocabulary.py` fails on exactly these three, because `glossary_problems` doesn't check duplicates yet
- [ ] 1.2 In `glossary_problems`, report each term with more than one row (every term, design D3), comparing terms case-folded with runs of whitespace collapsed, one message per term in order of first appearance, after the code-font messages and before the missing-term ones (design D2). Update the module's docstring or comments only if they describe the rules. Verify: the three new tests and the existing rule tests pass, and `test_the_glossary_has_plain_terms_and_the_terms_it_must` now fails on the real glossary with `the glossary has 2 rows for audition: keep one`; record that output here

## 2. One audition row

- [ ] 2.1 Remove the audition row after "performance" from `docs/prompt-book/glossary.md` (#260's), keeping the one after "rehearsal" unchanged (design D4, owner on #264). Verify: `git diff docs/` shows that one line removed and nothing else, `grep -c '^| audition |' docs/prompt-book/glossary.md` prints 1, and `uv run pytest packages/troupe/tests/test_user_docs_vocabulary.py` passes

## 3. Verify

- [ ] 3.1 Run `openspec validate one-audition-row --strict` and `uv run scripts/check.py`. Verify: validation passes and every gate passes; record the counts here
- [ ] 3.2 Push and let CI run on Linux, macOS and Windows once the PR is marked ready. Verify: every leg of the run on the last code commit passes; record the run here

## Workflow follow-up

- Open the PR as a draft with `Closes #264`; mark it ready once the review of the last push is clean, so CI runs on all three platforms.
- Act on Claude's review of the last push, then archive the change on the branch (`/opsx:archive`) before merging. The `user-docs` delta syncs at archive; no Purpose changes, so no `oob/troupe-spec-purposes.json` update.
- After the merge, comment on #264 with the PR and the archived change, check it's closed, and check its card on the roadmap board says Done.
