"""Tests for face matching logic (no live models required)."""

from app.face.matcher import classify, OPENCV_COSINE_THRESHOLD


class TestClassify:
    """The three-way verdict classification is the core decision function."""

    def test_match_above_threshold(self):
        assert classify(0.5, match=0.363, review=0.300) == "MATCH"

    def test_match_at_threshold(self):
        assert classify(0.363, match=0.363, review=0.300) == "MATCH"

    def test_possible_match_in_band(self):
        assert classify(0.33, match=0.363, review=0.300) == "POSSIBLE MATCH"

    def test_possible_match_at_review(self):
        assert classify(0.300, match=0.363, review=0.300) == "POSSIBLE MATCH"

    def test_no_match_below_review(self):
        assert classify(0.1, match=0.363, review=0.300) == "NO MATCH"

    def test_no_match_zero(self):
        assert classify(0.0, match=0.363, review=0.300) == "NO MATCH"

    def test_no_match_negative(self):
        assert classify(-0.1, match=0.363, review=0.300) == "NO MATCH"

    def test_perfect_match(self):
        assert classify(1.0, match=0.363, review=0.300) == "MATCH"


class TestOpencvThreshold:
    """Verify the published threshold constant is what we expect."""

    def test_value(self):
        assert OPENCV_COSINE_THRESHOLD == 0.363
