"""Unit tests for TerminalAuditRenderer (app/terminal.py) and EventSink integration.

Tests:
1. hello (job start header)
2. step (stage dividers)
3. log (structured event rows)
4. kv (key-value formatting)
5. milestone (faces, search, sources, candidate, record hash, blockchain, integrity)
6. verdict (pass/fail banner)
7. result (final forensic summary card)
8. error (audit failure card)
9. ANSI disabled when stdout is not a TTY
10. ANSI disabled when NO_COLOR is set
11. Renderer failures do not break event emission (isolation)
12. Exact SSE event payload is preserved
13. Concurrent rendering does not corrupt output (thread-safety)
"""

from __future__ import annotations

import asyncio
import io
import os
import threading
from typing import Any

import pytest

from app.server import EventSink
from app.terminal import TerminalAuditRenderer, _is_color_enabled


@pytest.fixture
def string_stream():
    return io.StringIO()


@pytest.fixture
def renderer(string_stream):
    return TerminalAuditRenderer(
        stream=string_stream,
        job_id="80df0cab0595",
        filename="test_face.png",
    )


class TestTerminalAuditRenderer:
    def test_hello_renders_job_header(self, renderer, string_stream):
        event = {
            "type": "hello",
            "job_id": "80df0cab0595",
            "filename": "test_face.png",
            "time": "12:00:00",
        }
        renderer.render(event)
        output = string_stream.getvalue()

        assert "FORENSIC AUDIT SESSION" in output
        assert "80df0cab0595" in output
        assert "test_face.png" in output
        assert "12:00:00 UTC" in output
        assert "YuNet" in output

    def test_step_renders_stage_divider(self, renderer, string_stream):
        event = {
            "type": "step",
            "index": 1,
            "total": 7,
            "title": "Loading image",
            "time": "12:00:01",
        }
        renderer.render(event)
        output = string_stream.getvalue()

        assert "[STAGE 1/7] LOADING IMAGE" in output
        assert "──" in output or "--" in output

    def test_log_renders_structured_row(self, renderer, string_stream):
        event = {
            "type": "log",
            "level": "ok",
            "message": "Image loaded successfully",
            "category": "IMAGE",
            "job_id": "80df0cab0595",
            "time": "12:00:02",
        }
        renderer.render(event)
        output = string_stream.getvalue()

        assert "[12:00:02]" in output
        assert "[job:80df0cab]" in output
        assert "[IMAGE ]" in output
        assert "OK" in output
        assert "Image loaded successfully" in output

    def test_kv_renders_aligned_pair(self, renderer, string_stream):
        event = {
            "type": "kv",
            "key": "Dimensions",
            "value": "512x512",
            "category": "IMAGE",
            "job_id": "80df0cab0595",
            "time": "12:00:03",
        }
        renderer.render(event)
        output = string_stream.getvalue()

        assert "[12:00:03]" in output
        assert "[job:80df0cab]" in output
        assert "Dimensions:" in output
        assert "512x512" in output

    def test_milestones_render_genuine_data(self, renderer, string_stream):
        # 1. faces_detected
        renderer.render({
            "type": "milestone",
            "kind": "faces_detected",
            "payload": {
                "count": 1,
                "target_index": 0,
                "faces": [{"x": 10, "y": 20, "width": 100, "height": 100, "confidence": 0.985}],
            },
            "job_id": "80df0cab0595",
            "time": "12:00:04",
        })
        # 2. search_results
        renderer.render({
            "type": "milestone",
            "kind": "search_results",
            "payload": {"provider": "serpapi", "result_count": 8},
            "job_id": "80df0cab0595",
            "time": "12:00:05",
        })
        # 3. source_validated
        renderer.render({
            "type": "milestone",
            "kind": "source_validated",
            "payload": {"rank": 1, "source": "twitter.com", "similarity": 0.8842},
            "job_id": "80df0cab0595",
            "time": "12:00:06",
        })
        # 4. candidate_matched
        renderer.render({
            "type": "milestone",
            "kind": "candidate_matched",
            "payload": {
                "verdict": "MATCH",
                "similarity": 0.8842,
                "threshold": 0.363,
                "page_url": "https://twitter.com/example/photo.jpg",
            },
            "job_id": "80df0cab0595",
            "time": "12:00:07",
        })
        # 5. chain_confirmed (real tx)
        renderer.render({
            "type": "milestone",
            "kind": "chain_confirmed",
            "payload": {
                "tx_hash": "0x1234abcd5678",
                "block": 5821942,
                "gas_used": 68421,
                "explorer_url": "https://sepolia.etherscan.io/tx/0x1234abcd5678",
                "network": "Sepolia Testnet",
                "idempotent": False,
            },
            "job_id": "80df0cab0595",
            "time": "12:00:08",
        })
        # 6. integrity
        renderer.render({
            "type": "milestone",
            "kind": "integrity",
            "payload": {"match": True, "local_hash": "aaa", "on_chain_hash": "aaa"},
            "job_id": "80df0cab0595",
            "time": "12:00:09",
        })

        out = string_stream.getvalue()
        assert "1 face(s) detected (target confidence: 98.5%)" in out
        assert "8 candidate(s) discovered via serpapi" in out
        assert "Candidate #1 (twitter.com) verified: similarity 0.8842" in out
        assert "Primary Match: verdict=MATCH (sim: 0.8842, threshold: 0.363)" in out
        assert "On-chain anchor confirmed on Sepolia Testnet (block #5821942)" in out
        assert "Tx Hash: 0x1234abcd5678" in out
        assert "Gas Used: 68,421" in out
        assert "State Check: VERIFIED (Local SHA-256 == On-chain SHA-256)" in out

    def test_verdict_renders_banner(self, renderer, string_stream):
        event = {
            "type": "verdict",
            "label": "INTEGRITY CHECK",
            "passed": True,
            "time": "12:00:10",
        }
        renderer.render(event)
        out = string_stream.getvalue()

        assert "INTEGRITY CHECK" in out
        assert "PASS" in out
        assert "═" in out or "=" in out

    def test_result_renders_forensic_summary(self, renderer, string_stream):
        event = {
            "type": "result",
            "job_id": "80df0cab0595",
            "result": {
                "artifact": {
                    "record": {
                        "input": {"filename": "test.jpg", "sha256": "9f8e7d6c5b4a"},
                        "candidate": {
                            "page_url": "https://example.com/profile",
                            "similarity": 0.8842,
                            "threshold": 0.363,
                            "verdict": "MATCH",
                        },
                    },
                    "blockchain": {
                        "network": "Sepolia Testnet",
                        "contract_address": "0x3d077E8039E9237Bdf4b06A3F40562D58a36dFE7",
                        "transaction_hash": "0xdeadbeef12345678",
                        "block_number": 5821942,
                        "gas_used": 68421,
                    },
                    "record_hash": "4f1a2b3c4d5e",
                },
                "record_hash": "4f1a2b3c4d5e",
                "integrity_match": True,
                "artifact_path": "artifacts/latest_verification.json",
                "validated_sources": [{"source": "example.com"}],
            },
        }
        renderer.render(event)
        out = string_stream.getvalue()

        assert "FORENSIC VERIFICATION EVIDENCE" in out
        assert "80df0cab0595" in out
        assert "9f8e7d6c5b4a" in out
        assert "https://example.com/profile" in out
        assert "Cosine Sim 0.8842" in out
        assert "4f1a2b3c4d5e" in out
        assert "0x3d077E8039E9237Bdf4b06A3F40562D58a36dFE7" in out
        assert "0xdeadbeef12345678" in out
        assert "5821942" in out
        assert "CONFIRMED & IMMUTABLE" in out

    def test_error_renders_card(self, renderer, string_stream):
        # Set current step first
        renderer.render({"type": "step", "index": 2, "total": 7, "title": "Detecting faces"})
        event = {
            "type": "error",
            "kind": "NO FACE DETECTED",
            "message": "No face found in image.",
            "hint": "Try a clearer portrait.",
            "job_id": "80df0cab0595",
        }
        renderer.render(event)
        out = string_stream.getvalue()

        assert "AUDIT FAILURE: NO FACE DETECTED" in out
        assert "80df0cab0595" in out
        assert "[STAGE 2/7] Detecting faces" in out
        assert "No face found in image." in out
        assert "Try a clearer portrait." in out


class TestColorAndTTY:
    def test_ansi_disabled_when_not_a_tty(self):
        buf = io.StringIO()
        assert not _is_color_enabled(buf)

    def test_ansi_disabled_when_no_color_env(self, monkeypatch):
        class FakeTTY(io.StringIO):
            def isatty(self):
                return True

        tty = FakeTTY()
        monkeypatch.setenv("NO_COLOR", "1")
        assert not _is_color_enabled(tty)


class TestFailureIsolationAndSSEPreservation:
    def test_renderer_failure_does_not_break_emission(self):
        class CrashingRenderer:
            def render(self, event: dict[str, Any]) -> None:
                raise RuntimeError("Renderer intentional explosion")

        loop = asyncio.new_event_loop()
        queue = asyncio.Queue()
        sink = EventSink(loop, queue, job_id="job123", renderer=CrashingRenderer())

        # Calling sink.ok should NOT raise despite renderer exploding
        sink.ok("Pipeline is moving forward")
        sink.step(1, 7, "Stage 1")
        sink.emit_result({"status": "verified"})

        # Process threadsafe callbacks scheduled on the loop
        loop.run_until_complete(asyncio.sleep(0))

        # Verify events were successfully placed in the queue
        assert queue.qsize() == 3
        ev1 = queue.get_nowait()
        assert ev1["type"] == "log"
        assert ev1["message"] == "Pipeline is moving forward"
        assert ev1["job_id"] == "job123"

        ev2 = queue.get_nowait()
        assert ev2["type"] == "step"

        ev3 = queue.get_nowait()
        assert ev3["type"] == "result"
        loop.close()

    def test_exact_sse_event_payload_preserved(self):
        loop = asyncio.new_event_loop()
        queue = asyncio.Queue()
        buf = io.StringIO()
        renderer = TerminalAuditRenderer(stream=buf, job_id="job_abc")
        sink = EventSink(loop, queue, job_id="job_abc", renderer=renderer)

        orig_event = {
            "type": "milestone",
            "kind": "chain_confirmed",
            "payload": {
                "tx_hash": "0xabc",
                "block": 100,
                "gas_used": 21000,
                "network": "Sepolia",
            },
            "category": "BLOCKCHAIN",
        }
        sink._emit(orig_event)

        # Process threadsafe callbacks scheduled on the loop
        loop.run_until_complete(asyncio.sleep(0))

        queued = queue.get_nowait()
        # Verify exact payload is preserved
        assert queued["type"] == "milestone"
        assert queued["kind"] == "chain_confirmed"
        assert queued["payload"]["tx_hash"] == "0xabc"
        assert queued["payload"]["block"] == 100
        assert queued["job_id"] == "job_abc"
        assert "time" in queued
        loop.close()


class TestConcurrentRendering:
    def test_concurrent_threads_do_not_crash_or_interleave(self):
        buf = io.StringIO()
        shared_lock = threading.Lock()
        renderer1 = TerminalAuditRenderer(stream=buf, job_id="job_1", lock=shared_lock)
        renderer2 = TerminalAuditRenderer(stream=buf, job_id="job_2", lock=shared_lock)

        def worker(ren: TerminalAuditRenderer, jid: str):
            for i in range(10):
                ren.render({
                    "type": "log",
                    "level": "ok",
                    "message": f"Worker log iteration {i}",
                    "job_id": jid,
                    "time": "12:34:56",
                    "category": "SYSTEM",
                })

        t1 = threading.Thread(target=worker, args=(renderer1, "job_1"))
        t2 = threading.Thread(target=worker, args=(renderer2, "job_2"))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        output = buf.getvalue()
        lines = [line for line in output.splitlines() if line.strip()]
        assert len(lines) == 20
        # Every line has intact prefix and job id
        for line in lines:
            assert "Worker log iteration" in line
            assert "[job:job_1   ]" in line or "[job:job_2   ]" in line
