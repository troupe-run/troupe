# Design

## Context

`glossary_problems(text)` in `packages/troupe/tests/test_user_docs_vocabulary.py` parses the glossary table into
`(term, meaning)` pairs and returns a list of problem messages; `test_the_glossary_has_plain_terms_and_the_terms_it_must`
asserts the list is empty for the real glossary, and the other tests feed it edited copies of `GLOSSARY_TABLE`. It
reads the cue row with `dict(rows)`, which silently keeps the last of any duplicates. See proposal.md for why.

## Goals / Non-Goals

**Goals:**
- One more rule in `glossary_problems`, in the same shape as the others: a plain message per problem, in a stable order.

**Non-Goals:**
- Checking that two different terms don't mean the same thing (synonyms). Only the term cell is compared.
- Changing how the table is parsed, or the other rules' messages.

## Decisions

**D1. Terms are compared case-insensitively, with runs of whitespace collapsed.** A reader sees "Audition" and
"audition", or "the house" and "the  house", as the same word, and so does the website's search and anchor links. A
byte-exact comparison would let the shape of #264 back in with a capital letter. The message names the term as the
first of its rows writes it. Alternative: exact match, which is simpler but misses those cases.

**D2. One message per duplicated term, with the count:** `the glossary has 2 rows for audition: keep one`. Three
rows give one message saying 3, not two messages. The messages come in the order the terms first appear, after the
code-font messages and before the missing-term ones, so a test can compare whole lists as the existing tests do.
Line numbers aren't included: `glossary_problems` takes the table's text, the other glossary messages don't carry
lines either, and the term is enough to find both rows.

**D3. A duplicate is checked for every term, not only `REQUIRED_TERMS`.** The spec says one row per term, and a
duplicate of "stage" or "gate" is as wrong as one of "audition".

**D4. The real glossary keeps the row after rehearsal and loses the one after performance**, as the owner decided on
#264. The kept row's text is unchanged.

## Risks / Trade-offs

- [The new rule is tested only against the sample table] → the real glossary is also checked by the existing
  `test_the_glossary_has_plain_terms_and_the_terms_it_must`, which fails on `main` today once the rule exists. Run
  the rule before removing the row to see it fail on the real file, then remove the row and see it pass.
