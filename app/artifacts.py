"""Reading and writing run artifacts.

Three files land in ``artifacts/``:

* ``latest_verification.json`` -- the record, its hash, and the chain receipt.
  This is the file ``verify`` reads and the file to edit for the tamper demo.
* ``candidates.json`` -- every result the provider returned plus the outcome of
  each verification attempt. This is the audit trail showing the candidate was
  chosen from live search output rather than picked in advance.
* ``blockchain_record.json`` -- what was read back off the chain.

None of these contain secrets, embeddings, or image bytes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import ARTIFACT_DIR
from .errors import ArtifactError

LATEST_VERIFICATION = "latest_verification.json"
CANDIDATES = "candidates.json"
BLOCKCHAIN_RECORD = "blockchain_record.json"


def _write(name: str, payload: dict[str, Any]) -> Path:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    path = ARTIFACT_DIR / name
    # indent=2 so a human can edit one field for the tamper demonstration.
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def write_verification(payload: dict[str, Any]) -> Path:
    return _write(LATEST_VERIFICATION, payload)


def write_candidates(payload: dict[str, Any]) -> Path:
    return _write(CANDIDATES, payload)


def write_blockchain_record(payload: dict[str, Any]) -> Path:
    return _write(BLOCKCHAIN_RECORD, payload)


def default_verification_path() -> Path:
    return ARTIFACT_DIR / LATEST_VERIFICATION


def load_verification(path: str | Path | None = None) -> tuple[dict[str, Any], Path]:
    """Load a verification artifact, validating the shape ``verify`` relies on."""
    target = Path(path) if path else default_verification_path()

    if not target.exists():
        raise ArtifactError(
            f"Verification artifact not found: {target}",
            hint="Run the pipeline first:\n    python -m app run --image samples/input.jpg",
        )
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ArtifactError(
            f"{target} is not valid JSON: {exc}",
            hint=(
                "If you edited it for the tamper demonstration, the file must stay "
                "syntactically valid JSON -- change a value, not the structure."
            ),
        ) from exc

    if not isinstance(payload, dict):
        raise ArtifactError(f"{target} must contain a JSON object.")
    for key in ("record", "record_hash"):
        if key not in payload:
            raise ArtifactError(f"{target} is missing the required '{key}' field.")
    if not isinstance(payload["record"], dict):
        raise ArtifactError(f"{target}: 'record' must be a JSON object.")

    return payload, target
