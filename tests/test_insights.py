import unittest
from datetime import date, datetime

from helpers import PROJECT_ROOT  # noqa: F401  (adds the project root to sys.path)
from src.insights import budget_forecast, burnup, oversight, supplier_shares, supplier_totals

TODAY = date(2026, 11, 20)


def approval(day, category, amount, supplier="X"):
    return {"timestamp": datetime(2026, *day), "category": category, "amount": amount, "supplier": supplier}


class TestBudgetForecast(unittest.TestCase):
    def test_line_lasting_the_year_shows_year_end_usage(self):
        lines = [{"category": "IT", "total": 150000.0, "remaining": 90000.0}]
        approvals = [
            approval((10, 1), "IT", 9000.0),
            approval((11, 1), "IT", 9000.0),
            approval((5, 1), "IT", 42000.0),  # older than 90 days: not part of the rate
        ]
        row = budget_forecast(lines, approvals, TODAY)[0]
        # 18,000 in 90 days = 200 per day; 90,000 left would last until 2028: no date shown
        self.assertEqual(row["status"], "year_end")
        self.assertIsNone(row["runout_date"])
        self.assertEqual(row["recent_orders"], 2)
        self.assertEqual(row["committed"], 60000.0)
        # 41 days to 31 Dec at 200 per day: 60,000 + 8,200 = 68,200 of 150,000
        self.assertAlmostEqual(row["year_end_committed"], 68200.0)
        self.assertAlmostEqual(row["year_end_share"], 68200.0 / 150000.0)

    def test_run_out_within_the_year_and_soon_flag(self):
        lines = [{"category": "IT", "total": 20000.0, "remaining": 4000.0}]
        approvals = [approval((10, 1), "IT", 9000.0), approval((11, 1), "IT", 9000.0)]
        row = budget_forecast(lines, approvals, TODAY)[0]
        # 200 per day: 4,000 lasts 20 days -> 10 Dec, within 60 days
        self.assertEqual(row["status"], "runs_out")
        self.assertEqual(row["runout_date"], date(2026, 12, 10))
        self.assertTrue(row["runout_soon"])

    def test_not_enough_data_gives_no_projection(self):
        lines = [{"category": "IT", "total": 1000.0, "remaining": 500.0},
                 {"category": "Empty", "total": 1000.0, "remaining": 1000.0}]
        rows = budget_forecast(lines, [approval((11, 1), "IT", 500.0)], TODAY)
        self.assertEqual([r["status"] for r in rows], ["not_enough_data", "not_enough_data"])
        self.assertIsNone(rows[0]["runout_date"])
        self.assertIsNone(rows[0]["year_end_share"])

    def test_exhausted_line(self):
        lines = [{"category": "IT", "total": 1000.0, "remaining": -200.0}]
        row = budget_forecast(lines, [], TODAY)[0]
        self.assertEqual(row["status"], "exhausted")
        self.assertIsNone(row["runout_date"])


class TestBurnup(unittest.TestCase):
    def test_actual_and_projection_stay_in_the_budget_year(self):
        line = {"category": "IT", "total": 150000.0, "remaining": 90000.0}
        approvals = [approval((10, 1), "IT", 9000.0), approval((11, 1), "IT", 9000.0),
                     approval((5, 1), "IT", 42000.0)]
        data = burnup(line, approvals, TODAY)
        # 60,000 committed, all three orders this year: starts at 0 on 1 Jan
        self.assertEqual(data["actual"][0], {"date": date(2026, 1, 1), "cumulative": 0.0})
        self.assertEqual([p["cumulative"] for p in data["actual"]], [0.0, 42000.0, 51000.0, 60000.0, 60000.0])
        self.assertEqual(data["actual"][-1]["date"], TODAY)
        self.assertEqual(data["projection"][-1]["date"], date(2026, 12, 31))
        self.assertAlmostEqual(data["projection"][-1]["cumulative"], 68200.0)
        dates = [p["date"] for p in data["actual"] + data["projection"]]
        self.assertTrue(all(d.year == 2026 for d in dates))

    def test_no_projection_without_enough_data(self):
        data = burnup({"category": "IT", "total": 1000.0, "remaining": 500.0}, [approval((11, 1), "IT", 500.0)], TODAY)
        self.assertEqual(data["projection"], [])
        # 500 committed, 500 of it this year
        self.assertEqual([p["cumulative"] for p in data["actual"]], [0.0, 500.0, 500.0])


class TestSupplierShares(unittest.TestCase):
    def test_concentration_needs_enough_spend_orders_and_suppliers(self):
        rows = supplier_shares([
            approval((10, 1), "IT", 6000.0, "Dell"),
            approval((10, 2), "IT", 3000.0, "Bechtle"),
            approval((10, 3), "IT", 1000.0, "HP"),
            approval((10, 4), "Office", 500.0, "OfficeDepot"),
        ])
        it = [r for r in rows if r["category"] == "IT"]
        self.assertEqual([r["supplier"] for r in it], ["Dell", "Bechtle", "HP"])
        self.assertAlmostEqual(it[0]["share"], 0.6)
        # 10,000 spend, 3 orders, 3 suppliers: checked; only Dell is above 40 %
        self.assertTrue(it[0]["line_checked"])
        self.assertEqual([r["above_limit"] for r in it], [True, False, False])
        # One small order: too little data, no warning
        office = [r for r in rows if r["category"] == "Office"][0]
        self.assertFalse(office["line_checked"])
        self.assertFalse(office["above_limit"])
        self.assertEqual(supplier_shares([]), [])

    def test_below_minimum_spend_or_orders_is_not_checked(self):
        small = supplier_shares([approval((10, d), "IT", 3000.0, "Dell") for d in (1, 2, 3)])  # 9,000 < 10,000
        self.assertEqual([(r["line_checked"], r["above_limit"]) for r in small], [(False, False)])
        few = supplier_shares([approval((10, 1), "IT", 9000.0, "Dell"), approval((10, 2), "IT", 9000.0, "HP")])
        self.assertFalse(any(r["line_checked"] for r in few))  # only 2 orders

    def test_single_supplier_needs_three_orders(self):
        one_big = supplier_shares([approval((10, 1), "IT", 30000.0, "Dell"), approval((10, 2), "IT", 100.0, "Dell"),
                                   approval((10, 3), "IT", 100.0, "Dell")])
        self.assertTrue(one_big[0]["above_limit"])  # 3 orders from the one supplier
        self.assertEqual(one_big[0]["orders"], 3)

    def test_supplier_totals_across_lines(self):
        rows = supplier_shares([
            approval((10, 1), "IT", 6000.0, "Dell"), approval((10, 2), "IT", 3000.0, "Bechtle"),
            approval((10, 3), "IT", 1000.0, "HP"), approval((10, 4), "Office", 2000.0, "Dell"),
        ])
        totals = supplier_totals(rows)
        self.assertEqual([t["supplier"] for t in totals], ["Dell", "Bechtle", "HP"])
        self.assertEqual((totals[0]["spend"], totals[0]["orders"], totals[0]["lines"], totals[0]["flagged"]),
                         (8000.0, 2, ["IT", "Office"], True))


class TestOversight(unittest.TestCase):
    def test_agreement_rate_overrides_and_deferred(self):
        requests = [
            {"ref": "A", "agent_decision": "APPROVED", "decision": "APPROVED"},
            {"ref": "B", "agent_decision": "REJECTED", "decision": "REJECTED"},
            {"ref": "C", "agent_decision": "APPROVED", "decision": "REJECTED"},
            {"ref": "D", "agent_decision": "REQUIRES_REVIEW", "decision": "APPROVED"},
        ]
        transfers = [{"ref": "D", "accepted": True}, {"ref": "E", "accepted": False}]
        result = oversight(requests, transfers)
        self.assertEqual((result["agreed"], result["compared"]), (2, 3))
        self.assertAlmostEqual(result["rate"], 2 / 3)
        self.assertEqual([r["ref"] for r in result["overrides"]], ["C"])
        self.assertEqual([r["ref"] for r in result["deferred"]], ["D"])
        self.assertEqual((result["transfers_proposed"], result["transfers_accepted"]), (2, 1))

    def test_no_decisions(self):
        result = oversight([], [])
        self.assertIsNone(result["rate"])
        self.assertEqual(result["overrides"], [])


if __name__ == "__main__":
    unittest.main()
