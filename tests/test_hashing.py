"""Tests for canonical hashing and the integrity claim."""

import json

from app.hashing import canonical_json, quantize, record_hash, sha256_hex, to_bytes32


class TestCanonicalJson:
    """The exact byte output of canonical_json determines every hash in the
    system, so these tests pin the exact bytes we expect."""

    def test_empty_object(self):
        assert canonical_json({}) == b"{}"

    def test_keys_sorted(self):
        result = canonical_json({"z": 1, "a": 2, "m": 3})
        assert result == b'{"a":2,"m":3,"z":1}'

    def test_no_whitespace(self):
        result = canonical_json({"key": "value"})
        # No spaces after : or ,
        assert b" " not in result

    def test_nested_sorting(self):
        obj = {"b": {"d": 1, "c": 2}, "a": 3}
        result = canonical_json(obj)
        parsed = json.loads(result)
        keys_outer = list(parsed.keys())
        keys_inner = list(parsed["b"].keys())
        assert keys_outer == ["a", "b"]
        assert keys_inner == ["c", "d"]

    def test_unicode_preserved(self):
        result = canonical_json({"emoji": "\U0001f600"})
        # ensure_ascii=False means the emoji is UTF-8, not \\uXXXX
        assert "\U0001f600".encode("utf-8") in result

    def test_nan_rejected(self):
        import pytest
        with pytest.raises(ValueError):
            canonical_json({"x": float("nan")})

    def test_deterministic(self):
        """Same input always produces identical bytes."""
        obj = {"b": 1, "a": [3, 2, 1], "c": {"z": True, "y": None}}
        assert canonical_json(obj) == canonical_json(obj)


class TestSha256Hex:
    def test_known_value(self):
        # SHA-256 of empty string is well known
        assert sha256_hex(b"") == (
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )

    def test_different_input_different_hash(self):
        assert sha256_hex(b"hello") != sha256_hex(b"world")


class TestQuantize:
    def test_rounds_to_six(self):
        assert quantize(0.1234567890) == 0.123457

    def test_identity_for_round_numbers(self):
        assert quantize(1.0) == 1.0

    def test_negative(self):
        assert quantize(-0.3629999) == -0.363


class TestRecordHash:
    def test_same_record_same_hash(self):
        record = {"a": 1, "b": "hello", "c": [1, 2, 3]}
        assert record_hash(record) == record_hash(record)

    def test_key_order_irrelevant(self):
        """Records with the same data but different insertion order hash the same."""
        r1 = {"a": 1, "b": 2}
        r2 = {"b": 2, "a": 1}
        assert record_hash(r1) == record_hash(r2)

    def test_modified_record_different_hash(self):
        original = {"similarity": 0.37, "url": "https://example.com"}
        tampered = {"similarity": 0.38, "url": "https://example.com"}
        assert record_hash(original) != record_hash(tampered)

    def test_one_bit_change(self):
        """Even a tiny change produces a completely different hash."""
        original = {"verified": True}
        tampered = {"verified": False}
        h1 = record_hash(original)
        h2 = record_hash(tampered)
        assert h1 != h2
        # SHA-256 should produce 64 hex chars
        assert len(h1) == 64
        assert len(h2) == 64


class TestToBytes32:
    def test_valid_hex(self):
        hex_digest = "a" * 64
        result = to_bytes32(hex_digest)
        assert len(result) == 32
        assert isinstance(result, bytes)

    def test_with_0x_prefix(self):
        hex_digest = "0x" + "b" * 64
        result = to_bytes32(hex_digest)
        assert len(result) == 32

    def test_wrong_length_raises(self):
        import pytest
        with pytest.raises(ValueError, match="64-character"):
            to_bytes32("abc")
