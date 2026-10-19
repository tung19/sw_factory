"""The governed, keyless chat box (area/web/chat.py): intent classification,
answering questions from the factory's own state, and routing a change request
to a confirmable iterate (never raw to the model). Pure logic — no agents."""
import types

import area.web.chat as C


# ---- intent classification --------------------------------------------------

def test_classify_change_vn_en():
    for m in ["thêm nút xoá", "bỏ đăng nhập", "add a delete button", "fix the signup", "đổi sang dark mode"]:
        assert C.classify_intent(m) == "change", m


def test_classify_build_new_app():
    assert C.classify_intent("tạo một app todo") == "build"
    assert C.classify_intent("build me a notes web app") == "build"


def test_classify_question():
    for m in ["spec của notes_cf là gì?", "có app nào?", "why did the gate fail", "app này deploy chưa"]:
        assert C.classify_intent(m) == "question", m


def test_classify_greetings_are_smalltalk():
    for m in ["hello", "hi", "chào bạn", "bạn khoẻ ko", "cảm ơn nhé", "thanks"]:
        assert C.classify_intent(m) == "smalltalk", m


def test_classify_short_unknown_is_unknown_not_build():
    # a short, unrecognized utterance must NOT become a surprise "create app"
    assert C.classify_intent("dark mode") == "unknown"
    assert C.classify_intent("xyz abc") == "unknown"
    # but a substantive description still reads as a build
    assert C.classify_intent("một trang web bán cà phê có giỏ hàng") == "build"


# ---- answer_from_state (no model call) --------------------------------------

def _patch_state(monkeypatch, *, spec=None, apps=None, jobs=None):
    monkeypatch.setattr(C.J, "read_spec", lambda name: spec or {"spec": "", "acceptance": ""})
    monkeypatch.setattr(C.J, "list_apps", lambda: apps or [])
    fake = types.SimpleNamespace(list=lambda: jobs or [])
    monkeypatch.setattr(C.J, "MANAGER", fake)


def test_answer_spec(monkeypatch):
    _patch_state(monkeypatch, spec={"spec": "summary: tip calc", "acceptance": "AC-1 ok"})
    out = C.answer_from_state("cho xem spec", app="lf_real")
    assert "tip calc" in out and "AC-1 ok" in out


def test_answer_deploy_url(monkeypatch):
    _patch_state(monkeypatch, jobs=[{"name": "lf_real", "kind": "deploy", "status": "green",
                                     "url": "https://x.vercel.app"}])
    out = C.answer_from_state("url deploy ở đâu", app="lf_real")
    assert "https://x.vercel.app" in out


def test_answer_list_apps(monkeypatch):
    _patch_state(monkeypatch, apps=[{"name": "lf_real"}, {"name": "notes_cf"}])
    out = C.answer_from_state("có app nào?")
    assert "lf_real" in out and "notes_cf" in out


def test_answer_fallback(monkeypatch):
    _patch_state(monkeypatch)
    out = C.answer_from_state("giải thích thuật toán hashing bạn dùng")
    assert "iterate" in out.lower()  # nudges toward the governed path


# ---- route ------------------------------------------------------------------

def test_route_change_with_app_proposes_iterate(monkeypatch):
    _patch_state(monkeypatch)
    r = C.route("thêm nút xoá", app="notes_cf")
    assert r["action"] == "iterate" and r["app"] == "notes_cf"
    assert r["instruction"] == "thêm nút xoá" and "oracle" in r["reply"].lower()


def test_route_change_without_app_goes_to_run(monkeypatch):
    _patch_state(monkeypatch)
    r = C.route("thêm dark mode", app="")
    assert r["action"] == "run" and r["instruction"] == "thêm dark mode"


def test_route_build_goes_to_run(monkeypatch):
    _patch_state(monkeypatch)
    assert C.route("tạo app blog", app="anything")["action"] == "run"


def test_route_question_answers(monkeypatch):
    _patch_state(monkeypatch, apps=[{"name": "lf_real"}])
    r = C.route("có app nào?", app="")
    assert r["action"] == "answer" and "lf_real" in r["reply"]


def test_route_greeting_is_friendly_not_build(monkeypatch):
    _patch_state(monkeypatch)
    r = C.route("hello", app="")
    assert r["action"] == "answer" and "tạo app mới" not in r["reply"]


def test_route_unknown_without_app_guides_not_build(monkeypatch):
    _patch_state(monkeypatch)
    r = C.route("dark mode", app="")
    assert r["action"] == "answer" and "chưa rõ" in r["reply"]


def test_route_unknown_with_app_iterates(monkeypatch):
    _patch_state(monkeypatch)
    r = C.route("dark mode", app="notes_cf")      # short command on a selected app
    assert r["action"] == "iterate" and r["app"] == "notes_cf"
