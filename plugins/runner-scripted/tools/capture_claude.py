"""Capture real Claude Code stream-json as a scripted-runner fixture (design D14). Not run in CI.

Usage:
    python capture_claude.py <fixture> <output directory>

Fixtures that need no credential (an invalid key against a local fake API, so nothing reaches
Anthropic):
    is-error-success-subtype  the key is refused, no retries: init, then an error under "success"
    auth-retries              the same with two retries: api_retry events, then the error result
    terminated-no-result      retries, then SIGTERM during the backoff: no result at all

The one fixture that needs a real credential is captured by the owner, never in an agent session:
    success-with-tools        needs CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY: one short run
                              that writes a file and reads it back, pinned model, budget-capped

The tool writes recording.jsonl (each native line as {"transcript": ..., "atMs": ...}, scrubbed)
and provenance.json. The paired run events and expected.json are written by hand afterwards.
"""

import http.server
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MODEL = "claude-haiku-5-5"
BUDGET_USD = "0.10"
SUCCESS_PROMPT = (
    "Use the Write tool to create out/hello.txt containing exactly: hi\n"
    "Then use the Read tool to read it back, and reply with one word: done."
)
OFFLINE_PROMPT = "say hi"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


class _RefuseEveryKey(http.server.BaseHTTPRequestHandler):
    """A stand-in for api.anthropic.com that refuses the key, so no request ever succeeds."""

    def _refuse(self) -> None:
        self.rfile.read(int(self.headers.get("content-length") or 0))
        self.send_response(401)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(
            b'{"type":"error","error":{"type":"authentication_error",'
            b'"message":"invalid x-api-key"}}'
        )

    do_GET = do_POST = _refuse  # noqa: N815 - the names http.server dispatches to

    def log_message(self, *args: Any) -> None:  # noqa: ANN401
        pass


def _fake_api() -> tuple[http.server.ThreadingHTTPServer, str]:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _RefuseEveryKey)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


class Scrubber:
    """Replaces what identifies the capturing machine or run with fixed values, consistently."""

    def __init__(self, replacements: dict[str, str]) -> None:
        # Longest first, so a path is replaced before any of its prefixes.
        self.replacements = sorted(replacements.items(), key=lambda kv: -len(kv[0]))
        self.uuids: dict[str, str] = {}

    def _uuid(self, match: re.Match[str]) -> str:
        found = match.group(0)
        if found not in self.uuids:
            self.uuids[found] = f"00000000-0000-4000-8000-{len(self.uuids) + 1:012d}"
        return self.uuids[found]

    def __call__(self, line: str) -> str:
        for old, new in self.replacements:
            line = line.replace(old, new)
        return UUID.sub(self._uuid, line)

    def describe(self) -> list[str]:
        return [
            "the temporary workspace -> /workspace",
            "the temporary home and config directories -> ~",
            "the capturing user's home directory -> ~, and their login name -> user",
            "the fake API's port -> 8080",
            "every UUID (session ids, message ids) -> 00000000-0000-4000-8000-<n>, consistently",
        ]


def capture(fixture: str, out: Path) -> None:
    owner_run = fixture == "success-with-tools"
    if fixture not in {
        "is-error-success-subtype",
        "auth-retries",
        "terminated-no-result",
        "success-with-tools",
    }:
        sys.exit(f"capture: unknown fixture {fixture!r}")
    claude = shutil.which("claude")
    if claude is None:
        sys.exit("capture: claude isn't on PATH. Fix: install Claude Code.")
    version = subprocess.run(
        [claude, "--version"], capture_output=True, text=True, check=True
    ).stdout.split()[0]
    scratch = Path(tempfile.mkdtemp(prefix="troupe-capture-"))
    workspace, home = scratch / "workspace", scratch / "home"
    workspace.mkdir()
    home.mkdir()
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "CLAUDE_CONFIG_DIR": str(home / ".claude"),
        "DISABLE_AUTOUPDATER": "1",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
    }
    flags = ["--output-format", "stream-json", "--verbose", "--no-session-persistence"]
    server = None
    if owner_run:
        for name in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"):
            if name in os.environ:
                env[name] = os.environ[name]
        if not {"CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"} & set(env):
            sys.exit("capture: set CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY for this fixture")
        prompt = SUCCESS_PROMPT
        flags += [
            "--setting-sources",
            "",
            "--strict-mcp-config",
            "--model",
            MODEL,
            "--max-budget-usd",
            BUDGET_USD,
            "--permission-mode",
            "acceptEdits",
            "--allowedTools",
            "Write,Read",
        ]
        env["CLAUDE_CODE_MAX_RETRIES"] = "2"
    else:
        server, base_url = _fake_api()
        env["ANTHROPIC_BASE_URL"] = base_url
        env["ANTHROPIC_API_KEY"] = "sk-troupe-capture-deliberately-invalid"
        env["CLAUDE_CODE_MAX_RETRIES"] = {
            "is-error-success-subtype": "0",
            "auth-retries": "2",
            "terminated-no-result": "10",
        }[fixture]
        prompt = OFFLINE_PROMPT
        flags += ["--bare", "--model", MODEL]
    argv = [claude, "-p", prompt, *flags]

    started = time.monotonic()
    lines: list[tuple[int, str]] = []
    process = subprocess.Popen(
        argv,
        cwd=workspace,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if process.stdout is None:
        sys.exit("capture: claude's output wasn't piped")
    terminated = False
    for raw in process.stdout:
        lines.append((round((time.monotonic() - started) * 1000), raw.rstrip("\n")))
        if fixture == "terminated-no-result" and not terminated and '"api_retry"' in raw:
            process.send_signal(signal.SIGTERM)
            terminated = True
    exit_code = process.wait()
    if server is not None:
        server.shutdown()

    user_home = str(Path.home())
    replacements = {
        str(workspace): "/workspace",
        str(workspace.resolve()): "/workspace",
        str(home): "~",
        str(home.resolve()): "~",
        user_home: "~",
        os.environ.get("USER", "nobody-at-all"): "user",
    }
    if server is not None:
        replacements[f"127.0.0.1:{server.server_address[1]}"] = "127.0.0.1:8080"
    scrub = Scrubber(replacements)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "recording.jsonl").open("w", encoding="utf-8") as recording:
        for at_ms, line in lines:
            recording.write(
                json.dumps({"transcript": scrub(line), "atMs": at_ms}, ensure_ascii=False) + "\n"
            )
    shown = [scrub(part) for part in argv]
    shown[0] = "claude"
    provenance = {
        "fixture": fixture,
        "claudeCodeVersion": version,
        "date": datetime.now(UTC).date().isoformat(),
        "command": shown,
        "environment": sorted(name for name in env if "TOKEN" not in name and "KEY" not in name)
        + (
            ["(credential: owner's, not recorded)"]
            if owner_run
            else ["ANTHROPIC_API_KEY (deliberately invalid)"]
        ),
        "credential": "owner" if owner_run else "none: a local fake API refused an invalid key",
        "exitCode": exit_code,
        "terminatedWith": "SIGTERM during the retry backoff" if terminated else None,
        "scrubbing": scrub.describe(),
    }
    (out / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    shutil.rmtree(scratch, ignore_errors=True)
    print(f"capture: {len(lines)} lines, exit {exit_code} -> {out}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    capture(sys.argv[1], Path(sys.argv[2]))
