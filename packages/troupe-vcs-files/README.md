# troupe-vcs-files

troupe's VCS adapter for a theatre with no version control. It reports no branch, no HEAD and no identity, and
counts every file as committed. It implements the VCS port in `troupe.core.vcs`, is registered as `files` in the
`troupe.vcs` entry point group, and runs no commands. See [docs/event-store.md](../../docs/event-store.md).
