"""Stdlib parsing for obilet.com JSON API responses.

Verified live 2026-11-06 against real responses:
- Locations (POST /json/duraklar or /json/ucak-duraklari):
  {items: [{id, text, display, ...}]}. Bus ids are ints (Ankara 356,
  İstanbul Avrupa 349, İstanbul Anadolu 350); flight ids are strings
  like "250_0" (İstanbul Tümü), "349_5157" (IST), "350_67" (SAW).
- Journeys (POST /json/journeys/{o}-{d}/{date}): {journeys: [421 items
  for 349->356 on 2026-11-07], flightSummary: {...}, seaSummary: {...}}.
  Each journey: id, partner-id, partner-name, route-id, bus-type
  ("2+1"), total-seats, available-seats, partner-rating (8.637/10),
  partner-route-rating, origin-location / destination-location names,
  and a nested `journey` object: kind, code, origin/destination station
  names, departure/arrival ("2026-11-07T09:00:00"), duration
  ("07:30:00"), currency ("TRY"), original-price (700.0),
  internet-price (539.0), sorting-price, bus-name, peron-no,
  service-fee, description, stops[] (name, time, is-origin,
  is-destination).
- Journey detail (POST /json/sefer-tam/{id}): the same journey object,
  full (9002 bytes for id 1432053091).
- flightSummary: {journey-count: 26, has-direct: true, prices: {Key:
  1461.99, Value: 7399.34} (min/max TRY), durations: {Key: "01:00:00",
  Value: "12:05:00"}, departures: {Key: "00:05:00", Value: "23:30:00"},
  airlines: [{name: "Pegasus", iata-code: "PC"}, {name: "AJet",
  iata-code: "VF"}, {name: "THY", iata-code: "TK"}]}.
"""
from __future__ import annotations

import re
import statistics
from datetime import datetime

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

SORTS = ("price_asc", "departure", "duration")
SAMPLINGS = ("first", "day")


def validate_date(date: str) -> str:
    if not _DATE_RE.match(date or ""):
        raise ValueError(f"date must be YYYY-MM-DD, got {date!r}")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError as e:
        raise ValueError(f"invalid date {date!r}") from e
    return date


def resolve_sort(sort: str) -> str:
    if sort not in SORTS:
        raise ValueError(
            f"unknown sort {sort!r} (expected one of: {', '.join(SORTS)})"
        )
    return sort


def validate_time(value: str | None, name: str) -> str | None:
    """HH:MM (24h) or None; raises ValueError on a bad value."""
    if value is None:
        return None
    if not isinstance(value, str) or not _TIME_RE.match(value):
        raise ValueError(f"{name} must be HH:MM (24h), got {value!r}")
    return value


def validate_offset(offset: int) -> int:
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError(f"offset must be an integer >= 0, got {offset!r}")
    return offset


def validate_min_seats(min_seats: int | None) -> int | None:
    if min_seats is None:
        return None
    if isinstance(min_seats, bool) or not isinstance(min_seats, int) or min_seats < 0:
        raise ValueError(f"min_seats must be an integer >= 0, got {min_seats!r}")
    return min_seats


def validate_min_rating(min_rating: float | None) -> float | None:
    if min_rating is None:
        return None
    if isinstance(min_rating, bool) or not isinstance(min_rating, (int, float)):
        raise ValueError(f"min_rating must be a number between 0 and 10, got {min_rating!r}")
    if not 0 <= min_rating <= 10:
        raise ValueError(f"min_rating must be between 0 and 10, got {min_rating!r}")
    return float(min_rating)


def validate_sampling(sampling: str) -> str:
    if sampling not in SAMPLINGS:
        raise ValueError(
            f"unknown sampling {sampling!r} (expected one of: {', '.join(SAMPLINGS)})"
        )
    return sampling


def _departure_hhmm(row: dict) -> str | None:
    """'2026-11-07T09:00:00' -> '09:00' (None if unparseable)."""
    dep = row.get("departure") or ""
    if "T" in dep:
        hhmm = dep.split("T", 1)[1][:5]
        return hhmm if _TIME_RE.match(hhmm) else None
    return None


def filter_journeys(
    rows: list[dict],
    after: str | None = None,
    before: str | None = None,
    destination_terminal: str | None = None,
    min_seats: int | None = None,
    min_rating: float | None = None,
) -> list[dict]:
    """Client-side filters over parsed journey rows (all optional).

    after/before: HH:MM departure window (inclusive). destination_terminal:
    case-insensitive substring match on the destination station/terminal
    name. min_seats: available_seats >= value. min_rating: partner_rating
    >= value (journeys with no rating are excluded when set).
    """
    after = validate_time(after, "after")
    before = validate_time(before, "before")
    if after and before and after > before:
        raise ValueError(f"after ({after}) must not be later than before ({before})")
    min_seats = validate_min_seats(min_seats)
    min_rating = validate_min_rating(min_rating)
    out: list[dict] = []
    for r in rows:
        if after or before:
            hhmm = _departure_hhmm(r)
            if hhmm is None:
                continue
            if after and hhmm < after:
                continue
            if before and hhmm > before:
                continue
        if destination_terminal:
            dest = (r.get("destination") or "").lower()
            if destination_terminal.lower() not in dest:
                continue
        if min_seats is not None:
            seats = r.get("available_seats")
            if not isinstance(seats, (int, float)) or seats < min_seats:
                continue
        if min_rating is not None:
            rating = r.get("partner_rating")
            if not isinstance(rating, (int, float)) or rating < min_rating:
                continue
        out.append(r)
    return out


def sample_day_journeys(rows: list[dict], cheapest_n: int = 5) -> list[dict]:
    """Day sampling: the cheapest journeys plus one service per 2-hour
    slot across the day (earliest departure in each 00–02, 02–04, …,
    22–24 slot). Deduplicated by journey_id; cheapest first, then the
    slot picks in time order."""
    if not rows:
        return []
    by_price = sorted(
        rows, key=lambda r: (r.get("price_try") is None, r.get("price_try") or 0)
    )
    picked: list[dict] = []
    seen: set = set()

    def _add(row: dict) -> None:
        key = row.get("journey_id", id(row))
        if key not in seen:
            seen.add(key)
            picked.append(row)

    for r in by_price[:cheapest_n]:
        _add(r)
    by_departure = sorted(rows, key=lambda r: r.get("departure") or "")
    for slot_start in range(0, 24, 2):
        lo = f"{slot_start:02d}:00"
        hi = f"{slot_start + 2:02d}:00"
        for r in by_departure:
            hhmm = _departure_hhmm(r)
            if hhmm is None:
                continue
            if lo <= hhmm < hi or (slot_start == 22 and hhmm == "24:00"):
                _add(r)
                break
    return picked


# ---------------------------------------------------------------- locations

def parse_locations(data: dict) -> list[dict]:
    """Location autocomplete items -> clean rows."""
    out: list[dict] = []
    for item in data.get("items") or []:
        if not isinstance(item, dict):
            continue
        row: dict = {
            "id": item.get("id"),
            "name": item.get("text"),
            "display": item.get("display"),
        }
        if item.get("locationName") and item.get("locationName") != item.get("text"):
            row["location"] = item["locationName"]
        if item.get("cityId") is not None:
            row["city_id"] = item["cityId"]
        if item.get("isDomestic") is not None:
            row["is_domestic"] = item["isDomestic"]
        out.append({k: v for k, v in row.items() if v is not None})
    return out


# ---------------------------------------------------------------- journeys

def _stops(journey: dict) -> list[dict]:
    out: list[dict] = []
    for s in journey.get("stops") or []:
        if not isinstance(s, dict):
            continue
        out.append(
            {
                "name": s.get("name"),
                "time": s.get("time"),
                "is_origin": bool(s.get("is-origin")),
                "is_destination": bool(s.get("is-destination")),
            }
        )
    return out


def parse_journey(raw: dict) -> dict:
    """One raw journey object -> clean row."""
    j = raw.get("journey") or {}
    rating = raw.get("partner-rating")
    route_rating = raw.get("partner-route-rating")
    row: dict = {
        "journey_id": raw.get("id"),
        "partner": raw.get("partner-name"),
        "partner_id": raw.get("partner-id"),
        "route_id": raw.get("route-id"),
        "bus_type": raw.get("bus-type"),
        "total_seats": raw.get("total-seats"),
        "available_seats": raw.get("available-seats"),
        "origin": j.get("origin") or raw.get("origin-location"),
        "destination": j.get("destination") or raw.get("destination-location"),
        "departure": j.get("departure"),
        "arrival": j.get("arrival"),
        "duration": j.get("duration"),
        "price_try": j.get("internet-price"),
        "original_price_try": j.get("original-price"),
        "price_currency": j.get("currency") or "TRY",
        "partner_rating": round(rating, 2) if isinstance(rating, (int, float)) else None,
        "route_rating": (
            round(route_rating, 2)
            if isinstance(route_rating, (int, float))
            else None
        ),
        "bus_name": j.get("bus-name"),
        "peron": j.get("peron-no"),
        "service_fee_try": j.get("service-fee"),
    }
    stops = _stops(j)
    if stops:
        row["stops"] = stops
    if j.get("description"):
        row["description"] = j["description"]
    return {k: v for k, v in row.items() if v is not None}


def _duration_seconds(value: str | None) -> float:
    """'07:30:00' -> seconds (unparseable -> +inf so it sorts last)."""
    if not value:
        return float("inf")
    try:
        parts = [int(p) for p in str(value).split(":")]
        return parts[0] * 3600 + parts[1] * 60 + (parts[2] if len(parts) > 2 else 0)
    except (ValueError, IndexError):
        return float("inf")


def parse_journeys(
    data: dict,
    limit: int = 10,
    sort: str = "price_asc",
    offset: int = 0,
    after: str | None = None,
    before: str | None = None,
    destination_terminal: str | None = None,
    min_seats: int | None = None,
    min_rating: float | None = None,
) -> list[dict]:
    """All journeys in the response, filtered client-side, sorted and
    limited. Filters apply before sorting; offset applies after sorting
    and before the limit."""
    offset = validate_offset(offset)
    rows = [parse_journey(r) for r in (data.get("journeys") or []) if isinstance(r, dict)]
    rows = filter_journeys(
        rows,
        after=after,
        before=before,
        destination_terminal=destination_terminal,
        min_seats=min_seats,
        min_rating=min_rating,
    )
    if sort == "price_asc":
        rows.sort(key=lambda r: (r.get("price_try") is None, r.get("price_try") or 0))
    elif sort == "departure":
        rows.sort(key=lambda r: r.get("departure") or "")
    elif sort == "duration":
        rows.sort(key=lambda r: _duration_seconds(r.get("duration")))
    return rows[offset : offset + limit]


def total_journeys(data: dict) -> int:
    return len(data.get("journeys") or [])


def price_stats(rows: list[dict]) -> dict:
    prices = sorted(r["price_try"] for r in rows if r.get("price_try") is not None)
    if not prices:
        return {"count": 0}
    return {
        "count": len(prices),
        "min_try": prices[0],
        "median_try": round(statistics.median(prices), 2),
        "mean_try": round(sum(prices) / len(prices), 2),
        "max_try": prices[-1],
    }


def parse_flight_summary(data: dict) -> dict:
    """The flightSummary block of a journeys response -> clean summary."""
    fs = data.get("flightSummary") or {}
    prices = fs.get("prices") or {}
    durations = fs.get("durations") or {}
    departures = fs.get("departures") or {}
    airlines = [
        {"name": a.get("name"), "iata": a.get("iata-code")}
        for a in (fs.get("airlines") or [])
        if isinstance(a, dict) and a.get("name")
    ]
    out: dict = {
        "flight_count": fs.get("journey-count"),
        "has_direct": fs.get("has-direct"),
        "min_price_try": prices.get("Key"),
        "max_price_try": prices.get("Value"),
        "min_duration": durations.get("Key"),
        "max_duration": durations.get("Value"),
        "first_departure": departures.get("Key"),
        "last_departure": departures.get("Value"),
        "origin": fs.get("origin-location"),
        "destination": fs.get("destination-location"),
        "airlines": airlines,
    }
    return {k: v for k, v in out.items() if v is not None}
