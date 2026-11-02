## MODIFIED Requirements

### Requirement: The glossary is the single source of troupe's vocabulary
`docs/prompt-book/glossary.md` SHALL hold one table row per term, each term in plain text. It SHALL have rows for
stage, rehearsal, audition, system and cue, and cue's meaning SHALL mark it as provisional. The glossary and the
house's page SHALL NOT call the house's name unconfirmed ("TBC", "isn't final").

#### Scenario: A term in code font
- **WHEN** a glossary row's term is written `` `system` ``
- **THEN** the docs check fails, naming the row, and says to write the term plainly and name any literal in its
  meaning

#### Scenario: A missing term
- **WHEN** the glossary has no row for rehearsal
- **THEN** the docs check fails, naming rehearsal

#### Scenario: No audition row
- **WHEN** the glossary has no row for audition
- **THEN** the docs check fails, naming audition
