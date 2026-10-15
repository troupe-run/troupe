# The flake hunt on Linux (docs/flake-hunt.md; flake-hunt design D8). Build it from the committed tree,
# so the container holds its own copy and nothing is bind-mounted from the host:
#
#   git archive HEAD | docker build -t troupe-hunt:3.12 --build-arg PY=3.12 -f scripts/flake_hunt.Dockerfile -
#
# and run it with --init, so orphans are reaped as on a CI runner:
#
#   docker run --init --name hunt troupe-hunt:3.12 --workers 3 --rounds 10

ARG PY=3.12
FROM ghcr.io/astral-sh/uv:0.13.1-python${PY}-trixie

# Debian trixie's git (2.47) prints the same --local-env-vars the git adapter excludes.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Not root: CI runs as an ordinary user, and root changes what chmod and kill(pid, 0) do.
RUN useradd --create-home hunter
USER hunter
WORKDIR /home/hunter/troupe
COPY --chown=hunter . .

# A git checkout of the copy, as on CI, with an identity for the tests' own repositories.
RUN git init --quiet \
    && git config --global user.email hunter@example.invalid \
    && git config --global user.name "Flake hunter" \
    && git add --all \
    && git commit --quiet --message "the tree being hunted"

ARG PY
RUN uv sync --locked --python "${PY}"

ENTRYPOINT [".venv/bin/python", "scripts/flake_hunt.py", "--out", "/home/hunter/out"]
