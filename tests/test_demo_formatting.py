"""Tests for terminal box formatting and alignment in demo mode."""

import sys
from app.demo import (
    BOX_W,
    _box_line,
    _card_line,
    _stage_box,
    _stage_end,
    _visible_len,
    C_V,
    S_V,
    CYAN,
    GREEN,
    RESET,
    BOLD,
    DIM,
)


class TestDemoFormatting:
    def test_visible_len_plain(self):
        assert _visible_len("hello world") == 11

    def test_visible_len_ansi(self):
        styled = f"{BOLD}{CYAN}hello world{RESET}"
        assert _visible_len(styled) == 11

    def test_visible_len_unicode_symbols(self):
        text = "✓ PASS • VALIDATED"
        assert _visible_len(text) == len(text)

    def test_box_line_total_visible_width(self):
        line = _box_line(f"  {BOLD}Image File:{RESET} images.jpeg")
        assert _visible_len(line) == BOX_W

    def test_box_line_empty(self):
        line = _box_line("")
        assert _visible_len(line) == BOX_W

    def test_box_line_long_content_overflow_handled(self):
        long_text = "x" * 100
        line = _box_line(long_text)
        # Should not crash and visible length should be at least BOX_W
        assert _visible_len(line) >= BOX_W

    def test_card_line_total_visible_width(self):
        line = _card_line("  R01  Face Detection  YuNet ONNX detected face... ✓ PASS")
        assert _visible_len(line) == BOX_W

    def test_card_line_with_ansi_styles(self):
        line = _card_line(f"  {BOLD}R01{RESET}  Face Detection  {DIM}YuNet ONNX...{RESET} {GREEN}✓ PASS{RESET}")
        assert _visible_len(line) == BOX_W
