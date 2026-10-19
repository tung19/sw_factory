"""area.web.intake — the keyless forcing-intake conversation. Pure prompt-build +
reply-parse are tested directly; the single `claude -p` call (_ask_llm) is stubbed
(same posture as the deploy tests: no live model call here)."""
import area.web.intake as I


def test_build_prompt_includes_system_history_and_message():
    p = I.build_prompt(
        [{"role": "user", "text": "app ghi chú"}, {"role": "assistant", "text": "hỏi 1 câu"}],
        "có tìm kiếm",
    )
    assert "CHUYÊN VIÊN LẤY YÊU CẦU" in p
    assert "Người dùng: app ghi chú" in p and "Trợ lý: hỏi 1 câu" in p
    assert "có tìm kiếm" in p and I.SENTINEL in p  # the sentinel instruction is present


def test_build_prompt_caps_history_to_last_10():
    hist = [{"role": "user", "text": f"m{i}"} for i in range(20)]
    p = I.build_prompt(hist, "x")
    assert "m19" in p and "m10" in p and "m9" not in p


def test_parse_reply_not_ready_is_a_question():
    r = I.parse_reply("Bạn muốn chạy trên web hay mobile?")
    assert r["ready"] is False and r["requirement"] is None
    assert "web hay mobile" in r["reply"]


def test_parse_reply_ready_extracts_requirement_after_sentinel():
    raw = ("Đã đủ rõ!\n" + I.SENTINEL +
           "\nApp ghi chú web.\nTiêu chí nghiệm thu:\n- thêm note\n- liệt kê note")
    r = I.parse_reply(raw)
    assert r["ready"] is True
    assert r["reply"] == "Đã đủ rõ!"
    assert "App ghi chú web." in r["requirement"] and "thêm note" in r["requirement"]
    assert I.SENTINEL not in r["requirement"]


def test_intake_turn_parses_model_output(monkeypatch):
    monkeypatch.setattr(I, "_ask_llm",
                        lambda prompt: "ok\n" + I.SENTINEL + "\nmô tả app\nTiêu chí:\n- a")
    r = I.intake_turn([{"role": "user", "text": "hi"}], "làm app")
    assert r["ready"] is True and "mô tả app" in r["requirement"]


def test_intake_turn_degrades_on_failure(monkeypatch):
    def boom(prompt):
        raise RuntimeError("no cli")

    monkeypatch.setattr(I, "_ask_llm", boom)
    r = I.intake_turn([], "x")
    assert r["ready"] is False and "chưa gọi được LLM" in r["reply"]
