"""HTTP layer for obilet_mcp.

obilet.com exposes a JSON API on www.obilet.com, but it is session
gated: a GET of an HTML page must come first (it sets cookies incl.
`ob_Session` and `__cf_bm`), then POSTs go out with
`X-Requested-With: XMLHttpRequest`, `Referer` = that page and
`Accept: application/json`. Verified live 2026-11-06:
- GET https://www.obilet.com/ then POST /json/duraklar (bus locations)
  or /json/ucak-duraklari (flight locations) -> 200, real items.
- GET /seferler/{origin}-{dest}/{date} then POST
  /json/journeys/{origin}-{dest}/{date} with {} -> 200, 421 journeys
  for İstanbul Avrupa (349) -> Ankara (356) on 2026-11-07.
- POST /json/sefer-tam/{journeyId} with {} -> 200, full journey JSON.
- Plain GET to /json/duraklar returns 404; the async flights endpoint
  (/json/ucuslar/...) returns 404/500 — flights are summary-only in v1.

Transport uses a persistent curl-cffi session (cookies are kept
across calls), the same proven pattern as the other Turkey-factory
servers. Fingerprint rotation (2026-11-10 fix): profiles
chrome120 -> chrome131 -> safari17_0, sticky — the profile that last
succeeded is kept; on HTTP 403/429 the session is closed, rebuilt
with the next profile, re-primed (cookies are session-bound) and the
request is retried once before raising a specific error. Requests
are kept gentle (one at a time, ~0.8s apart) and read-only.

A short prime cache (120s per referer URL) skips repeat HTML primes
when the session is alive; any doubt re-primes.
"""
from __future__ import annotations

import time

from curl_cffi import requests as _r

BASE = "https://www.obilet.com"
TIMEOUT = 60.0
MIN_INTERVAL = 0.8  # seconds between requests — be polite

_PROFILES = ("chrome120", "chrome131", "safari17_0")
_MAX_ATTEMPTS = 2  # initial try + one retry with the next profile
_RETRY_BACKOFF = 1.0  # seconds before the retry
_PRIME_TTL = 120.0  # seconds a prime stays fresh for the same URL

_HEADERS = {
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}

_SESSION: _r.Session | None = None
_profile_idx = 0  # sticky: index into _PROFILES of the last good profile
_last_fetch = 0.0
_prime_cache: dict[str, float] = {}  # referer URL -> monotonic prime time


class ObiletError(RuntimeError):
    pass


def _session() -> _r.Session:
    global _SESSION
    if _SESSION is None:
        _SESSION = _r.Session(impersonate=_PROFILES[_profile_idx])
        _SESSION.headers.update(_HEADERS)
    return _SESSION


def _close_session() -> None:
    global _SESSION
    if _SESSION is not None:
        try:
            _SESSION.close()
        except Exception:
            pass
        _SESSION = None


def _rotate_profile() -> str:
    """Drop the current session and switch to the next profile.

    Cookies are session-bound, so the prime cache is cleared too —
    a rotated session MUST re-prime before its next POST.
    Returns the new profile name.
    """
    global _profile_idx
    _close_session()
    _profile_idx = (_profile_idx + 1) % len(_PROFILES)
    _prime_cache.clear()
    return _PROFILES[_profile_idx]


def _pace() -> None:
    global _last_fetch
    wait = MIN_INTERVAL - (time.monotonic() - _last_fetch)
    if wait > 0:
        time.sleep(wait)
    _last_fetch = time.monotonic()


def _http_error(status: int, url: str) -> ObiletError:
    """Actionable error taxonomy (403/429/404 distinguished)."""
    if status == 403:
        return ObiletError(
            "obilet.com refused the request (HTTP 403, bot wall) — try again later"
        )
    if status == 429:
        return ObiletError(
            "obilet.com rate-limited the request (HTTP 429) — try again later"
        )
    if status == 404:
        return ObiletError(f"page not found (HTTP 404): {url}")
    return ObiletError(f"unexpected HTTP {status} fetching {url}")


def _get_once(url: str):
    """One GET with the current session; network errors raise."""
    _pace()
    try:
        return _session().get(url, timeout=TIMEOUT)
    except Exception as e:
        raise ObiletError(f"network error fetching {url}: {e}") from e


def _prime(url: str) -> None:
    """GET an HTML page first so the session cookies (ob_Session,
    __cf_bm) are set; the same URL is then used as Referer.

    Skips the GET when the same URL was primed within the last 120s
    and the session is alive. On 403/429 rotates to the next profile
    and retries once, then raises the taxonomy error.
    """
    if _SESSION is not None and url in _prime_cache:
        if time.monotonic() - _prime_cache[url] < _PRIME_TTL:
            return
    for attempt in range(_MAX_ATTEMPTS):
        resp = _get_once(url)
        if resp.status_code == 200:
            _prime_cache[url] = time.monotonic()
            return
        if resp.status_code in (403, 429) and attempt + 1 < _MAX_ATTEMPTS:
            _rotate_profile()
            time.sleep(_RETRY_BACKOFF)
            continue
        raise _http_error(resp.status_code, url)


def _post_json(path: str, body: dict, referer: str) -> dict:
    """POST a JSON body to the obilet JSON API, return the parsed JSON.

    On 403/429 rotates to the next profile, re-primes (cookies are
    session-bound) and retries the POST once, then raises the
    taxonomy error.
    """
    url = f"{BASE}{path}"
    for attempt in range(_MAX_ATTEMPTS):
        _pace()
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Referer": referer,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        try:
            resp = _session().post(url, json=body, headers=headers, timeout=TIMEOUT)
        except Exception as e:
            raise ObiletError(f"network error posting {url}: {e}") from e
        if resp.status_code == 200:
            break
        if resp.status_code in (403, 429) and attempt + 1 < _MAX_ATTEMPTS:
            _rotate_profile()
            time.sleep(_RETRY_BACKOFF)
            _prime(referer)  # rotated session needs fresh cookies
            continue
        if resp.status_code == 404:
            raise ObiletError(f"endpoint not found (HTTP 404): {url}")
        raise _http_error(resp.status_code, url)
    try:
        data = resp.json()
    except ValueError as e:
        raise ObiletError(f"non-JSON response from {url}") from e
    if not isinstance(data, dict):
        raise ObiletError(f"unexpected JSON shape from {url}")
    return data


def health_check() -> dict:
    """One polite probe of the homepage.

    Returns status ok/blocked/error + http_status + url + detail.
    A single probe only — no rotation, no retry.
    """
    url = f"{BASE}/"
    try:
        resp = _get_once(url)
    except ObiletError as e:
        return {
            "status": "error",
            "http_status": None,
            "url": url,
            "detail": str(e),
        }
    if resp.status_code == 200:
        return {
            "status": "ok",
            "http_status": 200,
            "url": url,
            "detail": "homepage reachable",
        }
    if resp.status_code in (403, 429):
        return {
            "status": "blocked",
            "http_status": resp.status_code,
            "url": url,
            "detail": str(_http_error(resp.status_code, url)),
        }
    return {
        "status": "error",
        "http_status": resp.status_code,
        "url": url,
        "detail": str(_http_error(resp.status_code, url)),
    }


def fetch_locations(query: str, kind: str = "bus") -> dict:
    """Location autocomplete. kind: 'bus' or 'flight'."""
    if kind not in ("bus", "flight"):
        raise ObiletError("kind must be 'bus' or 'flight'")
    _prime(f"{BASE}/")
    path = "/json/duraklar" if kind == "bus" else "/json/ucak-duraklari"
    return _post_json(
        path, {"query": query, "page": 1, "element": "origin"}, f"{BASE}/"
    )


def fetch_journeys(origin_id: int, destination_id: int, date: str) -> dict:
    """All bus journeys for one route + date. date: YYYY-MM-DD."""
    sefer = f"{BASE}/seferler/{origin_id}-{destination_id}/{date}"
    _prime(sefer)
    return _post_json(f"/json/journeys/{origin_id}-{destination_id}/{date}", {}, sefer)


def fetch_journey_detail(journey_id: int) -> dict:
    """Full JSON of one journey (stops, prices, features)."""
    _prime(f"{BASE}/")
    return _post_json(f"/json/sefer-tam/{journey_id}", {}, f"{BASE}/")
