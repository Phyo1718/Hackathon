import sqlite3
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from helpers import PROJECT_ROOT, IsolatedTestCase
from src.agent import ExtractionError, check_budget, check_supplier

APP_PATH = str(PROJECT_ROOT / "app.py")


class TestStreamlitApp(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        # Never read a developer's real .env during app tests.
        dotenv_patch = patch("dotenv.load_dotenv")
        dotenv_patch.start()
        self.addCleanup(dotenv_patch.stop)

    def make_eval(self, supplier, amount, category, decision):
        budget = check_budget(amount, category)
        return {
            "supplier_name": supplier,
            "amount": amount,
            "category": category,
            "konto": budget.get("konto", ""),
            "summary": f"{supplier} request",
            "procurement_type": "LuD",
            "is_extension": False,
            "supplier_check": check_supplier(supplier),
            "budget_check": budget,
            "decision": decision,
            "reasoning": f"Agent decision: {decision}",
        }

    def run_evaluation(self, evaluation=None, side_effect=None):
        """Submits a request through the UI with evaluate_request mocked."""
        self.set_dummy_api_key()
        with patch("src.agent.evaluate_request", return_value=evaluation, side_effect=side_effect), \
                patch("src.agent.genai.Client") as client_cls:
            at = AppTest.from_file(APP_PATH, default_timeout=60)
            at.run()
            at.text_area(key="request_text_0").input("Some procurement request")
            at.button(key="evaluate_btn").click().run()
            client_cls.assert_not_called()
        self.assertFalse(at.exception)
        return at

    @staticmethod
    def button_keys(at):
        return [b.key for b in at.button]

    def test_no_api_key_shows_only_setup_error(self):
        at = AppTest.from_file(APP_PATH, default_timeout=60)
        at.run()
        self.assertFalse(at.exception)
        self.assertEqual(len(at.error), 1)
        self.assertIn("GEMINI_API_KEY", at.error[0].value)
        self.assertEqual(len(at.tabs), 0)
        self.assertEqual(len(at.button), 0)
        self.assertEqual(len(at.text_area), 0)

    def test_rejected_decision_has_no_approve_button(self):
        at = self.run_evaluation(self.make_eval("TechCorp", 38000.0, "IT-Ausstattung", "REJECTED"))
        keys = self.button_keys(at)
        self.assertNotIn("approve_btn", keys)
        self.assertIn("reject_btn", keys)

    def test_requires_review_needs_justification(self):
        at = self.run_evaluation(self.make_eval("Stadtwerke Hildesheim", 76000.0, "Fahrzeuge", "REQUIRES_REVIEW"))
        self.assertTrue(at.button(key="approve_btn").disabled)

        # 19 non-whitespace characters (padded with spaces) is not enough.
        at.text_area(key="override_justification").input("  short   text  1234567890  ").run()
        self.assertTrue(at.button(key="approve_btn").disabled)

        reason = "Urgent replacement of the broken service vehicle."
        at.text_area(key="override_justification").input(reason).run()
        self.assertFalse(at.button(key="approve_btn").disabled)

        at.button(key="approve_btn").click().run()
        self.assertFalse(at.exception)
        conn = sqlite3.connect(self.db_path)
        try:
            remaining, = conn.execute("SELECT Remaining_Budget FROM Budgets WHERE Category = 'Fahrzeuge';").fetchone()
            reasoning, = conn.execute("SELECT Reasoning FROM Audit_Logs ORDER BY Id DESC LIMIT 1;").fetchone()
        finally:
            conn.close()
        self.assertEqual(remaining, 73600.0 - 76000.0)
        self.assertIn(f"Caseworker justification: {reason}", reasoning)

    def test_evaluation_error_shows_error_and_stores_nothing(self):
        at = self.run_evaluation(side_effect=ExtractionError("Gemini extraction failed for all models: 503"))
        self.assertTrue(any("503" in e.value for e in at.error))
        self.assertIsNone(at.session_state["last_evaluation"])
        self.assertNotIn("approve_btn", self.button_keys(at))
        self.assertNotIn("reject_btn", self.button_keys(at))


if __name__ == "__main__":
    unittest.main()
