"""Face embedding with SFace (cv2.FaceRecognizerSF).

SFace produces a 128-D embedding from a 112x112 aligned crop. Alignment uses the
five landmarks YuNet returns, which is why the detector's raw output row has to
be carried through rather than just the bounding box.
"""

from __future__ import annotations

import cv2
import numpy as np

from ..errors import ModelError
from ..models import DetectedFace, FaceEncoding
from .models_store import SFACE, ensure_model

EMBEDDING_DIM = 128


class FaceEncoder:
    """Turns detected faces into 128-D embeddings."""

    model_name = SFACE.name
    metric = "cosine"

    def __init__(self, *, on_progress=None) -> None:
        model_path = ensure_model(SFACE, on_progress=on_progress)
        try:
            self._recognizer = cv2.FaceRecognizerSF.create(
                model=str(model_path), config=""
            )
        except cv2.error as exc:
            raise ModelError(f"OpenCV could not load the SFace model: {exc}") from exc

    def encode(self, image: np.ndarray, face: DetectedFace) -> FaceEncoding:
        """Align and encode a single detected face."""
        try:
            aligned = self._recognizer.alignCrop(image, face.raw)
            vector = self._recognizer.feature(aligned)
        except cv2.error as exc:
            raise ModelError(f"SFace encoding failed: {exc}") from exc

        vector = np.asarray(vector, dtype=np.float32).reshape(-1)
        if vector.size != EMBEDDING_DIM:
            raise ModelError(
                f"SFace returned a {vector.size}-D embedding, expected {EMBEDDING_DIM}."
            )
        return FaceEncoding(vector=vector, box=face.box)

    def encode_all(
        self, image: np.ndarray, faces: list[DetectedFace]
    ) -> list[FaceEncoding]:
        """Encode every detected face, skipping any that fail to align.

        A candidate image found on the web can contain a face that YuNet locates
        but SFace cannot align (heavily cropped at the frame edge, for example).
        One unusable face should not discard the whole candidate.
        """
        encodings: list[FaceEncoding] = []
        for face in faces:
            try:
                encodings.append(self.encode(image, face))
            except ModelError:
                continue
        return encodings

    # -- comparison ---------------------------------------------------------

    def cosine_similarity(self, a: FaceEncoding, b: FaceEncoding) -> float:
        """SFace cosine similarity. HIGHER means more similar."""
        return float(
            self._recognizer.match(
                a.vector, b.vector, cv2.FaceRecognizerSF_FR_COSINE
            )
        )

    def l2_distance(self, a: FaceEncoding, b: FaceEncoding) -> float:
        """SFace L2 norm distance. LOWER means more similar."""
        return float(
            self._recognizer.match(
                a.vector, b.vector, cv2.FaceRecognizerSF_FR_NORM_L2
            )
        )
