"""Prepare a copy of the input image that a search provider will accept.

Providers cap upload size (SerpAPI: 500 KB) and accept a limited set of formats.
A high-resolution portrait routinely exceeds that, so a downscaled JPEG copy is
derived for the upload.

The copy is kept strictly separate from the input fingerprint: the record's
``input.sha256`` always refers to the original file on disk, and the derived
copy gets its own ``search_copy_sha256``. That way the artifact never implies we
fingerprinted something we did not.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from .errors import ImageError
from .hashing import sha256_hex

# Register the HEIF/HEIC opener with Pillow once, at import. AVIF is decoded by
# Pillow natively (12+); pillow-heif adds HEIC/HEIF (iPhone photos). Guarded so a
# missing/old pillow-heif never breaks import -- those formats just won't decode.
try:  # pragma: no cover - depends on the installed pillow-heif build
    from pillow_heif import register_heif_opener

    register_heif_opener()
except Exception:  # noqa: BLE001 - optional codec; degrade gracefully
    pass

#: Longest-edge sizes tried in order. Reverse image search does not benefit from
#: more than ~1600px, and dropping resolution shrinks bytes far faster than
#: dropping JPEG quality does.
_MAX_DIMS = (1600, 1280, 1024, 800, 640, 512)
_QUALITIES = (88, 80, 72, 64, 55)


def decode_to_bgr(data: bytes, *, filename: str | None = None) -> np.ndarray:
    """Decode arbitrary image bytes into an OpenCV BGR ``ndarray``.

    OpenCV's ``imdecode`` is tried first: it handles JPEG/PNG/WebP/BMP/TIFF and
    keeps existing inputs decoding byte-for-byte as before (so face detection is
    unchanged). Anything it declines -- notably AVIF and HEIC/HEIF -- falls back
    to Pillow (+ pillow-heif), with EXIF orientation applied so phone photos are
    not processed sideways.

    Raises :class:`ImageError` with a helpful hint when nothing can decode it.
    """
    if not data:
        label = filename or "image"
        raise ImageError(
            f"Could not decode {label} as an image.",
            hint=(
                "Supported formats: JPEG, PNG, WebP, BMP, TIFF, GIF, AVIF, "
                "HEIC/HEIF. Is the file corrupt or truncated?"
            ),
        )

    array = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if array is not None:
        return array

    try:
        with Image.open(io.BytesIO(data)) as img:
            oriented = ImageOps.exif_transpose(img)
            rgb = oriented.convert("RGB")
            arr = np.asarray(rgb)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        label = filename or "image"
        raise ImageError(
            f"Could not decode {label} as an image.",
            hint=(
                "Supported formats: JPEG, PNG, WebP, BMP, TIFF, GIF, AVIF, "
                "HEIC/HEIF. Is the file corrupt or truncated?"
            ),
        ) from exc

    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ImageError(
            f"Decoded {filename or 'image'} but it is not a 3-channel colour image."
        )
    # Pillow gives RGB; OpenCV/YuNet expect BGR.
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def downscale_bgr(image: np.ndarray, *, max_edge: int = 1600) -> np.ndarray:
    """Downscale a BGR image so its longest edge is at most ``max_edge``.

    Candidate images fetched from the web can be very large (up to the 12 MB
    fetch cap), and a full-resolution decode is wasteful for face detection and
    risky on a 512 MB instance. Returns the array unchanged when it already fits,
    so small images are never re-sampled. Used only for downloaded *candidate*
    images -- never the input, whose recorded dimensions must reflect the
    original file.
    """
    height, width = image.shape[:2]
    longest = max(height, width)
    if longest <= max_edge:
        return image
    scale = max_edge / float(longest)
    new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return cv2.resize(image, new_size, interpolation=cv2.INTER_AREA)


@dataclass(frozen=True)
class SearchCopy:
    """Bytes actually uploaded to the search provider."""

    data: bytes
    sha256: str
    mime_type: str
    filename: str
    width: int
    height: int
    #: True when the original file was sent unmodified.
    is_original: bool

    @property
    def size(self) -> int:
        return len(self.data)


def prepare_search_copy(
    path: str | Path,
    original_bytes: bytes,
    *,
    max_bytes: int,
    allow_original_formats: tuple[str, ...] = ("jpeg", "png", "webp"),
) -> SearchCopy:
    """Return a copy of the image that fits within ``max_bytes``.

    Sends the original untouched when it already fits and is in an accepted
    format, so the common small-image case involves no re-encoding at all.
    """
    p = Path(path)
    try:
        with Image.open(io.BytesIO(original_bytes)) as probe:
            fmt = (probe.format or "").lower()
            probe.load()
            source = probe.convert("RGB")
            orig_w, orig_h = probe.size
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageError(f"Could not read {p.name} for search upload: {exc}") from exc

    if len(original_bytes) <= max_bytes and fmt in allow_original_formats:
        return SearchCopy(
            data=original_bytes,
            sha256=sha256_hex(original_bytes),
            mime_type=f"image/{'jpeg' if fmt == 'jpg' else fmt}",
            filename=p.name,
            width=orig_w,
            height=orig_h,
            is_original=True,
        )

    for max_dim in _MAX_DIMS:
        resized = source
        if max(source.size) > max_dim:
            resized = source.copy()
            resized.thumbnail((max_dim, max_dim), Image.LANCZOS)
        for quality in _QUALITIES:
            buf = io.BytesIO()
            resized.save(buf, format="JPEG", quality=quality, optimize=True)
            data = buf.getvalue()
            if len(data) <= max_bytes:
                return SearchCopy(
                    data=data,
                    sha256=sha256_hex(data),
                    mime_type="image/jpeg",
                    filename=f"{p.stem}_search.jpg",
                    width=resized.width,
                    height=resized.height,
                    is_original=False,
                )

    raise ImageError(
        f"Could not compress {p.name} below the provider's "
        f"{max_bytes / 1024:.0f} KB upload limit.",
        hint="Crop the image to the face region and try again.",
    )
