# obilet-mcp 🇹🇷

mcp-name: io.github.mohammad-abbasi-sh/obilet-mcp

Unofficial **read-only** MCP server for obilet.com**, Türkiye's bus & flight ticket search — search bus locations, list all bus journeys for a route + date (partner, bus type, seats, departure/arrival, duration, price in TRY, partner rating, stops), read full journey details, get price statistics, and read the flight summary (flight count, min/max price, airlines) for the same city pair.

> Built by Mohammad Abbasi as part of the "Turkey MCP factory" (Sepehr-style pipeline). Not affiliated with obilet.com.

## For AI agents

Add to your MCP client config (stdio):

```json
{
  "mcpServers": {
    "obilet": {
      "command": "uvx",
      "args": ["obilet-mcp"]
    }
  }
}
```

Or run locally: `python -m obilet_mcp.server` (needs `mcp<2`, `curl-cffi`).

## Tools

| Tool | Description |
|------|-------------|
| `obilet_search_locations` | Search locations by name — `query` ("Ankara", "İstanbul"), `kind` ("bus" / "flight"); returns id, name, display name, city id per match (bus ids are ints, flight ids are strings like "250_0") |
| `obilet_search_bus_journeys` | Bus journeys for a route + date — `origin_id` / `destination_id` (bus location ids, e.g. 349 İstanbul Avrupa -> 356 Ankara), `date` "YYYY-MM-DD", `sort` ("price_asc" / "departure" / "duration"), `limit` 1..24; filters: `offset` (>= 0), `after` / `before` ("HH:MM" departure window), `destination_terminal` (substring of the destination station name, e.g. "Aşti"), `min_seats`, `min_rating` (0-10); returns journey id, partner, bus type, seats, stations, departure/arrival, duration, price in TRY, partner rating (0-10), stops, plus the total and filtered counts |
| `obilet_journey_detail` | Full detail of one journey (`journey_id`): partner, bus type, seats, stations, departure/arrival, duration, internet & original price in TRY, service fee, partner rating, bus name, platform, description, every stop with its time |
| `obilet_price_stats` | Price statistics for a route + date: journey count, min / median / mean / max ticket price in TRY; `sampling`: "first" (all journeys, default) or "day" (cheapest journeys + one service per 2-hour slot across the day) |
| `obilet_flight_summary` | Flight summary for a route + date: flight count, min/max price in TRY, min/max duration, first/last departure, direct-flight flag, airlines with IATA codes (individual flight listings are NOT in v1 — the live flight-list endpoint returns 404/500) |
| `obilet_health` | Health check: one polite probe of the obilet.com homepage — returns status "ok" / "blocked" / "error", HTTP status, URL and detail |

Example output (`obilet_search_bus_journeys` / İstanbul Avrupa -> Ankara, 2026-11-07):

```json
{"origin_id": 349, "destination_id": 356, "date": "2026-11-07",
 "sort": "price_asc", "total": 421, "count": 2, "journeys": [
  {"journey_id": 1432053091, "partner": "Yükseller Aksaray Birlik",
   "bus_type": "2+1", "total_seats": 41, "available_seats": 36,
   "origin": "Esenler Otogarı", "destination": "Ankara (Aşti) Otogarı",
   "departure": "2026-11-07T07:30:00", "arrival": "2026-11-07T15:30:00",
   "duration": "08:00:00", "price_try": 539.0, "original_price_try": 700.0,
   "price_currency": "TRY", "partner_rating": 8.64, …}, …]}
```

Example output (`obilet_flight_summary` / same route & date):

```json
{"origin_id": 349, "destination_id": 356, "date": "2026-11-07",
 "flight_count": 26, "has_direct": true, "min_price_try": 1461.99,
 "max_price_try": 7399.34, "min_duration": "01:00:00",
 "max_duration": "12:05:00", "first_departure": "00:05:00",
 "last_departure": "23:30:00",
 "airlines": [{"name": "Pegasus", "iata": "PC"}, {"name": "AJet", "iata": "VF"},
              {"name": "THY", "iata": "TK"}]}
```

Example output (`obilet_price_stats` / same route & date):

```json
{"origin_id": 349, "destination_id": 356, "date": "2026-11-07",
 "count": 421, "min_try": 539.0, "median_try": 800.0,
 "mean_try": 852.38, "max_try": 1150.0}
```

## How it works

obilet.com exposes a JSON API, but it is session-gated: an HTML page
is fetched first (it sets cookies incl. `ob_Session` and `__cf_bm`),
then POSTs carry `X-Requested-With: XMLHttpRequest` with that page as
Referer. Locations: POST /json/duraklar (bus) or /json/ucak-duraklari
(flight). Journeys: POST /json/journeys/{origin}-{destination}/{date}
with `{}` — one response holds every journey for the route. Detail:
POST /json/sefer-tam/{journeyId}. The same journeys response carries
the flightSummary. Sorting is client-side (price / departure /
duration). The async flights endpoint is broken on the site side
(404/500), so individual flight listings are out of scope for v1.
Transport uses a persistent curl-cffi session with profile rotation
(chrome120 -> chrome131 -> safari17_0, sticky on the last working
profile): on HTTP 403/429 the session is rebuilt with the next
profile, re-primed and the request retried once, then a specific
error is returned (403 bot wall / 429 rate-limited / 404 not found).
A short 120s prime cache skips repeat HTML primes for the same page.
Requests are spaced ~0.8s apart; everything is read-only, no login,
no API key. Every tool output carries `fetched_at` (UTC),
`source="obilet.com"` and an unofficial-data disclaimer. A daily
live smoke test (`.github/workflows/smoke.yml`, 06:00 UTC) probes the
homepage via `obilet_health` so site/transport breakage is caught
before users hit it.

## Install

```bash
uvx obilet-mcp==0.1.1        # run directly (needs uv)
# or
pip install obilet-mcp==0.1.1
obilet-mcp         # starts the MCP server on stdio
```

## Tests

```bash
python -m venv .venv && .venv/bin/pip install -e .
.venv/bin/python -m unittest discover -s tests -v
```

Offline tests run on recorded fixtures (real pages fetched 2026-11-06);
live tests hit obilet.com.

## Roadmap

- Individual flight listings (if the async flights endpoint is fixed)
- Round-trip search (outbound + return in one call)
- Seat-map / available-seat detail per journey

## License

MIT — see [LICENSE](LICENSE).

---

Built by [Mohammad Abbasi](https://github.com/mohammad-abbasi-sh) — [Almanibama](https://almanibama.ir) · [mabbasi.ir](https://mabbasi.ir)
