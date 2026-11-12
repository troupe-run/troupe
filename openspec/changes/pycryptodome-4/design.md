# Design

## Context

See proposal.md, "Why". What the update can reach:

- pycryptodome is named once, in the root `pyproject.toml`'s `dev` group. No package or plugin depends on it, and
  nothing in `packages/`, `plugins/`, `scripts/` or `tests/` imports `Crypto` or `Cryptodome`.
- The one use is in eventsourcing 9.5.6 (locked). `eventsourcing/cipher.py` defines `AESCipher`, and
  `eventsourcing/tests/persistence.py` imports it at module scope. `packages/troupe-store-text/tests/test_library_suite.py`
  imports that module to run the library's recorder suite unmodified (spec: event-store, "The store meets the
  library's recorder contract"). Its `test_mapper_with_cipher` and `test_mapper_with_cipher_and_compressor` encrypt
  and decrypt with `AESCipher`.
- `AESCipher` uses `Crypto.Cipher.AES` (`new`, `MODE_GCM`, `key_size`), the private `Crypto.Cipher._mode_gcm.GcmMode`
  for an `isinstance` check and a return type, and GCM's `encrypt_and_digest` and `decrypt_and_verify`. It relies on
  a wrong tag raising `ValueError`.

## Goals / Non-Goals

**Goals:**

- Land the same update as Dependabot's #343, with each use checked against 4.x's breaking changes.

**Non-Goals:**

- Using any of 4.x's new features (ML-KEM, ML-DSA, the hybrid keys, the one-call `digest()`).
- Changing eventsourcing's version or how troupe-store-text runs its suite.

## Decisions

### D1. Nothing troupe runs is affected by 4.0.0's breaking changes

Each breaking change in pycryptodome's `Changelog.rst` (4.0.0), checked against the uses above:

| 4.0.0 breaking change | Reaches troupe? |
|---|---|
| Python 2.7 and 3.8 dropped; minimum is 3.9 | No: troupe requires 3.12+ |
| `pycryptodomex` (`Cryptodome` namespace) no longer released | No: nothing imports `Cryptodome` |
| Self-tests need pytest; `setup.py test` removed | No: troupe never runs them |
| `SP800_108_Counter()` label and context rules | No: not used |
| ECC and ElGamal components are `int`, not `Integer` | No: not used |
| GMP dropped; `Integer` has no negative values | No: not used |
| Stricter EC and EdDSA point decoding | No: not used |
| RSA modulus capped at 16384 bits | No: not used |
| `bcrypt_check()` rejects cost above 20 | No: not used |
| ChaCha20-Poly1305 with an 8-byte nonce follows RFC 8439 | No: not used |
| Passphrase key export defaults to PKCS#8 and PBKDF2-SHA256 | No: no keys are exported |
| `long2str()` and `str2long()` removed | No: not used |

None of the breaking changes touches AES or GCM. One resolved issue does: AEAD modes now compare tags with
`hmac.compare_digest()`. Checked on pycryptodome 4.2.0 in an isolated environment (CPython 3.12): `Crypto.__version__`
is `4.2.0`; `Crypto.Cipher._mode_gcm.GcmMode` and `Crypto.Cipher.AES.key_size` import, and `key_size` is
`(16, 24, 32)`; `AES.new(key, AES.MODE_GCM, nonce)` is a `GcmMode`; `encrypt_and_digest` then `decrypt_and_verify`
round-trips; and a wrong tag still raises `ValueError` ("MAC check failed"). The full check repeats this through
eventsourcing's own cipher cases, against the locked versions on every CI leg.

The 4.0.0 deprecations (`HMAC.new()` without `digestmod`, `PBKDF2()` without `count` or a hash) don't apply either:
`AESCipher` calls neither, so no new `DeprecationWarning` can reach pytest's warning filters.

### D2. Take Dependabot's line as it is: `pycryptodome>=4.2.0`

The workflow asks for the same update as Dependabot's pull request, and the lower bound records the version the lock
was checked against. Alternatives considered:

- **Keep `>=3.23` and only move the lock.** It hides the major update from anyone who reads `pyproject.toml`, and
  lets a fresh resolve that ignores the lock pick a 3.x that wasn't checked.
- **Add a cap (`<5`).** The other unpinned dev dependencies (`pytest-xdist`, `hypothesis`, `mypy`) have none, and
  a future major comes as a Dependabot major update that needs a change anyway.

The lock is regenerated with `uv lock --upgrade-package pycryptodome`, and its diff is compared with #343's: the
same pycryptodome entry and the same dev-group specifier, nothing else.

### D3. Dependabot's #343 is closed only after this change merges

Closing a Dependabot pull request while its issue is open closes the issue as not planned an hour later
(development-workflow, "Dependabot pull requests"). So this change's pull request closes #250 when it merges. Then
Dependabot closes #343 as up to date, or, if it's still open, it's closed by hand with a comment that links this
pull request.

## Risks / Trade-offs

- [`AESCipher` imports a private module, `Crypto.Cipher._mode_gcm`, which a later 4.x could move] → It works in
  4.2.0, and moving it would break the import of `eventsourcing.tests.persistence`, so `test_library_suite.py`
  would fail at collection on every leg, not quietly. Dependabot's minor updates run the full check before merging.
- [4.2.0 has no wheels for the free-threaded CPython 3.13t and 3.14t, which 3.24.1 had] → CI's matrix runs the
  standard builds only, which the `cp39-abi3` wheels cover on all three systems. A free-threaded leg would need
  pycryptodome built from source, or a wheel from a later release.

## Migration Plan

None: it's a dev dependency. `uv sync` installs 4.2.0. To roll back, revert the commit.
