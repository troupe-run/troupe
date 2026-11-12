"""Capture a fixture for the LM Studio runner from a real LM Studio (lmstudio-runner design D12,
D14). Run by the owner, or by an agent while the owner's LM Studio is running; it needs no key.

    python3 tools/capture_lm_studio.py <name> --model google/gemma-4-e4b \
        --direction "Read notes.txt, then write its first line into out/first.txt." \
        [--upstream 127.0.0.1:1234] [--options '{"maxTurns": 6}'] [--file notes.txt=...]

It starts a recording proxy on a free local port, runs the real runner with its runtime pointed at
the proxy, and forwards everything to LM Studio: the greeting, and every websocket the library
opens. The fixture directory gets ``exchange.json`` (each websocket's path and its frames, in
order, each marked from the client or from LM Studio), ``workspace.json`` (the files the run
started with), ``run.json`` (what the runner was given) and ``provenance.json``. The library's
made-up client identifier and passkey, and the capturing host's home directory, are scrubbed from
everything written. ``expected.json`` is written separately and reviewed by hand.
"""

import argparse
import datetime
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import websocket

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SCRUBBED_ID = "client-identifier"
SCRUBBED_KEY = "client-passkey"


class Recorder:
    """The proxy: forwards each request to LM Studio and records each websocket's frames."""

    def __init__(self, upstream: str) -> None:
        host, _, port = upstream.rpartition(":")
        self.host, self.port = host, int(port)
        self.sockets: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self.server = websocket.Server(self._handle)

    def _handle(
        self, sock: socket.socket, request: str, headers: dict[str, str], rest: bytes
    ) -> None:
        path = request.split(" ")[1]
        if headers.get("upgrade", "").lower() != "websocket":
            self._forward_http(sock, request, rest)
            return
        upstream = websocket.connect(self.host, self.port, path)
        client = websocket.server_handshake(sock, headers, rest)
        frames: list[dict[str, Any]] = []
        with self._lock:
            self.sockets.append({"path": path, "frames": frames})

        def pump(source: websocket.Connection, sink: websocket.Connection, origin: str) -> None:
            try:
                while True:
                    text = source.receive()
                    with self._lock:
                        frames.append({"from": origin, "message": json.loads(text)})
                    sink.send(text)
            except (websocket.Closed, OSError):
                sink.close()

        back = threading.Thread(target=pump, args=(upstream, client, "lm-studio"), daemon=True)
        back.start()
        pump(client, upstream, "client")
        back.join(5)

    def _forward_http(self, sock: socket.socket, request: str, rest: bytes) -> None:
        upstream = socket.create_connection((self.host, self.port), timeout=10)
        upstream.sendall(
            f"{request}\r\nHost: {self.host}:{self.port}\r\nConnection: close\r\n\r\n".encode()
            + rest
        )
        while chunk := upstream.recv(65536):
            sock.sendall(chunk)
        upstream.close()


def scrub(value: Any, home: str, work: tuple[str, ...] = ()) -> Any:  # noqa: ANN401 - JSON
    """``value`` with the library's made-up client identifier and passkey replaced, the run's
    temporary directory shown as <work>, and the capturing host's home directory as ~."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key == "clientIdentifier":
                out[key] = SCRUBBED_ID
            elif key == "clientPasskey":
                out[key] = SCRUBBED_KEY
            else:
                out[key] = scrub(item, home, work)
        return out
    if isinstance(value, list):
        return [scrub(item, home, work) for item in value]
    if isinstance(value, str):
        for path in work:
            value = value.replace(path, "<work>")
        return value.replace(home, "~") if home else value
    return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("name")
    parser.add_argument("--model", required=True)
    parser.add_argument("--direction", required=True)
    parser.add_argument("--upstream", default="127.0.0.1:1234")
    parser.add_argument("--options", default='{"maxTurns": 6, "maxTotalTokens": 50000}')
    parser.add_argument("--effects", default='{"write": ["out/**"], "delete": [], "move": []}')
    parser.add_argument(
        "--file", action="append", default=[], help="path=content, in the workspace"
    )
    parser.add_argument("--lm-studio-version", required=True, help="as LM Studio's About shows it")
    args = parser.parse_args()

    recorder = Recorder(args.upstream)
    recorder.server.start()
    work = Path(tempfile.mkdtemp(prefix="lms-capture-"))
    workspace, scratch = work / "ws", work / "scratch"
    workspace.mkdir()
    scratch.mkdir()
    files = dict(item.split("=", 1) for item in args.file)
    for path, content in files.items():
        target = workspace / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content.replace("\\n", "\n"), encoding="utf-8")

    start = {
        "runId": str(uuid.uuid4()),
        "direction": args.direction,
        "workspace": str(workspace),
        "options": json.loads(args.options),
        "limits": {"eventMaxBytes": 65536},
        "effects": json.loads(args.effects),
        "scratch": str(scratch),
        "onContextFull": "fail",
        "runtime": {
            "name": "lm-studio",
            "endpoint": f"http://127.0.0.1:{recorder.server.port}",
            "model": args.model,
            "credential": False,
        },
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "troupe_runner_lm_studio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        env={k: v for k, v in os.environ.items() if k != "TROUPE_RUNTIME_CREDENTIAL"},
    )
    if proc.stdin is None or proc.stdout is None:
        raise SystemExit("the runner's standard input and output weren't opened")
    for message in (
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersions": [0], "capabilities": ["transcript-kinds"]},
        },
        {"jsonrpc": "2.0", "id": 2, "method": "run/start", "params": start},
    ):
        proc.stdin.write((json.dumps(message) + "\n").encode())
    proc.stdin.flush()
    for raw in proc.stdout:
        message = json.loads(raw)
        if "error" in message or (
            message.get("method") == "run/event" and message["params"]["type"] == "result"
        ):
            break
    proc.stdin.write(b'{"jsonrpc": "2.0", "id": 3, "method": "shutdown"}\n')
    proc.stdin.flush()
    proc.wait(30)
    recorder.server.stop()

    home = str(Path.home())
    out = FIXTURES / args.name
    out.mkdir(parents=True, exist_ok=True)
    temporary = tuple(sorted({str(work), str(work.resolve())}, key=len, reverse=True))
    exchange = scrub(recorder.sockets, home, temporary)
    (out / "exchange.json").write_text(
        json.dumps(exchange, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    run = {k: start[k] for k in ("direction", "options", "effects")} | {"model": args.model}
    (out / "run.json").write_text(json.dumps(run, indent=1) + "\n", encoding="utf-8")
    (out / "workspace.json").write_text(json.dumps(files, indent=1) + "\n", encoding="utf-8")
    import lmstudio  # the library's version, for the provenance

    provenance = {
        "source": "recorded",
        "lmStudio": args.lm_studio_version,
        "lmstudio": lmstudio.__version__,
        "model": args.model,
        "date": datetime.date.today().isoformat(),
        "tool": "tools/capture_lm_studio.py",
    }
    (out / "provenance.json").write_text(json.dumps(provenance, indent=1) + "\n", encoding="utf-8")
    text = "".join(p.read_text(encoding="utf-8") for p in out.iterdir())
    if re.search(re.escape(home), text):
        raise SystemExit("the host's home directory is still in the fixture")
    if "lms-capture-" in text:
        raise SystemExit("the run's temporary directory is still in the fixture")
    frames = sum(len(s["frames"]) for s in exchange)
    print(f"wrote {out}: {frames} frames on {len(exchange)} websockets")
    return 0


if __name__ == "__main__":
    sys.exit(main())
