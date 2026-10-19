# troupe-identity-local

troupe's local identity sources: `env` (the `TROUPE_ACTOR` override), `vcs` (the identity the VCS adapter is
configured with, such as git's `user.email`) and `os-login`. Each implements the identity source port in
`troupe.core.identity` and is registered in the `troupe.identity` entry point group. See
[contributing/event-store.md](../../contributing/event-store.md#identity).
