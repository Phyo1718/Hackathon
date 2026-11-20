import io
import json
import sqlite3
import unittest
from unittest.mock import MagicMock, patch

from pypdf import PdfReader

from helpers import IsolatedTestCase
from src.agent import (
    ExtractionError,
    MissingApiKeyError,
    calculate_price_score,
    check_budget,
    check_contract_extension,
    check_supplier,
    commit_decision,
    evaluate_bids,
    evaluate_request,
    generate_anmeldebogen_pdf,
)

OLD_TEMPLATE_TEXT = "Gemäß § 13 UVgO wird Ihr Angebot nicht berücksichtigt"


def mock_client_returning(text):
    client = MagicMock()
    client.models.generate_content.return_value = MagicMock(text=text)
    return client


class TestProcurementAgent(IsolatedTestCase):
    def db_state(self, category):
        conn = sqlite3.connect(self.db_path)
        try:
            remaining = conn.execute(
                "SELECT Remaining_Budget FROM Budgets WHERE Category = ?;", (category,)
            ).fetchone()[0]
            audit_count = conn.execute("SELECT COUNT(*) FROM Audit_Logs;").fetchone()[0]
        finally:
            conn.close()
        return remaining, audit_count

    def last_reasoning(self):
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute("SELECT Reasoning FROM Audit_Logs ORDER BY Id DESC LIMIT 1;").fetchone()[0]
        finally:
            conn.close()

    def test_check_supplier(self):
        res_dell = check_supplier("Dell Technologies")
        self.assertTrue(res_dell["exists"])
        self.assertTrue(res_dell["is_approved"])
        self.assertEqual(res_dell["category"], "IT-Ausstattung")

    def test_contract_extension(self):
        # Dell Technologies has pre-existing audit history in init_db
        is_ext = check_contract_extension("Dell Technologies")
        self.assertTrue(is_ext)

        # TechCorp has no history
        is_ext_tech = check_contract_extension("TechCorp")
        self.assertFalse(is_ext_tech)

    def test_check_budget(self):
        res_it = check_budget(14500.0, "IT-Ausstattung")
        self.assertTrue(res_it["sufficient"])

    # --- Issue 1: Excel price interpolation -------------------------------------------

    def test_excel_example_scores(self):
        self.set_dummy_api_key()
        with patch("src.agent.genai.Client", return_value=mock_client_returning("Absage")):
            res = evaluate_bids([
                {"bidder": "Bieter 1", "price": 50000.0, "references_score": 8, "concept_score": 3},
                {"bidder": "Bieter 2", "price": 70000.0, "references_score": 5, "concept_score": 6},
            ])
        totals = {b["bidder"]: b["total_points"] for b in res["ranked_bids"]}
        self.assertEqual(totals, {"Bieter 1": 600, "Bieter 2": 450})
        self.assertEqual(res["winner"]["bidder"], "Bieter 1")

    def test_winner_flip(self):
        self.set_dummy_api_key()
        with patch("src.agent.genai.Client", return_value=mock_client_returning("Absage")):
            res = evaluate_bids([
                {"bidder": "A", "price": 50000.0, "references_score": 8, "concept_score": 8},
                {"bidder": "B", "price": 70000.0, "references_score": 10, "concept_score": 10},
            ])
        totals = {b["bidder"]: b["total_points"] for b in res["ranked_bids"]}
        self.assertEqual(totals, {"A": 700, "B": 680})
        self.assertEqual(res["winner"]["bidder"], "A")

    def test_price_at_or_above_double_lowest_gets_zero(self):
        self.assertEqual(calculate_price_score(100000.0, 50000.0), 0.0)
        self.assertEqual(calculate_price_score(150000.0, 50000.0), 0.0)
        self.assertEqual(calculate_price_score(50000.0, 50000.0), 10.0)

        self.set_dummy_api_key()
        with patch("src.agent.genai.Client", return_value=mock_client_returning("Absage")):
            res = evaluate_bids([
                {"bidder": "Low", "price": 50000.0, "references_score": 5, "concept_score": 5},
                {"bidder": "Double", "price": 100000.0, "references_score": 5, "concept_score": 5},
                {"bidder": "Triple", "price": 150000.0, "references_score": 5, "concept_score": 5},
            ])
        by_name = {b["bidder"]: b for b in res["ranked_bids"]}
        for name in ("Double", "Triple"):
            self.assertEqual(by_name[name]["price_score"], 0.0)
            self.assertEqual(by_name[name]["price_points"], 0.0)

    def test_non_positive_price_raises(self):
        for bad_price in (0.0, -100.0):
            with self.assertRaises(ValueError) as ctx:
                evaluate_bids([
                    {"bidder": "Good", "price": 1000.0, "references_score": 5, "concept_score": 5},
                    {"bidder": "Bad", "price": bad_price, "references_score": 5, "concept_score": 5},
                ])
            self.assertIn("Bad", str(ctx.exception))

    # --- Issue 4: letter failures do not break scoring ----------------------------------

    def test_evaluate_bids_with_gemini_failure_still_returns_scores(self):
        self.set_dummy_api_key()
        with patch("src.agent.genai.Client", side_effect=RuntimeError("503 Service Unavailable")):
            res = evaluate_bids([
                {"bidder": "A", "price": 50000.0, "references_score": 8, "concept_score": 8},
                {"bidder": "B", "price": 70000.0, "references_score": 10, "concept_score": 10},
            ])
        self.assertEqual(res["winner"]["bidder"], "A")
        self.assertEqual(res["winner"]["total_points"], 700)
        loser = res["losers"][0]
        self.assertEqual(loser["total_points"], 680)
        self.assertIsNone(loser["legal_justification"])
        self.assertIn("503 Service Unavailable", loser["letter_error"])
        self.assertNotIn(OLD_TEMPLATE_TEXT, str(res))

    def test_evaluate_bids_without_api_key_sets_letter_error(self):
        with patch("src.agent.genai.Client") as client_cls:
            res = evaluate_bids([
                {"bidder": "A", "price": 50000.0, "references_score": 8, "concept_score": 8},
                {"bidder": "B", "price": 70000.0, "references_score": 10, "concept_score": 10},
            ])
        client_cls.assert_not_called()
        self.assertIsNone(res["losers"][0]["legal_justification"])
        self.assertIn("GEMINI_API_KEY", res["losers"][0]["letter_error"])

    # --- Issue 2: no offline fallback -----------------------------------------------------

    def test_evaluate_request_without_api_key_raises(self):
        with patch("src.agent.genai.Client") as client_cls:
            with self.assertRaises(MissingApiKeyError):
                evaluate_request("TechCorp, EUR 38,000, IT-Ausstattung")
        client_cls.assert_not_called()

    def test_evaluate_request_all_models_fail_raises(self):
        self.set_dummy_api_key()
        client = MagicMock()
        client.models.generate_content.side_effect = RuntimeError("429 quota exhausted")
        with patch("src.agent.genai.Client", return_value=client):
            with self.assertRaises(ExtractionError) as ctx:
                evaluate_request("TechCorp, EUR 38,000, IT-Ausstattung")
        self.assertIn("429 quota exhausted", str(ctx.exception))
        self.assertGreaterEqual(client.models.generate_content.call_count, 2)

    def test_evaluate_request_invalid_schema_raises(self):
        self.set_dummy_api_key()
        with patch("src.agent.genai.Client", return_value=mock_client_returning('{"supplier_name": "X"}')):
            with self.assertRaises(ExtractionError):
                evaluate_request("some request")

    def test_evaluate_request_rejects_unapproved_supplier(self):
        self.set_dummy_api_key()
        payload = json.dumps({
            "supplier_name": "TechCorp",
            "amount": 38000.0,
            "category": "IT-Ausstattung",
            "summary": "Server infrastructure from TechCorp.",
        })
        with patch("src.agent.genai.Client", return_value=mock_client_returning(payload)):
            res = evaluate_request("TechCorp, EUR 38,000, IT-Ausstattung")
        self.assertEqual(res["decision"], "REJECTED")
        self.assertFalse(res["supplier_check"]["is_approved"])

    # --- Issue 3: server-side approval guard ---------------------------------------------

    def test_commit_approved_for_unapproved_supplier_is_blocked(self):
        before = self.db_state("IT-Ausstattung")
        with self.assertRaises(ValueError):
            commit_decision(
                request_text="Server infrastructure",
                supplier="TechCorp",
                amount=38000.0,
                category="IT-Ausstattung",
                decision="APPROVED",
                reasoning="UI bypass attempt",
            )
        self.assertEqual(self.db_state("IT-Ausstattung"), before)

    def test_commit_approved_for_unknown_supplier_is_blocked(self):
        before = self.db_state("IT-Ausstattung")
        with self.assertRaises(ValueError):
            commit_decision("x", "Nobody GmbH", 100.0, "IT-Ausstattung", "APPROVED", "r")
        self.assertEqual(self.db_state("IT-Ausstattung"), before)

    def test_commit_approved_within_budget(self):
        remaining_before, audits_before = self.db_state("IT-Ausstattung")
        commit_decision("Laptops", "Dell Technologies", 14500.0, "IT-Ausstattung", "APPROVED", "ok")
        self.assertEqual(self.db_state("IT-Ausstattung"), (remaining_before - 14500.0, audits_before + 1))

    def test_commit_borderline_requires_override_reason(self):
        # Fahrzeuge has EUR 73,600 remaining; 76,000 is 2,400 over (within the 5% tolerance).
        before = self.db_state("Fahrzeuge")
        for empty_reason in (None, "", "   "):
            with self.assertRaises(ValueError):
                commit_decision(
                    "Vehicle", "Stadtwerke Hildesheim", 76000.0, "Fahrzeuge", "APPROVED", "agent reasoning",
                    override_reason=empty_reason,
                )
        self.assertEqual(self.db_state("Fahrzeuge"), before)

        reason = "Replacement vehicle is urgent; overage covered by next quarter."
        commit_decision(
            "Vehicle", "Stadtwerke Hildesheim", 76000.0, "Fahrzeuge", "APPROVED", "agent reasoning",
            override_reason=reason,
        )
        self.assertEqual(self.db_state("Fahrzeuge"), (before[0] - 76000.0, before[1] + 1))
        reasoning = self.last_reasoning()
        self.assertIn("agent reasoning", reasoning)
        self.assertIn(f"Caseworker justification: {reason}", reasoning)

    def test_commit_beyond_tolerance_rejected_even_with_override(self):
        before = self.db_state("Fahrzeuge")
        with self.assertRaises(ValueError):
            commit_decision(
                "Vehicle", "Stadtwerke Hildesheim", 90000.0, "Fahrzeuge", "APPROVED", "agent reasoning",
                override_reason="Please approve anyway, this is important.",
            )
        self.assertEqual(self.db_state("Fahrzeuge"), before)

    def test_commit_rejected_writes_audit_only(self):
        remaining_before, audits_before = self.db_state("IT-Ausstattung")
        commit_decision("Server", "TechCorp", 38000.0, "IT-Ausstattung", "REJECTED", "unapproved supplier")
        self.assertEqual(self.db_state("IT-Ausstattung"), (remaining_before, audits_before + 1))

    # --- Issue 3: PDF states only checked facts ---------------------------------------------

    def eval_data(self, supplier, amount, category, decision, procurement_type="LuD"):
        budget = check_budget(amount, category)
        return {
            "supplier_name": supplier,
            "amount": amount,
            "category": category,
            "konto": budget.get("konto", ""),
            "summary": "Test procurement",
            "procurement_type": procurement_type,
            "supplier_check": check_supplier(supplier),
            "budget_check": budget,
            "decision": decision,
        }

    @staticmethod
    def pdf_text(pdf_bytes):
        reader = PdfReader(io.BytesIO(pdf_bytes))
        return " ".join(" ".join(page.extract_text() for page in reader.pages).split())

    def test_generate_anmeldebogen_pdf(self):
        pdf_bytes = generate_anmeldebogen_pdf(
            self.eval_data("Dell Technologies", 14500.0, "IT-Ausstattung", "APPROVED", "Auftragserweiterung")
        )
        self.assertIsInstance(pdf_bytes, bytes)
        text = self.pdf_text(pdf_bytes)
        self.assertIn("Auftragserweiterung", text)
        self.assertIn("EUR 124.300,00", text)

    def test_pdf_borderline_override_contains_overage_and_justification(self):
        reason = "Replacement vehicle is urgent; overage covered by next quarter."
        data = self.eval_data("Stadtwerke Hildesheim", 76000.0, "Fahrzeuge", "REQUIRES_REVIEW")
        text = self.pdf_text(generate_anmeldebogen_pdf(data, override_reason=reason))

        self.assertIn("EUR 2.400,00", text)  # overage: 76,000 - 73,600
        self.assertIn("EUR 73.600,00", text)
        self.assertIn(reason, text)
        for unchecked_claim in (
            "Die vergaberechtlichen Voraussetzungen wurden geprüft",
            "Die Haushaltsmittel stehen zur Verfügung",
            "im zugelassenen Lieferantenverzeichnis registriert",
            "Markterkundung",
            "Direktvergabe",
            "Die verfügbaren Mittel decken",
        ):
            self.assertNotIn(unchecked_claim, text)

    def test_pdf_refused_for_rejected_or_unverified_requests(self):
        with self.assertRaises(ValueError):
            generate_anmeldebogen_pdf(self.eval_data("TechCorp", 38000.0, "IT-Ausstattung", "REJECTED"))
        # Even if the decision field is tampered with, an unapproved supplier gets no PDF.
        with self.assertRaises(ValueError):
            generate_anmeldebogen_pdf(self.eval_data("TechCorp", 38000.0, "IT-Ausstattung", "APPROVED"))
        # Borderline overage without a justification gets no PDF.
        with self.assertRaises(ValueError):
            generate_anmeldebogen_pdf(self.eval_data("Stadtwerke Hildesheim", 76000.0, "Fahrzeuge", "REQUIRES_REVIEW"))


if __name__ == "__main__":
    unittest.main()
