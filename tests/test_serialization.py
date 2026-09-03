"""Tests for data model serialisation and record round-tripping."""

import json

from app.hashing import canonical_json, record_hash
from app.models import (
    SCHEMA_VERSION,
    Artifact,
    CandidateVerification,
    ChainReceipt,
    FaceBox,
    FaceComparison,
    InputImage,
    SearchResponse,
    SearchResult,
    VerificationRecord,
)


def _make_record() -> VerificationRecord:
    """Build a realistic VerificationRecord for testing."""
    return VerificationRecord(
        input_image=InputImage(
            path="/tmp/test.jpg",
            filename="test.jpg",
            sha256="a" * 64,
            width=640,
            height=480,
            bytes_len=102400,
            search_copy_sha256="b" * 64,
            search_copy_bytes_len=98000,
        ),
        search=SearchResponse(
            provider="serpapi_google_lens",
            results=[
                SearchResult(
                    rank=1,
                    page_url="https://example.com/post",
                    title="Test Post",
                    source="Example",
                    image_url="https://example.com/image.jpg",
                    thumbnail_url=None,
                    platform="Reddit",
                ),
            ],
            query_method="reverse_image_upload",
            raw_result_count=5,
        ),
        candidate=CandidateVerification(
            result=SearchResult(
                rank=1,
                page_url="https://example.com/post",
                title="Test Post",
                source="Example",
                image_url="https://example.com/image.jpg",
                thumbnail_url=None,
                platform="Reddit",
            ),
            image_sha256="c" * 64,
            image_origin="publisher",
            image_url_used="https://example.com/image.jpg",
            image_bytes_len=200000,
            faces_detected=2,
            best=FaceComparison(
                similarity=0.456789,
                l2_distance=0.987654,
                verdict="MATCH",
                threshold=0.363,
                box=FaceBox(x=10, y=20, width=100, height=120, confidence=0.95),
            ),
        ),
        detector_model="yunet_2023mar",
        encoder_model="sface_2021dec",
        metric="cosine",
        threshold=0.363,
        review_threshold=0.300,
        created_at="2026-09-03T12:00:00+00:00",
    )


class TestVerificationRecordSerialization:
    def test_to_record_returns_dict(self):
        vr = _make_record()
        record = vr.to_record()
        assert isinstance(record, dict)

    def test_schema_version_present(self):
        vr = _make_record()
        record = vr.to_record()
        assert record["schema_version"] == SCHEMA_VERSION

    def test_no_embedding_in_record(self):
        """Biometric data must never appear in the hashed record."""
        vr = _make_record()
        record_json = json.dumps(vr.to_record())
        assert "vector" not in record_json
        assert "embedding" not in record_json

    def test_record_hash_deterministic(self):
        vr = _make_record()
        h1 = record_hash(vr.to_record())
        h2 = record_hash(vr.to_record())
        assert h1 == h2

    def test_float_quantization(self):
        """Similarity values must be rounded so they survive JSON round-trips."""
        vr = _make_record()
        record = vr.to_record()
        sim = record["candidate"]["similarity"]
        # quantize rounds to 6 decimal places
        assert sim == round(0.456789, 6)

    def test_canonical_json_deterministic(self):
        vr = _make_record()
        b1 = canonical_json(vr.to_record())
        b2 = canonical_json(vr.to_record())
        assert b1 == b2

    def test_record_round_trip_through_json(self):
        """Record -> JSON -> parse -> re-hash must produce the same hash."""
        vr = _make_record()
        record = vr.to_record()
        h1 = record_hash(record)

        # Simulate writing and reading back from disk
        json_str = json.dumps(record, indent=2, ensure_ascii=False)
        parsed = json.loads(json_str)
        h2 = record_hash(parsed)

        assert h1 == h2


class TestArtifactSerialization:
    def test_artifact_to_json(self):
        vr = _make_record()
        record = vr.to_record()
        rh = record_hash(record)
        artifact = Artifact(
            record=record,
            record_hash=rh,
            blockchain={"network": "sepolia", "tx_hash": "0xabc"},
        )
        payload = artifact.to_json()
        assert payload["artifact_version"] == SCHEMA_VERSION
        assert payload["record_hash"] == rh
        assert payload["record"] == record

    def test_artifact_hash_reproducible(self):
        """Re-hashing the record from an artifact must match the stored hash."""
        vr = _make_record()
        record = vr.to_record()
        rh = record_hash(record)
        artifact = Artifact(record=record, record_hash=rh)
        payload = artifact.to_json()

        # This is exactly what the verify command does
        recomputed = record_hash(payload["record"])
        assert recomputed == payload["record_hash"]


class TestSearchResultSerialization:
    def test_to_json(self):
        sr = SearchResult(
            rank=1,
            page_url="https://example.com",
            title="Test",
            source="web",
            platform="Reddit",
        )
        j = sr.to_json()
        assert j["rank"] == 1
        assert j["page_url"] == "https://example.com"
        assert j["platform"] == "Reddit"

    def test_none_fields_preserved(self):
        sr = SearchResult(rank=1, page_url="https://example.com")
        j = sr.to_json()
        assert j["title"] is None
        assert j["image_url"] is None


class TestChainReceiptSerialization:
    def test_to_json(self):
        cr = ChainReceipt(
            network="sepolia",
            chain_id=11155111,
            contract_address="0x123",
            transaction_hash="0xabc",
            block_number=42,
            gas_used=100000,
            submitter="0xdef",
        )
        j = cr.to_json()
        assert j["network"] == "sepolia"
        assert j["chain_id"] == 11155111
        assert j["transaction_hash"] == "0xabc"
