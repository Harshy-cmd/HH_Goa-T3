"""Face detection with YuNet (cv2.FaceDetectorYN)."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ..errors import ImageError, ModelError, NoFaceDetectedError
from ..hashing import sha256_hex
from ..imaging import decode_to_bgr
from ..models import DetectedFace, FaceBox, InputImage
from .models_store import YUNET, ensure_model

#: YuNet's own NMS/top-k defaults from the OpenCV Zoo reference implementation.
_NMS_THRESHOLD = 0.3
_TOP_K = 5000

#: Below this the SFace 112x112 alignment is upscaling noise more than signal,
#: so such detections are reported but flagged.
MIN_USABLE_FACE_PX = 32


class FaceDetector:
    """Detects faces and returns them sorted largest-first."""

    model_name = YUNET.name

    def __init__(self, confidence: float, *, on_progress=None) -> None:
        model_path = ensure_model(YUNET, on_progress=on_progress)
        try:
            # Input size is a placeholder; it is set per-image in detect().
            self._detector = cv2.FaceDetectorYN.create(
                model=str(model_path),
                config="",
                input_size=(320, 320),
                score_threshold=float(confidence),
                nms_threshold=_NMS_THRESHOLD,
                top_k=_TOP_K,
            )
        except cv2.error as exc:
            raise ModelError(f"OpenCV could not load the YuNet model: {exc}") from exc
        self.confidence = confidence

    def detect(self, image: np.ndarray) -> list[DetectedFace]:
        """Detect faces in a BGR image, largest first."""
        height, width = image.shape[:2]
        self._detector.setInputSize((width, height))
        try:
            _, raw = self._detector.detect(image)
        except cv2.error as exc:
            raise ModelError(f"YuNet detection failed: {exc}") from exc

        if raw is None:
            return []

        faces = [
            DetectedFace(
                box=FaceBox(
                    x=int(round(row[0])),
                    y=int(round(row[1])),
                    width=int(round(row[2])),
                    height=int(round(row[3])),
                    confidence=float(row[14]),
                ),
                raw=np.asarray(row, dtype=np.float32),
            )
            for row in raw
        ]
        faces.sort(key=lambda f: f.box.area, reverse=True)
        return faces


# --- image loading -----------------------------------------------------------


def load_image(path: str | Path) -> tuple[np.ndarray, InputImage]:
    """Load an image from disk, returning the BGR array and its metadata.

    The SHA-256 is computed over the original file bytes, before any decoding or
    re-encoding, so the input fingerprint refers to the file the user supplied.
    """
    p = Path(path)
    if not p.exists():
        raise ImageError(
            f"Input image not found: {p}",
            hint="Pass a path that exists, e.g. --image samples/input.jpg",
        )
    if p.is_dir():
        raise ImageError(f"Input path is a directory, not an image file: {p}")

    try:
        data = p.read_bytes()
    except OSError as exc:
        raise ImageError(f"Could not read {p}: {exc}") from exc

    if not data:
        raise ImageError(f"Input image is empty (0 bytes): {p}")

    # decode_to_bgr decodes from bytes (imread(path) silently returns None for
    # non-ASCII paths on Windows) and handles every common format -- JPEG/PNG/
    # WebP/BMP/TIFF via OpenCV, AVIF/HEIC/HEIF via Pillow -- raising ImageError
    # with a helpful hint when the bytes are not a decodable image.
    array = decode_to_bgr(data, filename=p.name)

    height, width = array.shape[:2]
    meta = InputImage(
        path=str(p),
        filename=p.name,
        sha256=sha256_hex(data),
        width=int(width),
        height=int(height),
        bytes_len=len(data),
    )
    return array, meta


def select_target_face(
    faces: list[DetectedFace],
    *,
    index: int | None = None,
    context: str = "input image",
) -> DetectedFace:
    """Pick the face to encode.

    With ``index`` the choice is explicit. Without it the largest face is used --
    the caller is responsible for telling the user that a choice was made.
    """
    if not faces:
        raise NoFaceDetectedError(
            f"No face detected in the {context}.",
            hint=(
                "Use a clear, front-facing photo where the face is reasonably "
                "large. You can also lower FACE_DETECT_CONFIDENCE in .env "
                "(default 0.850) to accept weaker detections."
            ),
        )
    if index is None:
        return faces[0]
    if not 0 <= index < len(faces):
        raise ImageError(
            f"--face {index} is out of range: {len(faces)} face(s) detected "
            f"in the {context} (valid indices 0..{len(faces) - 1}).",
            hint="Run with --list-faces to see the detected faces and their sizes.",
        )
    return faces[index]
