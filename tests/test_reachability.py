"""Link reachability classification + SSRF safety (Workstream 2).

All network access is mocked. Classification tests inject a fake session and
disable the SSRF guard; SSRF tests use literal private IPs (which resolve
without DNS) and assert the probe is never attempted.
"""

from __future__ import annotations

import pytest
import requests

from app.net.reachability import LinkStatus, check_link, check_links_concurrent

PUBLIC = "https://example.com/post/123"


class FakeResp:
    def __init__(self, code):
        self.status_code = code

    def close(self):
        pass


class FakeSession:
    """Returns a canned status per method, or raises a canned exception."""

    def __init__(self, *, head=None, get=None, raises=None):
        self._codes = {"HEAD": head, "GET": get}
        self._raises = raises
        self.calls = []

    def request(self, method, url, **kw):
        self.calls.append((method, url))
        if self._raises is not None:
            raise self._raises
        code = self._codes.get(method)
        if code is None:
            code = self._codes.get("GET") or self._codes.get("HEAD")
        return FakeResp(code)


@pytest.fixture
def no_ssrf(monkeypatch):
    """Treat every URL as public so classification is exercised in isolation."""
    monkeypatch.setattr("app.net.reachability._assert_public_url", lambda url: None)


class TestClassification:
    def test_200_is_live(self, no_ssrf):
        assert check_link(PUBLIC, session=FakeSession(head=200)) is LinkStatus.LIVE

    def test_redirect_is_live(self, no_ssrf):
        assert check_link(PUBLIC, session=FakeSession(head=301)) is LinkStatus.LIVE

    @pytest.mark.parametrize("code", [401, 403, 406, 429, 451, 999])
    def test_login_wall_codes(self, no_ssrf, code):
        status = check_link(PUBLIC, session=FakeSession(head=code, get=code))
        assert status is LinkStatus.LOGIN_WALL

    @pytest.mark.parametrize("code", [404, 410])
    def test_dead_codes(self, no_ssrf, code):
        assert check_link(PUBLIC, session=FakeSession(head=code)) is LinkStatus.DEAD

    def test_server_error_is_unknown(self, no_ssrf):
        assert check_link(PUBLIC, session=FakeSession(head=500, get=500)) is LinkStatus.UNKNOWN

    def test_head_blocked_then_get_ok_is_live(self, no_ssrf):
        # Hosts that 403 a HEAD but serve a GET should read as live.
        assert check_link(PUBLIC, session=FakeSession(head=403, get=200)) is LinkStatus.LIVE

    def test_timeout_is_dead(self, no_ssrf):
        assert check_link(PUBLIC, session=FakeSession(raises=requests.Timeout())) is LinkStatus.DEAD

    def test_connection_error_is_dead(self, no_ssrf):
        assert check_link(PUBLIC, session=FakeSession(raises=requests.ConnectionError())) is LinkStatus.DEAD

    def test_generic_request_error_is_unknown(self, no_ssrf):
        status = check_link(PUBLIC, session=FakeSession(raises=requests.RequestException()))
        assert status is LinkStatus.UNKNOWN


class TestSsrfSafety:
    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/admin",
            "http://10.0.0.5/x",
            "http://169.254.169.254/latest/meta-data/",  # cloud metadata endpoint
        ],
    )
    def test_private_urls_are_unknown_and_never_probed(self, url):
        sess = FakeSession(raises=AssertionError("must not probe a private URL"))
        assert check_link(url, session=sess) is LinkStatus.UNKNOWN
        assert sess.calls == []

    def test_non_http_scheme_is_unknown(self):
        sess = FakeSession(raises=AssertionError("must not probe"))
        assert check_link("ftp://example.com/x", session=sess) is LinkStatus.UNKNOWN
        assert sess.calls == []

    def test_empty_url_is_unknown(self):
        assert check_link("") is LinkStatus.UNKNOWN


class TestConcurrent:
    def test_empty_input(self):
        assert check_links_concurrent([]) == {}

    def test_dedupes_and_never_raises(self):
        urls = ["http://127.0.0.1/a", "http://127.0.0.1/a", "http://10.0.0.1/b", ""]
        out = check_links_concurrent(urls)
        assert set(out) == {"http://127.0.0.1/a", "http://10.0.0.1/b"}  # empties dropped, dupes collapsed
        assert all(v is LinkStatus.UNKNOWN for v in out.values())
