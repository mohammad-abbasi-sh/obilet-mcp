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

Transport uses a persistent curl-cffi chrome120 session (cookies are
kept across calls), the same proven pattern as the other Turkey-factory
servers. Requests are kept gentle (one at a time, ~0.8s apart) and
read-only.
"""
from __future__ import annotations

import time

from curl_cffi import requests as _r

BASE = "https://www.obilet.com"
TIMEOUT = 60.0
MIN_INTERVAL = 0.8  # seconds between requests — be polite

_HEADERS = {
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}

_SESSION: _r.Session | None = None
_last_fetch = 0.0


class ObiletError(RuntimeError):
    pass


def _session() -> _r.Session:
    global _SESSION
    if _SESSION is None:
        _SESSION = _r.Session(impersonate="chrome120")
        _SESSION.headers.update(_HEADERS)
    return _SESSION


def _pace() -> None:
    global _last_fetch
    wait = MIN_INTERVAL - (time.monotonic() - _last_fetch)
    if wait > 0:
        time.sleep(wait)
    _last_fetch = time.monotonic()


def _prime(url: str) -> None:
    """GET an HTML page first so the session cookies (ob_Session,
    __cf_bm) are set; the same URL is then used as Referer."""
    _pace()
    try:
        resp = _session().get(url, timeout=TIMEOUT)
    except Exception as e:
        raise ObiletError(f"network error fetching {url}: {e}") from e
    if resp.status_code != 200:
        raise ObiletError(f"unexpected HTTP {resp.status_code} fetching {url}")


def _post_json(path: str, body: dict, referer: str) -> dict:
    """POST a JSON body to the obilet JSON API, return the parsed JSON."""
    _pace()
    headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Referer": referer,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    url = f"{BASE}{path}"
    try:
        resp = _session().post(url, json=body, headers=headers, timeout=TIMEOUT)
    except Exception as e:
        raise ObiletError(f"network error posting {url}: {e}") from e
    if resp.status_code == 404:
        raise ObiletError(f"endpoint not found (HTTP 404): {url}")
    if resp.status_code != 200:
        raise ObiletError(f"unexpected HTTP {resp.status_code} posting {url}")
    try:
        data = resp.json()
    except ValueError as e:
        raise ObiletError(f"non-JSON response from {url}") from e
    if not isinstance(data, dict):
        raise ObiletError(f"unexpected JSON shape from {url}")
    return data


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
