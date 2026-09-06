# Brutal Status Report — `feat/faceid-web-render`

**Generated:** 2026-09-06 11:17 IST  
**Branch:** `feat/faceid-web-render` (exists locally, **0 commits** — everything is unstaged/uncommitted)  
**Baseline:** `origin/main` at `911e0ac` (4 commits)  
**Test suite:** 114 passed · **1 failed** · 3 warnings (in the `.venv`)

---

## 🟢 What Actually Exists and Works

Claude Code wrote a lot of real, substantive code. Here's what's actually in the working tree:

### Modified files (11 files, +586 / −113 lines)

| File | What changed | Quality |
|------|-------------|---------|
| [`requirements.txt`](file:///c:/Users/Deepak/OneDrive/Desktop/T3/requirements.txt) | Added `Pillow≥12`, `pillow-heif≥1`, `fastapi`, `uvicorn`, `python-multipart`. Clean dep split. | ✅ Good |
| [`requirements-dev.txt`](file:///c:/Users/Deepak/OneDrive/Desktop/T3/requirements-dev.txt) | **NEW.** Separates `pytest`, `py-solc-x`, `httpx` from production. | ✅ Good |
| [`app/imaging.py`](file:///c:/Users/Deepak/OneDrive/Desktop/T3/app/imaging.py) | Universal decoder (`decode_to_bgr`): CV2-first → Pillow fallback with EXIF transpose. `downscale_bgr` for candidate memory cap. | ✅ Solid — correct BGR channel handling |
| [`app/ui.py`](file:///c:/Users/Deepak/OneDrive/Desktop/T3/app/ui.py) | `ConsoleSink` class + `ContextVar`-based `use_sink()`. Module-level delegators preserve every `ui.*` call site. | ✅ Excellent design — the right architecture |
| [`app/models.py`](file:///c:/Users/Deepak/OneDrive/Desktop/T3/app/models.py) | Added `page_link_status` on `CandidateVerification`, `link_statuses` on `SearchResponse`. Both optional, `to_record()` untouched. | ✅ Safe — hash-stable |
| [`app/search/social.py`](file:///c:/Users/Deepak/OneDrive/Desktop/T3/app/search/social.py) | `prioritise()` now accepts optional `link_statuses` map. Tier ordering: live+social → live → login-wall → unknown → dead. | ✅ Correct — default preserved |
| [`app/pipeline.py`](file:///c:/Users/Deepak/OneDrive/Desktop/T3/app/pipeline.py) | Milestone events (`ui.event()`), reachability integration, `run()` returns dict, `download_models`/`precompile_contract` commands. | ✅ Comprehensive — all 7 stages emit milestones |
| [`app/chain/compile.py`](file:///c:/Users/Deepak/OneDrive/Desktop/T3/app/chain/compile.py) | Lazy `solcx` import. 3-tier resolution: committed artifact → local cache → fresh compile. `precompile()` for dev. | ✅ Clean — runtime needs no Solidity toolchain |
| [`app/__main__.py`](file:///c:/Users/Deepak/OneDrive/Desktop/T3/app/__main__.py) | Added `download-models` and `precompile` CLI commands. | ✅ Clean |
| [`app/face/detector.py`](file:///c:/Users/Deepak/OneDrive/Desktop/T3/app/face/detector.py) | `load_image()` now routes through `decode_to_bgr()` for universal format support. | ✅ Correct |
| [`.gitignore`](file:///c:/Users/Deepak/OneDrive/Desktop/T3/.gitignore) | Anchored `/build/` so `contracts/build/` is tracked; committed artifact survives. | ✅ Correct |

### New files (8 files)

| File | Lines | Purpose | Quality |
|------|-------|---------|---------|
| [`app/net/reachability.py`](file:///c:/Users/Deepak/OneDrive/Desktop/T3/app/net/reachability.py) | 149 | Link classification (HEAD → GET fallback), SSRF-safe. `LinkStatus` enum. `check_links_concurrent()`. | ✅ Solid |
| [`app/server.py`](file:///c:/Users/Deepak/OneDrive/Desktop/T3/app/server.py) | 375 | FastAPI backend: staged uploads, SSE streaming via `ThreadPoolExecutor`, generator-driven heartbeat, bounded concurrency, single-use jobs, tamper-test endpoint. | ✅ Well-architected |
| [`app/web/index.html`](file:///c:/Users/Deepak/OneDrive/Desktop/T3/app/web/index.html) | 242 | SPA shell: upload card, 7-stage rail, live console, result panel (face box overlay, similarity gauge, evidence links, chain proof, integrity badge), verify/tamper section. | ✅ Rich structure |
| [`app/web/styles.css`](file:///c:/Users/Deepak/OneDrive/Desktop/T3/app/web/styles.css) | 364 | Dark "terminal-meets-fintech" theme. Design tokens, glassmorphism cards, animated gauge, face-box overlay, stage rail. | ✅ Premium look |
| [`app/web/app.js`](file:///c:/Users/Deepak/OneDrive/Desktop/T3/app/web/app.js) | 590 | Fetch-based SSE stream parser (no EventSource auto-reconnect), stage rail, live console, result rendering, box overlay, verify/tamper buttons, toast, copy hash. | ✅ Complete |
| [`tests/test_imaging_decode.py`](file:///c:/Users/Deepak/OneDrive/Desktop/T3/tests/test_imaging_decode.py) | 107 | Universal decoder tests: JPEG/PNG/WebP/BMP/GIF, AVIF/HEIC (skip-if-unavailable), EXIF transpose, failure modes, downscale. | ⚠️ 1 failing test |
| [`tests/test_reachability.py`](file:///c:/Users/Deepak/OneDrive/Desktop/T3/tests/test_reachability.py) | 116 | Link classification: all codes, HEAD→GET fallback, timeouts, SSRF safety (private IPs never probed), concurrent batching. | ✅ All pass |
| [`tests/test_server.py`](file:///c:/Users/Deepak/OneDrive/Desktop/T3/tests/test_server.py) | 187 | Upload validation, SSE streaming with mocked pipeline, typed errors, single-use jobs, capacity 429, verify endpoint. | ✅ All pass |
| [`contracts/build/VerificationRegistry.json`](file:///c:/Users/Deepak/OneDrive/Desktop/T3/contracts/build/VerificationRegistry.json) | — | Committed precompiled contract artifact (ABI + bytecode). | ✅ Generated and tracked |

---

## 🔴 What's Broken Right Now

### 1. Test failure: `test_empty_bytes_raise`

```
tests/test_imaging_decode.py::TestDecodeFailures::test_empty_bytes_raise - FAILED
```

**Root cause:** `cv2.imdecode()` crashes with an assertion error on empty `bytes` instead of returning `None`. The test expects `ImageError` but gets an unhandled OpenCV crash. Fix is trivial: guard `data` before calling `imdecode`.

```python
# imaging.py line 54 — needs an early-return guard:
if not data:
    raise ImageError("Image data is empty.", hint="The file contains zero bytes.")
```

> **Impact:** Blocks a clean test run. ~30-second fix.

---

### 2. Nothing is committed

```
git log feat/faceid-web-render --not origin/main
# (empty)
```

**All work is in the working tree only.** Zero commits on the feature branch. A power failure or accidental `git checkout` wipes everything.

---

## 🟡 What's Missing (Required for PR)

### Critical path to PR (deadline blockers)

| # | Item | Estimated effort | Status |
|---|------|-----------------|--------|
| 1 | **Fix the empty-bytes test** | 5 min | ❌ Not done |
| 2 | **Commit all changes** on `feat/faceid-web-render` | 5 min | ❌ Not done |
| 3 | **Push branch and open PR** | 5 min | ❌ Not done |
| 4 | **Render deploy config** (`render.yaml` or Render dashboard settings) | 15 min | ❌ **Completely missing** |
| 5 | **Render build script** (`render-build.sh` or similar to run `pip install` + `python -m app download-models`) | 10 min | ❌ **Completely missing** |
| 6 | **README update** — document the web app, new CLI commands, Render deploy, `.env` additions | 20 min | ❌ Not started |

### Deploy config gap (the biggest miss)

The plan called for **Render deployment** as a core deliverable. There is:
- No `render.yaml` (Render Blueprint)
- No `Dockerfile`
- No `Procfile`  
- No `render-build.sh`
- No documentation on how to start the web server

The server is fully functional — you'd run `uvicorn app.server:app --host 0.0.0.0 --port $PORT` — but there's **zero deploy infrastructure** to get it onto Render's free tier. This needs at minimum a `render.yaml` like:

```yaml
services:
  - type: web
    name: faceid-verify
    runtime: python
    plan: free
    buildCommand: pip install -r requirements.txt && python -m app download-models
    startCommand: uvicorn app.server:app --host 0.0.0.0 --port $PORT
    envVars:
      - key: SERPAPI_API_KEY
        sync: false
      # ...etc
```

---

## 🔍 Code Quality Deep-Dive

### Architecture assessment

| Aspect | Verdict | Notes |
|--------|---------|-------|
| **ContextVar sink** | ✅ Correct | Isolates concurrent SSE clients. `asyncio.to_thread` copies context per call. |
| **Heartbeat** | ✅ Generator-driven | `wait_for(queue.get(), timeout=15s)` — keeps Render alive during 300s receipt wait. |
| **Thread safety** | ✅ Clean | Worker uses `call_soon_threadsafe` to bridge to the loop. Never touches the queue directly. |
| **Concurrency guard** | ✅ Single-use jobs | `job.started` flag prevents double-run on reconnect. `_running` counter caps parallelism. |
| **No biometric leaks** | ✅ Verified | `to_record()` is untouched. Embeddings never leave memory. Server never streams face vectors. |
| **Hash stability** | ✅ Safe | New model fields are trailing optionals; `to_record()` reads none of them. |
| **SSRF protection** | ✅ Reuses existing guard | `reachability.py` delegates to `_assert_public_url` from `fetch.py`. Private IPs never probed. |
| **Image format support** | ✅ Comprehensive | JPEG/PNG/WebP/BMP/TIFF via CV2, GIF/AVIF/HEIC via Pillow fallback. EXIF orientation handled. |

### Things done well
- **The `ui.py` refactor is the cleanest piece.** Zero call-site changes, ContextVar isolation is correct, ConsoleSink preserves byte-identical CLI output.
- **The SSE streaming is production-quality.** The fetch-based (not EventSource) client, the `_SENTINEL` pattern, graceful disconnect handling, and the `X-Accel-Buffering: no` header show real SSE experience.
- **The pipeline's `run()` return value** was correctly added — the validated design's 6th terminal `result` event carrying the integrity verdict works.
- **The frontend is genuinely polished** — 590 lines of JS, 364 lines of CSS, real UX (drag-drop, face box overlay with coordinate mapping, animated similarity gauge, copy-hash chip).

### Things done poorly
- **No commits.** This is egregious. Thousands of lines of working code in the working tree only.
- **No deploy config.** The whole point of the web workstream was Render deployment. The server works but can't be deployed.
- **Empty-bytes edge case** was missed in `decode_to_bgr()` — a trivial guard but the test proves it's needed.

---

## 📊 Score by Workstream

| Workstream | Plan Target | Actual Status | % |
|-----------|------------|---------------|---|
| **WS1: Universal decoder** | JPEG/PNG/WebP/AVIF/HEIC/BMP/TIFF/GIF | ✅ Done (1 test bug) | 95% |
| **WS2: Link reliability** | Reachability module + liveness-aware ordering | ✅ Done | 100% |
| **WS3: Data model extensions** | `page_link_status`, `link_statuses`, return value | ✅ Done | 100% |
| **WS4: Pipeline enrichment** | 7 milestone events, reachability integration | ✅ Done | 100% |
| **WS5: Web streaming backend** | FastAPI + SSE + heartbeat + concurrency | ✅ Done | 100% |
| **WS6: Web SPA** | Upload, stage rail, console, result panel, verify | ✅ Done | 100% |
| **WS7: Tests** | Imaging, reachability, server suites | ⚠️ 1/115 failing | 99% |
| **WS8: Deploy infrastructure** | `render.yaml`, build script, README | ❌ Not started | 0% |
| **WS9: Git hygiene** | Commits, push, PR | ❌ Not started | 0% |

**Overall: ~80% of the planned work is done and working.** The 20% gap is entirely in the "ship it" layer — deploy config, commits, PR.

---

## ⚡ Recommended Action Plan (Priority Order)

> [!CAUTION]
> **Nothing is committed.** Step 1 is non-negotiable — do it before anything else.

1. **Fix the empty-bytes guard** in `imaging.py:54` (1 min)
2. **`git add -A && git commit`** — a single atomic commit is fine for deadline pressure (5 min)
3. **Create `render.yaml`** with build/start commands (10 min)
4. **Update README** with web app usage + deploy instructions (15 min)
5. **Push + open PR** against `main` (5 min)
6. **Run tests one more time** to confirm green (2 min)

**Minimum viable time to PR: ~40 minutes if you focus.**
