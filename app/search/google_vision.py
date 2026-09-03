"""Google Cloud Vision WEB_DETECTION provider (fallback).

Exists so a live demo can survive the primary provider's monthly quota running
out. It queries a different vendor over a different index, and -- unlike Google
Lens via SerpAPI -- accepts the image bytes inline, so no upload step is needed.

  ``POST https://vision.googleapis.com/v1/images:annotate?key=KEY``
  ``{"requests":[{"image":{"content": <base64>},
                  "features":[{"type":"WEB_DETECTION","maxResults":50}]}]}``

``pagesWithMatchingImages`` is the block that matters: each entry is a web page
hosting a matching image, with the image URL nested inside it. That is exactly
the shape the pipeline needs -- a page to record and an image to face-verify.
"""

from __future__ import annotations

import base64
import html
import re

import requests

from ..errors import NoSearchResultsError, SearchAuthError, SearchError, SearchQuotaError
from ..imaging import prepare_search_copy
from ..models import SearchResponse, SearchResult
from . import social
from .base import ReverseImageSearchProvider, SearchQuery

_ENDPOINT = "https://vision.googleapis.com/v1/images:annotate"
_TIMEOUT = 90
_MAX_RESULTS = 50

_TAG_RE = re.compile(r"<[^>]+>")


class GoogleVisionWebDetectionProvider(ReverseImageSearchProvider):
    name = "google_vision_web_detection"
    description = "Google Cloud Vision WEB_DETECTION (cloud.google.com/vision)"
    # Vision accepts up to 20 MB inline, but 4 MB is ample for web detection and
    # keeps the request fast.
    max_upload_bytes = 4 * 1024 * 1024
    upload_formats = ("jpeg", "png", "webp")

    def __init__(self, api_key: str, *, session: requests.Session | None = None) -> None:
        self._api_key = api_key
        self._session = session or requests.Session()

    # -- credentials --------------------------------------------------------

    def check_credentials(self) -> str:
        """Probe with a 1x1 PNG: cheap, and it exercises real authentication."""
        pixel = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGP4"
            "//8/AAX+Av7czFnnAAAAAElFTkSuQmCC"
        )
        self._annotate(pixel)
        return "API key accepted by vision.googleapis.com"

    # -- search -------------------------------------------------------------

    def search(self, query: SearchQuery, *, on_progress=None) -> SearchResponse:
        copy = prepare_search_copy(
            query.image_path,
            query.image_bytes,
            max_bytes=self.max_upload_bytes,
            allow_original_formats=self.upload_formats,
        )
        if on_progress:
            on_progress(
                f"submitting {copy.size / 1024:.0f} KB inline to Vision WEB_DETECTION"
            )

        payload = self._annotate(copy.data)
        results = self._normalise(payload)

        if not results:
            raise NoSearchResultsError(
                "Vision WEB_DETECTION found no web pages hosting a matching image.",
                hint=(
                    "Reverse image search only finds content that is already indexed. "
                    "Try an image that exists publicly on the web."
                ),
            )

        return SearchResponse(
            provider=self.name,
            results=social.annotate(results),
            query_method="reverse_image_inline",
            raw_result_count=len(results),
            search_copy_sha256=copy.sha256,
            search_copy_bytes=copy.size,
        )

    # -- transport ----------------------------------------------------------

    def _annotate(self, image_bytes: bytes) -> dict:
        body = {
            "requests": [
                {
                    "image": {"content": base64.b64encode(image_bytes).decode("ascii")},
                    "features": [{"type": "WEB_DETECTION", "maxResults": _MAX_RESULTS}],
                }
            ]
        }
        try:
            resp = self._session.post(
                _ENDPOINT, params={"key": self._api_key}, json=body, timeout=_TIMEOUT
            )
        except requests.Timeout as exc:
            raise SearchError(
                f"Vision API did not respond within {_TIMEOUT}s."
            ) from exc
        except requests.RequestException as exc:
            raise SearchError(
                f"Vision API request failed: {type(exc).__name__}: {exc}"
            ) from exc

        try:
            data = resp.json()
        except ValueError:
            raise SearchError(
                f"Vision API returned unparseable data (HTTP {resp.status_code}): "
                f"{resp.text[:200]}"
            ) from None

        if error := data.get("error"):
            self._raise_for_error(resp.status_code, error)

        responses = data.get("responses") or []
        if not responses:
            raise SearchError("Vision API returned an empty responses array.")
        # Per-image errors are nested one level deeper than transport errors.
        if error := responses[0].get("error"):
            self._raise_for_error(resp.status_code, error)
        return responses[0]

    @staticmethod
    def _raise_for_error(status: int, error: dict) -> None:
        message = error.get("message", str(error))
        lowered = message.lower()
        if "api key not valid" in lowered or "api key" in lowered or status in (401, 403):
            raise SearchAuthError(
                f"Vision API rejected the credentials: {message}",
                hint=(
                    "Confirm the Vision API is enabled on the project and that "
                    "GOOGLE_VISION_API_KEY is correct:\n"
                    "    https://console.cloud.google.com/apis/library/vision.googleapis.com"
                ),
            )
        if "quota" in lowered or "billing" in lowered or status == 429:
            raise SearchQuotaError(
                f"Vision API quota or billing problem: {message}",
                hint="Check quotas and billing at https://console.cloud.google.com/",
            )
        raise SearchError(f"Vision API error (HTTP {status}): {message}")

    # -- normalisation ------------------------------------------------------

    @classmethod
    def _normalise(cls, response: dict) -> list[SearchResult]:
        web = response.get("webDetection") or {}
        results: list[SearchResult] = []
        seen: set[str] = set()

        for rank, page in enumerate(web.get("pagesWithMatchingImages") or [], start=1):
            url = page.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            # Prefer a full match; fall back to a partial match on the same page.
            images = (page.get("fullMatchingImages") or []) + (
                page.get("partialMatchingImages") or []
            )
            image_url = images[0].get("url") if images else None
            results.append(
                SearchResult(
                    rank=rank,
                    page_url=url,
                    title=cls._clean_title(page.get("pageTitle")),
                    # Vision does not label the platform; social.annotate() will
                    # derive it from the host. Left None rather than guessed.
                    source=None,
                    image_url=image_url,
                    thumbnail_url=None,
                )
            )
        return results

    @staticmethod
    def _clean_title(raw: str | None) -> str | None:
        """Vision returns HTML-escaped titles containing <b> highlight tags."""
        if not raw:
            return None
        return html.unescape(_TAG_RE.sub("", raw)).strip() or None
