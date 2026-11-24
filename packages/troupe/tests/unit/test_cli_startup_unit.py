"""The client dispatcher's table names exactly the methods its command families offer, and an
unknown method is refused listing every method troupe offers (spec: cli; cli-starts-fast design
D6).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_cli_startup.py."""

import asyncio
import importlib
from pathlib import Path

import pytest

from cli_startup_shared import FAMILIES
from troupe.core.client import dispatch
from troupe.core.client.session import Session
from troupe.core.errors import TroupeError


def test_the_dispatchers_table_names_every_method_the_families_offer() -> None:
    every: set[str] = set()
    for module in FAMILIES.values():
        every |= set(importlib.import_module(module).methods())
    assert set(dispatch.FAMILIES) == every
    assert set(dispatch.handlers()) == every


def test_an_unknown_method_is_refused_listing_every_method_troupe_offers() -> None:
    with pytest.raises(TroupeError) as caught:
        asyncio.run(dispatch.call("deploy", {}, Session(theatre=Path())))
    assert caught.value.code == "client.unknown-method"
    assert caught.value.details["known"] == sorted(dispatch.handlers())
