"""Configuration loaded from the environment, validated up front.

Every value the pipeline needs is resolved and checked here so that a missing
key produces a readable sentence at startup rather than a KeyError halfway
through a demo. Validation is scoped per command: ``verify`` must work without
a search key, so only the pieces a command actually uses are demanded.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from .errors import ConfigError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_DIR = PROJECT_ROOT / "artifacts"
MODEL_DIR = PROJECT_ROOT / "models"
SAMPLE_DIR = PROJECT_ROOT / "samples"
CONTRACT_PATH = PROJECT_ROOT / "contracts" / "VerificationRegistry.sol"

VALID_PROVIDERS = ("serpapi", "google_vision")

_MISSING_ENV_HINT = (
    "Copy .env.example to .env and fill in the value:\n"
    "    cp .env.example .env"
)


def _get(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _get_float(name: str, default: float) -> float:
    raw = _get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        raise ConfigError(
            f"{name} must be a number, got {raw!r}.",
            hint=f"Set {name} to a decimal value, or remove it to use the default ({default}).",
        ) from None


@dataclass(frozen=True)
class Config:
    # search
    search_provider: str
    serpapi_api_key: str
    google_vision_api_key: str
    # chain
    rpc_url: str
    private_key: str
    contract_address: str
    # face matching
    match_threshold: float
    review_threshold: float
    detect_confidence: float

    # -- loading ------------------------------------------------------------

    @classmethod
    def load(cls) -> "Config":
        """Read .env (if present) and the process environment."""
        load_dotenv(PROJECT_ROOT / ".env", override=False)

        provider = _get("SEARCH_PROVIDER", "serpapi").lower()
        if provider not in VALID_PROVIDERS:
            raise ConfigError(
                f"SEARCH_PROVIDER must be one of {', '.join(VALID_PROVIDERS)}, got {provider!r}.",
                hint="Set SEARCH_PROVIDER=serpapi in .env.",
            )

        cfg = cls(
            search_provider=provider,
            serpapi_api_key=_get("SERPAPI_API_KEY"),
            google_vision_api_key=_get("GOOGLE_VISION_API_KEY"),
            rpc_url=_get("RPC_URL"),
            private_key=_normalise_private_key(_get("PRIVATE_KEY")),
            contract_address=_get("CONTRACT_ADDRESS"),
            match_threshold=_get_float("FACE_MATCH_THRESHOLD", 0.363),
            review_threshold=_get_float("FACE_REVIEW_THRESHOLD", 0.300),
            detect_confidence=_get_float("FACE_DETECT_CONFIDENCE", 0.850),
        )
        cfg.validate_thresholds()
        return cfg

    # -- per-area validation ------------------------------------------------

    def validate_thresholds(self) -> None:
        if not 0.0 < self.match_threshold < 1.0:
            raise ConfigError(
                f"FACE_MATCH_THRESHOLD must be between 0 and 1 (cosine similarity), "
                f"got {self.match_threshold}."
            )
        if not 0.0 <= self.review_threshold <= self.match_threshold:
            raise ConfigError(
                f"FACE_REVIEW_THRESHOLD ({self.review_threshold}) must be >= 0 and "
                f"<= FACE_MATCH_THRESHOLD ({self.match_threshold})."
            )
        if not 0.0 < self.detect_confidence < 1.0:
            raise ConfigError(
                f"FACE_DETECT_CONFIDENCE must be between 0 and 1, got {self.detect_confidence}."
            )

    def require_search(self) -> None:
        """Demand the credentials for the selected search provider."""
        if self.search_provider == "serpapi" and not self.serpapi_api_key:
            raise ConfigError(
                "SERPAPI_API_KEY is missing, but SEARCH_PROVIDER=serpapi.\n"
                "The reverse image search step cannot run without it.",
                hint=(
                    "Create a free key at https://serpapi.com/users/sign_up "
                    "(100 searches/month), then put it in .env as SERPAPI_API_KEY=...\n"
                    + _MISSING_ENV_HINT
                ),
            )
        if self.search_provider == "google_vision" and not self.google_vision_api_key:
            raise ConfigError(
                "GOOGLE_VISION_API_KEY is missing, but SEARCH_PROVIDER=google_vision.\n"
                "The reverse image search step cannot run without it.",
                hint=(
                    "Enable the Vision API and create an API key at "
                    "https://console.cloud.google.com/apis/credentials, then put it in "
                    ".env as GOOGLE_VISION_API_KEY=...\n" + _MISSING_ENV_HINT
                ),
            )

    def require_rpc(self) -> None:
        if not self.rpc_url:
            raise ConfigError(
                "RPC_URL is missing. The pipeline cannot reach a blockchain node.",
                hint=(
                    "For Ethereum Sepolia you can use the keyless public endpoint:\n"
                    "    RPC_URL=https://ethereum-sepolia-rpc.publicnode.com\n"
                    + _MISSING_ENV_HINT
                ),
            )

    def require_signer(self) -> None:
        self.require_rpc()
        if not self.private_key:
            raise ConfigError(
                "PRIVATE_KEY is missing. Writing a record to the chain requires a "
                "funded account to sign the transaction.",
                hint=(
                    "Use a THROWAWAY testnet wallet. Fund it from a Sepolia faucet:\n"
                    "    https://cloud.google.com/application/web3/faucet/ethereum/sepolia\n"
                    "Then set PRIVATE_KEY=0x... in .env\n" + _MISSING_ENV_HINT
                ),
            )
        if len(self.private_key) != 66:
            raise ConfigError(
                f"PRIVATE_KEY does not look like a 32-byte hex key "
                f"(got {len(self.private_key) - 2} hex characters, expected 64).",
                hint="Paste the raw hex private key, with or without a 0x prefix.",
            )

    def require_contract(self) -> None:
        if not self.contract_address:
            raise ConfigError(
                "CONTRACT_ADDRESS is missing. No VerificationRegistry has been deployed yet.",
                hint=(
                    "Deploy one and copy the printed address into .env:\n"
                    "    python -m app deploy"
                ),
            )


def _normalise_private_key(raw: str) -> str:
    """Accept a key with or without 0x; store it with the prefix."""
    if not raw:
        return ""
    return raw if raw.startswith("0x") else f"0x{raw}"
