"""FastAPI backend: run the pipeline from the browser with live progress.

The CLI pipeline is reused unchanged. Its ``ui.*`` output is captured per request
by an :class:`EventSink` (installed via ``ui.use_sink`` inside the worker thread)
and streamed to the browser as Server-Sent Events, so the web UI shows the same
seven stages the terminal does -- plus structured milestones (``ui.event``) the
SPA renders as rich cards.

Why SSE + a worker thread + a generator-driven heartbeat:

* A blockchain confirmation can take 1-3 minutes, during which the pipeline emits
  nothing (web3 blocks in ``wait_for_transaction_receipt``). Render cuts idle
  connections, so the SSE generator sends a heartbeat comment on a timer to keep
  the socket warm -- this MUST be generator-driven, not pipeline-driven.
* ``pipeline.run`` is blocking, so it runs in a bounded ``ThreadPoolExecutor``.
  ``asyncio.Queue`` is not thread-safe, so the worker bridges every event to the
  loop with ``loop.call_soon_threadsafe`` -- never touching the queue directly.
* The free tier is 1 CPU / 512 MB and an in-flight job cannot be cancelled (only
  bounded), so concurrency is capped and excess requests get 429.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import artifacts, pipeline, ui
from .chain.registry import load_registry
from .config import Config
from .errors import PipelineError
from .hashing import record_hash
from .terminal import TerminalAuditRenderer

logger = logging.getLogger("app.server")

WEB_DIR = Path(__file__).resolve().parent / "web"

#: Hard cap on concurrent pipeline runs. Each pins a worker thread until it
#: finishes (up to the ~300 s receipt timeout) and loads the SFace model, so on
#: the 512 MB free tier we run one at a time by default. Excess requests get 429.
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT_JOBS", "1"))
#: Seconds between SSE heartbeats while the pipeline is quiet.
HEARTBEAT_S = 15.0
#: Largest upload accepted (bytes). Generous enough for phone photos.
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
#: How long a staged upload lives before it is purged.
JOB_TTL_S = 30 * 60

_EXECUTOR = ThreadPoolExecutor(max_workers=MAX_CONCURRENT, thread_name_prefix="pipeline")
_SENTINEL = object()
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # disable proxy buffering so events flush promptly
}

app = FastAPI(title="Face ID + Blockchain Verification", docs_url=None, redoc_url=None)


# ---------------------------------------------------------------------------
# Job store (staged uploads)
# ---------------------------------------------------------------------------


@dataclass
class Job:
    id: str
    path: Path
    filename: str
    created_at: float
    started: bool = False


_JOBS: dict[str, Job] = {}
#: Number of pipelines currently running. Mutated only on the event-loop thread,
#: between which there is never an ``await``, so plain int arithmetic is atomic.
_running = 0


def _purge_expired() -> None:
    now = time.time()
    for job_id in [jid for jid, j in _JOBS.items() if now - j.created_at > JOB_TTL_S]:
        job = _JOBS.pop(job_id, None)
        if job:
            job.path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Event sink: pipeline (worker thread) -> asyncio queue (loop thread)
# ---------------------------------------------------------------------------


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return str(value)


class EventSink(ui.ConsoleSink):
    """Captures pipeline progress as structured events on a thread-safe bridge.

    Installed inside the worker thread via ``ui.use_sink``. Single emission
    point for both the web SSE stream and the dedicated TerminalAuditRenderer.
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        queue: "asyncio.Queue",
        job_id: str | None = None,
        renderer: TerminalAuditRenderer | None = None,
    ) -> None:
        self._loop = loop
        self._queue = queue
        self._job_id = job_id
        self._renderer = renderer
        self._step = 0

    def _now(self) -> str:
        import datetime
        return datetime.datetime.now().strftime("%H:%M:%S")

    def _classify_category(self, message: str, level: str) -> str:
        if level == "fail":
            return "ERROR"
        msg_lower = message.lower()
        if "tx hash" in msg_lower or "transaction" in msg_lower or "gas" in msg_lower or "receipt" in msg_lower or "confirmed" in msg_lower:
            return "TRANSACTION"
        if "chain" in msg_lower or "contract" in msg_lower or "sepolia" in msg_lower or self._step in (6, 7):
            return "BLOCKCHAIN"
        if "search" in msg_lower or "provider" in msg_lower or self._step == 4:
            return "SEARCH"
        if "candidate" in msg_lower or "source" in msg_lower or "verified" in msg_lower or self._step == 5:
            return "SOURCE"
        if "face" in msg_lower or "image" in msg_lower or "embed" in msg_lower or self._step in (1, 2, 3):
            return "IMAGE"
        return "SYSTEM"

    def _emit(self, event: dict[str, Any]) -> None:
        """Single emission point for verification audit events.

        Forwards the exact event payload to the terminal renderer (if enabled)
        and to the SSE queue. Rendering failures are strictly isolated.
        """
        if "time" not in event:
            event["time"] = self._now()
        if self._job_id and "job_id" not in event:
            event["job_id"] = self._job_id

        # 1. Forward exact event to TerminalAuditRenderer when enabled
        if self._renderer is not None:
            try:
                self._renderer.render(event)
            except Exception as exc:
                logger.warning("Terminal rendering error isolated: %s", exc)

        # 2. Queue exact same event payload for SSE
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, event)
        except RuntimeError:
            # Loop is shutting down; nothing to stream to.
            pass

    def emit_hello(self, job_id: str, filename: str) -> None:
        self._emit({"type": "hello", "job_id": job_id, "filename": filename})

    def emit_result(self, result: dict[str, Any]) -> None:
        self._emit({"type": "result", "result": result})

    def emit_error(self, kind: str, message: str, hint: str | None = None) -> None:
        self._emit({"type": "error", "kind": kind, "message": message, "hint": hint})

    def step(self, index: int, total: int, title: str) -> None:
        self._step = index
        self._emit({"type": "step", "index": index, "total": total, "title": title, "category": "SYSTEM"})

    def ok(self, message: str) -> None:
        cat = self._classify_category(message, "ok")
        self._emit({"type": "log", "level": "ok", "message": message, "step": self._step, "category": cat})

    def info(self, message: str) -> None:
        cat = self._classify_category(message, "info")
        self._emit({"type": "log", "level": "info", "message": message, "step": self._step, "category": cat})

    def warn(self, message: str) -> None:
        cat = self._classify_category(message, "warn")
        self._emit({"type": "log", "level": "warn", "message": message, "step": self._step, "category": cat})

    def fail(self, message: str) -> None:
        cat = self._classify_category(message, "fail")
        self._emit({"type": "log", "level": "fail", "message": message, "step": self._step, "category": cat})

    def kv(self, key: str, value: object, indent: int = 2) -> None:
        cat = self._classify_category(f"{key}: {value}", "info")
        self._emit({"type": "kv", "key": key, "value": _jsonable(value), "step": self._step, "category": cat})

    def banner(self, title: str) -> None:
        self._emit({"type": "banner", "title": title, "category": "SYSTEM"})

    def section(self, title: str) -> None:
        self._emit({"type": "section", "title": title, "category": "SYSTEM"})

    def verdict(self, label: str, passed: bool) -> None:
        cat = "BLOCKCHAIN" if "INTEGRITY" in label or "VERIFICATION" in label else "SYSTEM"
        self._emit({"type": "verdict", "label": label, "passed": bool(passed), "category": cat})

    def rule(self, char: str = "=") -> None:
        return None  # purely visual in the terminal; irrelevant to the web stream

    def event(self, kind: str, payload: dict[str, Any]) -> None:
        cat = "BLOCKCHAIN" if "chain" in kind or "record" in kind else "SOURCE" if "source" in kind or "candidate" in kind else "IMAGE"
        self._emit({"type": "milestone", "kind": kind, "payload": _jsonable(payload), "category": cat})


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event)}\n\n"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "running": _running, "max_concurrent": MAX_CONCURRENT}


@app.get("/api/pipeline-info")
async def pipeline_info() -> dict[str, Any]:
    """Expose pipeline architecture metadata for the Technical Pipeline Inspector."""
    config = Config.load()
    return {
        "schema_version": "1.0",
        "contract_address": config.contract_address,
        "network": "Sepolia Testnet",
        "chain_id": 11155111,
        "search_provider": config.search_provider,
        "detector": "YuNet (OpenCV)",
        "encoder": "SFace (128-D normalized embedding, cosine metric)",
        "match_threshold": config.match_threshold,
        "review_threshold": config.review_threshold,
        "max_concurrent": MAX_CONCURRENT,
        "memory_budget": "512 MB Free Tier Safe (Render)",
        "contract_explorer": f"https://sepolia.etherscan.io/address/{config.contract_address}" if config.contract_address else None,
    }


@app.get("/api/latest-artifact")
async def latest_artifact() -> Any:
    """Return the raw JSON artifact of the most recent verification run."""
    try:
        payload, _ = artifacts.load_verification(None)
        return payload
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"No artifact available: {exc}")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.post("/api/jobs")
async def create_job(image: UploadFile) -> dict[str, Any]:
    """Stage an uploaded image and return a job id to stream against."""
    _purge_expired()
    data = await image.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Image exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit.",
        )

    suffix = Path(image.filename or "upload").suffix or ".img"
    fd, tmp = tempfile.mkstemp(prefix="faceid_", suffix=suffix)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)

    job = Job(
        id=uuid.uuid4().hex,
        path=Path(tmp),
        filename=image.filename or Path(tmp).name,
        created_at=time.time(),
    )
    _JOBS[job.id] = job
    return {"job_id": job.id, "filename": job.filename, "bytes": len(data)}


def _run_worker(loop: asyncio.AbstractEventLoop, queue: "asyncio.Queue", job: Job) -> None:
    """Blocking pipeline run on a worker thread; emits events onto the queue."""
    config = Config.load()
    terminal_audit = getattr(config, "terminal_audit", True)
    renderer = TerminalAuditRenderer(job_id=job.id, filename=job.filename) if terminal_audit else None
    sink = EventSink(loop, queue, job_id=job.id, renderer=renderer)
    sink.emit_hello(job.id, job.filename)
    try:
        with ui.use_sink(sink):
            result = pipeline.run(str(job.path), config)
        sink.emit_result(result)
    except PipelineError as exc:
        sink.emit_error(exc.kind, exc.message, exc.hint)
    except Exception as exc:  # noqa: BLE001 - surface anything else as a clean error event
        sink.emit_error("InternalError", str(exc), None)
    finally:
        loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)
        loop.call_soon_threadsafe(_release_slot)


def _release_slot() -> None:
    global _running
    _running = max(0, _running - 1)


@app.get("/api/jobs/{job_id}/stream")
async def stream_job(job_id: str, request: Request):
    """Run the staged job and stream its progress as Server-Sent Events."""
    global _running
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown or expired job id.")

    if job.started:
        # Each stream GET launches a real pipeline run (including an on-chain
        # write), so a job is single-use. A second open -- a double-click, a
        # refresh, an EventSource auto-reconnect -- must never start a second run.
        return JSONResponse(
            status_code=409,
            content={
                "kind": "AlreadyStarted",
                "message": "This verification was already started.",
                "hint": "Upload the image again to run a fresh verification.",
            },
        )

    if _running >= MAX_CONCURRENT:
        # No await between the check above and here: the count cannot change.
        return JSONResponse(
            status_code=429,
            content={
                "kind": "Busy",
                "message": "The server is verifying another image right now.",
                "hint": "The free tier runs one verification at a time -- retry in a moment.",
            },
        )
    _running += 1
    job.started = True

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    loop.run_in_executor(_EXECUTOR, _run_worker, loop, queue, job)

    async def _events():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_S)
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        break
                    yield ": heartbeat\n\n"
                    continue
                if event is _SENTINEL:
                    break
                yield _sse(event)
        except asyncio.CancelledError:
            # Client disconnected. Stop streaming; the worker drains on its own
            # and releases its slot when it finishes.
            raise

    return StreamingResponse(_events(), media_type="text/event-stream", headers=_SSE_HEADERS)


@app.post("/api/verify")
async def verify(tamper: bool = Form(False)) -> Any:
    """Re-verify the latest artifact against the chain (optionally tampered).

    Fast (a couple of read-only chain calls, no receipt wait), so this returns a
    single JSON verdict rather than a stream. With ``tamper=true`` it flips one
    field of a *copy* of the record to demonstrate that the recomputed hash no
    longer matches the on-chain hash -- the on-chain data is never touched.
    """
    try:
        return await asyncio.to_thread(_do_verify, tamper)
    except PipelineError as exc:
        return JSONResponse(
            status_code=400,
            content={"kind": exc.kind, "message": exc.message, "hint": exc.hint},
        )


def _do_verify(tamper: bool) -> dict[str, Any]:
    payload, path = artifacts.load_verification(None)
    record = payload["record"]
    stored_hash = payload["record_hash"]

    check_record = record
    if tamper:
        # Work on a deep copy so the artifact on disk is untouched.
        check_record = json.loads(json.dumps(record))
        _flip_a_field(check_record)

    recomputed = record_hash(check_record)

    config = Config.load()
    config.require_rpc()
    config.require_contract()
    registry = load_registry(config.rpc_url, config.contract_address)

    on_chain = registry.get_record(recomputed)
    chain_match = bool(on_chain) and on_chain.record_hash == recomputed

    if tamper:
        verdict = "TAMPER DETECTED" if not chain_match else "UNCHANGED"
    else:
        verdict = "PASS" if chain_match else "FAIL"

    return {
        "verdict": verdict,
        "tampered": tamper,
        "stored_hash": stored_hash,
        "recomputed_hash": recomputed,
        "on_chain_hash": on_chain.record_hash if on_chain else None,
        "chain_match": chain_match,
        "submitter": on_chain.submitter if on_chain else None,
        "block_timestamp": on_chain.block_timestamp if on_chain else None,
        "artifact_path": str(path),
    }


def _flip_a_field(record: dict[str, Any]) -> None:
    """Nudge one numeric field so the hash changes but the JSON stays valid."""
    try:
        current = record["candidate"]["similarity"]
        if isinstance(current, (int, float)):
            record["candidate"]["similarity"] = round(float(current) + 1e-6, 6)
            return
    except (KeyError, TypeError):
        pass
    # Fallback: mark the record so its hash differs even if the shape is unusual.
    record["_tampered_demo"] = True


# Static assets (styles.css, app.js, ...). Mounted last so /api and / win.
if WEB_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
