"""area.web.intake — the KEYLESS conversational "forcing" intake.

A real back-and-forth with Claude (via the Claude Code CLI in print mode — no API
key) that acts as a product-intake interviewer: it answers briefly, but FORCES the
conversation to converge on a clear, buildable requirement + acceptance criteria.
It never writes the product — the moment it is ready it emits a SPEC and hands off
to the normal oracle-loop (`run`: lock an independent holdout → build-to-green →
gates). So the LLM only sharpens the oracle's INPUT; the governed build is unchanged.

build_prompt() and parse_reply() are pure (unit-tested); _ask_llm() is the only
side-effecting part (one `claude -p` subprocess per turn, in a neutral cwd).
"""
from __future__ import annotations

import subprocess
import tempfile

SENTINEL = "<<<SPEC_READY>>>"

_SYSTEM = (
    "Bạn là CHUYÊN VIÊN LẤY YÊU CẦU của AREA — một nhà máy phần mềm tự động.\n"
    "Mục tiêu: qua hội thoại NGẮN GỌN, ÉP người dùng làm rõ ý tưởng tới mức ĐỦ ĐỂ BUILD.\n"
    "Quy tắc:\n"
    "- KHÔNG viết code, KHÔNG dùng tool. Trả lời bằng tiếng Việt, thân thiện, ngắn.\n"
    "- Nếu người dùng hỏi điều gì, trả lời ngắn — rồi LÁI về việc làm rõ phần mềm cần làm.\n"
    "- Mỗi lượt chỉ hỏi MỘT câu làm rõ quan trọng nhất (đối tượng dùng, tính năng cốt lõi, "
    "dữ liệu/lưu trữ, cách dùng, ràng buộc).\n"
    "- Khi đã đủ rõ để build (không cần hoàn hảo), DỪNG hỏi và XUẤT ĐÚNG định dạng sau, "
    "KHÔNG thêm gì phía sau:\n"
    f"{SENTINEL}\n"
    "<1–2 đoạn mô tả phần mềm>\n"
    "Tiêu chí nghiệm thu:\n"
    "- <tiêu chí 1>\n"
    "- <tiêu chí 2>\n"
    "- <...>\n"
)


def build_prompt(history: list[dict] | None, message: str) -> str:
    """Compose the single-shot prompt from the system brief + recent history + the
    latest user message. Pure."""
    lines: list[str] = []
    for h in (history or [])[-10:]:
        who = "Người dùng" if (h.get("role") == "user") else "Trợ lý"
        txt = (h.get("text") or "").strip()
        if txt:
            lines.append(f"{who}: {txt}")
    convo = "\n".join(lines) or "(chưa có)"
    return (f"{_SYSTEM}\n\n=== LỊCH SỬ HỘI THOẠI ===\n{convo}\n\n"
            f"=== NGƯỜI DÙNG VỪA NÓI ===\n{(message or '').strip()}")


def parse_reply(raw: str) -> dict:
    """Split a model turn into {reply, ready, requirement}. When the SPEC sentinel
    is present, everything after it is the handoff requirement. Pure."""
    text = (raw or "").strip()
    if SENTINEL in text:
        before, _, after = text.partition(SENTINEL)
        return {
            "reply": before.strip() or "Đã đủ rõ — mình chốt spec. Bấm build nhé.",
            "ready": True,
            "requirement": after.strip(),
        }
    return {"reply": text or "(không có phản hồi)", "ready": False, "requirement": None}


def _ask_llm(prompt: str) -> str:
    """One keyless turn via the Claude Code CLI (print mode). Runs in a throwaway
    empty dir so the agent has nothing to explore — it just answers."""
    with tempfile.TemporaryDirectory() as d:
        p = subprocess.run(
            ["claude", "-p", prompt],
            cwd=d, capture_output=True, text=True, timeout=180,
        )
        return (p.stdout or p.stderr or "").strip()


def intake_turn(history: list[dict] | None, message: str) -> dict:
    """One conversational intake turn. Returns {reply, ready, requirement}; never
    raises (a model/CLI failure degrades to a plain, non-ready reply)."""
    try:
        return parse_reply(_ask_llm(build_prompt(history, message)))
    except Exception as e:  # noqa: BLE001
        return {"reply": f"(xin lỗi, chưa gọi được LLM: {e}) — thử lại nhé.",
                "ready": False, "requirement": None}
