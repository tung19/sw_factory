# AREA — Kế hoạch kiến trúc & trạng thái

> **Loại:** Sản phẩm **nội bộ** (internal tool).
> **Cập nhật:** 2026-10-19.
> **▶ RESUME (session mới):** đọc memory `area-session-handoff` + §11 bên dưới. Tóm tắt: shipped --tdd/clone-parity/intake/author-oracle-loop/dashboard/Langfuse/expected-results+clarify/**multi-provider deploy (cloudflare+vercel)**; live: gb-d1 ✅, notes-cf (signup vỡ — bug server-action intent), dashboard :8787, Langfuse :3000. Next: Vercel live-deploy (cần `VERCEL_TOKEN`), Vercel pha-b (Postgres/KV), xác nhận gate E2E cứu signup, PR1–PR8.
> **Repo:** github.com/tung19/sw_factory (private).
>
> **Nhật ký quyết định:**
> - **Lõi = OpenHands `software-agent-sdk` 1.55.1** (pin), chạy **keyless qua Claude Code (ACP)** — đã chứng minh.
> - **Deploy = Cloudflare Workers (vinext + `@vinext/cloudflare`)**; auth keyless bằng **`cf auth login`** (Cloudflare CLI — KHÔNG phải wrangler), hoặc `CLOUDFLARE_API_TOKEN`. `vinext` beta. ✅ Đã deploy thật: `guestbook.monbkel.workers.dev` (HTTP 200).
> - **Self-correct = oracle-bằng-test (`run_until`)**, KHÔNG dùng `run_goal`+judge (judge cần key). *(Xem gap P1: oracle hiện bị agent tự-chấm.)*
> - **KHÔNG lấy nguyên Specora** (khóa stack Docker/FastAPI, alpha, patent) → chỉ "đào" ý tưởng contract-schema + healer-loop, cài lại trên stack Cloudflare.
> - **Xương sống = HYBRID 2 lớp** (2026-10-18): AREA (engine tự trị oracle-loop) làm Construction+Validation core; **AI-DLC (`awslabs/aidlc-workflows`)** làm front-end quy trình (Inception: requirement→stories→Units of Work + Testing Posture, truy vết/audit). Nối qua **artifact seam** ở `area/intake/aidlc.py` (map artifact AI-DLC → spec.yaml/acceptance.yaml), **KHÔNG wiring runtime in-process** (TS↔Python quá đắt). Hút thêm từ AI-DLC: bản đồ phase/stage + "reviewer as adversary" (= holdout). **Audit/truy vết + harness-neutral + cộng đồng/bus-factor lấy bằng cách DEPEND + EMIT (AREA ghi evidence vào trail AI-DLC), KHÔNG migrate code** — fork sẽ phá chính bus-factor/cộng đồng và không mang được tính harness-neutral (đó là kiến trúc, không phải module).

AREA = một **orchestrator do ta tự viết** (~1000 dòng keo) điều phối OpenHands SDK. Không repo đơn lẻ nào là "toàn bộ lõi".

---

## 1. Tầm nhìn — 2 luồng vào, 1 lõi chung

```
LUỒNG A (Requirement):  Requirement (NL) ─┐
                                           ├─▶ SPEC ─▶ DEV LOOP ─▶ VERIFY ─▶ DEPLOY ─▶ (HEAL)
LUỒNG B (Clone app):    App mẫu ──────────┘  (artifact)  (self-correct)           (lỗi→sửa spec→regen)
```

**Xương sống = vòng hội tụ theo oracle** (không phải tooling). Nguyên tắc bất biến:
- Mọi spec phải sinh acceptance criteria + test chạy được = "oracle"; **không phó mặc LLM tự sinh+tự chấm** (holdout độc lập — P1 ✅).
- Vòng lặp chỉ hội tụ tới **"oracle xanh"**, không tới "perfect" trừu tượng → *chất lượng ≤ độ mạnh + độ độc lập của oracle*.
- **TDD = đặt oracle ra TRƯỚC code** (vòng có đích từ iteration 0; build bị lái bởi test implementer không viết/không sửa được). Chế độ `--tdd` (xem §10).
- Clone/RE: **app gốc LÀ oracle vàng** → "perfect" = parity hành vi; build-to-parity.
- "Loop tới perfect" phải có cửa DỪNG: oracle xanh | budget/iteration cap (P2) | phát hiện kẹt; + human gate tầng trên ("oracle có đúng không" là bài toán spec).

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
│   ├── intake/    ✅ aidlc.py (Hybrid seam: AI-DLC artifact→spec + emit evidence)
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

**Đã xong P1–P6 + design.** **Rigor thêm:** security/static gate (`area audit`) + chaos/resilience (`area chaos`). **Prod-monitoring + self-heal loop** (`area monitor/status/watch`: probe→heal→rebuild→gate→redeploy) ✅. Còn (tùy chọn): perf/load gate, NFR, CI/CD. **Tự động:** `area run ... --all [--deploy]` chạy mọi gate (verify→audit→e2e→chaos) sau build, chặn deploy nếu fail; audit/chaos tự ghi memory.

**Command box (`area iterate` + dashboard tab "Iterate (ra lệnh)")** ✅ (2026-10-19): user ra lệnh NL cho app ĐANG CÓ ("thêm nút xoá", "đổi dark mode") → lệnh được **gộp vào spec** (`compose_amended_requirement`, không raw-to-agent) → **re-lock oracle (TDD mặc định)** → rebuild + gate; target tự nhận theo app. Giữ nguyên xương sống oracle-loop. Chạy qua job-manager (SSE timeline) + sau auth PR6. `area/pipeline.py:iterate_pipeline`, `area/cli.py` lệnh `iterate`, `area/web` kind `iterate`. 11 test.

### Lộ trình Hybrid + TDD (2026-10-18, đang làm theo thứ tự)
| # | Việc | Done khi |
|---|---|---|
| **T1** | 🟢 `--tdd` (run+clone+intake): khóa holdout TRƯỚC build; oracle = test đã khóa (TDD + chống tự-chấm hợp nhất). **Escape-hatch** `_CHALLENGE.md`→verifier độc lập tái-thẩm→re-lock (evolving-under-governance, có cận). **Clone build-to-parity** (neo test vào hành vi app gốc). ✅ **validated live**: `run --tdd` (counter) + `clone --tdd` **parity** (tip-calc, test neo vào app gốc) đều GREEN; author-wander được retry cứu | `area run/clone --tdd` build xanh *qua* test độc lập đã khóa |
| **T2** | ✅ **Test suite dogfood cho AREA** (`tests/`, 41 tests, logic thuần, không agent): lock/challenge, thứ tự pipeline+vòng challenge, CLI, safe_name, memory, intake, parity, author-retry | `python -m pytest` xanh |
| **T3** | 🟢 **Adapter `area/intake/aidlc.py`** + `area intake`: artifact AI-DLC → spec/acceptance (Testing Posture→AC); **emit evidence** ngược vào trail AI-DLC (`aidlc_trace.jsonl`) cho audit end-to-end. ✅ **validated live** (temp-converter GREEN; Testing Posture→6 AC đúng từng số; trail 3 event cùng trace id) | `area intake <path> --tdd` ra app từ artifact AI-DLC |
| **T4** | 🟢 **Author oracle-loop** (`author_until` + `_authoring_oracle`): trị gốc "author-wander" (keyless ACP KHÔNG cắt được tool → ép chất lượng output: phủ mọi AC + CONTRACT + assertion, no-progress detect, feedback cụ thể). ✅ **validated live** (locked "all 3 AC covered", author 1 lượt 64s) | author không fail vì wander, phủ đủ AC |
| **T5** | 🟢 **Dashboard nâng cấp** (`area/web`): tab **Intake** upload PDF/Word/MD (`pypdf`/`python-docx`) + describe → `area intake`; toggle **TDD + gates**; **pipeline timeline** live (parse marker SSE); preview iframe app deploy. ✅ smoke live (index/jobs/upload) | upload doc → build; xem tiến trình trực quan |
| **T6** | 🟢 **Langfuse process-viz** (`area/trace.py`): 1 **trace/pipeline**, 1 **span/agent-run** (cost/latency/outcome lấy từ `area/obs`); emit TRỰC TIẾP (không phụ thuộc OTel-từ-ACP). Optional + no-op nếu thiếu SDK/keys (giữ keyless sạch). URL trace in ra log → link trên dashboard. ✅ tested fake-sink 63/63. Kích hoạt: `pip install 'area[trace]'` + `LANGFUSE_PUBLIC_KEY/SECRET_KEY[/HOST]` | thấy cây trace cost/latency mỗi stage |

---

## 11. Production readiness — đánh giá & kế hoạch (2026-10-18)

**Trạng thái:** POC đã validated end-to-end trên app NHỎ tự-chứa. **Chưa production** cho phần mềm thật.

### Blocker (theo mức nghiêm trọng)
| # | Blocker | Kế hoạch |
|---|---|---|
| ~~**PR1**~~ | **Scope build = app đồ chơi** (prompt hardcode "in-memory, no auth, single user") | ✅ **MỞ + validated live** (plain/`node:sqlite`): `prod_notes` — signup/login + **password hash** (AC "không plaintext"), **per-user isolation** (user A không thấy note user B), **durable qua restart** (test `vi.resetModules()` + reopen cùng file DB), holdout 6 file/**8 AC**, build GREEN (~$5.2). ⏳ còn: **cloudflare D1** (target deploy thật) + 2–3 app nữa (PR5) |
| **PR2** | Phụ thuộc beta/mong manh (OpenHands weekly-break, vinext beta, REA lỗi) | pin + adapter đã có; cần fallback vinext ổn định; khoanh/bỏ REA |
| **PR3** | Không tất định + chi phí ($2–6/run, có wander) | model-tiering, cap chặt, đo tỉ lệ retry; author oracle-loop ✅ đã giảm |
| **PR4** | Thiếu gate **perf/load, NFR, CI/CD**; security gate cơ bản. **E2E gate CHỨNG MINH là BẮT BUỘC** (2026-10-19): notes_cf holdout-logic GREEN nhưng **signup VỠ live** (server-action intent không tới formData) — Playwright E2E bắt trong vài giây, logic-holdout không thể | **bật `--e2e`/`--all` trước deploy mọi app có auth/session/form** ✅ (validated live notes_cf). **CI/CD cho AREA ✅ DONE** (`.github/workflows/ci.yml`: pin deps từ requirements.lock + `pip install -e .` + pytest 126 trên push/PR→main; compileall; concurrency-cancel). Còn: perf/load + NFR gate |
| **PR5** | Chỉ test app bé; chưa có app thật (DB+auth+multi-page) | mốc tiếp: 2–3 app thật có DB+auth |
| ~~**PR6**~~ | ✅ **DONE**: dashboard có **token-auth** (`area/web/auth.py`, kiểu Jupyter). Mọi request phải có token qua `?token=`/Bearer/cookie; `?token=` set cookie HttpOnly+SameSite=Strict để fetch/SSE tự authed. Token = `AREA_GUI_TOKEN` hoặc tự sinh (in URL kèm token khi `area gui`); escape-hatch `AREA_GUI_NO_AUTH=1`. Pure-ASGI (không phá SSE). 9 test + smoke live (401 thiếu/sai token, 200 khi có). Còn (tùy): HTTPS/reverse-proxy nếu expose ngoài localhost | thêm auth + không expose công khai |
| **PR7** | Deploy/rollback/monitor mới validate 1 lần (guestbook) | ✅ **DEPLOY D1 LIVE validated**: `area deploy gb_d1` → auto-provision D1 (`wrangler d1 create gb-d1: ok`) → deploy vinext/cf → **https://gb-d1.monbkel.workers.dev HTTP 200**. **Persist proven live** (Playwright: post message → reload → vẫn còn trong D1). Handshake wrangler-D1 ↔ vinext `bindings.d1()` **OK, không cần chỉnh** (table tạo lazy). Còn: rollback/monitor nhiều lần |
| **PR8** | Bus factor (~2500 dòng, 1 người); Hybrid front-end chưa dựng | dựng AI-DLC front-end thật + emit evidence nối trail |

### "Production-ready" = done khi
- [ ] Build được app **persistence thật + auth + multi-user**, validated live trên 2–3 app.
- [ ] Gate **perf/load + NFR + security sâu** + **CI/CD** cho AREA.
- [ ] Phụ thuộc beta có fallback; chi phí/độ tất định đo & kiểm soát được.
- [ ] Dashboard có auth; deploy/rollback/monitor validated nhiều lần.
