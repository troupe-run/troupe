# troupe-vcs-git

troupe's git adapter. It implements the VCS port in `troupe.core.vcs` by running git with a declared environment
policy (`troupe_vcs_git.defaults.GIT_ENVIRONMENT`), and is registered as `git` in the `troupe.vcs` entry point
group. See [contributing/event-store.md](../../contributing/event-store.md).
