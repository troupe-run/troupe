"""What test_run_host.py and test_run_host_unit.py share."""

import asyncio
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from protocol_schemas import check_error, check_notice
from runner_schemas import is_valid, validate
from troupe.core.artifacts import ArtifactStore, MemoryArtifactStore
from troupe.core.notices import Notice
from troupe.core.runners.effects import (
    Audit,
    DeclaredEffects,
    EffectCheck,
    NoAudit,
    NoEffectExpected,
)
from troupe.core.runners.host import RunnerCommand, RunRequest, run_actor
from troupe.core.runners.limits import RunLimits
from troupe.core.runners.outcome import RunOutcome
from troupe_plugin_sdk import runner as p
from troupe_plugin_sdk.effects import Effects

FAST = RunLimits(cancel_grace=2.0, start_timeout=30.0)
STORED_RECORD = "https://troupe.run/protocol/transcript-record.schema.json"


@dataclass
class Ran:
    outcome: RunOutcome
    store: ArtifactStore
    events: list[p.RunEvent] = field(default_factory=list)
    notices: list[Notice] = field(default_factory=list)
    sent: list[dict[str, Any]] = field(default_factory=list)
    received: list[dict[str, Any]] = field(default_factory=list)
    times: list[float] = field(default_factory=list)

    @property
    def types(self) -> list[str]:
        return [str(e.TYPE) for e in self.events]

    def transcript(self) -> bytes:
        assert self.outcome.transcript is not None
        return self.store.read(self.outcome.transcript)

    def stderr(self) -> bytes:
        assert self.outcome.stderr is not None
        return self.store.read(self.outcome.stderr)


def _run(
    tmp_path: Path,
    script: dict[str, Any] | None = None,
    *,
    argv: list[str] | None = None,
    effect: EffectCheck | None = None,
    audit: Audit | None = None,
    limits: RunLimits = FAST,
    store: ArtifactStore | None = None,
    env: dict[str, str] | None = None,
    cancel_after: float | None = None,
    options: dict[str, Any] | None = None,
    valid_options: bool = True,
    character: str | None = None,
    direction: str = "test",
    effects: p.EffectsDeclaration = p.READ_ONLY_DECLARATION,
    scratch_root: Path | None = None,
    runtime: p.RunStartRuntime | None = None,
    credential: str | None = None,
) -> Ran:
    """Run the scripted runner (or ``argv``) and check every message troupe sent against the
    contract, with the scripted runner's schemas bound. ``valid_options=False`` marks options the
    runner must refuse, which its options schema must refuse too."""
    store = store if store is not None else MemoryArtifactStore()
    command = RunnerCommand(
        argv or [sys.executable, "-m", "troupe_runner_scripted"], cwd=tmp_path, env=env or {}
    )
    request = RunRequest(
        str(uuid.uuid4()),
        direction,
        tmp_path,
        options if options is not None else {"script": script or {"steps": []}},
        character=character,
        effects=effects,
        runtime=runtime,
        credential=credential,
    )
    ran: dict[str, Any] = {"events": [], "notices": [], "sent": [], "received": [], "times": []}

    async def on_event(event: p.RunEvent) -> None:
        ran["events"].append(event)
        ran["times"].append(time.monotonic())

    def on_message(direction: str, message: Any) -> None:  # noqa: ANN401
        ran["sent" if direction == "sent" else "received"].append(dict(message))

    async def main() -> RunOutcome:
        cancel = asyncio.Event()
        if cancel_after is not None:
            asyncio.get_running_loop().call_later(cancel_after, cancel.set)
        return await run_actor(
            command,
            request,
            store=store,
            effect=effect or NoEffectExpected(),
            audit=audit or NoAudit(),
            limits=limits,
            on_event=on_event,
            on_announce=ran["notices"].append,
            on_message=on_message,
            cancel=cancel,
            scratch_root=scratch_root,
        )

    outcome = asyncio.run(main())
    result = Ran(outcome, store, **ran)
    if outcome.error is not None:
        check_error(outcome.error.to_data())
    for notice in result.notices:
        check_notice(notice.to_data())
    for message in result.sent:
        if message.get("method") == "run/start" and not valid_options:
            assert not is_valid(message, "message.schema.json#/$defs/fromHost")
        else:
            validate(message, "message.schema.json#/$defs/fromHost")
    return result


def _code(ran: Ran) -> str | None:
    return None if ran.outcome.error is None else ran.outcome.error.code


# Requirement: The audit's findings are part of the outcome (failed-run-audit design D1)


def _states(root: Path) -> dict[str, str]:
    """Every file under ``root``, as the files adapter reads a workspace: path to content."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes().hex()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _audit(tmp_path: Path, effects: Effects | None = None) -> DeclaredEffects:
    """The real audit, over the run's workspace, as perform builds it for a run in the theatre."""
    return DeclaredEffects(
        "tester", effects or Effects(), lambda: _states(tmp_path), lambda: _states(tmp_path)
    )
