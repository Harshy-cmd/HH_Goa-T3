"""Deterministic canonical serialisation and hashing.

This module is the root of the integrity claim, so it is deliberately tiny and
has no dependencies outside the standard library.

Canonicalisation rules (all four matter):

1. ``sort_keys=True``      -- key order cannot influence the digest.
2. ``separators=(",",":")`` -- no incidental whitespace.
3. ``ensure_ascii=False`` + explicit UTF-8 encode -- one byte representation for
   non-ASCII text (post titles routinely contain emoji and non-Latin script).
4. ``allow_nan=False``     -- NaN/Infinity are not valid JSON and would produce
   a digest that no other parser could reproduce.

Floats are rounded via :func:`quantize` before they enter a record, so that a
value written today and the same value re-read from JSON tomorrow serialise to
identical bytes.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

#: Decimal places kept for every float that enters a hashed record.
FLOAT_PRECISION = 6


def quantize(value: float) -> float:
    """Round ``value`` so it round-trips through JSON byte-identically."""
    return round(float(value), FLOAT_PRECISION)


def canonical_json(obj: Any) -> bytes:
    """Serialise ``obj`` to its one canonical UTF-8 byte representation."""
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    """SHA-256 of raw bytes, lowercase hex, no prefix."""
    return hashlib.sha256(data).hexdigest()


def record_hash(record: dict[str, Any]) -> str:
    """SHA-256 of the canonical JSON form of ``record``, lowercase hex.

    This exact function is used both when writing to the chain and when
    re-verifying, which is what makes tampering detectable.
    """
    return sha256_hex(canonical_json(record))


def to_bytes32(hex_digest: str) -> bytes:
    """Convert a 64-char hex SHA-256 digest to the 32 bytes solidity expects."""
    cleaned = hex_digest[2:] if hex_digest.startswith("0x") else hex_digest
    if len(cleaned) != 64:
        raise ValueError(f"expected a 64-character hex digest, got {len(cleaned)}")
    return bytes.fromhex(cleaned)
