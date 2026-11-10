"""Offline tests for obilet_mcp.http — error taxonomy, profile
rotation, prime cache and health check, all against a fake session
(no network)."""
import unittest
from unittest import mock

from obilet_mcp import http as H


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class _FakeSession:
    created = []
    get_responses = []
    post_responses = []
    get_calls = []
    post_calls = []

    def __init__(self, impersonate=None):
        self.impersonate = impersonate
        self.headers = {}
        _FakeSession.created.append(impersonate)

    def close(self):
        pass

    def get(self, url, timeout=None):
        _FakeSession.get_calls.append(url)
        return _FakeSession.get_responses.pop(0)

    def post(self, url, json=None, headers=None, timeout=None):
        _FakeSession.post_calls.append(url)
        return _FakeSession.post_responses.pop(0)


class HttpTestCase(unittest.TestCase):
    def setUp(self):
        self._orig_interval = H.MIN_INTERVAL
        self._orig_backoff = H._RETRY_BACKOFF
        H.MIN_INTERVAL = 0
        H._RETRY_BACKOFF = 0
        H._SESSION = None
        H._profile_idx = 0
        H._prime_cache.clear()
        H._last_fetch = 0.0
        _FakeSession.created.clear()
        _FakeSession.get_responses.clear()
        _FakeSession.post_responses.clear()
        _FakeSession.get_calls.clear()
        _FakeSession.post_calls.clear()
        self._patcher = mock.patch.object(H._r, "Session", _FakeSession)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def tearDown(self):
        H.MIN_INTERVAL = self._orig_interval
        H._RETRY_BACKOFF = self._orig_backoff
        H._SESSION = None
        H._profile_idx = 0
        H._prime_cache.clear()


class TestTaxonomy(HttpTestCase):
    def test_403_message(self):
        err = H._http_error(403, "https://www.obilet.com/")
        self.assertIn("HTTP 403, bot wall", str(err))
        self.assertIn("try again later", str(err))

    def test_429_message(self):
        err = H._http_error(429, "https://www.obilet.com/")
        self.assertIn("HTTP 429", str(err))
        self.assertIn("rate-limited", str(err))

    def test_404_message(self):
        err = H._http_error(404, "https://www.obilet.com/x")
        self.assertIn("HTTP 404", str(err))
        self.assertIn("https://www.obilet.com/x", str(err))

    def test_other_message(self):
        self.assertIn("unexpected HTTP 500", str(H._http_error(500, "u")))


class TestPrimeRotation(HttpTestCase):
    def test_prime_rotates_on_403_then_succeeds(self):
        _FakeSession.get_responses.extend([_Resp(403), _Resp(200)])
        H._prime("https://www.obilet.com/")
        self.assertEqual(_FakeSession.created, ["chrome120", "chrome131"])
        self.assertEqual(H._profile_idx, 1)  # sticky: stays on chrome131

    def test_prime_raises_after_two_403s(self):
        _FakeSession.get_responses.extend([_Resp(403), _Resp(403)])
        with self.assertRaises(H.ObiletError) as ctx:
            H._prime("https://www.obilet.com/")
        self.assertIn("HTTP 403, bot wall", str(ctx.exception))

    def test_prime_cache_skips_repeat_get(self):
        _FakeSession.get_responses.extend([_Resp(200)])
        H._prime("https://www.obilet.com/")
        H._prime("https://www.obilet.com/")
        self.assertEqual(len(_FakeSession.get_calls), 1)

    def test_rotation_clears_prime_cache(self):
        _FakeSession.get_responses.extend([_Resp(200), _Resp(200)])
        H._prime("https://www.obilet.com/")
        H._prime("https://www.obilet.com/")  # cached, no GET
        self.assertEqual(len(_FakeSession.get_calls), 1)
        H._rotate_profile()
        H._prime("https://www.obilet.com/")  # cache cleared -> GET again
        self.assertEqual(len(_FakeSession.get_calls), 2)


class TestPostRetry(HttpTestCase):
    def test_post_rotates_reprimes_and_retries_on_429(self):
        _FakeSession.post_responses.extend([_Resp(429), _Resp(200, {"ok": True})])
        _FakeSession.get_responses.extend([_Resp(200)])  # re-prime after rotation
        out = H._post_json("/json/duraklar", {"query": "Ankara"}, "https://www.obilet.com/")
        self.assertEqual(out, {"ok": True})
        self.assertEqual(_FakeSession.created, ["chrome120", "chrome131"])
        self.assertEqual(_FakeSession.get_calls, ["https://www.obilet.com/"])

    def test_post_raises_after_two_429s(self):
        _FakeSession.post_responses.extend([_Resp(429), _Resp(429)])
        _FakeSession.get_responses.extend([_Resp(200)])
        with self.assertRaises(H.ObiletError) as ctx:
            H._post_json("/json/duraklar", {}, "https://www.obilet.com/")
        self.assertIn("HTTP 429", str(ctx.exception))

    def test_post_404_no_retry(self):
        _FakeSession.post_responses.extend([_Resp(404)])
        with self.assertRaises(H.ObiletError) as ctx:
            H._post_json("/json/duraklar", {}, "https://www.obilet.com/")
        self.assertIn("HTTP 404", str(ctx.exception))
        self.assertEqual(len(_FakeSession.post_calls), 1)


class TestHealthCheck(HttpTestCase):
    def test_ok(self):
        _FakeSession.get_responses.extend([_Resp(200)])
        hc = H.health_check()
        self.assertEqual(hc["status"], "ok")
        self.assertEqual(hc["http_status"], 200)
        self.assertEqual(hc["url"], "https://www.obilet.com/")

    def test_blocked(self):
        _FakeSession.get_responses.extend([_Resp(403)])
        hc = H.health_check()
        self.assertEqual(hc["status"], "blocked")
        self.assertEqual(hc["http_status"], 403)

    def test_error(self):
        _FakeSession.get_responses.extend([_Resp(500)])
        hc = H.health_check()
        self.assertEqual(hc["status"], "error")
        self.assertEqual(hc["http_status"], 500)


if __name__ == "__main__":
    unittest.main()
