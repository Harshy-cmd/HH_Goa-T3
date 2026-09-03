"""Download candidate images discovered by the search provider.

These URLs come from a third-party API and point at arbitrary hosts, so the
fetcher is deliberately defensive:

* only http/https
* refuses hosts that resolve to private, loopback, or link-local addresses
  (the URL is attacker-influenced data, so this closes the obvious SSRF path)
* caps the response body, streaming so an oversized body is abandoned rather
  than buffered
* requires an image content type
* no redirects to non-http(s) schemes

It fetches only publicly accessible URLs. It sends no credentials, solves no
CAPTCHAs, and does not attempt to reach anything behind a login.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

import requests

from ..errors import CandidateFetchError
from ..hashing import sha256_hex

#: Largest candidate image we will pull down.
MAX_IMAGE_BYTES = 12 * 1024 * 1024
_TIMEOUT = 45
_CHUNK = 1 << 15

#: Sent so hosts can identify the client. Some CDNs 403 an empty User-Agent.
_USER_AGENT = (
    "FaceIdChainVerifier/1.0 (+https://github.com/; reverse-image-search verification)"
)

_ALLOWED_SCHEMES = ("http", "https")
_IMAGE_CONTENT_TYPES = ("image/",)


@dataclass(frozen=True)
class FetchedImage:
    url: str
    data: bytes
    sha256: str
    content_type: str | None

    @property
    def size(self) -> int:
        return len(self.data)


def _assert_public_url(url: str) -> None:
    """Reject non-http(s) URLs and hosts that resolve to private ranges."""
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise CandidateFetchError(f"Refusing non-HTTP(S) candidate URL: {url[:120]}")
    host = parsed.hostname
    if not host:
        raise CandidateFetchError(f"Candidate URL has no host: {url[:120]}")

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise CandidateFetchError(f"Could not resolve {host}: {exc}") from exc

    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
        ):
            raise CandidateFetchError(
                f"Refusing to fetch {host}: resolves to non-public address {address}."
            )


def fetch_image(url: str, *, session: requests.Session | None = None) -> FetchedImage:
    """Download an image and fingerprint the exact bytes received.

    The SHA-256 is taken over the bytes as received, before any decoding, so the
    fingerprint is of the transferred artefact itself.
    """
    _assert_public_url(url)
    http = session or requests.Session()

    try:
        with http.get(
            url,
            timeout=_TIMEOUT,
            stream=True,
            allow_redirects=True,
            headers={"User-Agent": _USER_AGENT, "Accept": "image/*,*/*;q=0.8"},
        ) as resp:
            if resp.status_code == 403:
                raise CandidateFetchError(
                    f"Host refused the request (HTTP 403): {_short(url)}",
                    hint="Social CDNs commonly block hotlinking; the pipeline will try the next candidate.",
                )
            if resp.status_code == 404:
                raise CandidateFetchError(f"Candidate image is gone (HTTP 404): {_short(url)}")
            if resp.status_code >= 400:
                raise CandidateFetchError(
                    f"Candidate image request failed (HTTP {resp.status_code}): {_short(url)}"
                )

            content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
            if content_type and not content_type.startswith(_IMAGE_CONTENT_TYPES):
                raise CandidateFetchError(
                    f"Candidate URL is not an image (Content-Type: {content_type}): {_short(url)}"
                )

            declared = resp.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > MAX_IMAGE_BYTES:
                raise CandidateFetchError(
                    f"Candidate image is too large ({int(declared) / 1e6:.1f} MB, "
                    f"limit {MAX_IMAGE_BYTES / 1e6:.0f} MB): {_short(url)}"
                )

            buffer = bytearray()
            for chunk in resp.iter_content(_CHUNK):
                buffer.extend(chunk)
                if len(buffer) > MAX_IMAGE_BYTES:
                    raise CandidateFetchError(
                        f"Candidate image exceeded the {MAX_IMAGE_BYTES / 1e6:.0f} MB "
                        f"limit while downloading: {_short(url)}"
                    )
    except requests.Timeout as exc:
        raise CandidateFetchError(f"Timed out after {_TIMEOUT}s fetching {_short(url)}") from exc
    except requests.RequestException as exc:
        raise CandidateFetchError(
            f"Could not fetch {_short(url)}: {type(exc).__name__}: {exc}"
        ) from exc

    data = bytes(buffer)
    if not data:
        raise CandidateFetchError(f"Candidate image was empty: {_short(url)}")

    return FetchedImage(
        url=url, data=data, sha256=sha256_hex(data), content_type=content_type or None
    )


def _short(url: str, limit: int = 110) -> str:
    return url if len(url) <= limit else url[: limit - 3] + "..."
