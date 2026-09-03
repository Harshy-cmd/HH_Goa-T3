"""Tests for configuration loading and validation."""

import os
import pytest

from app.config import Config, _normalise_private_key
from app.errors import ConfigError


class TestNormalisePrivateKey:
    def test_empty(self):
        assert _normalise_private_key("") == ""

    def test_with_prefix(self):
        key = "0x" + "a" * 64
        assert _normalise_private_key(key) == key

    def test_without_prefix(self):
        raw = "a" * 64
        assert _normalise_private_key(raw) == "0x" + raw


class TestConfigValidation:
    def test_match_threshold_out_of_range(self):
        with pytest.raises(ConfigError, match="FACE_MATCH_THRESHOLD"):
            cfg = Config(
                search_provider="serpapi",
                serpapi_api_key="",
                google_vision_api_key="",
                rpc_url="",
                private_key="",
                contract_address="",
                match_threshold=1.5,  # out of range
                review_threshold=0.3,
                detect_confidence=0.85,
            )
            cfg.validate_thresholds()

    def test_review_above_match_rejected(self):
        with pytest.raises(ConfigError, match="FACE_REVIEW_THRESHOLD"):
            cfg = Config(
                search_provider="serpapi",
                serpapi_api_key="",
                google_vision_api_key="",
                rpc_url="",
                private_key="",
                contract_address="",
                match_threshold=0.363,
                review_threshold=0.5,  # above match
                detect_confidence=0.85,
            )
            cfg.validate_thresholds()

    def test_valid_thresholds(self):
        cfg = Config(
            search_provider="serpapi",
            serpapi_api_key="",
            google_vision_api_key="",
            rpc_url="",
            private_key="",
            contract_address="",
            match_threshold=0.363,
            review_threshold=0.300,
            detect_confidence=0.85,
        )
        # Should not raise
        cfg.validate_thresholds()

    def test_require_search_serpapi_missing(self):
        cfg = Config(
            search_provider="serpapi",
            serpapi_api_key="",
            google_vision_api_key="",
            rpc_url="",
            private_key="",
            contract_address="",
            match_threshold=0.363,
            review_threshold=0.300,
            detect_confidence=0.85,
        )
        with pytest.raises(ConfigError, match="SERPAPI_API_KEY"):
            cfg.require_search()

    def test_require_search_serpapi_present(self):
        cfg = Config(
            search_provider="serpapi",
            serpapi_api_key="test_key_123",
            google_vision_api_key="",
            rpc_url="",
            private_key="",
            contract_address="",
            match_threshold=0.363,
            review_threshold=0.300,
            detect_confidence=0.85,
        )
        # Should not raise
        cfg.require_search()

    def test_require_rpc_missing(self):
        cfg = Config(
            search_provider="serpapi",
            serpapi_api_key="",
            google_vision_api_key="",
            rpc_url="",
            private_key="",
            contract_address="",
            match_threshold=0.363,
            review_threshold=0.300,
            detect_confidence=0.85,
        )
        with pytest.raises(ConfigError, match="RPC_URL"):
            cfg.require_rpc()

    def test_require_signer_missing_key(self):
        cfg = Config(
            search_provider="serpapi",
            serpapi_api_key="",
            google_vision_api_key="",
            rpc_url="http://localhost:8545",
            private_key="",
            contract_address="",
            match_threshold=0.363,
            review_threshold=0.300,
            detect_confidence=0.85,
        )
        with pytest.raises(ConfigError, match="PRIVATE_KEY"):
            cfg.require_signer()

    def test_require_contract_missing(self):
        cfg = Config(
            search_provider="serpapi",
            serpapi_api_key="",
            google_vision_api_key="",
            rpc_url="",
            private_key="",
            contract_address="",
            match_threshold=0.363,
            review_threshold=0.300,
            detect_confidence=0.85,
        )
        with pytest.raises(ConfigError, match="CONTRACT_ADDRESS"):
            cfg.require_contract()


class TestConfigProviderValidation:
    def test_invalid_provider(self, monkeypatch):
        monkeypatch.setenv("SEARCH_PROVIDER", "invalid_provider")
        monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_VISION_API_KEY", raising=False)
        with pytest.raises(ConfigError, match="SEARCH_PROVIDER"):
            Config.load()
