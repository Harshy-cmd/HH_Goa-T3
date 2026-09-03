"""SerpAPI Google Lens provider (primary).

Two-step flow, both documented by SerpAPI:

1. ``POST https://serpapi.com/image`` with the image as multipart field
   ``image`` -> returns an ``image_id`` (valid for 10 minutes, 500 KB cap,
   jpg/png/webp only).
2. ``GET https://serpapi.com/search?engine=google_lens&image_id=...`` -> returns
   ``visual_matches``, each carrying the page ``link``, a ``source`` platform
   label, and the publisher's full-size ``image`` URL.

The upload step is what lets us search a *local* file without publishing the
user's face photo to a third-party image host. If the caller already has a
public URL for the image, step 1 is skipped and ``url`` is passed instead.

Nothing here is cached or pre-seeded: every run performs a live HTTP request and
the candidate list is whatever Google Lens returns at that moment.
"""

from __future__ import annotations

import requests

from ..errors import NoSearchResultsError, SearchAuthError, SearchError, SearchQuotaError
from ..imaging import prepare_search_copy
from ..models import SearchResponse, SearchResult
from . import social
from .base import ReverseImageSearchProvider, SearchQuery

_UPLOAD_URL = "https://serpapi.com/image"
_SEARCH_URL = "https://serpapi.com/search"
_ACCOUNT_URL = "https://serpapi.com/account"

_UPLOAD_TIMEOUT = 60
_SEARCH_TIMEOUT = 90


class SerpApiGoogleLensProvider(ReverseImageSearchProvider):
    name = "serpapi_google_lens"
    description = "Google Lens via SerpAPI (serpapi.com/google-lens-api)"
    max_upload_bytes = 500 * 1024  # documented SerpAPI Image API limit
    upload_formats = ("jpeg", "png", "webp")

    def __init__(self, api_key: str, *, session: requests.Session | None = None) -> None:
        self._api_key = api_key
        self._session = session or requests.Session()

    # -- credentials --------------------------------------------------------

    def check_credentials(self) -> str:
        try:
            resp = self._session.get(
                _ACCOUNT_URL, params={"api_key": self._api_key}, timeout=30
            )
        except requests.RequestException as exc:
            raise SearchError(
                f"Could not reach serpapi.com: {type(exc).__name__}: {exc}",
                hint="Check your internet connection.",
            ) from exc

        if resp.status_code in (401, 403):
            raise SearchAuthError(
                "SerpAPI rejected the API key.",
                hint="Check SERPAPI_API_KEY in .env against https://serpapi.com/manage-api-key",
            )
        try:
            data = resp.json()
        except ValueError:
            raise SearchError(
                f"SerpAPI account endpoint returned unparseable data (HTTP {resp.status_code})."
            ) from None

        left = data.get("total_searches_left")
        used = data.get("this_month_usage")
        plan = data.get("plan_name") or data.get("plan_id") or "unknown plan"
        if left is not None and int(left) <= 0:
            raise SearchQuotaError(
                f"SerpAPI key is valid but has no searches left this month ({plan}).",
                hint=(
                    "Wait for the monthly reset, upgrade the plan, or switch to the "
                    "fallback provider with SEARCH_PROVIDER=google_vision."
                ),
            )
        return f"{plan}, {left} searches left (used {used} this month)"

    # -- search -------------------------------------------------------------

    def search(self, query: SearchQuery, *, on_progress=None) -> SearchResponse:
        params = {
            "engine": "google_lens",
            "api_key": self._api_key,
            "hl": "en",
            "country": "us",
            # Google Lens caches identical queries for an hour; the demo must
            # show a genuinely live lookup every run.
            "no_cache": "true",
        }

        if query.public_image_url:
            if on_progress:
                on_progress(f"searching by public URL: {query.public_image_url}")
            params["url"] = query.public_image_url
            copy_sha = None
            copy_len = None
        else:
            copy = prepare_search_copy(
                query.image_path,
                query.image_bytes,
                max_bytes=self.max_upload_bytes,
                allow_original_formats=self.upload_formats,
            )
            if on_progress:
                detail = (
                    "original file"
                    if copy.is_original
                    else f"re-encoded to {copy.width}x{copy.height} JPEG"
                )
                on_progress(
                    f"uploading search copy ({copy.size / 1024:.0f} KB, {detail})"
                )
            params["image_id"] = self._upload(copy)
            copy_sha = copy.sha256
            copy_len = copy.size

        if on_progress:
            on_progress("querying Google Lens visual matches")
        payload = self._request_search(params)
        results = self._normalise(payload)

        if not results:
            raise NoSearchResultsError(
                "Google Lens returned no visual matches for this image.",
                hint=(
                    "Reverse image search only finds content that is already indexed. "
                    "Try an image that exists publicly on the web (a profile photo "
                    "that has been posted, for example)."
                ),
            )

        return SearchResponse(
            provider=self.name,
            results=social.annotate(results),
            query_method=(
                "reverse_image_url" if query.public_image_url else "reverse_image_upload"
            ),
            raw_result_count=len(results),
            search_copy_sha256=copy_sha,
            search_copy_bytes=copy_len,
        )

    # -- steps --------------------------------------------------------------

    def _upload(self, copy) -> str:
        """Step 1: upload the image, return its ``image_id``."""
        try:
            resp = self._session.post(
                _UPLOAD_URL,
                files={"image": (copy.filename, copy.data, copy.mime_type)},
                data={"api_key": self._api_key},
                timeout=_UPLOAD_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise SearchError(
                f"Uploading the image to SerpAPI failed: {type(exc).__name__}: {exc}",
                hint="Check your internet connection and retry.",
            ) from exc

        if resp.status_code in (401, 403):
            raise SearchAuthError(
                "SerpAPI rejected the API key during image upload.",
                hint="Check SERPAPI_API_KEY in .env.",
            )

        try:
            data = resp.json()
        except ValueError:
            raise SearchError(
                f"SerpAPI image upload returned a non-JSON response "
                f"(HTTP {resp.status_code}): {resp.text[:200]}"
            ) from None

        if error := data.get("error"):
            raise SearchError(f"SerpAPI rejected the uploaded image: {error}")

        image_id = data.get("image_id")
        if not image_id:
            raise SearchError(
                f"SerpAPI image upload succeeded but returned no image_id: {data}"
            )
        return image_id

    def _request_search(self, params: dict) -> dict:
        """Step 2: run the Google Lens search."""
        try:
            resp = self._session.get(_SEARCH_URL, params=params, timeout=_SEARCH_TIMEOUT)
        except requests.Timeout as exc:
            raise SearchError(
                f"SerpAPI did not respond within {_SEARCH_TIMEOUT}s.",
                hint="Retry; Google Lens queries occasionally run long.",
            ) from exc
        except requests.RequestException as exc:
            raise SearchError(
                f"SerpAPI request failed: {type(exc).__name__}: {exc}"
            ) from exc

        if resp.status_code in (401, 403):
            raise SearchAuthError(
                "SerpAPI rejected the API key.",
                hint="Check SERPAPI_API_KEY in .env.",
            )
        if resp.status_code == 429:
            raise SearchQuotaError(
                "SerpAPI rate limit or monthly quota exceeded (HTTP 429).",
                hint="Check https://serpapi.com/dashboard, or set SEARCH_PROVIDER=google_vision.",
            )

        try:
            data = resp.json()
        except ValueError:
            raise SearchError(
                f"SerpAPI returned unparseable data (HTTP {resp.status_code}): "
                f"{resp.text[:200]}"
            ) from None

        if error := data.get("error"):
            lowered = str(error).lower()
            if "run out of searches" in lowered or "quota" in lowered:
                raise SearchQuotaError(f"SerpAPI: {error}")
            if "invalid api key" in lowered or "api_key" in lowered:
                raise SearchAuthError(f"SerpAPI: {error}")
            raise SearchError(f"SerpAPI: {error}")

        status = (data.get("search_metadata") or {}).get("status")
        if status and status.lower() not in ("success", "cached"):
            raise SearchError(f"SerpAPI search did not succeed (status: {status}).")
        return data

    # -- normalisation ------------------------------------------------------

    @staticmethod
    def _normalise(payload: dict) -> list[SearchResult]:
        """Flatten Google Lens visual matches into SearchResult objects.

        ``exact_matches`` is merged in when present: those are pages hosting the
        same image, which is exactly what we want to face-verify, and Lens
        sometimes returns them in a separate block from ``visual_matches``.
        """
        results: list[SearchResult] = []
        seen: set[str] = set()
        rank = 0

        for block in ("exact_matches", "visual_matches"):
            for item in payload.get(block) or []:
                link = item.get("link")
                if not link or link in seen:
                    continue
                seen.add(link)
                rank += 1
                results.append(
                    SearchResult(
                        rank=rank,
                        page_url=link,
                        title=item.get("title"),
                        source=item.get("source"),
                        image_url=item.get("image"),
                        thumbnail_url=item.get("thumbnail"),
                        timestamp=item.get("date"),
                    )
                )
        return results
