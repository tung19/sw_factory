# AREA — Kế hoạch kiến trúc & trạng thái

> **Loại:** Sản phẩm **nội bộ** (internal tool).
> **Cập nhật:** 2026-10-18 (đồng bộ với hệ thống đã ship + chaos-audit).
> **Repo:** github.com/tung19/sw_factory (private).
>
> **Nhật ký quyết định:**
> - **Lõi = OpenHands `software-agent-sdk` 1.55.1** (pin), chạy **keyless qua Claude Code (ACP)** — đã chứng minh.
> - **Deploy = Cloudflare Workers (vinext + `@vinext/cloudflare`)**; auth keyless bằng **`cf auth login`** (Cloudflare CLI — KHÔNG phải wrangler), hoặc `CLOUDFLARE_API_TOKEN`. `vinext` beta. ✅ Đã deploy thật: `guestbook.monbkel.workers.dev` (HTTP 200).
> - **Self-correct = oracle-bằng-test (`run_until`)**, KHÔNG dùng `run_goal`+judge (judge cần key). *(Xem gap P1: oracle hiện bị agent tự-chấm.)*
> - **KHÔNG lấy nguyên Specora** (khóa stack Docker/FastAPI, alpha, patent) → chỉ "đào" ý tưởng contract-schema + healer-loop, cài lại trên stack Cloudflare.

AREA = một **orchestrator do ta tự viết** (~1000 dòng keo) điều phối OpenHands SDK. Không repo đơn lẻ nào là "toàn bộ lõi".

---

## 1. Tầm nhìn — 2 luồng vào, 1 lõi chung

```
LUỒNG A (Requirement):  Requirement (NL) ─┐
                                           ├─▶ SPEC ─▶ DEV LOOP ─▶ VERIFY ─▶ DEPLOY ─▶ (HEAL)
LUỒNG B (Clone app):    App mẫu ──────────┘  (artifact)  (self-correct)           (lỗi→sửa spec→regen)
```

Nguyên tắc bất biến: **mọi spec phải sinh acceptance criteria + test chạy được** = "oracle". ⚠️ PLAN yêu cầu **không phó mặc LLM tự sinh test** — hiện chưa đạt (gap **P1**).

---

## 2. Quyết định lõi (đã ship)

| Thành phần | Chọn | Ghi chú |
|---|---|---|
| **Execution engine** | OpenHands `software-agent-sdk` 1.55.1 (MIT, pin) | bọc sau `area/engine` |
| **Harness/model** | **Claude Code qua ACP** (keyless, không key) | `area/engine.build_agent(backend="acp")` |
| **Self-correct** | **`run_until`** (oracle = test, lặp tới khi xanh) | KHÔNG dùng run_goal/judge (cần key) |
| **Spec stage** | tự xây, schema Pydantic + prompt | `area/spec` |
| **Clone (RE)** | 2 tầng (xem §4) | `area/re` |
| **Deploy** | **Cloudflare Workers (vinext)** + human gate | `area/deploy`, auth `cf auth login` |
| **Healer** | lỗi runtime → sửa **spec** → regen | `area/heal` (ý tưởng Specora) |
| **GUI** | Starlette web dashboard | `area/web`, lệnh `area gui` |

---

## 3. Kiến trúc tổng thể (thực tế)

```
  Luồng A: Requirement ─┐
  Luồng B: App mẫu ─▶ area/re (Tier1 source/curl | Tier2 REA MCP, opt-in)
                        │
                        ▼
               area/spec  → spec.yaml + acceptance.yaml  (Pydantic-validated, oracle)
                        ▼
               area/build → scaffold Next.js (vinext) ─┐
                        │                               │ run_until: agent build → test → fix → lặp
                        ◀───────────────────────────────┘ (oracle = next/vinext build + Vitest)
                        ▼
               area/deploy → `cf`/vinext deploy  → 🔒 human gate → *.workers.dev
                        ▼
               area/heal → (khi có lỗi runtime) sửa spec → regen
   Giao diện: area/cli (run/clone/deploy/heal/gui) + area/web (GUI + SSE log)
```

## 4. Luồng B — Clone 2 tầng (đã ship)

- **Tier 1 (mặc định, keyless, không Docker):** agent dùng tool của chính nó — `git clone`/đọc source, hoặc `curl` URL — suy ra feature + data model → spec. *(Khác PLAN cũ "browser+repomix MCP" vì né Docker.)*
- **Tier 2 (opt-in `--rea`, chỉ app được phép):** cắm REA MCP (`rea_mcp_config`, stdio `npx rea-agents`). ⚠️ REA beta + phiên gần đây lỗi kết nối `-32000` → wiring sẵn nhưng chưa chạy thật ổn.

## 5. Command surface

```
area run   "<requirement>"  [--target cloudflare|plain] [--deploy]
area clone "<git|path|url>"  [--kind ...] [--rea] [--deploy]
area deploy <name>           [--yes]
area heal  <name> --error "<log>"  [--no-rebuild]
area gui                     # dashboard http://127.0.0.1:8787
```

## 6. Roadmap — trạng thái

| Phase | Mục tiêu | Trạng thái |
|---|---|---|
| 0. Setup | uv + Python 3.12 + pin OpenHands SDK | ✅ |
| 1. Luồng A | requirement → spec → app (`area run`) | ✅ (todo, notes) |
| 2. Self-correct | `run_until` oracle-test (keyless) | ✅ (deviation: không dùng judge) |
| 3. Deploy | Cloudflare + human gate + **rollback** | ✅ (guestbook live) · `area rollback` ✅ |
| 4. Clone Tier 1 | RE app mẫu → spec → app | ✅ (source/curl) · E2E via `area e2e` ✅ |
| 5. Tier 2 + hardening | REA opt-in; hardening | ⚠️ một phần: REA wiring ✅, compat-date fix ✅, healer ✅; **thiếu cost-cap, model-tiering, observability** |
| + GUI | web dashboard | ✅ (ngoài plan gốc) |
| + Chaos-audit | path-traversal, server-400, command_verifier, atomic jobs.json | ✅ đã vá |

## 7. Cấu trúc thực tế

```
SW_Factory/
├── area/
│   ├── engine/    ✅ adapter OpenHands (build_agent acp/llm, run_until, verifiers)
│   ├── spec/      ✅ schema + extract_spec
│   ├── build/     ✅ nextjs (target cloudflare|plain)
│   ├── re/        ✅ clone Tier1/Tier2 (spec_from_source, rea_mcp_config)
│   ├── deploy/    ✅ cloudflare + human gate
│   ├── heal.py    ✅ spec-level healer
│   ├── pipeline.py / cli.py / _util.py  ✅
│   ├── web/       ✅ GUI (Starlette + SSE)
│   ├── intake/    ⬜ rỗng (gộp vào spec/re)
│   ├── verify/    ⬜ rỗng (gộp vào engine oracle; CHƯA có E2E/holdout)
│   └── memory/    ⬜ rỗng (CHƯA có experience store)
├── workspace/     (gitignored) apps + specs sinh ra
├── scripts/       01–05 demo + _reference/
├── .mcp.json · pyproject.toml · requirements.lock · PLAN.md · README.md
```

## 8. Điều kiện tiên quyết — trạng thái
- [x] Python 3.12 (uv) · [x] uv · [x] GitHub (gh) · [x] Cloudflare (`cf auth login`)
- [x] Keyless qua Claude Code (không cần `LLM_API_KEY`)
- [~] Docker daemon: tắt — **không cần** cho đường keyless/local; cần nếu bật sandbox prod

## 9. Rủi ro & trạng thái
| Rủi ro | Cách chặn | Trạng thái |
|---|---|---|
| **LLM tự chấm test** (oracle bị lừa) | holdout / human acceptance test | ✅ **P1 shipped** (`area/verify`, validated notes 7/7) |
| Cháy quota (agent loop) | budget cap per run | ✅ **P2 shipped**: cap 80 steps/run + `--budget $`/`AREA_MAX_BUDGET` |
| OpenHands breaking (release tuần) | pin version + adapter | ✅ pin 1.55.1 + `area/engine` |
| REA mong manh/pháp lý | mặc định Tier 1; REA opt-in | ✅ |
| Code "trôi" | giữ spec artifact + regen | ✅ (regen từ spec) |
| vinext compat-date gotcha | bake fix vào build prompt | ✅ |
| Path traversal / server 500 / verifier crash / jobs.json race | chaos-audit fixes | ✅ đã vá |

---

## 10. VIỆC CÒN LẠI — ưu tiên (làm theo thứ tự)

| # | Mức | Việc | Định nghĩa "done" |
|---|---|---|---|
| ~~**P1**~~ | ✅ | ~~**Oracle holdout**~~ **XONG**: `area/verify` — verifier agent viết test, khóa checksum, fixer không được sửa (`area verify`, `--verify`) | ✅ validated notes 7/7 độc lập |
| ~~**P2**~~ | ✅ | ~~**Cost/budget cap**~~ **XONG**: cap 80 steps/run (mặc định, SDK là 500) + `--budget $`/`--agent-iters`/env | run dừng khi vượt cap |
| ~~**P3**~~ | ✅ | ~~**Rollback**~~ **XONG**: `area rollback <name>` (wrangler rollback, server-side, human gate) | ⚠️ cần re-deploy thật để validate |
| **P4** | 🟢 | **E2E/parity test** (Playwright) cho app & clone | parity test pass trên UI thật |
| **P5** | 🟢 | **Model tiering + observability** (log chi phí/vòng mỗi stage) | thấy được cost/latency mỗi run |
| **P6** | 🟢 | **Memory/experience store** (`area/memory`): lưu pattern lỗi→fix, inject lại | lần sau tránh lỗi đã gặp |

**Đã xong P1–P5.** **Còn lại: P6** (memory store).
