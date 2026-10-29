# troupe-run

What you install to run troupe. It holds no code of its own: it depends on `troupe`, every adapter bundled with it,
and the scripted and Claude Code runners, and it provides the `troupe` command. Core finds its adapters and starts
its runners in its own environment, so they're installed together.

Install it with [uv](https://docs.astral.sh/uv/), from `main` or, in place of `main`, a commit:

```sh
uv tool install "git+https://github.com/troupe-run/troupe@main#subdirectory=packages/troupe-run"
```

See [Install](https://troupe.run/docs/opening-night/install/) for more.
