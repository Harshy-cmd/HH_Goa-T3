"""Unit tests for multi-candidate verification, deterministic ranking,
blockchain idempotency, and evaluator endpoints.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from app.models import (
    CandidateVerification,
    FaceBox,
    FaceComparison,
    OnChainRecord,
    SearchResult,
)
from app.net.reachability import LinkStatus
from app.pipeline import _rank_primary_candidate, _blockchain_register
from app.config import Config


def _make_candidate(
    rank: int,
    url: str,
    sim: float,
    status: str = "live",
    origin: str = "publisher",
    source: str = "web",
    platform: str | None = None,
) -> CandidateVerification:
    sr = SearchResult(
        rank=rank,
        page_url=url,
        title=f"Source {rank}",
        source=source,
        platform=platform,
    )
    box = FaceBox(x=10, y=10, width=50, height=50, confidence=0.99)
    fc = FaceComparison(
        similarity=sim,
        l2_distance=0.2,
        verdict="MATCH",
        threshold=0.82,
        box=box,
    )
    return CandidateVerification(
        result=sr,
        image_sha256="abc12345" * 8,
        image_origin=origin,
        image_url_used=f"{url}/img.jpg",
        image_bytes_len=12345,
        faces_detected=1,
        best=fc,
        page_link_status=status,
    )


class TestPrimaryCandidateRanking:
    def test_higher_similarity_wins(self):
        c1 = _make_candidate(rank=2, url="https://a.com", sim=0.95, status="live")
        c2 = _make_candidate(rank=1, url="https://b.com", sim=0.84, status="live")
        winner = _rank_primary_candidate([c1, c2])
        assert winner.result.page_url == "https://a.com"

    def test_live_link_beats_login_wall_for_comparable_scores(self):
        # When similarity scores round to the same 2 decimal places (e.g., 0.941 vs 0.942)
        nyt = _make_candidate(rank=1, url="https://nytimes.com/article", sim=0.941, status="live")
        insta = _make_candidate(rank=9, url="https://instagram.com/p/123", sim=0.944, status="login_wall")
        winner = _rank_primary_candidate([insta, nyt])
        # nytimes is live, so it takes precedence over login_wall
        assert winner.result.page_url == "https://nytimes.com/article"

    def test_search_engine_rank_tie_breaker(self):
        # Both live and equal similarity bucket
        c1 = _make_candidate(rank=1, url="https://nyt.com", sim=0.92, status="live")
        c2 = _make_candidate(rank=5, url="https://other.com", sim=0.92, status="live")
        winner = _rank_primary_candidate([c2, c1])
        assert winner.result.rank == 1

    def test_publisher_image_over_thumbnail(self):
        c_pub = _make_candidate(rank=3, url="https://pub.com", sim=0.90, status="live", origin="publisher")
        c_thumb = _make_candidate(rank=2, url="https://thumb.com", sim=0.90, status="live", origin="provider_thumbnail")
        winner = _rank_primary_candidate([c_thumb, c_pub])
        assert winner.image_origin == "publisher"

    def test_deterministic_bill_gates_scenario(self):
        """Simulates the real Bill Gates test run: NY Times vs Instagram."""
        nyt = _make_candidate(
            rank=1,
            url="https://www.nytimes.com/2019/09/20/books/review/bill-gates-what-im-reading.html",
            sim=0.94,
            status="live",
            origin="publisher",
            source="The New York Times",
        )
        insta = _make_candidate(
            rank=9,
            url="https://www.instagram.com/thisisbillgates/p/B3F1eNygN-j/",
            sim=0.94,
            status="login_wall",
            origin="publisher",
            source="Instagram",
            platform="Instagram",
        )
        reddit = _make_candidate(
            rank=10,
            url="https://www.reddit.com/r/technology/comments/bill_gates/",
            sim=0.91,
            status="live",
            origin="publisher",
            source="Reddit",
            platform="Reddit",
        )

        candidates = [insta, reddit, nyt]
        winner = _rank_primary_candidate(candidates)
        # NY Times must be picked deterministically because of live status and lower rank
        assert winner.result.rank == 1
        assert "nytimes.com" in winner.result.page_url


class TestBlockchainIdempotency:
    def test_idempotent_skip_when_record_already_anchored(self, monkeypatch):
        mock_registry = MagicMock()
        mock_registry.network.name = "Sepolia"
        mock_registry.network.chain_id = 11155111
        mock_registry.address = "0x75d5e23637C091398867aA64287B8E6A6d2466be"

        existing_onchain = OnChainRecord(
            record_hash="d" * 64,
            block_timestamp=1720000000,
            submitter="0x72540F38B3ff3A0423B7DF9d88fE6F70329b1677",
            source="web",
            candidate_url="https://example.com",
        )
        mock_registry.get_record.return_value = existing_onchain

        monkeypatch.setattr("app.pipeline.load_registry", lambda rpc, addr: mock_registry)

        cfg = Config(
            search_provider="serpapi",
            serpapi_api_key="fake",
            google_vision_api_key="",
            rpc_url="http://fake-rpc",
            contract_address="0x75d5e23637C091398867aA64287B8E6A6d2466be",
            private_key="0x" + "1" * 64,
            match_threshold=0.82,
            review_threshold=0.70,
            detect_confidence=0.90,
        )

        cand = _make_candidate(1, "https://example.com", 0.95)
        rec = {"candidate": {"page_url": "https://example.com"}}

        receipt = _blockchain_register(rec, "d" * 64, cand, cfg)

        assert receipt["idempotent"] is True
        assert receipt["gas_used"] == 0
        assert receipt["block_timestamp"] == 1720000000
        # Crucially: register() was NOT called on the contract, saving gas!
        mock_registry.register.assert_not_called()


class TestServerEndpoints:
    def test_pipeline_info_endpoint(self):
        from fastapi.testclient import TestClient
        from app.server import app

        client = TestClient(app)
        res = client.get("/api/pipeline-info")
        assert res.status_code == 200
        data = res.json()
        assert data["schema_version"] == "1.0"
        assert data["detector"] == "YuNet (OpenCV)"
        assert "SFace" in data["encoder"]
        assert data["chain_id"] == 11155111
        assert "512 MB" in data["memory_budget"]
