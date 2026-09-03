"""The reverse-image-search provider interface.

Every provider takes the input image and returns normalised
:class:`~app.models.SearchResult` objects. Nothing downstream of this module
knows which provider ran, which is what keeps the rest of the pipeline honest:
the candidate URL can only ever come from a live provider response.

Two providers exist, and the second is not decoration -- it is what makes a live
demo survivable if the primary's monthly quota runs out mid-recording.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from ..models import SearchResponse, SearchResult

__all__ = ["ReverseImageSearchProvider", "SearchQuery", "SearchResult", "SearchResponse"]


@dataclass(frozen=True)
class SearchQuery:
    """What the pipeline hands a provider."""

    #: Path of the original image on disk (used for naming/diagnostics only).
    image_path: Path
    #: Original file bytes as read from disk.
    image_bytes: bytes
    #: An already-public URL for the same image, when the user supplied one.
    #: Providers that can search by URL prefer this and skip uploading.
    public_image_url: str | None = None


class ReverseImageSearchProvider(ABC):
    """A genuine reverse-image-search backend."""

    #: Stable identifier recorded in the hashed record.
    name: str
    #: Human-readable description for `python -m app doctor`.
    description: str
    #: Largest upload the provider accepts, in bytes.
    max_upload_bytes: int
    #: Image formats the provider accepts for upload.
    upload_formats: tuple[str, ...] = ("jpeg", "png", "webp")

    @abstractmethod
    def search(self, query: SearchQuery, *, on_progress=None) -> SearchResponse:
        """Run a reverse image search and return normalised results.

        Must raise a :class:`~app.errors.SearchError` subclass on failure. A
        provider must never return placeholder, cached, or synthesised results.
        """

    @abstractmethod
    def check_credentials(self) -> str:
        """Verify credentials against the live API.

        Returns a short human-readable status line. Raises
        :class:`~app.errors.SearchAuthError` if the credentials are rejected.
        """
