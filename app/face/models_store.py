"""Download and cache the ONNX model weights.

Weights are not committed to the repo (39 MB) and are fetched on first run into
``models/``. Each file is pinned to a SHA-256 digest and verified after download,
so a corrupted transfer or a substituted mirror fails loudly instead of silently
producing garbage embeddings.

Both models are published by the OpenCV Zoo project:
  * YuNet  -- face detection, 232 KB
    "YuNet: A Tiny Millisecond-level Face Detector", Wu et al., 2023
  * SFace  -- face recognition / 128-D embeddings, 37 MB
    "SFace: Sigmoid-Constrained Hypersphere Loss for Robust Face Recognition",
    Zhong et al., IEEE TIP 2021
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import requests

from ..config import MODEL_DIR
from ..errors import ModelError

_CHUNK = 1 << 16
_TIMEOUT = 180


@dataclass(frozen=True)
class ModelSpec:
    name: str
    filename: str
    sha256: str
    size_bytes: int
    #: Tried in order. Hugging Face is the project's current home; the GitHub
    #: repo is kept as a second source so one host being down is survivable.
    urls: tuple[str, ...]

    @property
    def path(self) -> Path:
        return MODEL_DIR / self.filename


YUNET = ModelSpec(
    name="yunet_2023mar",
    filename="face_detection_yunet_2023mar.onnx",
    sha256="8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    size_bytes=232589,
    urls=(
        "https://huggingface.co/opencv/face_detection_yunet/resolve/main/face_detection_yunet_2023mar.onnx",
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    ),
)

SFACE = ModelSpec(
    name="sface_2021dec",
    filename="face_recognition_sface_2021dec.onnx",
    sha256="0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    size_bytes=38696353,
    urls=(
        "https://huggingface.co/opencv/face_recognition_sface/resolve/main/face_recognition_sface_2021dec.onnx",
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
    ),
)

ALL_MODELS = (YUNET, SFACE)


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_model(spec: ModelSpec, *, on_progress=None) -> Path:
    """Return a local path to ``spec``, downloading and verifying if needed."""
    path = spec.path
    if path.exists() and _digest(path) == spec.sha256:
        return path

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    errors: list[str] = []

    for url in spec.urls:
        try:
            if on_progress:
                on_progress(f"downloading {spec.filename} ({spec.size_bytes / 1e6:.1f} MB)")
            with requests.get(url, timeout=_TIMEOUT, stream=True) as resp:
                resp.raise_for_status()
                with tmp.open("wb") as fh:
                    for chunk in resp.iter_content(_CHUNK):
                        fh.write(chunk)
        except requests.RequestException as exc:
            errors.append(f"{url} -> {type(exc).__name__}: {exc}")
            tmp.unlink(missing_ok=True)
            continue

        actual = _digest(tmp)
        if actual != spec.sha256:
            tmp.unlink(missing_ok=True)
            errors.append(f"{url} -> sha256 mismatch (got {actual[:16]}...)")
            continue

        tmp.replace(path)
        return path

    raise ModelError(
        f"Could not obtain model weights for {spec.name}.\n" + "\n".join(errors),
        hint=(
            "Check your internet connection, or download the file manually to "
            f"models/{spec.filename} from:\n    {spec.urls[0]}"
        ),
    )


def ensure_all(*, on_progress=None) -> dict[str, Path]:
    return {spec.name: ensure_model(spec, on_progress=on_progress) for spec in ALL_MODELS}
