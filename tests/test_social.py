"""Tests for social platform detection from URLs."""

from app.search.social import platform_for_url, extract_profile_url, annotate, prioritise
from app.models import SearchResult


class TestPlatformForUrl:
    def test_twitter(self):
        assert platform_for_url("https://twitter.com/user/status/123") == "X"

    def test_x_dot_com(self):
        assert platform_for_url("https://x.com/user/status/123") == "X"

    def test_reddit(self):
        assert platform_for_url("https://www.reddit.com/r/test/comments/abc") == "Reddit"

    def test_instagram(self):
        assert platform_for_url("https://www.instagram.com/p/abc") == "Instagram"

    def test_facebook(self):
        assert platform_for_url("https://www.facebook.com/photo/123") == "Facebook"

    def test_youtube(self):
        assert platform_for_url("https://www.youtube.com/watch?v=abc") == "YouTube"

    def test_linkedin(self):
        assert platform_for_url("https://www.linkedin.com/in/someone") == "LinkedIn"

    def test_tiktok(self):
        assert platform_for_url("https://www.tiktok.com/@user/video/123") == "TikTok"

    def test_non_social(self):
        assert platform_for_url("https://example.com/page") is None

    def test_none_url(self):
        assert platform_for_url(None) is None

    def test_empty_url(self):
        assert platform_for_url("") is None

    def test_subdomain(self):
        assert platform_for_url("https://m.facebook.com/photo") == "Facebook"


class TestPrioritise:
    def test_social_first(self):
        results = [
            SearchResult(rank=1, page_url="https://example.com", platform=None),
            SearchResult(rank=2, page_url="https://x.com/post", platform="X"),
            SearchResult(rank=3, page_url="https://reddit.com/r/test", platform="Reddit"),
        ]
        ordered = prioritise(results)
        # Social results should come first
        assert ordered[0].platform is not None
        assert ordered[1].platform is not None
        assert ordered[2].platform is None

    def test_preserves_rank_within_group(self):
        results = [
            SearchResult(rank=3, page_url="https://x.com/a", platform="X"),
            SearchResult(rank=1, page_url="https://reddit.com/b", platform="Reddit"),
        ]
        ordered = prioritise(results)
        assert ordered[0].rank == 1  # Reddit rank 1
        assert ordered[1].rank == 3  # X rank 3


class TestExtractProfileUrl:
    def test_linkedin_profile(self):
        url = "https://www.linkedin.com/in/vairagya-32b8692b4"
        assert extract_profile_url(url) == "https://www.linkedin.com/in/vairagya-32b8692b4/"

    def test_linkedin_regional_profile(self):
        url = "https://in.linkedin.com/in/vairagya-32b8692b4/"
        assert extract_profile_url(url) == "https://www.linkedin.com/in/vairagya-32b8692b4/"

    def test_linkedin_post_with_slug(self):
        url = "https://www.linkedin.com/posts/vairagya-32b8692b4_after-school-coding-activity-7123456789012-abcd"
        assert extract_profile_url(url) == "https://www.linkedin.com/in/vairagya-32b8692b4/"

    def test_linkedin_feed_update_with_slug(self):
        url = "https://www.linkedin.com/feed/update/vairagya-32b8692b4_after-school-activity-123456"
        assert extract_profile_url(url) == "https://www.linkedin.com/in/vairagya-32b8692b4/"

    def test_x_status(self):
        url = "https://x.com/billgates/status/1234567890"
        assert extract_profile_url(url) == "https://x.com/billgates"

    def test_twitter_status(self):
        url = "https://twitter.com/satyanadella/status/9876543210"
        assert extract_profile_url(url) == "https://x.com/satyanadella"

    def test_reddit_user(self):
        url = "https://www.reddit.com/user/spez"
        assert extract_profile_url(url) == "https://www.reddit.com/user/spez"

    def test_non_social(self):
        assert extract_profile_url("https://www.nytimes.com/2025/01/01/tech.html") is None

    def test_empty_or_none(self):
        assert extract_profile_url(None) is None
        assert extract_profile_url("") is None
