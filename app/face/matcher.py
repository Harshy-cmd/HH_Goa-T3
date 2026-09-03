"""Face comparison and match classification.

Thresholds
----------
SFace is compared by cosine similarity, where HIGHER means more similar. The
default match threshold of **0.363** is the value published by OpenCV alongside
this exact model checkpoint (``face_recognition_sface_2021dec``); it is not a
number we invented. OpenCV's reference L2 threshold for the same model is 1.128,
and the L2 distance is reported alongside the similarity for transparency.

Between ``review_threshold`` (default 0.300) and the match threshold, the result
is reported as POSSIBLE MATCH. That band is our own conservative convention, not
a published value, and exists so borderline scores are visibly borderline rather
than being rounded into a yes or a no.

A MATCH means "these two images contain a face the model scores as the same
identity". It is not proof of real-world identity. See README > Limitations.
"""

from __future__ import annotations

from ..models import FaceComparison, FaceEncoding, MatchVerdict

#: OpenCV's published thresholds for face_recognition_sface_2021dec.
OPENCV_COSINE_THRESHOLD = 0.363
OPENCV_L2_THRESHOLD = 1.128


def classify(similarity: float, *, match: float, review: float) -> MatchVerdict:
    """Turn a cosine similarity into a three-way verdict."""
    if similarity >= match:
        return "MATCH"
    if similarity >= review:
        return "POSSIBLE MATCH"
    return "NO MATCH"


def compare(
    encoder,
    reference: FaceEncoding,
    candidate: FaceEncoding,
    *,
    match_threshold: float,
    review_threshold: float,
) -> FaceComparison:
    """Compare one reference face against one candidate face."""
    similarity = encoder.cosine_similarity(reference, candidate)
    return FaceComparison(
        similarity=similarity,
        l2_distance=encoder.l2_distance(reference, candidate),
        verdict=classify(similarity, match=match_threshold, review=review_threshold),
        threshold=match_threshold,
        box=candidate.box,
    )


def best_match(
    encoder,
    reference: FaceEncoding,
    candidates: list[FaceEncoding],
    *,
    match_threshold: float,
    review_threshold: float,
) -> tuple[FaceComparison, list[FaceComparison]]:
    """Compare the reference against every candidate face.

    Returns the single best comparison (highest cosine similarity) plus the full
    list, so a multi-face candidate image can be reported honestly instead of
    only showing the winner.
    """
    if not candidates:
        raise ValueError("best_match requires at least one candidate encoding")

    comparisons = [
        compare(
            encoder,
            reference,
            candidate,
            match_threshold=match_threshold,
            review_threshold=review_threshold,
        )
        for candidate in candidates
    ]
    return max(comparisons, key=lambda c: c.similarity), comparisons
