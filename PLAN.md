# AREA — Kế hoạch kiến trúc (bản đã audit)

> **Loại:** Sản phẩm **nội bộ** (internal tool).
> **Ngày chốt:** 2026-10-17.
> **Trạng thái quyết định:** Lõi đã chốt sau 2 vòng khảo sát code-level + 1 vòng deep audit (kiểm chứng GitHub API) + 1 vòng khảo sát Specora bằng tay.
>
> **Nhật ký quyết định (2026-10-17):**
> - **Lõi = OpenHands `software-agent-sdk`**, chạy keyless qua Claude Code (ACP) — đã chứng minh.
> - **Deploy target = Next.js-on-Vercel (monolith)** — giữ nguyên.
> - **KHÔNG lấy nguyên Specora**: khảo sát tay cho thấy nó khóa cứng FastAPI+Postgres+Docker, Next.js chỉ là vỏ client, **không có đường Vercel** + alpha/1-dev → mâu thuẫn mục tiêu. Thay vào đó **"đào" hệ contract-schema (meta-YAML + stdlib mixins) và mô hình healer-loop** của Specora, cài lại trên OpenHands cho stack Vercel-native.
> - **Oracle self-correct = test (không judge-LLM)**: `run_goal` của OpenHands cần judge-LLM (tốn key) → đường keyless dùng oracle-bằng-test (`area/engine.run_until`).

AREA = một **orchestrator do ta tự viết**, điều phối các engine/stage best-of-breed. Không repo đơn lẻ nào là "toàn bộ lõi".

---

## 1. Tầm nhìn — 2 luồng vào, 1 lõi chung

```
LUỒNG A (Requirement):  Requirement (NL) ─┐
                                           ├─▶ SPEC ─▶ PLAN ─▶ DEV LOOP ─▶ VERIFY ─▶ DEPLOY
LUỒNG B (Clone app):    App mẫu ──────────┘        (artifact)  (code+test+self-correct)  (prod)
                        (reverse-engineer, 2 tầng)
```

Nguyên tắc bất biến: **mọi spec phải sinh acceptance criteria + test chạy được** → đó là "oracle" để vòng lặp biết khi nào "xong". Ưu tiên **acceptance test do người viết / holdout**, không phó mặc LLM tự sinh test (judge có thể bị lừa).

---

## 2. Quyết định lõi (đã chốt)

| Thành phần | Chọn | Lý do (đã kiểm chứng) |
|---|---|---|
| **Execution engine** | **OpenHands `software-agent-sdk`** (Python, MIT) | Có sẵn **vòng tự sửa có kiểm chứng** (`run_goal` + judge LLM đòi bằng chứng test-pass, `critic`, iterative-refinement). MCP first-class. Repo **đang active** (push hằng ngày). |
| **Harness/model** | LiteLLM (model-agnostic); tùy chọn chạy **Claude làm coder dưới OpenHands qua ACP** | Linh hoạt model; tận dụng chất lượng Claude khi cần. |
| **Clone app (RE)** | **2 tầng** (xem §4) | Giảm phụ thuộc + rủi ro pháp lý. |
| **Spec stage** | Tự xây — mượn **pattern PRD/TRD-eval-loop của MetaGPT** + giữ **spec artifact** kiểu Specora | MetaGPT mạnh khâu spec nhưng repo đã **đình trệ ~9 tháng** → chỉ mượn pattern, không phụ thuộc. |
| **Deploy** | **Vercel** qua Terminal tool / Vercel MCP, gate bằng stop-hook | Web app Next.js → Vercel. |
| **Tham khảo kiến trúc** | **Specora Core** (ý tưởng "contract = chân lý, code vứt đi, regen tất định") | Chỉ **mượn ý tưởng** — Specora alpha + **patent-pending**, KHÔNG dùng làm code. |

### ⚠️ Lưu ý vận hành bắt buộc
- **Pin version OpenHands SDK** + **bọc sau adapter của ta** (`run_goal`/`critic` là subsystem mới, repo release hằng tuần có breaking change).
- Local mode **không sandbox** → prod phải bật **Docker/cloud runtime**.
- OpenHands/MetaGPT đều **MIT** (không patent grant — nội bộ nên chấp nhận được).

---

## 3. Kiến trúc tổng thể

```
                 ┌─────────────── INTAKE ───────────────┐
  Luồng A:  Requirement (text/PRD) ─────────┐
  Luồng B:  App mẫu ──▶ RE 2 tầng ──────────┤
                                            ▼
                                ┌───────────────────────┐
                                │  SPEC STAGE            │  → spec.yaml + acceptance.yaml + tests/
                                │  (PRD/TRD pattern)     │     (spec artifact, versioned)
                                └───────────┬───────────┘
                                            ▼
                                ┌───────────────────────┐
                                │  OpenHands SDK engine  │  → dev + run_goal(judge) + critic
                                │  (pinned + adapter)    │     (self-correct tới khi test xanh)
                                └───────────┬───────────┘
                                            ▼
                         VERIFY (E2E + acceptance + holdout do người viết)
                                            ▼
                     Vercel staging → smoke test → 🔒 human gate → production
```

## 4. Luồng B — Clone app theo 2 tầng

- **Tầng 1 (mặc định, rủi ro thấp):** dùng **BrowserToolSet + repomix MCP + grep** của OpenHands → agent tự duyệt app mẫu (web/open-source/app của chính ta), suy ra hành vi, dựng **parity tests**. *Không cần REA.*
- **Tầng 2 (tùy chọn, chỉ khi được phép):** cắm **REA** qua `mcp_config` cho binary/closed-source sâu. Kèm xác nhận "authorized use".

➡️ Output cả 2 tầng đều đổ vào **SPEC STAGE** rồi chạy chung pipeline.

## 5. Các điểm cắm (integration points) trên OpenHands SDK

| Hạng mục | Cách cắm | Công sức |
|---|---|---|
| **Spec-extraction** | stage thượng nguồn + `register_tool` có `response_schema`; seed qua `AgentContext`/skills; tham khảo planning preset | trung bình |
| **REA (Tầng 2)** | thêm vào `Agent.mcp_config` = `MCPServer(url, auth)`; mẫu `examples/.../07_mcp_integration.py` | thấp |
| **Vercel deploy** | Terminal chạy `vercel --prod` *hoặc* Vercel MCP; gate "done" bằng stop-hook hoặc gộp vào `run_goal` objective | thấp |
| **Self-correct** | dùng sẵn `run_goal` + `critic` (bọc adapter, pin version) | gần như 0 |

---

## 6. Roadmap MVP

| Phase | Mục tiêu | "Done" khi |
|---|---|---|
| **0. Setup** | git init; cài OpenHands SDK bằng `uv` (Python 3.12); cấu hình key; chạy `01_hello_world` | agent chạy được 1 task đơn giản |
| **1. Luồng A tối giản** | requirement → spec artifact → 1 web app Next.js 1 tính năng → chạy local | app chạy, test pass |
| **2. Self-correct loop** | nối `run_goal`+judge vào acceptance test; auto-fix tới khi xanh | agent tự sửa tới khi test xanh |
| **3. Deploy** | Vercel staging → human gate → prod + rollback | 1 app lên prod thật |
| **4. Clone Tầng 1** | browser+repomix → clone 1 tính năng web app mẫu | parity tests pass |
| **5. Clone Tầng 2 (REA) + hardening** | cắm REA (opt-in); cost caps; model tiering; observability; pin/adapter | chạy ổn định nhiều lap |

## 7. Cấu trúc thư mục đề xuất

```
SW_Factory/
├── area/
│   ├── intake/          # nhận requirement + app mẫu
│   ├── re/              # reverse-engineer 2 tầng (browser/repomix | REA MCP)
│   ├── spec/            # spec stage → spec.yaml + acceptance.yaml + tests/
│   ├── engine/          # adapter bọc OpenHands SDK (pin version)
│   ├── verify/          # E2E + acceptance + holdout
│   ├── deploy/          # Vercel adapter + human gate
│   └── memory/          # experience/learning store
├── workspace/           # các web app được sinh ra
├── .mcp.json            # REA (opt-in) + Vercel + github
├── config/
├── PLAN.md
└── README.md
```

## 8. Điều kiện tiên quyết (môi trường hiện tại còn thiếu)

- [ ] **Python 3.12+** (máy đang 3.9.6) — cài qua `uv`.
- [ ] **`uv`** (chưa có) — để quản dep + tạo venv 3.12.
- [ ] **Docker daemon đang chạy** (hiện tắt) — cho sandbox prod & một số runtime.
- [ ] **1 API key LLM** (`LLM_API_KEY` + `LLM_MODEL`) — đặt qua biến môi trường, không dán vào chat.
- [ ] Tài khoản **Vercel** + **GitHub** (GitHub MCP cần authorize).

## 9. Rủi ro & cách chặn (từ deep audit)

| Rủi ro | Cách xử lý |
|---|---|
| Judge LLM bị "lừa" bằng test dễ | Acceptance test do người viết + holdout scenario |
| OpenHands SDK breaking change (release tuần) | Pin version + adapter cách ly |
| REA mong manh / pháp lý | Mặc định Tầng 1 (không REA); REA chỉ opt-in, authorized-use |
| Code "trôi" do LLM viết tự do | Giữ spec artifact + regen có kiểm soát (ý tưởng Specora) |
| Local mode không sandbox | Bật Docker/cloud runtime ở prod |

---

## Phụ lục — vì sao KHÔNG chọn các phương án khác
- **MetaGPT làm lõi:** không có MCP (cắm REA phải tự viết), deploy chỉ là stub trỏ cloud thương mại MGX, repo **đình trệ ~9 tháng**. Chỉ mượn pattern spec.
- **Specora Core làm lõi:** sát ý tưởng nhất, Forge codegen tất định/keyless chất lượng tốt (~16k LOC, ít stub) — nhưng **khóa cứng FastAPI+Postgres+Docker, Next.js chỉ là vỏ client, KHÔNG có đường Vercel**, cộng alpha/1-dev/patent-pending/no-tests. Stack mâu thuẫn mục tiêu Vercel → chỉ **"đào" contract-schema + healer-loop**, không lấy nguyên.
- **REA làm trung tâm:** REA chỉ "đọc hiểu", không build/deploy; mới, breaking change, pháp lý nhạy cảm.
```
