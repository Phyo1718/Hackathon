import unittest
from datetime import date, datetime

from helpers import PROJECT_ROOT  # noqa: F401  (adds the project root to sys.path)
from src.insights import budget_forecast, oversight, supplier_shares

TODAY = date(2026, 11, 20)


def approval(day, category, amount, supplier="X"):
    return {"timestamp": datetime(2026, *day), "category": category, "amount": amount, "supplier": supplier}


class TestBudgetForecast(unittest.TestCase):
    def test_runout_date_at_90_day_rate(self):
        lines = [{"category": "IT", "total": 150000.0, "remaining": 90000.0}]
        approvals = [
            approval((10, 1), "IT", 9000.0),
            approval((11, 1), "IT", 9000.0),
            approval((5, 1), "IT", 42000.0),  # older than 90 days: not part of the rate
        ]
        row = budget_forecast(lines, approvals, TODAY)[0]
        # 18,000 in 90 days = 200 per day; 90,000 left lasts 450 days
        self.assertEqual(row["status"], "forecast")
        self.assertEqual(row["recent_orders"], 2)
        self.assertEqual(row["runout_date"], date(2028, 2, 13))
        self.assertEqual(row["committed"], 60000.0)
        self.assertAlmostEqual(row["used_share"], 0.4)

    def test_not_enough_data_gives_no_date(self):
        lines = [{"category": "IT", "total": 1000.0, "remaining": 500.0},
                 {"category": "Empty", "total": 1000.0, "remaining": 1000.0}]
        rows = budget_forecast(lines, [approval((11, 1), "IT", 500.0)], TODAY)
        self.assertEqual([r["status"] for r in rows], ["not_enough_data", "not_enough_data"])
        self.assertIsNone(rows[0]["runout_date"])

    def test_exhausted_line(self):
        lines = [{"category": "IT", "total": 1000.0, "remaining": -200.0}]
        row = budget_forecast(lines, [], TODAY)[0]
        self.assertEqual(row["status"], "exhausted")
        self.assertIsNone(row["runout_date"])


class TestSupplierShares(unittest.TestCase):
    def test_shares_per_line_and_40_percent_flag(self):
        rows = supplier_shares([
            approval((10, 1), "IT", 6000.0, "Dell"),
            approval((10, 2), "IT", 3000.0, "Bechtle"),
            approval((10, 3), "IT", 1000.0, "HP"),
            approval((10, 4), "Office", 500.0, "OfficeDepot"),
        ])
        it = [r for r in rows if r["category"] == "IT"]
        self.assertEqual([r["supplier"] for r in it], ["Dell", "Bechtle", "HP"])
        self.assertAlmostEqual(it[0]["share"], 0.6)
        self.assertEqual([r["above_limit"] for r in it], [True, False, False])
        office = [r for r in rows if r["category"] == "Office"]
        self.assertTrue(office[0]["above_limit"])
        self.assertEqual(supplier_shares([]), [])


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
