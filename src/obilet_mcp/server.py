"""MCP server: unofficial read-only access to obilet.com bus & flight tickets."""
from __future__ import annotations

import json

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
(the async flights endpoint returns 404/500). Prices are in Turkish
Lira (TRY) unless noted. Sorting is client-side: price_asc (cheapest
first), departure (earliest first), duration (shortest first).
Read-only, no login, no API key. Transport uses Chrome TLS
impersonation with a persistent session; requests are spaced ~0.8s
apart. Built by Mohammad Abbasi (mohammad-abbasi-sh) — https://almanibama.ir · https://mabbasi.ir — Turkey MCP
factory.\
"""


def _err(e: Exception) -> str:
    return json.dumps({"error": str(e)}, ensure_ascii=False)


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
    return json.dumps(
        {"query": query.strip(), "kind": kind, "count": len(rows), "locations": rows},
        ensure_ascii=False,
    )


@mcp.tool()
def obilet_search_bus_journeys(origin_id: int, destination_id: int, date: str, limit: int = 10, sort: str = "price_asc") -> str:
    """Bus journeys for one route + date. origin_id / destination_id:
    bus location ids from obilet_search_locations (e.g. İstanbul Avrupa
    349 -> Ankara 356). date: YYYY-MM-DD (e.g. "2026-11-07"). sort:
    "price_asc" (cheapest first, default), "departure" (earliest first),
    "duration" (shortest first). limit 1..24. Returns journey id,
    partner, bus type, seats, origin/destination stations,
    departure/arrival, duration, price in TRY, partner rating (0-10)
    and stops per journey, plus the total count for the route."""
    try:
        _validate_limit(limit)
        _J.validate_date(date)
        _J.resolve_sort(sort)
        data = _http.fetch_journeys(origin_id, destination_id, date)
        rows = _J.parse_journeys(data, limit=limit, sort=sort)
    except (ValueError, _http.ObiletError) as e:
        return _err(e)
    return json.dumps(
        {
            "origin_id": origin_id,
            "destination_id": destination_id,
            "date": date,
            "sort": sort,
            "total": _J.total_journeys(data),
            "count": len(rows),
            "journeys": rows,
        },
        ensure_ascii=False,
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
    return json.dumps(detail, ensure_ascii=False)


@mcp.tool()
def obilet_price_stats(origin_id: int, destination_id: int, date: str) -> str:
    """Price statistics for a bus route + date: journey count, min /
    median / mean / max ticket price in TRY across all journeys.
    origin_id / destination_id: bus location ids; date: YYYY-MM-DD."""
    try:
        _J.validate_date(date)
        data = _http.fetch_journeys(origin_id, destination_id, date)
        rows = _J.parse_journeys(data, limit=1000, sort="price_asc")
        stats = _J.price_stats(rows)
    except (ValueError, _http.ObiletError) as e:
        return _err(e)
    return json.dumps(
        {
            "origin_id": origin_id,
            "destination_id": destination_id,
            "date": date,
            **stats,
        },
        ensure_ascii=False,
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
    return json.dumps(
        {
            "origin_id": origin_id,
            "destination_id": destination_id,
            "date": date,
            **summary,
        },
        ensure_ascii=False,
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
