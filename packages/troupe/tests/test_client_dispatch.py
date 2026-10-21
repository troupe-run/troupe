"""The dispatcher parses a request before anything runs (spec: client-protocol;
perform-status-logs design D2)."""

import asyncio
import threading
from pathlib import Path
from typing import Any

import pytest

from troupe.core.client import messages as m
from troupe.core.client.dispatch import Method, Send, call, handlers
from troupe.core.client.session import CancelSignal, Session
from troupe.core.errors import TroupeError
from troupe.core.messages import Message

RUN_ID = "0f8fad5b-d9cb-469f-a165-70867728950e"


class Spy:
    """A handler that records each call and sends one update."""

    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def __call__(self, request: Any, session: Session, send: Send) -> Message:  # noqa: ANN401
        self.calls.append(request)
        send(m.Started(run_id=RUN_ID))
        return m.StatusResult(runs=[], notices=[])


def run(method: str, params: object, spy: Spy, updates: list[dict[str, Any]] | None = None) -> Any:  # noqa: ANN401
    table = {
        "perform": Method(m.PerformRequest, spy),
        "status": Method(m.StatusRequest, spy),
    }
    return asyncio.run(
        call(
            method,
            params,
            Session(theatre=Path()),
            updates.append if updates is not None else None,
            methods=table,
        )
    )


def test_an_unknown_method_is_refused_naming_it_and_the_known_ones() -> None:
    spy = Spy()
    with pytest.raises(TroupeError) as caught:
        run("deploy", {}, spy)
    assert caught.value.code == "client.unknown-method"
    assert caught.value.details == {"method": "deploy", "known": ["perform", "status"]}
    assert spy.calls == []


def test_an_invalid_request_is_refused_before_its_handler_runs() -> None:
    spy = Spy()
    with pytest.raises(TroupeError) as caught:
        run("perform", {"actor": "tester", "runner": "scripted", "argv": ["sh"]}, spy)
    assert caught.value.code == "client.invalid-request"
    assert "'argv'" in caught.value.problem
    assert caught.value.exit_code == 2
    assert spy.calls == []


def test_a_valid_request_reaches_its_handler_parsed_and_updates_and_result_return_as_data() -> None:
    spy, updates = Spy(), list[dict[str, Any]]()
    result = run("status", {"limit": 3}, spy, updates)
    assert spy.calls == [m.StatusRequest(limit=3)]
    assert updates == [{"kind": "started", "runId": RUN_ID}]
    assert result == {"runs": [], "notices": []}


def test_the_core_offers_exactly_its_methods_with_their_request_types() -> None:
    assert {name: method.request for name, method in handlers().items()} == {
        "perform": m.PerformRequest,
        "status": m.StatusRequest,
        "logs": m.LogsRequest,
        "config-set": m.ConfigSetRequest,
        "config-get": m.ConfigGetRequest,
        "flush": m.FlushRequest,
    }


def test_a_cancel_requested_before_binding_sets_the_bound_event_at_once() -> None:
    signal = CancelSignal()
    signal.request()

    async def bound() -> bool:
        return signal.bind().is_set()

    assert asyncio.run(bound())


def test_a_cancel_requested_from_another_thread_reaches_the_loop() -> None:
    signal = CancelSignal()

    async def wait() -> bool:
        event = signal.bind()
        threading.Thread(target=signal.request).start()
        await asyncio.wait_for(event.wait(), 5)
        return signal.requested

    assert asyncio.run(wait())
