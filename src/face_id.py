"""
src/face_id.py
Stage 1 — Face Detection & Encoding
────────────────────────────────────
Uses the `face_recognition` library (wraps dlib) to:
  1. Load an image from disk.
  2. Detect all face bounding-boxes in the image.
  3. Compute a 128-dimensional encoding for each detected face.
  4. Return the encoding of the *first* (largest) face as a numpy array.

Usage (CLI):
    python -m src.face_id <image_path>
    python src/face_id.py  <image_path>

Usage (as a module, called by pipeline.py):
    from src.face_id import detect_and_encode
    encoding = detect_and_encode("photo.jpg")
"""

import sys
import pathlib
import numpy as np
import face_recognition


# ─── public API ───────────────────────────────────────────────────────────────

def detect_and_encode(image_path: str) -> np.ndarray:
    """
    Detect faces in *image_path* and return the 128-d encoding of the
    first (or only) face found.

    Parameters
    ----------
    image_path : str
        Absolute or relative path to a JPEG / PNG image file.

    Returns
    -------
    np.ndarray
        Shape (128,) float64 array — the face encoding.

    Raises
    ------
    FileNotFoundError
        If the image file does not exist.
    ValueError
        If no faces are detected in the image.
    """

    # ── Step 1: validate the path ──────────────────────────────────────────
    path = pathlib.Path(image_path).resolve()
    print(f"\n[face_id] ▶ Step 1 — Loading image")
    print(f"          Path : {path}")

    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")

    print(f"          ✔  File found ({path.stat().st_size / 1024:.1f} KB)")

    # ── Step 2: load image into RGB numpy array ────────────────────────────
    print(f"\n[face_id] ▶ Step 2 — Decoding image into RGB array")
    image_array = face_recognition.load_image_file(str(path))
    h, w, c = image_array.shape
    print(f"          ✔  Loaded  →  {w}×{h} px, {c} channels")

    # ── Step 3: detect face locations ─────────────────────────────────────
    # model="hog" is fast & CPU-friendly; use "cnn" for GPU-powered accuracy.
    print(f"\n[face_id] ▶ Step 3 — Detecting face bounding-boxes  (model=hog)")
    face_locations = face_recognition.face_locations(image_array, model="hog")
    n = len(face_locations)

    if n == 0:
        raise ValueError(
            "No faces detected in the image. "
            "Try a clearer, well-lit front-facing photo."
        )

    print(f"          ✔  {n} face(s) detected:")
    for i, (top, right, bottom, left) in enumerate(face_locations):
        box_w = right - left
        box_h = bottom - top
        print(f"             Face {i}: top={top} right={right} "
              f"bottom={bottom} left={left}  ({box_w}×{box_h} px)")

    # ── Step 4: compute face encodings ────────────────────────────────────
    print(f"\n[face_id] ▶ Step 4 — Computing 128-d face encoding(s)")
    face_encodings = face_recognition.face_encodings(
        image_array,
        known_face_locations=face_locations,
        num_jitters=1,       # increase to 10+ for higher accuracy (slower)
        model="small",       # "large" is more accurate but slower
    )

    if not face_encodings:
        raise ValueError("Encoding failed — face detected but could not be encoded.")

    print(f"          ✔  {len(face_encodings)} encoding(s) computed")

    # ── Step 5: select the first face (largest bounding box) ──────────────
    print(f"\n[face_id] ▶ Step 5 — Selecting primary face")

    if n > 1:
        # Pick the face with the largest bounding-box area.
        areas = [
            (right - left) * (bottom - top)
            for (top, right, bottom, left) in face_locations
        ]
        best_idx = int(np.argmax(areas))
        print(f"          ℹ  Multiple faces found — selecting Face {best_idx} "
              f"(largest, area={areas[best_idx]} px²)")
    else:
        best_idx = 0
        print(f"          ✔  Single face — using Face 0")

    encoding: np.ndarray = face_encodings[best_idx]

    # ── Step 6: summary ───────────────────────────────────────────────────
    print(f"\n[face_id] ▶ Step 6 — Encoding summary")
    print(f"          Shape  : {encoding.shape}")
    print(f"          dtype  : {encoding.dtype}")
    print(f"          Min    : {encoding.min():.6f}")
    print(f"          Max    : {encoding.max():.6f}")
    print(f"          Norm   : {np.linalg.norm(encoding):.6f}")
    print(f"          First 8 values: {encoding[:8].tolist()}")
    print(f"\n[face_id] ✅ Face encoding complete.\n")

    return encoding


# ─── CLI entry-point ──────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python -m src.face_id <image_path>")
        print("       python src/face_id.py  <image_path>")
        sys.exit(1)

    image_path = sys.argv[1]

    try:
        encoding = detect_and_encode(image_path)
        # Save the encoding to a .npy file next to the image for easy inspection.
        out_path = pathlib.Path(image_path).with_suffix(".encoding.npy")
        np.save(str(out_path), encoding)
        print(f"[face_id] 💾 Encoding saved to: {out_path}")
        print(f"          Load with: numpy.load('{out_path}')")
    except (FileNotFoundError, ValueError) as exc:
        print(f"\n[face_id] ❌ ERROR: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
