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


CH = "chan-1"  # a channel/pairing-token key


def test_hub_forwards_valid_job_to_runner():
    runner_got, runner_send = _sink()
    hub = Hub()
    hub.connect_runner(CH, runner_send)
    raw = P.encode(P.job_msg("1", "run", {"requirement": "x"}))
    assert asyncio.run(hub.from_ui(CH, raw)) is True
    assert runner_got == [raw]


def test_hub_drops_invalid_job():
    runner_got, runner_send = _sink()
    hub = Hub()
    hub.connect_runner(CH, runner_send)
    assert asyncio.run(hub.from_ui(CH, P.encode({"type": "job", "kind": "rm", "id": "1"}))) is False
    assert runner_got == []  # never relayed


def test_hub_no_runner_drops():
    hub = Hub()
    assert asyncio.run(hub.from_ui(CH, P.encode(P.job_msg("1", "doctor")))) is False


def test_hub_broadcasts_runner_output_to_uis():
    a_got, a_send = _sink()
    b_got, b_send = _sink()
    hub = Hub()
    hub.connect_ui(CH, a_send)
    hub.connect_ui(CH, b_send)
    raw = P.encode(P.log_msg("1", "building…"))
    asyncio.run(hub.from_runner(CH, raw))
    assert a_got == [raw] and b_got == [raw]


def test_hub_disconnect_ui_stops_delivery():
    a_got, a_send = _sink()
    hub = Hub()
    hub.connect_ui(CH, a_send)
    hub.disconnect_ui(CH, a_send)
    asyncio.run(hub.from_runner(CH, P.encode(P.status_msg("1", "done", 0))))
    assert a_got == []


def test_hub_channels_are_isolated():
    # P2: a UI on channel A can't reach a runner on channel B, and runner output
    # only reaches its own channel's UIs.
    a_runner_got, a_runner_send = _sink()
    b_ui_got, b_ui_send = _sink()
    hub = Hub()
    hub.connect_runner("A", a_runner_send)
    hub.connect_ui("B", b_ui_send)
    # a job on channel B has no runner → dropped; channel-A runner never sees it
    assert asyncio.run(hub.from_ui("B", P.encode(P.job_msg("1", "doctor")))) is False
    assert a_runner_got == []
    # channel-A runner output does NOT reach channel-B's UI
    asyncio.run(hub.from_runner("A", P.encode(P.log_msg("1", "x"))))
    assert b_ui_got == []


# ---- P1: chat / apps relay + runner control handling ------------------------

def test_relayable_from_ui():
    assert P.is_relayable_from_ui(P.job_msg("1", "run"))
    assert P.is_relayable_from_ui(P.chat_msg("1", "có app nào?"))
    assert P.is_relayable_from_ui(P.apps_req())
    assert not P.is_relayable_from_ui({"type": "job", "kind": "rm", "id": "1"})
    assert not P.is_relayable_from_ui({"type": "log", "line": "x"})


def test_hub_forwards_chat_and_apps():
    got, send = _sink()
    hub = Hub()
    hub.connect_runner(CH, send)
    assert asyncio.run(hub.from_ui(CH, P.encode(P.chat_msg("1", "hi")))) is True
    assert asyncio.run(hub.from_ui(CH, P.encode(P.apps_req()))) is True
    assert len(got) == 2


def test_runner_job_argv_backend_passthrough(monkeypatch):
    import area.runner as R

    monkeypatch.delenv("AREA_RUNNER_BACKEND", raising=False)
    assert "--backend" not in R.job_argv_for("run", {"requirement": "x"})  # default keyless
    monkeypatch.setenv("AREA_RUNNER_BACKEND", "llm")
    a = R.job_argv_for("run", {"requirement": "x"})
    assert a[a.index("--backend") + 1] == "llm"
    # kinds without --backend aren't touched
    assert "--backend" not in R.job_argv_for("doctor", {})
    assert "--backend" not in R.job_argv_for("deploy", {"name": "t"})


def test_runner_chat_hybrid_routes_fast_vs_llm(monkeypatch):
    import area.runner as R
    import area.web.chat as C
    import area.web.intake as I

    monkeypatch.setattr(C.J, "list_apps", lambda: [{"name": "a1"}])
    calls = {"llm": 0}

    def fake_intake(history, message):
        calls["llm"] += 1
        return {"reply": "Bạn muốn web hay mobile?", "ready": False, "requirement": None}

    monkeypatch.setattr(I, "intake_turn", fake_intake)

    # a factory-state question → fast, free path (no LLM call)
    r = R.handle_control(P.chat_msg("1", "có app nào?"))
    assert r["action"] == "answer" and "a1" in r["reply"] and calls["llm"] == 0

    # a new-app idea → keyless forcing-intake (LLM)
    r2 = R.handle_control({"type": "chat", "id": "2",
                           "message": "tôi muốn một app bán cà phê có giỏ hàng", "app": ""})
    assert calls["llm"] == 1 and r2["action"] == "intake"


def test_runner_chat_spec_ready_carries_requirement(monkeypatch):
    import area.runner as R
    import area.web.intake as I

    monkeypatch.setattr(I, "intake_turn",
                        lambda h, m: {"reply": "xong", "ready": True, "requirement": "app X"})
    r = R.handle_control({"type": "chat", "id": "9", "message": "làm cho tôi app X đi", "app": ""})
    assert r["action"] == "spec_ready" and r["requirement"] == "app X"


def test_runner_folds_uploaded_doc_into_requirement():
    import base64

    import area.runner as R

    # no doc → params pass through untouched
    p, note = R.fold_requirement_doc({"requirement": "x", "name": "a"})
    assert p == {"requirement": "x", "name": "a"} and note is None

    # a text doc (md) rides as base64 → extracted + folded into requirement
    doc = base64.b64encode(b"# Spec\nA guestbook that persists.").decode()
    p, note = R.fold_requirement_doc({"requirement": "base ask", "name": "g",
                                      "doc_b64": doc, "doc_name": "spec.md"})
    assert "doc_b64" not in p and "doc_name" not in p          # stripped before argv
    assert p["requirement"].startswith("base ask")
    assert "A guestbook that persists." in p["requirement"]
    assert "spec.md" in p["requirement"] and note and "spec.md" in note


def test_runner_handle_control_chat_and_apps(monkeypatch):
    import area.runner as R
    import area.web.chat as C
    import area.web.jobs as J

    monkeypatch.setattr(C.J, "list_apps", lambda: [{"name": "lf_real"}])
    monkeypatch.setattr(J, "list_apps", lambda: [{"name": "lf_real"}, {"name": "notes_cf"}])
    chat = R.handle_control(P.chat_msg("7", "có app nào?"))
    assert chat["type"] == "chat_reply" and chat["id"] == "7" and chat["action"] == "answer"
    apps = R.handle_control(P.apps_req())
    assert apps["type"] == "apps" and "lf_real" in apps["apps"]
    assert R.handle_control({"type": "log"}) is None
