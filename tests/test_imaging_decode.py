"""Universal image decoding + candidate downscaling (Workstream 1).

Covers the formats the audit called out (WebP/AVIF/HEIC alongside JPEG/PNG),
the OpenCV-first / Pillow-fallback split, EXIF orientation on the fallback path,
BGR channel ordering, and the failure mode that must raise ``ImageError``.
"""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image, features

import app.imaging as imaging
from app.errors import ImageError
from app.imaging import decode_to_bgr, downscale_bgr


def _encode(fmt: str, size=(64, 48), color=(255, 0, 0), **save_kw) -> bytes:
    """Return image bytes in ``fmt``. ``size`` is (width, height)."""
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format=fmt, **save_kw)
    return buf.getvalue()


class TestDecodeCommonFormats:
    @pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP", "BMP"])
    def test_roundtrip_shape(self, fmt):
        arr = decode_to_bgr(_encode(fmt))
        assert isinstance(arr, np.ndarray)
        assert arr.dtype == np.uint8
        assert arr.shape == (48, 64, 3)  # (H, W, C)

    def test_png_channel_order_is_bgr(self):
        # Pure RGB red must end up in OpenCV's red channel (index 2).
        arr = decode_to_bgr(_encode("PNG", size=(8, 8), color=(255, 0, 0)))
        b, g, r = arr[0, 0]
        assert (int(b), int(g), int(r)) == (0, 0, 255)

    def test_gif_uses_pillow_fallback(self):
        # OpenCV does not decode GIF, so this drives the Pillow fallback branch.
        arr = decode_to_bgr(_encode("GIF"))
        assert arr.shape == (48, 64, 3)


class TestModernFormats:
    def test_avif_roundtrip(self):
        if not features.check("avif"):
            pytest.skip("AVIF codec not available in this Pillow build")
        try:
            data = _encode("AVIF")
        except (OSError, KeyError, ValueError) as exc:  # encoder missing
            pytest.skip(f"AVIF encode unavailable: {exc}")
        assert decode_to_bgr(data, filename="x.avif").shape == (48, 64, 3)

    def test_heic_roundtrip(self):
        pytest.importorskip("pillow_heif")
        try:
            data = _encode("HEIF")
        except (OSError, KeyError, ValueError) as exc:
            pytest.skip(f"HEIC encode unavailable: {exc}")
        assert decode_to_bgr(data, filename="x.heic").shape == (48, 64, 3)


class TestExifOrientation:
    def test_orientation_applied_on_pillow_path(self, monkeypatch):
        # A 64x48 landscape image tagged orientation=6 displays as 48x64 portrait.
        img = Image.new("RGB", (64, 48), (10, 20, 30))
        exif = img.getexif()
        exif[0x0112] = 6  # Orientation: rotate 90 deg
        buf = io.BytesIO()
        img.save(buf, format="JPEG", exif=exif)

        # Force the Pillow fallback so EXIF transpose (skipped by cv2) runs.
        monkeypatch.setattr(imaging.cv2, "imdecode", lambda *a, **k: None)
        arr = decode_to_bgr(buf.getvalue())
        assert arr.shape == (64, 48, 3)  # width/height swapped by transpose


class TestDecodeFailures:
    def test_corrupt_bytes_raise(self):
        with pytest.raises(ImageError):
            decode_to_bgr(b"\x89PNG\r\n\x1a\n not a real png", filename="broken.png")

    def test_plain_text_raises(self):
        with pytest.raises(ImageError):
            decode_to_bgr(b"this is not an image at all")

    def test_empty_bytes_raise(self):
        with pytest.raises(ImageError):
            decode_to_bgr(b"")


class TestDownscale:
    def test_large_image_downscaled_preserving_aspect(self):
        big = np.zeros((2000, 3000, 3), dtype=np.uint8)  # H=2000, W=3000
        out = downscale_bgr(big, max_edge=1600)
        assert max(out.shape[:2]) == 1600
        assert out.shape[1] == 1600  # width was the long edge
        assert out.shape[0] == round(2000 * 1600 / 3000)

    def test_small_image_returned_unchanged(self):
        small = np.zeros((100, 120, 3), dtype=np.uint8)
        assert downscale_bgr(small, max_edge=1600) is small
