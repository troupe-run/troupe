"""Capture real Claude Code stream-json as a Claude Code runner fixture (design D14). Not run in CI.

Usage:
    python capture_claude.py <fixture> <output directory>
    python capture_claude.py --rescrub <fixture directory>   apply newer value scrubbing in place

Fixtures that need no credential (an invalid key against a local fake API, so nothing reaches
Anthropic):
    is-error-success-subtype  the key is refused, no retries: init, then an error under "success"
    auth-retries              the same with two retries: api_retry events, then the error result
    terminated-no-result      retries, then SIGTERM during the backoff: no result at all
    server-retries            the fake API answers 529 (overloaded): two retries, then the error
    rate-limit-retries        the fake API answers 429 (rate limited): two retries, then the error
    network-retries           nothing listens at the API's address: two retries, then the error
    context-limit-refused     launched as the runner launches it, so compaction is off: the fake
                              API answers a Read tool call reporting 185,000 input tokens, then
                              refuses the next request as too long (terminal_reason
                              prompt_too_long)
    context-limit-blocked     the same, reporting 990,000 tokens of a 1,000,000 window: Claude
                              Code stops without sending the next request (blocking_limit)

The context-limit fixtures check that compaction stayed off (compaction-off design D3): the tool
refuses to write either one when Claude Code reported compacting or sent the fake API more requests
than the case expects, so a recapture on a newer Claude Code checks the runner's setting again.

The fixtures that need a real credential are captured by the owner, never in an agent session. Each
needs CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY, and is one short run on a pinned model,
budget-capped:
    success-with-tools        writes a file and reads it back
    edit-denied-by-effects    the runner's translated rules (write declared for out/** only) deny
                              an edit to src/a.txt: a permission denial, then the result
    delete-through-troupe     delete declared for drafts/**: Claude Code calls troupe's own
                              mcp__troupe__Delete on drafts/old.md, served by the runner's MCP
                              server

The last two are launched exactly as the runner launches Claude Code: the actor's effects are
translated by the runner's own ClaudeCodePermissions and the command line built by its build(),
so the recording is of the rules a run really gets (declared-effects design D8).

The tool writes recording.jsonl (each native line as {"transcript": ..., "atMs": ...}, scrubbed)
and provenance.json. The paired run events and expected.json are written by hand afterwards.
"""

import http.server
import json
import os
import re
import shutil
import signal
import socket
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


ERRORS = {
    401: ("authentication_error", "invalid x-api-key"),
    429: ("rate_limit_error", "Number of requests has exceeded your rate limit"),
    529: ("overloaded_error", "Overloaded"),
}
"""What the fake API answers with, by status: the Anthropic API's error type and message."""


class _RefuseEveryRequest(http.server.BaseHTTPRequestHandler):
    """A stand-in for api.anthropic.com that answers every request with one error, so no request
    ever succeeds and nothing reaches Anthropic."""

    status = 401

    def _refuse(self) -> None:
        self.rfile.read(int(self.headers.get("content-length") or 0))
        kind, message = ERRORS[self.status]
        self.send_response(self.status)
        self.send_header("content-type", "application/json")
        if self.status == 429:
            self.send_header("retry-after", "0")
        self.end_headers()
        self.wfile.write(
            json.dumps({"type": "error", "error": {"type": kind, "message": message}}).encode()
        )

    do_GET = do_POST = _refuse  # noqa: N815 - the names http.server dispatches to

    def log_message(self, *args: Any) -> None:  # noqa: ANN401
        pass


def _fake_api(status: int) -> tuple[http.server.ThreadingHTTPServer, str]:
    handler = type("_Refuse", (_RefuseEveryRequest,), {"status": status})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


CONTEXT_LIMITS = {
    "context-limit-refused": (185_000, 2, "prompt_too_long"),
    "context-limit-blocked": (990_000, 1, "blocking_limit"),
}
"""Each context-limit fixture: the input tokens the fake API reports for its first answer, how many
requests Claude Code sends it when compaction is off (a compaction request would be one more), and
the terminal_reason its result must name. Each runs on the runner's default budget, since the fake
usage's cost would pass the other fixtures' cap."""

TOO_LONG = "prompt is too long: 1000345 tokens > 1000000 maximum"
"""What the fake API refuses an over-long request with, worded as the Anthropic API words it."""


class _ContextLimit(http.server.BaseHTTPRequestHandler):
    """A stand-in for api.anthropic.com that streams one Read tool call reporting a context near
    the window, then refuses every later request as too long, counting the requests it gets."""

    input_tokens = 0
    read_path = ""
    requests: list[str]

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
        self.requests.append(self.path)
        if len(self.requests) > 1:
            refusal = {
                "type": "error",
                "error": {"type": "invalid_request_error", "message": TOO_LONG},
            }
            data = json.dumps(refusal).encode()
            self.send_response(400)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        for name, payload in self._read_call(str(body.get("model", MODEL))):
            self.wfile.write(f"event: {name}\ndata: {json.dumps(payload)}\n\n".encode())
        self.wfile.flush()

    def _read_call(self, model: str) -> list[tuple[str, dict[str, Any]]]:
        usage = {
            "input_tokens": self.input_tokens,
            "output_tokens": 1,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }
        message: dict[str, Any] = {
            "id": "msg_capture",
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": usage,
        }
        block = {"type": "tool_use", "id": "toolu_capture", "name": "Read", "input": {}}
        arguments = json.dumps({"file_path": self.read_path})
        return [
            ("message_start", {"type": "message_start", "message": message}),
            (
                "content_block_start",
                {"type": "content_block_start", "index": 0, "content_block": block},
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "input_json_delta", "partial_json": arguments},
                },
            ),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                    "usage": {"output_tokens": 20},
                },
            ),
            ("message_stop", {"type": "message_stop"}),
        ]

    def log_message(self, *args: Any) -> None:  # noqa: ANN401
        pass


def _context_limit_api(
    input_tokens: int, read_path: Path
) -> tuple[http.server.ThreadingHTTPServer, list[str]]:
    requests: list[str] = []
    handler = type(
        "_Limit",
        (_ContextLimit,),
        {"input_tokens": input_tokens, "read_path": str(read_path), "requests": requests},
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, requests


def _json_object(line: str) -> dict[str, Any] | None:
    """The line's record, or None when it isn't a JSON object, as some lines Claude Code prints."""
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None
    return record if isinstance(record, dict) else None


def compaction_seen(lines: list[str]) -> list[str]:
    """The lines in which Claude Code reported compacting: a system/status record that says so, or
    a compact_boundary."""
    seen = []
    for line in lines:
        record = _json_object(line)
        if record is None or record.get("type") != "system":
            continue
        if record.get("subtype") == "compact_boundary" or (
            record.get("subtype") == "status"
            and (record.get("status") == "compacting" or "compact_result" in record)
        ):
            seen.append(line)
    return seen


def _unused_port() -> int:
    """A local port nothing listens on: bound, then released, so a connection to it is refused."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


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
        line = scrub_values(line)
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
            *VALUE_SCRUBBING,
        ]


SCRUBBED_PATH = "<host path>"
SCRUBBED_UTILIZATION = 0.5
SCRUBBED_RESETS_AT = 1790000000
VALUE_SCRUBBING = [
    f"messaging_socket_path (a host path outside the workspace) -> {SCRUBBED_PATH!r}",
    f"rate_limit_info: every utilization -> {SCRUBBED_UTILIZATION}, every resetsAt -> "
    f"{SCRUBBED_RESETS_AT} (the account's usage isn't published)",
]


def _scrub_rate_limits(node: Any) -> Any:  # noqa: ANN401 - any JSON value
    if isinstance(node, dict):
        return {
            key: SCRUBBED_UTILIZATION
            if key == "utilization"
            else SCRUBBED_RESETS_AT
            if key == "resetsAt"
            else _scrub_rate_limits(value)
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [_scrub_rate_limits(item) for item in node]
    return node


def scrub_values(line: str) -> str:
    """Scrub values that identify the host or the account, by field, keeping the record's shape.

    Lines with nothing to scrub are returned unchanged, byte for byte; a changed line is written
    back as compact JSON, as Claude Code writes it.
    """
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return line
    if not isinstance(record, dict):
        return line
    changed = dict(record)
    if "messaging_socket_path" in changed:
        changed["messaging_socket_path"] = SCRUBBED_PATH
    if "rate_limit_info" in changed:
        changed["rate_limit_info"] = _scrub_rate_limits(changed["rate_limit_info"])
    if changed == record:
        return line
    return json.dumps(changed, ensure_ascii=False, separators=(",", ":"))


def rescrub(directory: Path) -> None:
    """Apply the value scrubbing to a recording captured before it existed, and say so."""
    recording = directory / "recording.jsonl"
    entries = [json.loads(line) for line in recording.read_text(encoding="utf-8").splitlines()]
    for entry in entries:
        if "transcript" in entry:
            entry["transcript"] = scrub_values(entry["transcript"])
    recording.write_text(
        "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries), encoding="utf-8"
    )
    provenance_path = directory / "provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["scrubbing"] = [
        *provenance["scrubbing"],
        *(item for item in VALUE_SCRUBBING if item not in provenance["scrubbing"]),
    ]
    provenance_path.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")


THROUGH_RUNNER: dict[str, tuple[dict[str, list[str]], dict[str, bytes], str]] = {
    "edit-denied-by-effects": (
        {"write": ["out/**"]},
        {},
        "Use the Write tool to create src/a.txt containing exactly: hi\n"
        "If you can't, don't try another way: reply with one word: denied.",
    ),
    "delete-through-troupe": (
        {"delete": ["drafts/**"]},
        {"drafts/old.md": b"an old draft\n"},
        "Use the mcp__troupe__Delete tool to delete drafts/old.md, then reply with one word: done.",
    ),
    **{
        name: ({}, {"notes.txt": b"hi\n"}, "Read notes.txt, then reply with one word: done.")
        for name in CONTEXT_LIMITS
    },
}
"""Each fixture captured through the runner: the actor's effects, the workspace's files, and the
direction."""


def _through_runner(
    fixture: str, workspace: Path, private: Path, run_scratch: Path
) -> tuple[list[str], bytes, dict[str, str]]:
    """The command line, standard input and environment the runner would give Claude Code."""
    # Imported here: the offline fixtures need nothing but Claude Code and the standard library.
    from troupe_plugin_sdk.declaration import Declaration
    from troupe_plugin_sdk.effects import Effects
    from troupe_runner_claude_code.command import build
    from troupe_runner_claude_code.effects_server import write_config
    from troupe_runner_claude_code.options import parse_options
    from troupe_runner_claude_code.permissions import ClaudeCodePermissions

    declared, files, direction = THROUGH_RUNNER[fixture]
    for relative, data in files.items():
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    raw: dict[str, object] = {"model": MODEL}
    if fixture not in CONTEXT_LIMITS:
        raw["maxBudgetUsd"] = float(BUDGET_USD)
    options = parse_options(raw)
    effects = Effects(
        write=tuple(declared.get("write", [])),
        delete=tuple(declared.get("delete", [])),
        move=tuple(declared.get("move", [])),
    )
    declaration = Declaration(effects, workspace, run_scratch)
    rules = ClaudeCodePermissions(options).translate(declaration)
    server = None
    if rules.mcp_tools:
        config = private / "effects.json"
        write_config(
            config,
            run_id="00000000-0000-4000-8000-000000000000",
            declaration=declaration,
            tools=rules.mcp_tools,
            event_max_bytes=65536,
        )
        server = [sys.executable, "-m", "troupe_runner_claude_code.effects_server", str(config)]
    claude = shutil.which("claude")
    if claude is None:
        sys.exit("capture: claude isn't on PATH. Fix: install Claude Code.")
    launch = build(Path(claude), options, direction, None, private, {}, rules, server)
    return launch.argv, launch.stdin, launch.env


def capture(fixture: str, out: Path) -> None:
    through_runner = fixture in THROUGH_RUNNER
    context_limit = fixture in CONTEXT_LIMITS
    owner_run = fixture == "success-with-tools" or (through_runner and not context_limit)
    if fixture not in {
        "is-error-success-subtype",
        "auth-retries",
        "terminated-no-result",
        "server-retries",
        "rate-limit-retries",
        "network-retries",
        "success-with-tools",
        *THROUGH_RUNNER,
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
    private, run_scratch = scratch / "private", scratch / "run-scratch"
    for directory in (workspace, home, private, run_scratch):
        directory.mkdir()
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
    port: int | None = None
    requests: list[str] = []
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
        if fixture == "network-retries":
            port = _unused_port()
        elif context_limit:
            server, requests = _context_limit_api(
                CONTEXT_LIMITS[fixture][0], workspace / "notes.txt"
            )
            port = server.server_address[1]
        else:
            status = {"server-retries": 529, "rate-limit-retries": 429}.get(fixture, 401)
            server, _ = _fake_api(status)
            port = server.server_address[1]
        env["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{port}"
        env["ANTHROPIC_API_KEY"] = "sk-troupe-capture-deliberately-invalid"
        env["CLAUDE_CODE_MAX_RETRIES"] = {
            "is-error-success-subtype": "0",
            "auth-retries": "2",
            "terminated-no-result": "10",
            "server-retries": "2",
            "rate-limit-retries": "2",
            "network-retries": "2",
            "context-limit-refused": "0",
            "context-limit-blocked": "0",
        }[fixture]
        prompt = OFFLINE_PROMPT
        flags += ["--bare", "--model", MODEL]
    argv = [claude, "-p", prompt, *flags]
    stdin: bytes | None = None
    if through_runner:
        argv, stdin, launched = _through_runner(fixture, workspace, private, run_scratch)
        env = {**env, **{k: v for k, v in launched.items() if k not in ("HOME", "PATH")}}

    started = time.monotonic()
    lines: list[tuple[int, str]] = []
    process = subprocess.Popen(
        argv,
        cwd=workspace,
        env=env,
        stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if process.stdout is None:
        sys.exit("capture: claude's output wasn't piped")
    if stdin is not None and process.stdin is not None:
        process.stdin.write(stdin.decode("utf-8"))  # the direction, as the runner sends it
        process.stdin.close()
    terminated = False
    for raw in process.stdout:
        lines.append((round((time.monotonic() - started) * 1000), raw.rstrip("\n")))
        if fixture == "terminated-no-result" and not terminated and '"api_retry"' in raw:
            process.send_signal(signal.SIGTERM)
            terminated = True
    exit_code = process.wait()
    if server is not None:
        server.shutdown()
    if context_limit:
        compacted = compaction_seen([line for _, line in lines])
        _, expected, terminal_reason = CONTEXT_LIMITS[fixture]
        ended = [
            record.get("terminal_reason")
            for _, line in lines
            if (record := _json_object(line)) is not None and record.get("type") == "result"
        ]
        if ended != [terminal_reason]:
            shutil.rmtree(scratch, ignore_errors=True)
            sys.exit(
                f"capture: refusing to write {fixture}: its run didn't end at the context limit. "
                f"The results' terminal_reason was {ended}, not [{terminal_reason!r}]."
            )
        if compacted or len(requests) != expected:
            shutil.rmtree(scratch, ignore_errors=True)
            sys.exit(
                f"capture: refusing to write {fixture}: compaction wasn't off. Claude Code sent "
                f"{len(requests)} requests (expected {expected}) and reported compacting in "
                f"{len(compacted)} lines. Fix: check the runner's settings file still turns "
                "compaction off for this Claude Code version (compaction-off design D1)."
            )

    user_home = str(Path.home())
    replacements = {
        str(private): "/private",
        str(private.resolve()): "/private",
        str(run_scratch): "/scratch",
        str(run_scratch.resolve()): "/scratch",
        str(workspace): "/workspace",
        str(workspace.resolve()): "/workspace",
        str(home): "~",
        str(home.resolve()): "~",
        user_home: "~",
        os.environ.get("USER", "nobody-at-all"): "user",
    }
    if port is not None:
        replacements[f"127.0.0.1:{port}"] = "127.0.0.1:8080"
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
        "credential": "owner"
        if owner_run
        else "none: nothing listened at the API's address, and the key was invalid"
        if fixture == "network-retries"
        else "none: a local fake API, which ignored the invalid key, answered with a context near "
        f"the window ({CONTEXT_LIMITS[fixture][0]} input tokens, its cost included) and refused "
        "any later request as too long"
        if context_limit
        else "none: a local fake API refused an invalid key",
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
    if sys.argv[1] == "--rescrub":
        rescrub(Path(sys.argv[2]))
    else:
        capture(sys.argv[1], Path(sys.argv[2]))
