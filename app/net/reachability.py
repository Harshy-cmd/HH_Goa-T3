"""Classify whether a candidate's *source page* is actually reachable.

Reverse-image-search providers return the page a matched image was found on.
Those page URLs frequently 404 or sit behind a login wall even when the matched
*image* still renders fine -- so reporting the raw page link makes a correct
match look broken (the recurring "invalid post link" / 404 complaint). This
module probes each page URL and labels it, so the pipeline can:

* prefer live, social candidates when ordering what to verify, and
* surface the verified image URL (which reliably renders the matched face) as
  the primary evidence, with the page link shown but honestly labelled.

It never changes *which* candidate matches -- only ordering and labelling. Probes
are SSRF-safe (they reuse :func:`app.net.fetch._assert_public_url`) and use a
browser-like User-Agent so the result reflects what a human visitor would see,
not what an anonymous scraper hits.
"""

from __future__ import annotations

import concurrent.futures
from enum import Enum

import requests

from ..errors import CandidateFetchError
from .fetch import _assert_public_url


class LinkStatus(str, Enum):
    """Reachability classification for a page URL."""

    LIVE = "live"  # 2xx/3xx: loads for anyone
    LOGIN_WALL = "login_wall"  # blocks anonymous requests but works for a signed-in human
    DEAD = "dead"  # 404/410, DNS failure, or timeout: effectively gone
    UNKNOWN = "unknown"  # could not classify (e.g. server error, SSRF-blocked)

    @property
    def label(self) -> str:
        """Short human-facing label for the UI."""
        return {
            LinkStatus.LIVE: "live",
            LinkStatus.LOGIN_WALL: "requires login",
            LinkStatus.DEAD: "unavailable",
            LinkStatus.UNKNOWN: "unverified",
        }[self]

    @property
    def usable(self) -> bool:
        """True when a human could plausibly open the link."""
        return self in (LinkStatus.LIVE, LinkStatus.LOGIN_WALL)


_TIMEOUT = 8
#: A real browser UA. Many hosts 403 an unknown/bot UA but serve a browser, so
#: this predicts the human experience rather than the scraper experience.
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

#: A signed-out human still reaches these (login/consent/anti-bot walls), so they
#: are "usable", not "dead".
_LOGIN_WALL_CODES = frozenset({401, 403, 406, 429, 451, 999})
_DEAD_CODES = frozenset({404, 410})


def _probe(http: requests.Session, method: str, url: str) -> LinkStatus:
    try:
        resp = http.request(
            method,
            url,
            timeout=_TIMEOUT,
            allow_redirects=True,
            headers=_HEADERS,
            stream=(method == "GET"),
        )
    except (requests.Timeout, requests.ConnectionError):
        return LinkStatus.DEAD
    except requests.RequestException:
        return LinkStatus.UNKNOWN

    try:
        code = resp.status_code
    finally:
        resp.close()

    if code in _DEAD_CODES:
        return LinkStatus.DEAD
    if code in _LOGIN_WALL_CODES:
        return LinkStatus.LOGIN_WALL
    if 200 <= code < 400:
        return LinkStatus.LIVE
    return LinkStatus.UNKNOWN


def check_link(url: str, *, session: requests.Session | None = None) -> LinkStatus:
    """Probe ``url`` and classify its reachability for a human visitor.

    Tries a cheap HEAD first, then a streamed GET when HEAD is inconclusive
    (many servers mishandle or block HEAD). A GET that succeeds where HEAD was
    blocked means the page is genuinely live.
    """
    if not url:
        return LinkStatus.UNKNOWN
    try:
        _assert_public_url(url)
    except CandidateFetchError:
        # Non-public / unresolvable / non-HTTP: we won't (and can't safely) probe.
        return LinkStatus.UNKNOWN

    http = session or requests.Session()
    status = _probe(http, "HEAD", url)
    if status in (LinkStatus.UNKNOWN, LinkStatus.LOGIN_WALL):
        get_status = _probe(http, "GET", url)
        if get_status is not LinkStatus.UNKNOWN:
            status = get_status
    return status


def check_links_concurrent(
    urls: list[str], *, max_workers: int = 6
) -> dict[str, LinkStatus]:
    """Probe several URLs concurrently. Returns ``{url: LinkStatus}``.

    Each probe uses its own session (``requests.Session`` is not thread-safe).
    Duplicate/empty URLs are collapsed. Never raises: a failed probe is UNKNOWN.
    """
    unique = [u for u in dict.fromkeys(urls) if u]
    if not unique:
        return {}

    results: dict[str, LinkStatus] = {}
    workers = min(max_workers, len(unique))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(check_link, u): u for u in unique}
        for fut in concurrent.futures.as_completed(futures):
            url = futures[fut]
            try:
                results[url] = fut.result()
            except Exception:  # noqa: BLE001 - never let one bad probe break the batch
                results[url] = LinkStatus.UNKNOWN
    return results
