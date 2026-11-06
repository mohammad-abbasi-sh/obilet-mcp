"""Offline tests for obilet_mcp.journeys — recorded real API responses.

Fixtures are trimmed excerpts of real obilet.com JSON responses
fetched 2026-11-06: location search "Ankara", journeys İstanbul
Avrupa (349) -> Ankara (356) on 2026-11-07 (first 3 of 421 + full
flightSummary), journey detail for id 1432053091.
"""
import asyncio
import json
import os
import unittest

from obilet_mcp import journeys as J

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def _read(name: str) -> dict:
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return json.load(f)


class TestLocationsParse(unittest.TestCase):
    def test_ankara_first(self):
        rows = J.parse_locations(_read("locations-ankara.json"))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["id"], 356)
        self.assertEqual(rows[0]["name"], "Ankara")
        self.assertEqual(rows[0]["display"], "Ankara")
        self.assertTrue(rows[0]["is_domestic"])

    def test_empty(self):
        self.assertEqual(J.parse_locations({}), [])
        self.assertEqual(J.parse_locations({"items": []}), [])


class TestJourneysParse(unittest.TestCase):
    def setUp(self):
        self.data = _read("journeys-349-356.json")

    def test_total(self):
        self.assertEqual(J.total_journeys(self.data), 3)

    def test_cheapest_first(self):
        rows = J.parse_journeys(self.data, limit=3, sort="price_asc")
        self.assertEqual(len(rows), 3)
        first = rows[0]
        self.assertEqual(first["journey_id"], 1432053091)
        self.assertEqual(first["partner"], "Yükseller Aksaray Birlik")
        self.assertEqual(first["partner_id"], 32325)
        self.assertEqual(first["bus_type"], "2+1")
        self.assertEqual(first["total_seats"], 41)
        self.assertEqual(first["available_seats"], 36)
        self.assertEqual(first["origin"], "Esenler Otogarı")
        self.assertEqual(first["destination"], "Ankara (Aşti) Otogarı")
        self.assertEqual(first["departure"], "2026-11-07T07:30:00")
        self.assertEqual(first["arrival"], "2026-11-07T15:30:00")
        self.assertEqual(first["duration"], "08:00:00")
        self.assertEqual(first["price_try"], 539.0)
        self.assertEqual(first["original_price_try"], 700.0)
        self.assertEqual(first["price_currency"], "TRY")
        self.assertEqual(first["partner_rating"], 8.64)
        self.assertEqual(first["route_rating"], 8.64)
        self.assertEqual(first["bus_name"], "68 AFY 666")

    def test_price_sort_ascending(self):
        rows = J.parse_journeys(self.data, limit=3, sort="price_asc")
        prices = [r["price_try"] for r in rows]
        self.assertEqual(prices, sorted(prices))

    def test_departure_sort(self):
        rows = J.parse_journeys(self.data, limit=3, sort="departure")
        deps = [r["departure"] for r in rows]
        self.assertEqual(deps, sorted(deps))
        self.assertEqual(deps[0], "2026-11-07T07:30:00")

    def test_duration_sort(self):
        rows = J.parse_journeys(self.data, limit=3, sort="duration")
        self.assertEqual(rows[0]["duration"], "07:30:00")

    def test_limit(self):
        self.assertEqual(len(J.parse_journeys(self.data, limit=1)), 1)

    def test_stops(self):
        rows = J.parse_journeys(self.data, limit=1)
        stops = rows[0]["stops"]
        self.assertTrue(stops[0]["is_origin"])
        dest = [s for s in stops if s["is_destination"]]
        self.assertEqual(len(dest), 1)
        self.assertEqual(dest[0]["name"], "Ankara (Aşti) Otogarı")
        self.assertEqual(dest[0]["time"], "2026-11-07T15:30:00")

    def test_price_stats(self):
        rows = J.parse_journeys(self.data, limit=3)
        stats = J.price_stats(rows)
        self.assertEqual(stats["count"], 3)
        self.assertEqual(stats["min_try"], 539.0)
        self.assertEqual(stats["median_try"], 539.0)
        self.assertEqual(stats["mean_try"], 539.0)
        self.assertEqual(stats["max_try"], 539.0)

    def test_price_stats_empty(self):
        self.assertEqual(J.price_stats([]), {"count": 0})

    def test_empty_data(self):
        self.assertEqual(J.parse_journeys({}), [])


class TestDetailParse(unittest.TestCase):
    def test_detail(self):
        d = J.parse_journey(_read("journey-detail.json"))
        self.assertEqual(d["journey_id"], 1432053091)
        self.assertEqual(d["partner"], "Yükseller Aksaray Birlik")
        self.assertEqual(d["price_try"], 539.0)
        self.assertEqual(d["original_price_try"], 700.0)
        self.assertEqual(d["departure"], "2026-11-07T07:30:00")
        self.assertEqual(d["arrival"], "2026-11-07T15:30:00")
        self.assertEqual(len(d["stops"]), 9)
        self.assertEqual(d["stops"][0]["name"], "Esenler Otogarı")
        dest = [s for s in d["stops"] if s["is_destination"]]
        self.assertEqual(dest[0]["name"], "Ankara (Aşti) Otogarı")
        self.assertTrue(d["description"].startswith("ARACIMIZ 2026 MODEL"))


class TestFlightSummaryParse(unittest.TestCase):
    def test_summary(self):
        fs = J.parse_flight_summary(_read("journeys-349-356.json"))
        self.assertEqual(fs["flight_count"], 26)
        self.assertTrue(fs["has_direct"])
        self.assertEqual(fs["min_price_try"], 1461.99)
        self.assertEqual(fs["max_price_try"], 7399.34)
        self.assertEqual(fs["min_duration"], "01:00:00")
        self.assertEqual(fs["max_duration"], "12:05:00")
        self.assertEqual(fs["first_departure"], "00:05:00")
        self.assertEqual(fs["last_departure"], "23:30:00")
        self.assertEqual(
            [a["name"] for a in fs["airlines"]], ["Pegasus", "AJet", "THY"]
        )
        self.assertEqual(
            [a["iata"] for a in fs["airlines"]], ["PC", "VF", "TK"]
        )
        self.assertEqual(fs["origin"]["location-name"], "İstanbul")
        self.assertEqual(fs["destination"]["location-name"], "Ankara")

    def test_empty(self):
        self.assertEqual(J.parse_flight_summary({})["airlines"], [])


class TestValidation(unittest.TestCase):
    def test_valid_date(self):
        self.assertEqual(J.validate_date("2026-11-07"), "2026-11-07")

    def test_bad_date(self):
        for bad in ("2026-13-01", "2026-11-7", "07-11-2026", "tomorrow", ""):
            with self.assertRaises(ValueError):
                J.validate_date(bad)

    def test_resolve_sort(self):
        self.assertEqual(J.resolve_sort("price_asc"), "price_asc")
        self.assertEqual(J.resolve_sort("departure"), "departure")
        self.assertEqual(J.resolve_sort("duration"), "duration")
        with self.assertRaises(ValueError):
            J.resolve_sort("bogus")


class TestServerToolsRegistered(unittest.TestCase):
    def test_five_tools(self):
        from obilet_mcp.server import mcp

        tools = asyncio.run(mcp.list_tools())
        names = sorted(t.name for t in tools)
        self.assertEqual(
            names,
            [
                "obilet_flight_summary",
                "obilet_journey_detail",
                "obilet_price_stats",
                "obilet_search_bus_journeys",
                "obilet_search_locations",
            ],
        )


if __name__ == "__main__":
    unittest.main()
