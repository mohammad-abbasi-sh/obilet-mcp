"""MCP server: unofficial read-only access to obilet.com bus & flight tickets."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

from . import http as _http
from . import journeys as _J

mcp = FastMCP("obilet-mcp")

INSTRUCTIONS = """\
Unofficial read-only MCP server for obilet.com, Türkiye's bus & flight
ticket search. Data comes from the site's JSON API (session-gated: an
HTML page is fetched first for cookies, then POSTs carry
X-Requested-With: XMLHttpRequest). Locations: POST /json/duraklar
(bus) or /json/ucak-duraklari (flight) with a query — bus location ids
are ints (Ankara 356, İstanbul Avrupa 349, İstanbul Anadolu 350),
flight location ids are strings like "250_0" (İstanbul Tümü),
"349_5157" (IST), "350_67" (SAW). Bus journeys: POST
/json/journeys/{origin}-{destination}/{YYYY-MM-DD} — returns all
journeys for the route (421 for İstanbul Avrupa -> Ankara on
2026-11-07) with partner, bus type, seats, departure/arrival,
duration, internet price (TRY), original price, partner rating
(0-10), stops and description. Journey detail: POST
/json/sefer-tam/{journeyId}. The same response carries a flightSummary
(flight count, min/max price, min/max duration, airlines with IATA
codes, direct-flight flag) — flight booking itself is NOT in v1
(the async flights endpoint returns 404/500, so individual flight
listings are summary-only). Prices are in Turkish
Lira (TRY) unless noted. Sorting/filtering is client-side: price_asc
(cheapest first), departure (earliest first), duration (shortest
first); filters: offset, after/before HH:MM departure window,
destination_terminal substring, min_seats, min_rating. Price stats
support sampling="first" (all journeys) or "day" (cheapest + one
service per 2-hour slot). Every tool output carries fetched_at (UTC),
source="obilet.com" and an unofficial-data disclaimer. Health:
obilet_health probes the homepage. Read-only, no login, no API key.
Transport uses curl-cffi TLS impersonation with a persistent session
that rotates profiles (chrome120 -> chrome131 -> safari17_0) on
403/429; requests are spaced ~0.8s apart. Built by Mohammad Abbasi
(mohammad-abbasi-sh) — Turkey MCP factory.\
"""

_SOURCE = "obilet.com"
_DISCLAIMER = "Unofficial read-only data from obilet.com; verify on the site before acting on it."


def _envelope() -> dict:
    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": _SOURCE,
        "disclaimer": _DISCLAIMER,
    }


def _ok(payload: dict) -> str:
    return json.dumps({**_envelope(), **payload}, ensure_ascii=False)


def _err(e: Exception) -> str:
    return json.dumps({**_envelope(), "error": str(e)}, ensure_ascii=False)


def _validate_limit(limit: int) -> int:
    if not 1 <= limit <= 24:
        raise ValueError("limit must be between 1 and 24")
    return limit


@mcp.tool()
def obilet_search_locations(query: str, kind: str = "bus") -> str:
    """Search obilet.com locations (cities, towns, airports) by name.
    query: e.g. "Ankara", "İstanbul", "İzmir". kind: "bus" (default,
    int ids) or "flight" (string ids like "250_0"). Returns id, name,
    display name and city id per match. Use the id in
    obilet_search_bus_journeys (bus) or obilet_flight_summary
    (flight)."""
    try:
        if not query or not query.strip():
            raise ValueError("query must not be empty")
        data = _http.fetch_locations(query.strip(), kind=kind)
        rows = _J.parse_locations(data)
    except (ValueError, _http.ObiletError) as e:
        return _err(e)
    return _ok(
        {"query": query.strip(), "kind": kind, "count": len(rows), "locations": rows}
    )


@mcp.tool()
def obilet_search_bus_journeys(
    origin_id: int,
    destination_id: int,
    date: str,
    limit: int = 10,
    sort: str = "price_asc",
    offset: int = 0,
    after: str | None = None,
    before: str | None = None,
    destination_terminal: str | None = None,
    min_seats: int | None = None,
    min_rating: float | None = None,
) -> str:
    """Bus journeys for one route + date. origin_id / destination_id:
    bus location ids from obilet_search_locations (e.g. İstanbul Avrupa
    349 -> Ankara 356). date: YYYY-MM-DD (e.g. "2026-11-07"). sort:
    "price_asc" (cheapest first, default), "departure" (earliest first),
    "duration" (shortest first). limit 1..24. Filters (client-side):
    offset (int >= 0, skip that many journeys after sorting),
    after / before ("HH:MM", 24h departure window, inclusive),
    destination_terminal (case-insensitive substring of the destination
    station/terminal name, e.g. "Aşti"), min_seats (available seats >=
    value), min_rating (partner rating 0-10 >= value). Returns journey
    id, partner, bus type, seats, origin/destination stations,
    departure/arrival, duration, price in TRY, partner rating (0-10)
    and stops per journey, plus the total count for the route and the
    filtered count."""
    try:
        _validate_limit(limit)
        _J.validate_date(date)
        _J.resolve_sort(sort)
        _J.validate_offset(offset)
        _J.validate_time(after, "after")
        _J.validate_time(before, "before")
        if after and before and after > before:
            raise ValueError(f"after ({after}) must not be later than before ({before})")
        _J.validate_min_seats(min_seats)
        _J.validate_min_rating(min_rating)
        data = _http.fetch_journeys(origin_id, destination_id, date)
        all_filtered = _J.parse_journeys(
            data,
            limit=100000,
            sort=sort,
            offset=0,
            after=after,
            before=before,
            destination_terminal=destination_terminal,
            min_seats=min_seats,
            min_rating=min_rating,
        )
        rows = all_filtered[offset : offset + limit]
    except (ValueError, _http.ObiletError) as e:
        return _err(e)
    return _ok(
        {
            "origin_id": origin_id,
            "destination_id": destination_id,
            "date": date,
            "sort": sort,
            "filters": {
                "offset": offset,
                "after": after,
                "before": before,
                "destination_terminal": destination_terminal,
                "min_seats": min_seats,
                "min_rating": min_rating,
            },
            "total": _J.total_journeys(data),
            "filtered_total": len(all_filtered),
            "count": len(rows),
            "journeys": rows,
        }
    )


@mcp.tool()
def obilet_journey_detail(journey_id: int) -> str:
    """Full detail of one bus journey: partner, bus type, seats,
    origin/destination stations, departure/arrival, duration, internet
    price and original price in TRY, service fee, partner rating,
    bus name, platform (peron), description and every stop with its
    time. journey_id: from obilet_search_bus_journeys."""
    try:
        data = _http.fetch_journey_detail(journey_id)
        detail = _J.parse_journey(data)
    except (ValueError, _http.ObiletError) as e:
        return _err(e)
    return _ok(detail)


@mcp.tool()
def obilet_price_stats(
    origin_id: int, destination_id: int, date: str, sampling: str = "first"
) -> str:
    """Price statistics for a bus route + date: journey count, min /
    median / mean / max ticket price in TRY across all journeys.
    origin_id / destination_id: bus location ids; date: YYYY-MM-DD.
    sampling: "first" (default — stats over all journeys) or "day"
    (day sampling: the cheapest journeys plus one service per 2-hour
    slot across the day, so the stats reflect the whole day instead of
    just the cheapest block)."""
    try:
        _J.validate_date(date)
        _J.validate_sampling(sampling)
        data = _http.fetch_journeys(origin_id, destination_id, date)
        rows = _J.parse_journeys(data, limit=100000, sort="price_asc")
        if sampling == "day":
            sampled = _J.sample_day_journeys(rows)
            stats = _J.price_stats(sampled)
            extra = {
                "sampling": "day",
                "sampled_count": len(sampled),
                "sampled_journey_ids": [
                    r.get("journey_id") for r in sampled if r.get("journey_id")
                ],
            }
        else:
            stats = _J.price_stats(rows)
            extra = {"sampling": "first"}
        stats = {**stats, **extra}
    except (ValueError, _http.ObiletError) as e:
        return _err(e)
    return _ok(
        {
            "origin_id": origin_id,
            "destination_id": destination_id,
            "date": date,
            **stats,
        }
    )


@mcp.tool()
def obilet_flight_summary(origin_id: int, destination_id: int, date: str) -> str:
    """Flight summary for a route + date (from the bus-journeys
    response): flight count, min/max price in TRY, min/max duration,
    first/last departure, direct-flight flag and airlines with IATA
    codes. origin_id / destination_id: bus location ids (the summary
    covers the same city pair); date: YYYY-MM-DD. Note: individual
    flight listings are NOT available in v1 (the async flights
    endpoint is broken on the site side)."""
    try:
        _J.validate_date(date)
        data = _http.fetch_journeys(origin_id, destination_id, date)
        summary = _J.parse_flight_summary(data)
    except (ValueError, _http.ObiletError) as e:
        return _err(e)
    return _ok(
        {
            "origin_id": origin_id,
            "destination_id": destination_id,
            "date": date,
            **summary,
        }
    )


@mcp.tool()
def obilet_health() -> str:
    """Health check: one polite probe of the obilet.com homepage.
    Returns status "ok" (reachable), "blocked" (403/429 bot wall or
    rate limit) or "error", plus the HTTP status, URL and detail.
    Use it to tell a live site problem apart from a bug in this
    server."""
    try:
        return _ok(_http.health_check())
    except Exception as e:
        return _err(e)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
