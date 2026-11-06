"""Live tests for obilet_mcp — real requests to obilet.com.

Requires network + Chrome TLS impersonation (curl-cffi) with a session
(the API is session-gated: an HTML page is fetched first for cookies).
The server is polite by design (~0.8s between requests), so this file
takes ~15s. Run: python -m unittest discover -s tests -v

Dates: tests use 2026-11-07 (tomorrow at build time). If run much
later, journeys for that date may be gone — use a near-future date.
"""
import json
import unittest

from obilet_mcp import http as H
from obilet_mcp import journeys as J

DATE = "2026-11-07"
IST_AV = 349  # İstanbul Avrupa (bus)
ANKARA = 356


class TestLiveLocations(unittest.TestCase):
    def test_search_ankara(self):
        data = H.fetch_locations("Ankara")
        rows = J.parse_locations(data)
        self.assertGreaterEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], 356)
        self.assertEqual(rows[0]["name"], "Ankara")

    def test_search_flight_locations(self):
        data = H.fetch_locations("İstanbul", kind="flight")
        rows = J.parse_locations(data)
        self.assertGreaterEqual(len(rows), 1)
        ids = [str(r["id"]) for r in rows]
        self.assertIn("250_0", ids)  # İstanbul (Tümü)

    def test_bad_kind(self):
        with self.assertRaises(H.ObiletError):
            H.fetch_locations("Ankara", kind="train")


class TestLiveJourneys(unittest.TestCase):
    def test_journeys_count(self):
        data = H.fetch_journeys(IST_AV, ANKARA, DATE)
        self.assertGreaterEqual(J.total_journeys(data), 100)

    def test_price_asc_order(self):
        data = H.fetch_journeys(IST_AV, ANKARA, DATE)
        rows = J.parse_journeys(data, limit=10, sort="price_asc")
        self.assertGreaterEqual(len(rows), 2)
        prices = [r["price_try"] for r in rows]
        self.assertEqual(prices, sorted(prices))
        self.assertTrue(all(p > 0 for p in prices))

    def test_departure_order(self):
        data = H.fetch_journeys(IST_AV, ANKARA, DATE)
        rows = J.parse_journeys(data, limit=10, sort="departure")
        deps = [r["departure"] for r in rows]
        self.assertEqual(deps, sorted(deps))

    def test_first_journey_fields(self):
        data = H.fetch_journeys(IST_AV, ANKARA, DATE)
        rows = J.parse_journeys(data, limit=1)
        first = rows[0]
        self.assertTrue(first["journey_id"])
        self.assertTrue(first["partner"])
        self.assertTrue(first["price_try"] > 0)
        self.assertEqual(first["price_currency"], "TRY")
        self.assertTrue(first["stops"])
        dest = [s for s in first["stops"] if s["is_destination"]]
        self.assertEqual(len(dest), 1)

    def test_flight_summary(self):
        data = H.fetch_journeys(IST_AV, ANKARA, DATE)
        fs = J.parse_flight_summary(data)
        self.assertGreaterEqual(fs["flight_count"], 1)
        self.assertLessEqual(fs["min_price_try"], fs["max_price_try"])
        names = [a["name"] for a in fs["airlines"]]
        self.assertTrue(any(n in names for n in ("Pegasus", "AJet", "THY")))


class TestLiveDetail(unittest.TestCase):
    def test_known_journey(self):
        data = H.fetch_journeys(IST_AV, ANKARA, DATE)
        jid = J.parse_journeys(data, limit=1)[0]["journey_id"]
        detail = H.fetch_journey_detail(jid)
        d = J.parse_journey(detail)
        self.assertEqual(d["journey_id"], jid)
        self.assertTrue(d["price_try"] > 0)
        self.assertTrue(d["stops"])


class TestLiveToolsEndToEnd(unittest.TestCase):
    """Exercise the MCP tool functions themselves (they hit the network)."""

    def test_locations_tool_json(self):
        from obilet_mcp.server import obilet_search_locations

        out = json.loads(obilet_search_locations("Ankara"))
        self.assertEqual(out["query"], "Ankara")
        self.assertGreaterEqual(out["count"], 1)
        self.assertEqual(out["locations"][0]["id"], 356)

    def test_journeys_tool_json(self):
        from obilet_mcp.server import obilet_search_bus_journeys

        out = json.loads(obilet_search_bus_journeys(IST_AV, ANKARA, DATE, limit=2))
        self.assertEqual(out["date"], DATE)
        self.assertEqual(out["count"], 2)
        self.assertGreaterEqual(out["total"], 100)
        self.assertTrue(out["journeys"][0]["price_try"] > 0)

    def test_stats_tool_json(self):
        from obilet_mcp.server import obilet_price_stats

        out = json.loads(obilet_price_stats(IST_AV, ANKARA, DATE))
        self.assertGreaterEqual(out["count"], 100)
        self.assertLessEqual(out["min_try"], out["max_try"])

    def test_flight_summary_tool_json(self):
        from obilet_mcp.server import obilet_flight_summary

        out = json.loads(obilet_flight_summary(IST_AV, ANKARA, DATE))
        self.assertGreaterEqual(out["flight_count"], 1)
        self.assertLessEqual(out["min_price_try"], out["max_price_try"])

    def test_bad_date_tool_error_json(self):
        from obilet_mcp.server import obilet_search_bus_journeys

        out = json.loads(obilet_search_bus_journeys(IST_AV, ANKARA, "tomorrow"))
        self.assertIn("error", out)

    def test_bad_sort_tool_error_json(self):
        from obilet_mcp.server import obilet_search_bus_journeys

        out = json.loads(
            obilet_search_bus_journeys(IST_AV, ANKARA, DATE, sort="nope")
        )
        self.assertIn("error", out)


if __name__ == "__main__":
    unittest.main()
