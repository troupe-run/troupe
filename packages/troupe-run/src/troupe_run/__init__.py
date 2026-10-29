"""troupe-run: troupe, with the adapters and runners it bundles (install-with-uv design D1).

This package holds no code. It depends on core and every package troupe runs in its own environment,
so one `uv tool install` brings them all, and it provides core's `troupe` command.
"""
