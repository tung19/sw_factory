"""area.web.chat — the governed, KEYLESS command/chat box.

A chat message is routed, never piped raw to the model (that would bypass the
oracle spine). Intent is classified deterministically:

  * "change"  -> propose an `iterate` job on the selected app (spec -> re-lock
                 oracle -> rebuild). The UI confirms before spending (agent $).
  * "build"   -> a new app: prefill the Run tab (the user names + confirms).
  * "question"-> answered from the factory's OWN stored state (spec, apps, jobs,
                 deploy URL) — free + instant, no model call.

So free-form typing works, questions are cheap, and anything that changes code
still flows through the governed pipeline. (Keyless: no ANTHROPIC_API_KEY; the
actual model work happens inside the normal ACP build loop when a job runs.)
"""
from __future__ import annotations

import re

from area.web import jobs as J

_BUILD = re.compile(
    r"\b(build|create|make|generate|scaffold|new app|tạo|xây|dựng|viết)\b"
    r".{0,24}\b(app|site|web|page|trang|ứng dụng|phần mềm|dự án)\b",
    re.I,
)
_CHANGE = re.compile(
    r"\b(add|remove|delete|change|update|fix|rename|replace|disable|enable|refactor|"
    r"thêm|bỏ|xoá|xóa|sửa|đổi|cập nhật|chỉnh|tắt|bật|gỡ|làm lại)\b",
    re.I,
)
_QUESTION = re.compile(
    r"\?|\b(what|why|how|which|where|who|is|are|does|do|can|list|show|explain|"
    r"là gì|sao|tại sao|thế nào|bao nhiêu|giải thích|liệt kê|xem|có phải|đang|chưa|rồi chưa)\b",
    re.I,
)


def classify_intent(msg: str) -> str:
    """Return 'build' | 'change' | 'question'. Build and change win over question
    cues, because a mis-routed change is confirmed before spending anyway, while a
    mis-answered question costs nothing."""
    m = (msg or "").strip()
    if not m:
        return "question"
    if _BUILD.search(m):
        return "build"
    if _CHANGE.search(m):
        return "change"
    if _QUESTION.search(m):
        return "question"
    return "change"  # a bare imperative ("dark mode") -> treat as a command (confirmed)


def answer_from_state(msg: str, app: str = "") -> str:
    """Answer a question from the factory's OWN data — no model call."""
    m = (msg or "").lower()
    if app:
        spec = J.read_spec(app)
        app_jobs = [j for j in J.MANAGER.list() if j.get("name") == app]
        url = next((j["url"] for j in app_jobs if j.get("url")), None)
        if any(k in m for k in ("spec", "acceptance", "yêu cầu", "tiêu chí", " ac", "criteria")):
            return (f"Spec của '{app}':\n\n{spec.get('spec') or '(chưa có)'}\n\n"
                    f"Acceptance:\n{spec.get('acceptance') or '(chưa có)'}")
        if any(k in m for k in ("url", "deploy", "live", "địa chỉ", "link", "address")):
            return (f"'{app}' đang live tại {url}" if url
                    else f"'{app}' chưa có URL deploy (chưa deploy qua dashboard).")
        if any(k in m for k in ("status", "trạng thái", "gate", "test", "build", "kết quả", "job")):
            if app_jobs:
                last = app_jobs[0]
                tail = f" · {url}" if url else ""
                return f"Job gần nhất của '{app}': {last.get('kind')} · {last.get('status')}{tail}"
            return f"Chưa có job nào cho '{app}'."
    if any(k in m for k in ("app", "ứng dụng", "danh sách", "list", "có gì")):
        apps = J.list_apps()
        names = ", ".join(a["name"] for a in apps)
        return "Các app hiện có: " + (names or "(chưa có)")
    if any(k in m for k in ("job", "chạy", "running", "tiến trình")):
        js = J.MANAGER.list()
        head = ", ".join(f"{j.get('kind')}·{j.get('name')}[{j.get('status')}]" for j in js[:5])
        return f"{len(js)} job. Gần nhất: " + (head or "(trống)")
    return ("Mình trả lời được từ dữ liệu nhà máy: spec/acceptance, danh sách app, "
            "job & trạng thái, URL deploy. Câu này cần agent suy luận sâu — để governed + "
            "không tốn phí oan, hãy diễn đạt dạng lệnh (vd 'thêm …') để chạy qua iterate, "
            "hoặc hỏi về spec/app/job/URL.")


def route(message: str, app: str = "") -> dict:
    """Classify + build the chat response the dashboard acts on."""
    intent = classify_intent(message)
    if intent == "change" and app:
        return {
            "action": "iterate", "app": app, "instruction": message,
            "reply": (f"→ Sẽ sửa app «{app}» qua iterate: gộp lệnh vào spec → khoá lại oracle "
                      "(TDD) → rebuild + gates. Xác nhận chạy? (~$1–3, 1–3 phút)"),
        }
    if intent in ("build", "change"):
        return {
            "action": "run", "instruction": message,
            "reply": ("→ Đây là tạo app mới. Mình đã điền mô tả vào tab Run — đặt tên rồi bấm "
                      "Bắt đầu. (Hoặc chọn một app ở trên để sửa app đó qua iterate.)"),
        }
    return {"action": "answer", "reply": answer_from_state(message, app)}
