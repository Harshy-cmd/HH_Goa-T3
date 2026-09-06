"""Dataclasses for everything that moves between pipeline stages.

The important type here is :class:`VerificationRecord`. Its ``to_record()``
output is the *only* structure that gets hashed and committed to the chain, so
it is defined in one place and deliberately contains no biometric data:
embeddings never enter a record, an artifact, a log line, or the chain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

from .hashing import quantize

SCHEMA_VERSION = "1.0"

MatchVerdict = Literal["MATCH", "POSSIBLE MATCH", "NO MATCH"]

#: Where the bytes we fingerprinted actually came from.
#:   publisher          -- the image URL on the discovered page (preferred)
#:   provider_thumbnail -- the search provider's cached copy (fallback; recorded
#:                         explicitly so a thumbnail is never passed off as the
#:                         original post image)
ImageOrigin = Literal["publisher", "provider_thumbnail"]


# --- face --------------------------------------------------------------------


@dataclass(frozen=True)
class FaceBox:
    """A detected face in pixel coordinates."""

    x: int
    y: int
    width: int
    height: int
    confidence: float

    @property
    def area(self) -> int:
        return self.width * self.height

    def describe(self) -> str:
        return (
            f"x={self.x} y={self.y} w={self.width} h={self.height} "
            f"conf={self.confidence:.3f}"
        )


@dataclass
class DetectedFace:
    """A detected face plus the raw YuNet row needed to align and encode it."""

    box: FaceBox
    #: The 15-value YuNet detection row (bbox + 5 landmarks + score). Required
    #: by cv2.FaceRecognizerSF.alignCrop; not persisted anywhere.
    raw: np.ndarray


@dataclass
class FaceEncoding:
    """A 128-D SFace embedding.

    Held in memory only. Never serialised, printed, or sent anywhere.
    """

    vector: np.ndarray
    box: FaceBox

    def __repr__(self) -> str:  # keep vectors out of logs and tracebacks
        return f"FaceEncoding(dim={self.vector.size}, box={self.box.describe()})"


@dataclass(frozen=True)
class FaceComparison:
    """Result of comparing one input face against one candidate face."""

    similarity: float  # SFace cosine similarity; HIGHER = more similar
    l2_distance: float  # SFace L2 norm; LOWER = more similar
    verdict: MatchVerdict
    threshold: float
    box: FaceBox

    @property
    def is_match(self) -> bool:
        return self.verdict == "MATCH"


# --- search ------------------------------------------------------------------


@dataclass(frozen=True)
class SearchResult:
    """One normalised reverse-image-search hit.

    Providers return wildly different shapes; every provider must flatten into
    this. Fields the provider did not supply stay ``None`` -- they are never
    invented or back-filled.
    """

    rank: int
    page_url: str
    title: str | None = None
    source: str | None = None  # platform/site label, e.g. "Reddit"
    image_url: str | None = None  # full-size image on the publisher's host
    thumbnail_url: str | None = None  # provider-cached copy
    platform: str | None = None  # normalised social platform, if recognised
    timestamp: str | None = None  # only if the provider actually returned one

    @property
    def is_social(self) -> bool:
        return self.platform is not None

    def to_json(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "page_url": self.page_url,
            "title": self.title,
            "source": self.source,
            "image_url": self.image_url,
            "thumbnail_url": self.thumbnail_url,
            "platform": self.platform,
            "timestamp": self.timestamp,
        }


@dataclass
class SearchResponse:
    """Everything a provider returned for one query."""

    provider: str
    results: list[SearchResult]
    query_method: str = "reverse_image"
    #: Provider-reported total, when it differs from len(results).
    raw_result_count: int | None = None
    #: Digest and size of the derived copy the provider was actually given, when
    #: the original had to be re-encoded to satisfy an upload limit. None when
    #: the provider was given a public URL instead of bytes.
    search_copy_sha256: str | None = None
    search_copy_bytes: int | None = None
    #: page_url -> reachability label ("live"/"login_wall"/"dead"/"unknown"),
    #: filled in during candidate verification. Audit/UI metadata only: it is not
    #: read by ``VerificationRecord.to_record()`` and never enters the hash.
    link_statuses: dict[str, str] = field(default_factory=dict)

    @property
    def count(self) -> int:
        return len(self.results)

    @property
    def social_results(self) -> list[SearchResult]:
        return [r for r in self.results if r.is_social]


# --- candidate verification --------------------------------------------------


@dataclass
class CandidateVerification:
    """A search hit whose image was downloaded and face-verified."""

    result: SearchResult
    image_sha256: str
    image_origin: ImageOrigin
    image_url_used: str
    image_bytes_len: int
    faces_detected: int
    best: FaceComparison
    #: Reachability of ``result.page_url`` for a human visitor, when probed
    #: ("live"/"login_wall"/"dead"/"unknown"). UI/audit metadata only -- not part
    #: of the hashed record (``to_record()`` never reads it).
    page_link_status: str | None = None

    @property
    def verified(self) -> bool:
        return self.best.is_match


@dataclass
class InputImage:
    """The input face image and the derived copy handed to the search provider."""

    path: str
    filename: str
    sha256: str  # digest of the ORIGINAL file bytes on disk
    width: int
    height: int
    bytes_len: int
    #: Providers cap upload size (SerpAPI: 500 KB), so the search copy is often
    #: a re-encoded downscale. Its digest is recorded separately -- the input
    #: fingerprint always refers to the original file.
    search_copy_sha256: str | None = None
    search_copy_bytes_len: int | None = None


# --- the hashed record -------------------------------------------------------


@dataclass
class VerificationRecord:
    """The canonical record that gets hashed and committed on-chain.

    Contains public URLs, a similarity score, and content digests. It contains
    no image bytes, no embeddings, and no personal information.
    """

    input_image: InputImage
    search: SearchResponse
    candidate: CandidateVerification
    detector_model: str
    encoder_model: str
    metric: str
    threshold: float
    review_threshold: float
    created_at: str

    def to_record(self) -> dict[str, Any]:
        """Build the exact dict that gets canonicalised and hashed.

        Keep this stable: changing it changes every hash. Bump SCHEMA_VERSION if
        the shape ever has to change.
        """
        c = self.candidate
        return {
            "schema_version": SCHEMA_VERSION,
            "created_at": self.created_at,
            "algorithm": {
                "detector": self.detector_model,
                "encoder": self.encoder_model,
                "metric": self.metric,
                "match_threshold": quantize(self.threshold),
                "review_threshold": quantize(self.review_threshold),
            },
            "input": {
                "filename": self.input_image.filename,
                "sha256": self.input_image.sha256,
                "width": self.input_image.width,
                "height": self.input_image.height,
                "search_copy_sha256": self.input_image.search_copy_sha256,
            },
            "search": {
                "provider": self.search.provider,
                "query_method": self.search.query_method,
                "result_count": self.search.count,
                "social_result_count": len(self.search.social_results),
                "candidate_rank": c.result.rank,
            },
            "candidate": {
                "page_url": c.result.page_url,
                "title": c.result.title,
                "source": c.result.source,
                "platform": c.result.platform,
                "image_url": c.image_url_used,
                "image_origin": c.image_origin,
                "image_sha256": c.image_sha256,
                "image_bytes": c.image_bytes_len,
                "faces_detected": c.faces_detected,
                "similarity": quantize(c.best.similarity),
                "l2_distance": quantize(c.best.l2_distance),
                "verdict": c.best.verdict,
            },
            "verified": c.verified,
        }


# --- on-chain + artifact -----------------------------------------------------


@dataclass
class ChainReceipt:
    """Result of committing a record hash to the chain."""

    network: str
    chain_id: int
    contract_address: str
    transaction_hash: str
    block_number: int
    gas_used: int
    submitter: str
    explorer_tx_url: str | None = None
    explorer_address_url: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "network": self.network,
            "chain_id": self.chain_id,
            "contract_address": self.contract_address,
            "transaction_hash": self.transaction_hash,
            "block_number": self.block_number,
            "gas_used": self.gas_used,
            "submitter": self.submitter,
            "explorer_tx_url": self.explorer_tx_url,
            "explorer_address_url": self.explorer_address_url,
        }


@dataclass
class OnChainRecord:
    """A record read back out of the contract."""

    record_hash: str
    block_timestamp: int
    submitter: str
    source: str
    candidate_url: str


@dataclass
class Artifact:
    """What lands in artifacts/latest_verification.json.

    ``record`` is stored verbatim: re-hashing that sub-object with the same
    canonicalisation must reproduce ``record_hash``.
    """

    record: dict[str, Any]
    record_hash: str
    blockchain: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "artifact_version": SCHEMA_VERSION,
            "record": self.record,
            "record_hash": self.record_hash,
            "blockchain": self.blockchain,
        }
