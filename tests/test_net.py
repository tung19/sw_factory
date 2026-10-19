"""Coordinator/runner P0 (ADR 0002): the typed protocol + the relay hub. Pure
logic — no websockets, no agents. The hub only forwards valid typed jobs and
broadcasts runner output; it executes nothing."""
import asyncio

import pytest

import area.net.protocol as P
from area.net.hub import Hub


# ---- protocol ---------------------------------------------------------------

def test_encode_decode_roundtrip():
    msg = P.job_msg("abc", "run", {"requirement": "x"})
    assert P.decode(P.encode(msg)) == msg


def test_decode_garbage_is_empty():
    assert P.decode("not json") == {}
    assert P.decode("[1,2]") == {}  # not a dict


def test_is_valid_job():
    assert P.is_valid_job(P.job_msg("1", "run"))
    assert not P.is_valid_job(P.job_msg("1", "rm -rf"))      # kind not allowed
    assert not P.is_valid_job({"type": "job", "kind": "run"})  # no id
    assert not P.is_valid_job({"type": "log", "line": "x"})


def test_job_argv_kinds():
    assert P.job_argv("doctor") == ["doctor"]
    a = P.job_argv("run", {"requirement": "todo app", "name": "t", "tdd": True})
    assert a[:2] == ["run", "todo app"] and "--name" in a and "--tdd" in a
    assert P.job_argv("iterate", {"name": "t", "instruction": "add X"}) == ["iterate", "t", "add X"]
    assert P.job_argv("deploy", {"name": "t"}) == ["deploy", "t", "--yes"]
    e = P.job_argv("export", {"name": "t", "repo": "u", "push": True})
    assert e == ["export", "t", "--repo", "u", "--push"]


def test_job_argv_unknown_raises():
    with pytest.raises(ValueError):
        P.job_argv("bogus")


# ---- hub --------------------------------------------------------------------

def _sink():
    got = []

    async def send(text):
        got.append(text)

    return got, send


def test_hub_forwards_valid_job_to_runner():
    runner_got, runner_send = _sink()
    hub = Hub()
    hub.connect_runner(runner_send)
    raw = P.encode(P.job_msg("1", "run", {"requirement": "x"}))
    assert asyncio.run(hub.from_ui(raw)) is True
    assert runner_got == [raw]


def test_hub_drops_invalid_job():
    runner_got, runner_send = _sink()
    hub = Hub()
    hub.connect_runner(runner_send)
    assert asyncio.run(hub.from_ui(P.encode({"type": "job", "kind": "rm", "id": "1"}))) is False
    assert runner_got == []  # never relayed


def test_hub_no_runner_drops():
    hub = Hub()
    assert asyncio.run(hub.from_ui(P.encode(P.job_msg("1", "doctor")))) is False


def test_hub_broadcasts_runner_output_to_uis():
    a_got, a_send = _sink()
    b_got, b_send = _sink()
    hub = Hub()
    hub.connect_ui(a_send)
    hub.connect_ui(b_send)
    raw = P.encode(P.log_msg("1", "building…"))
    asyncio.run(hub.from_runner(raw))
    assert a_got == [raw] and b_got == [raw]


def test_hub_disconnect_ui_stops_delivery():
    a_got, a_send = _sink()
    hub = Hub()
    hub.connect_ui(a_send)
    hub.disconnect_ui(a_send)
    asyncio.run(hub.from_runner(P.encode(P.status_msg("1", "done", 0))))
    assert a_got == []
