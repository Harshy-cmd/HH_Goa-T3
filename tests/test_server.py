"""Web server: upload validation, SSE streaming, verify wiring (Workstream 5).

The heavy pipeline and chain calls are mocked, so these tests are hermetic and
fast. They assert the contract the SPA depends on: staged uploads, a streamed
run that carries stage/log/milestone/result events, typed errors as ``error``
events (not 500s), single-use jobs, capacity limiting, and the verify endpoint.
"""

from __future__ import annotations

import io
import json

import pytest
from fastapi.testclient import TestClient

from app import server, ui
from app.errors import ArtifactError, NoFaceDetectedError


@pytest.fixture
def client(monkeypatch):
    # Never touch a real .env/config from the worker thread.
    monkeypatch.setattr(server.Config, "load", staticmethod(lambda: object()))
    server._running = 0
    server._JOBS.clear()
    return TestClient(server.app)


def _png() -> bytes:
    buf = io.BytesIO()
    from PIL import Image

    Image.new("RGB", (4, 4), (0, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


def _upload(client) -> str:
    r = client.post("/api/jobs", files={"image": ("f.png", _png(), "image/png")})
    assert r.status_code == 200
    return r.json()["job_id"]


def _parse_sse(text: str) -> list[dict]:
    events = []
    for block in text.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data:"):
                payload = line[5:].strip()
                if payload:
                    events.append(json.loads(payload))
    return events


class TestBasics:
    def test_health(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_index_is_served(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "Blockchain" in r.text


class TestUploadValidation:
    def test_empty_file_rejected(self, client):
        r = client.post("/api/jobs", files={"image": ("empty.png", b"", "image/png")})
        assert r.status_code == 400

    def test_oversize_rejected(self, client):
        big = b"\x00" * (server.MAX_UPLOAD_BYTES + 1)
        r = client.post("/api/jobs", files={"image": ("big.png", big, "image/png")})
        assert r.status_code == 413

    def test_valid_upload_returns_job_id(self, client):
        assert _upload(client)


class TestStreaming:
    def test_stream_carries_stages_and_result(self, client, monkeypatch):
        def fake_run(path, config):
            ui.step(1, 7, "Loading image")
            ui.ok("Image loaded")
            ui.event("faces_detected", {"count": 1, "target_index": 0, "faces": []})
            ui.step(6, 7, "Writing to blockchain")
            ui.event(
                "chain_confirmed",
                {
                    "tx_hash": "0xabc",
                    "block": 5,
                    "gas_used": 21000,
                    "explorer_url": "https://sepolia.etherscan.io/tx/0xabc",
                    "network": "sepolia",
                    "chain_id": 11155111,
                    "contract": "0xC0ffee",
                },
            )
            return {
                "artifact": {},
                "record_hash": "deadbeef",
                "integrity_match": True,
                "on_chain_hash": "deadbeef",
                "artifact_path": "artifacts/latest_verification.json",
            }

        monkeypatch.setattr(server.pipeline, "run", fake_run)
        job_id = _upload(client)
        with client.stream("GET", f"/api/jobs/{job_id}/stream") as resp:
            assert resp.status_code == 200
            body = "".join(resp.iter_text())

        events = _parse_sse(body)
        types = [e["type"] for e in events]
        assert "step" in types
        assert "result" in types
        assert any(e["type"] == "milestone" and e["kind"] == "chain_confirmed" for e in events)
        result = next(e for e in events if e["type"] == "result")
        assert result["result"]["integrity_match"] is True

    def test_typed_error_becomes_error_event(self, client, monkeypatch):
        def boom(path, config):
            raise NoFaceDetectedError("No face found.", hint="Use a clearer photo.")

        monkeypatch.setattr(server.pipeline, "run", boom)
        job_id = _upload(client)
        with client.stream("GET", f"/api/jobs/{job_id}/stream") as resp:
            assert resp.status_code == 200  # errors stream as events, not HTTP 500
            body = "".join(resp.iter_text())

        err = next(e for e in _parse_sse(body) if e["type"] == "error")
        assert err["kind"] == "NO FACE DETECTED"
        assert "No face" in err["message"]
        assert err["hint"] == "Use a clearer photo."


class TestJobLifecycle:
    def test_unknown_job_404(self, client):
        assert client.get("/api/jobs/nope/stream").status_code == 404

    def test_job_is_single_use(self, client, monkeypatch):
        monkeypatch.setattr(server.pipeline, "run", lambda p, c: {"record_hash": "x", "integrity_match": True})
        job_id = _upload(client)
        with client.stream("GET", f"/api/jobs/{job_id}/stream") as r1:
            "".join(r1.iter_text())  # run to completion
        again = client.get(f"/api/jobs/{job_id}/stream")
        assert again.status_code == 409

    def test_capacity_returns_429(self, client):
        server._running = server.MAX_CONCURRENT  # pretend a run is already in flight
        job_id = _upload(client)
        try:
            assert client.get(f"/api/jobs/{job_id}/stream").status_code == 429
        finally:
            server._running = 0


class TestVerifyEndpoint:
    def test_tamper_flag_is_forwarded(self, client, monkeypatch):
        seen = {}

        def fake(tamper):
            seen["tamper"] = tamper
            return {"verdict": "TAMPER DETECTED" if tamper else "PASS", "tampered": tamper}

        monkeypatch.setattr(server, "_do_verify", fake)
        r = client.post("/api/verify", data={"tamper": "true"})
        assert r.status_code == 200
        assert seen["tamper"] is True
        assert r.json()["verdict"] == "TAMPER DETECTED"

    def test_defaults_to_no_tamper(self, client, monkeypatch):
        monkeypatch.setattr(server, "_do_verify", lambda tamper: {"verdict": "PASS", "tampered": tamper})
        r = client.post("/api/verify", data={})
        assert r.status_code == 200
        assert r.json()["tampered"] is False

    def test_artifact_error_is_400(self, client, monkeypatch):
        def boom(tamper):
            raise ArtifactError("No artifact yet.", hint="Run the pipeline first.")

        monkeypatch.setattr(server, "_do_verify", boom)
        r = client.post("/api/verify", data={"tamper": "false"})
        assert r.status_code == 400
        assert r.json()["kind"] == "ARTIFACT ERROR"
