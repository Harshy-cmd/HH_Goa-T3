"""Recognise and rank public social-media results.

The task asks for at least one real matching *social media* post, so results are
classified by host and social hits are tried first. Classification is purely a
label derived from the URL the provider returned -- it never changes, filters
out, or invents a result. Non-social results are kept and still reported.
"""

from __future__ import annotations

import re
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


def extract_profile_url(url: str | None) -> str | None:
    """Derive a direct user profile link from a social page or post URL, if identifiable.

    For LinkedIn posts (e.g. ``/posts/username_slug...`` or ``/feed/update/username_slug...``),
    extracts the username to provide the direct profile link ``https://www.linkedin.com/in/username/``.
    For X/Twitter, extracts the handle from status URLs.
    """
    if not url:
        return None

    # --- LinkedIn ----------------------------------------------------------
    # Direct profile: /in/{username}
    m = re.match(r"^https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/([a-zA-Z0-9\-_%]+)", url, re.IGNORECASE)
    if m:
        username = m.group(1).strip("/")
        return f"https://www.linkedin.com/in/{username}/"

    # Post or Feed update with username slug: /posts/{username}_{slug} or /feed/update/{username}_{slug}
    # LinkedIn conventions separate the member identifier from the post slug with an underscore '_'
    m = re.match(
        r"^https?://(?:[a-z]{2,3}\.)?linkedin\.com/(?:posts|feed/update)/([a-zA-Z0-9\-_%]+?)_[a-zA-Z0-9\-_%]+",
        url,
        re.IGNORECASE,
    )
    if m:
        username = m.group(1).strip("/")
        if username.lower() not in ("urn", "activity", "update", "feed"):
            return f"https://www.linkedin.com/in/{username}/"

    # --- X / Twitter -------------------------------------------------------
    # Status: /{username}/status/{id}
    m = re.match(
        r"^https?://(?:www\.)?(?:twitter\.com|x\.com)/([a-zA-Z0-9_]{1,25})/status/\d+",
        url,
        re.IGNORECASE,
    )
    if m:
        handle = m.group(1)
        if handle.lower() not in ("i", "home", "explore", "notifications", "search"):
            return f"https://x.com/{handle}"

    # --- Reddit ------------------------------------------------------------
    m = re.match(r"^https?://(?:www\.|old\.)?reddit\.com/u(?:ser)?/([a-zA-Z0-9_\-]+)", url, re.IGNORECASE)
    if m:
        return f"https://www.reddit.com/user/{m.group(1)}"

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


def prioritise(
    results: list[SearchResult],
    link_statuses: dict[str, str] | None = None,
) -> list[SearchResult]:
    """Order results for verification.

    Without ``link_statuses`` the order is the original one: social hits first,
    then provider rank. When a reachability map is supplied, candidates whose
    *page* link a human can actually open are tried first, so the link surfaced
    alongside a match is more likely to work:

        live+social -> live -> login-wall+social -> login-wall -> unprobed -> dead

    Provider rank breaks ties, so it is preserved as the secondary ordering and
    the artifact still records where the chosen candidate sat in the provider's
    own ranking. Nothing is ever filtered out -- ordering only.

    This does not change the face-match logic: the matcher still decides *whether*
    a candidate matches. It only changes the order in which candidates are tried
    (and the pipeline short-circuits on the first match).
    """
    if not link_statuses:
        return sorted(results, key=lambda r: (r.platform is None, r.rank))

    def tier(result: SearchResult) -> int:
        # LinkStatus is a str-enum, so "== 'live'" works for both enum and str.
        status = link_statuses.get(result.page_url) or "unknown"
        is_social = result.platform is not None
        if status == "live":
            return 0 if is_social else 1
        if status == "login_wall":
            return 2 if is_social else 3
        if status == "dead":
            return 5  # definitively broken: try last, but never drop
        return 4  # unknown / unprobed: ahead of known-dead

    return sorted(results, key=lambda r: (tier(r), r.rank))
