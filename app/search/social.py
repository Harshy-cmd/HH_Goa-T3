"""Recognise and rank public social-media results.

The task asks for at least one real matching *social media* post, so results are
classified by host and social hits are tried first. Classification is purely a
label derived from the URL the provider returned -- it never changes, filters
out, or invents a result. Non-social results are kept and still reported.
"""

from __future__ import annotations

from urllib.parse import urlparse

from .base import SearchResult

#: Registrable domain -> display name. Matched against the host and its parent
#: domains, so "www.reddit.com" and "old.reddit.com" both resolve to Reddit.
_PLATFORMS: dict[str, str] = {
    "x.com": "X",
    "twitter.com": "X",
    "t.co": "X",
    "instagram.com": "Instagram",
    "facebook.com": "Facebook",
    "fb.com": "Facebook",
    "fb.watch": "Facebook",
    "reddit.com": "Reddit",
    "redd.it": "Reddit",
    "linkedin.com": "LinkedIn",
    "tiktok.com": "TikTok",
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "threads.net": "Threads",
    "threads.com": "Threads",
    "bsky.app": "Bluesky",
    "mastodon.social": "Mastodon",
    "tumblr.com": "Tumblr",
    "pinterest.com": "Pinterest",
    "flickr.com": "Flickr",
    "vk.com": "VK",
    "weibo.com": "Weibo",
    "snapchat.com": "Snapchat",
    "quora.com": "Quora",
}


def platform_for_url(url: str | None) -> str | None:
    """Return the social platform for ``url``, or None if it is not one."""
    if not url:
        return None
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return None
    if not host:
        return None

    host = host.removeprefix("www.")
    parts = host.split(".")
    # Check the host and every parent domain: "m.facebook.com" -> "facebook.com".
    for i in range(len(parts) - 1):
        candidate = ".".join(parts[i:])
        if candidate in _PLATFORMS:
            return _PLATFORMS[candidate]
    # Regional variants such as pinterest.co.uk or facebook.com.br.
    if parts[0] == "pinterest":
        return "Pinterest"
    return None


def annotate(results: list[SearchResult]) -> list[SearchResult]:
    """Fill in the ``platform`` field for each result."""
    return [
        (
            result
            if result.platform
            else _with_platform(result, platform_for_url(result.page_url))
        )
        for result in results
    ]


def _with_platform(result: SearchResult, platform: str | None) -> SearchResult:
    if platform is None:
        return result
    return SearchResult(
        rank=result.rank,
        page_url=result.page_url,
        title=result.title,
        source=result.source,
        image_url=result.image_url,
        thumbnail_url=result.thumbnail_url,
        platform=platform,
        timestamp=result.timestamp,
    )


def prioritise(results: list[SearchResult]) -> list[SearchResult]:
    """Order results for verification: social first, then provider rank.

    Provider rank is preserved on each result, so the artifact records where the
    chosen candidate actually appeared in the provider's own ordering.
    """
    return sorted(results, key=lambda r: (r.platform is None, r.rank))
