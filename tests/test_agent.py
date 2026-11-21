import io
import json
from datetime import datetime, timedelta
import sqlite3
import unittest
from unittest.mock import MagicMock, patch

from pypdf import PdfReader

from helpers import IsolatedTestCase
from src.agent import (
    ExtractionError,
    MissingApiKeyError,
    ACCESSIBILITY_WARNING,
    approval_issues,
    CRITERIA_PRESETS,
    DEFAULT_WEIGHTS,
    calculate_price_score,
    check_accessibility,
    check_budget,
    check_contract_extension,
    check_supplier,
    commit_budget_transfer,
    commit_decision,
    draft_transfer_justification,
    evaluate_bids,
    get_prior_contracts,
    missing_bid_values,
    requests_awaiting_bids,
    suggest_budget_transfers,
    validate_weights,
    evaluate_request,
    generate_anmeldebogen_pdf,
    generate_deckungsantrag_pdf,
    get_budget_lines,
)

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
        # Demo addresses only on the reserved .example domain
        self.assertEqual(res_dell["email"], "angebote@dell.example")
        self.assertIsNone(check_supplier("Unbekannt GmbH")["email"])

    def test_contract_extension(self):
        # Cancom SE has pre-existing audit history in init_db (demo order H01)
        self.assertTrue(check_contract_extension("Cancom SE"))
        # Dell Technologies is on the approved list only (no previous contract)
        self.assertFalse(check_contract_extension("Dell Technologies"))

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
        # Weights 37.5/37.5/25 are the sheet's 30/30/20 normalised: sheet points = total x 8
        totals = {b["bidder"]: b["total_points"] for b in res["ranked_bids"]}
        self.assertEqual(totals, {"Bieter 1": 75.0, "Bieter 2": 56.25})
        self.assertEqual({k: v * 8 for k, v in totals.items()}, {"Bieter 1": 600, "Bieter 2": 450})
        self.assertEqual(res["winner"]["bidder"], "Bieter 1")

    def test_winner_flip(self):
        self.set_dummy_api_key()
        with patch("src.agent.genai.Client", return_value=mock_client_returning("Absage")):
            res = evaluate_bids([
                {"bidder": "A", "price": 50000.0, "references_score": 8, "concept_score": 8},
                {"bidder": "B", "price": 70000.0, "references_score": 10, "concept_score": 10},
            ])
        totals = {b["bidder"]: b["total_points"] for b in res["ranked_bids"]}
        self.assertEqual({k: v * 8 for k, v in totals.items()}, {"A": 700, "B": 680})
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

    # --- Configurable criteria: weights must total 100, no default scores ---------------

    def test_weights_must_sum_to_100(self):
        bids = [
            {"bidder": "A", "price": 100.0, "references_score": 5, "concept_score": 5},
            {"bidder": "B", "price": 120.0, "references_score": 5, "concept_score": 5},
        ]
        for weights in ({"price": 30, "references": 30, "concept": 20}, {"price": 60, "references": 50}):
            with self.subTest(weights=weights), self.assertRaises(ValueError) as ctx:
                evaluate_bids(bids, weights)
            self.assertIn("100", str(ctx.exception))
        with self.assertRaises(ValueError):
            validate_weights({"price": 100, "colour": 0})
        with self.assertRaises(ValueError):
            validate_weights({"price": 110, "delivery": -10})

    def test_missing_committee_scores_are_not_defaulted(self):
        bids = [
            {"bidder": "A", "price": 100.0, "references_score": 8},
            {"bidder": "B", "price": 120.0, "references_score": None, "concept_score": 6},
        ]
        self.assertEqual(missing_bid_values(bids, DEFAULT_WEIGHTS), [("A", "concept"), ("B", "references")])
        with patch("src.agent.genai.Client") as client_cls:
            with self.assertRaises(ValueError) as ctx:
                evaluate_bids(bids)
        client_cls.assert_not_called()
        self.assertIn("'A': concept", str(ctx.exception))
        self.assertIn("'B': references", str(ctx.exception))

    def test_committee_score_out_of_range_raises(self):
        with self.assertRaises(ValueError):
            evaluate_bids([
                {"bidder": "A", "price": 100.0, "references_score": 11, "concept_score": 5},
                {"bidder": "B", "price": 120.0, "references_score": 5, "concept_score": 5},
            ])

    def test_goods_criteria_price_delivery_warranty(self):
        with patch("src.agent.genai.Client", side_effect=RuntimeError("offline")):
            res = evaluate_bids(
                [
                    {"bidder": "Dell", "price": 14500.0, "delivery_days": 14, "warranty_months": 36},
                    {"bidder": "Bechtle", "price": 15200.0, "delivery_days": 7, "warranty_months": 36},
                    {"bidder": "OfficeDepot", "price": 16200.0, "delivery_days": 21, "warranty_months": 24},
                ],
                CRITERIA_PRESETS["goods"],
            )
        by_name = {b["bidder"]: b for b in res["ranked_bids"]}
        # Delivery uses the Excel interpolation: fastest 10 points, twice the fastest 0 points
        self.assertEqual(by_name["Bechtle"]["delivery_score"], 10.0)
        self.assertEqual(by_name["Dell"]["delivery_score"], 0.0)
        # Warranty is proportional to the longest warranty
        self.assertEqual(by_name["OfficeDepot"]["warranty_score"], 6.67)
        expected_bechtle = round(calculate_price_score(15200.0, 14500.0) * 6 + 10 * 2 + 10 * 2, 2)
        self.assertEqual(by_name["Bechtle"]["total_points"], expected_bechtle)
        self.assertEqual(res["weights"], {"price": 60.0, "delivery": 20.0, "warranty": 20.0})
        self.assertEqual(res["winner"]["bidder"], "Bechtle")

    # --- Bid evaluation is only for approved requests -----------------------------------

    def test_requests_awaiting_bids_filter(self):
        history = [
            {"ref": "VA-2026-0001", "decision": "APPROVED", "summary": "Laptops"},
            {"ref": "VA-2026-0002", "decision": "REJECTED", "summary": "Server"},
            {"ref": "VA-2026-0004", "decision": "APPROVED", "summary": "Monitors"},
            {"ref": "VA-2026-0005", "decision": "APPROVED", "summary": "Chairs"},
        ]
        tenders = [{"ref": "VA-2026-0004"}, {"ref": "VA-2025-0412"}]
        # Pending requests (e.g. VA-2026-0003) are not in the history, so they never qualify
        open_refs = [e["ref"] for e in requests_awaiting_bids(history, tenders)]
        self.assertEqual(open_refs, ["VA-2026-0001", "VA-2026-0005"])

        self.assertEqual(requests_awaiting_bids([], []), [])
        self.assertEqual(requests_awaiting_bids([{"ref": "X", "decision": "REJECTED"}], []), [])
        self.assertEqual(requests_awaiting_bids([{"ref": "X", "decision": "APPROVED"}], [{"ref": "X"}]), [])

    # --- Budget transfer (Deckungsantrag) ----------------------------------------------------

    def budget_line(self, category):
        return next(line for line in get_budget_lines() if line["category"] == category)

    def test_transfer_suggestions_rank_same_type_first_then_free_funds(self):
        options = suggest_budget_transfers("Fahrzeuge", 3300.0)
        self.assertEqual([o["category"] for o in options], ["IT-Ausstattung", "Gebäudeunterhaltung", "Büromaterial"])
        self.assertTrue(all(o["same_type"] and o["legal_basis"] == "§ 19 KomHKVO" for o in options))
        self.assertEqual(options[0]["spare_after"], 114500.0 - 3300.0)
        # The other account type ranks after all same-type lines, with § 117 NKomVG
        everything = suggest_budget_transfers("Fahrzeuge", 3300.0, limit=10)
        self.assertEqual(everything[-1]["category"], "Feuerwehrtechnik")
        self.assertEqual(everything[-1]["legal_basis"], "§ 117 NKomVG")
        # Only lines with enough free funds; never the requesting line itself
        self.assertEqual([o["category"] for o in suggest_budget_transfers("Fahrzeuge", 115000.0)], ["Feuerwehrtechnik"])
        self.assertNotIn("Fahrzeuge", [o["category"] for o in everything])
        self.assertEqual(suggest_budget_transfers("Fahrzeuge", 500000.0), [])
        self.assertEqual(suggest_budget_transfers("Fahrzeuge", 0.0), [])

    def test_commit_budget_transfer_moves_funds_and_logs(self):
        before_audit = self.db_state("Fahrzeuge")[1]
        commit_budget_transfer("Gebäudeunterhaltung", "Fahrzeuge", 3300.0, "VA-2026-0003", "Begründung")
        need, donor = self.budget_line("Fahrzeuge"), self.budget_line("Gebäudeunterhaltung")
        self.assertEqual((need["total"], need["remaining"]), (83300.0, 76000.0))
        self.assertEqual((donor["total"], donor["remaining"]), (56700.0, 56700.0))
        self.assertEqual(self.db_state("Fahrzeuge")[1], before_audit + 1)
        conn = sqlite3.connect(self.db_path)
        try:
            decision, amount, category = conn.execute(
                "SELECT Decision, Amount, Category FROM Audit_Logs ORDER BY Id DESC LIMIT 1;"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual((decision, amount, category), ("TRANSFER", 3300.0, "Fahrzeuge"))

    def test_commit_budget_transfer_guards(self):
        for source, target, amount in (
            ("Büromaterial", "Fahrzeuge", 50000.0),  # donor has only 21,550 free
            ("Fahrzeuge", "Fahrzeuge", 100.0),
            ("Gebäudeunterhaltung", "Fahrzeuge", 0.0),
            ("Unbekannt", "Fahrzeuge", 100.0),
        ):
            with self.subTest(source=source, amount=amount), self.assertRaises(ValueError):
                commit_budget_transfer(source, target, amount, "VA-X", "Begründung")
        self.assertEqual(self.budget_line("Fahrzeuge")["remaining"], 72700.0)

    def test_deckungsantrag_pdf_and_justification(self):
        need = self.budget_line("Fahrzeuge")
        for donor_name, basis in (("IT-Ausstattung", "§ 19 KomHKVO"), ("Feuerwehrtechnik", "§ 117 NKomVG")):
            donor = self.budget_line(donor_name)
            justification = draft_transfer_justification(need, donor, 3300.0, "Dienstleistungsfahrzeug", "VA-2026-0003")
            self.assertIn(basis, justification)
            self.assertIn("EUR 3.300,00", justification)
            reader = PdfReader(io.BytesIO(
                generate_deckungsantrag_pdf(need, donor, 3300.0, "Dienstleistungsfahrzeug", "VA-2026-0003", justification)
            ))
            self.assertEqual(len(reader.pages), 1)
            text = self.pdf_text(generate_deckungsantrag_pdf(need, donor, 3300.0, "Dienstleistungsfahrzeug", "VA-2026-0003", justification))
            for expected in ("Bedarf:", "Deckung:", "Begründung:", "Unterschrift", "VA-2026-0003", "541010 Bauhof",
                             donor["produkt"], donor["konto"], "Entwurf - Prüfung und Unterschrift durch Sachbearbeitung"):
                self.assertIn(expected, text)

    def test_requests_awaiting_bids_skips_archived_history(self):
        history = [{"ref": "VA-2026-H01", "decision": "APPROVED", "archived": True},
                   {"ref": "VA-2026-0001", "decision": "APPROVED"}]
        self.assertEqual([e["ref"] for e in requests_awaiting_bids(history, [])], ["VA-2026-0001"])

    def test_anmeldebogen_status_line_and_signature(self):
        text = self.pdf_text(generate_anmeldebogen_pdf(self.eval_data("Dell Technologies", 14500.0, "IT-Ausstattung", "APPROVED")))
        self.assertIn("Vom Agenten vorgeprüft - Freigabe durch Vergabestelle ausstehend", text)
        self.assertNotIn("Freigabe durch die Sachbearbeitung erteilt", text)
        self.assertIn("Ort, Datum, Unterschrift Vergabestelle", text)

    # --- Bid evaluation: scores only, letters are templates (src/letters.py) -------------

    def test_evaluate_bids_needs_no_gemini_and_carries_letter_fields(self):
        with patch("src.agent.genai.Client") as client_cls:
            res = evaluate_bids([
                {"bidder": "A", "price": 50000.0, "references_score": 8, "concept_score": 8,
                 "item": "15 Laptops", "quantity": 15, "email": "a@a.example"},
                {"bidder": "B", "price": 70000.0, "references_score": 10, "concept_score": 10},
            ])
        client_cls.assert_not_called()
        self.assertEqual(res["winner"]["bidder"], "A")
        self.assertEqual(res["winner"]["total_points"], 87.5)
        self.assertEqual(res["losers"][0]["total_points"], 85.0)
        self.assertEqual((res["winner"]["item"], res["winner"]["quantity"], res["winner"]["email"]),
                         ("15 Laptops", 15, "a@a.example"))

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

    def test_commit_borderline_is_left_to_the_caseworker(self):
        # Fahrzeuge has EUR 72,700 remaining; 76,000 is 3,300 over (within the 5% tolerance).
        # The agent recommends "review required": either decision is allowed, the note is optional.
        before = self.db_state("Fahrzeuge")
        commit_decision("Vehicle", "Stadtwerke Hildesheim", 76000.0, "Fahrzeuge", "APPROVED", "agent reasoning")
        self.assertEqual(self.db_state("Fahrzeuge"), (before[0] - 76000.0, before[1] + 1))
        self.assertNotIn("Caseworker justification", self.last_reasoning())

        reason = "Replacement vehicle is urgent; overage covered by next quarter."
        commit_decision(
            "Vehicle", "Stadtwerke Hildesheim", 100.0, "Fahrzeuge", "APPROVED", "agent reasoning", override_reason=reason
        )
        self.assertIn(f"Caseworker justification: {reason}", self.last_reasoning())

    def test_commit_against_failed_checks_needs_justification(self):
        # Beyond the 5% tolerance, and an unapproved supplier: overrides of the agent
        for args in (
            ("Vehicle", "Stadtwerke Hildesheim", 90000.0, "Fahrzeuge"),
            ("Servers", "TechCorp", 38000.0, "IT-Ausstattung"),
        ):
            before = self.db_state(args[3])
            for empty_reason in (None, "", "   "):
                with self.subTest(supplier=args[1], reason=empty_reason), self.assertRaises(ValueError):
                    commit_decision(*args, "APPROVED", "agent reasoning", override_reason=empty_reason)
            self.assertEqual(self.db_state(args[3]), before)

            reason = "Caseworker decision documented in the file."
            commit_decision(*args, "APPROVED", "agent reasoning", override_reason=reason)
            self.assertEqual(self.db_state(args[3]), (before[0] - args[2], before[1] + 1))
            self.assertIn(f"Caseworker justification: {reason}", self.last_reasoning())

    def test_approval_issues(self):
        approved = check_supplier("Dell Technologies")
        budget = check_budget(76000.0, "Fahrzeuge")  # 72,700 left
        self.assertEqual(approval_issues(approved, check_budget(1000.0, "Fahrzeuge"), 1000.0), [])
        self.assertEqual(approval_issues(approved, budget, 76000.0), [])  # borderline: caseworker decides
        self.assertEqual(approval_issues(approved, check_budget(90000.0, "Fahrzeuge"), 90000.0), ["budget_exceeded"])
        self.assertEqual(approval_issues(approved, check_budget(90000.0, "Fahrzeuge"), 90000.0, 17300.0), [])
        self.assertEqual(approval_issues(check_supplier("TechCorp"), budget, 100.0), ["supplier_not_approved"])
        self.assertEqual(approval_issues(check_supplier("Nobody AG"), budget, 100.0), ["supplier_unknown"])
        self.assertIn("budget_unknown", approval_issues(approved, check_budget(1.0, "Unbekannt"), 1.0))

    def test_approve_with_transfer_moves_both_lines_atomically(self):
        transfer = {"source": "Gebäudeunterhaltung", "amount": 3300.0, "reference": "VA-2026-0003", "justification": "J"}
        commit_decision(
            "Vehicle", "Stadtwerke Hildesheim", 76000.0, "Fahrzeuge", "APPROVED", "agent reasoning", transfer=transfer
        )
        need, donor = self.budget_line("Fahrzeuge"), self.budget_line("Gebäudeunterhaltung")
        # Fahrzeuge: +3,300 from the transfer, -76,000 for the order
        self.assertEqual((need["total"], need["remaining"]), (83300.0, 72700.0 + 3300.0 - 76000.0))
        self.assertEqual((donor["total"], donor["remaining"]), (56700.0, 56700.0))
        conn = sqlite3.connect(self.db_path)
        try:
            decisions = [r[0] for r in conn.execute("SELECT Decision FROM Audit_Logs ORDER BY Id DESC LIMIT 2;")]
        finally:
            conn.close()
        self.assertEqual(decisions, ["APPROVED", "TRANSFER"])

    def test_reject_with_transfer_moves_nothing(self):
        before = (self.budget_line("Fahrzeuge"), self.budget_line("Gebäudeunterhaltung"))
        transfer = {"source": "Gebäudeunterhaltung", "amount": 3300.0, "reference": "VA-2026-0003", "justification": "J"}
        commit_decision(
            "Vehicle", "Stadtwerke Hildesheim", 76000.0, "Fahrzeuge", "REJECTED", "agent reasoning", transfer=transfer
        )
        self.assertEqual((self.budget_line("Fahrzeuge"), self.budget_line("Gebäudeunterhaltung")), before)
        self.assertEqual(self.last_reasoning(), "agent reasoning")

    def test_failed_transfer_books_nothing(self):
        before = (self.budget_line("Fahrzeuge"), self.budget_line("Büromaterial"), self.db_state("Fahrzeuge")[1])
        transfer = {"source": "Büromaterial", "amount": 50000.0, "reference": "VA-X", "justification": "J"}
        with self.assertRaises(ValueError):
            commit_decision(
                "Vehicle", "Stadtwerke Hildesheim", 76000.0, "Fahrzeuge", "APPROVED", "agent reasoning", transfer=transfer
            )
        self.assertEqual(
            (self.budget_line("Fahrzeuge"), self.budget_line("Büromaterial"), self.db_state("Fahrzeuge")[1]), before
        )

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
        self.assertIn("EUR 114.500,00", text)

    def test_pdf_borderline_override_contains_overage_and_justification(self):
        reason = "Replacement vehicle is urgent; overage covered by next quarter."
        data = self.eval_data("Stadtwerke Hildesheim", 76000.0, "Fahrzeuge", "REQUIRES_REVIEW")
        text = self.pdf_text(generate_anmeldebogen_pdf(data, override_reason=reason))

        self.assertIn("EUR 3.300,00", text)  # overage: 76,000 - 72,700
        self.assertIn("EUR 72.700,00", text)
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

    def test_pdf_for_overrides_needs_justification_and_states_the_facts(self):
        techcorp = self.eval_data("TechCorp", 38000.0, "IT-Ausstattung", "REJECTED")
        with self.assertRaises(ValueError):
            generate_anmeldebogen_pdf(techcorp)
        text = self.pdf_text(generate_anmeldebogen_pdf(techcorp, override_reason="Sole supplier for this system."))
        self.assertIn("als nicht zugelassen geführt", text)
        self.assertIn("Empfehlung des Agenten: Ablehnen", text)
        self.assertIn("Freigabe entgegen der Empfehlung des Agenten", text)
        self.assertIn("Sole supplier for this system.", text)
        # A borderline overage is the caseworker's call: no justification needed
        borderline = self.eval_data("Stadtwerke Hildesheim", 76000.0, "Fahrzeuge", "REQUIRES_REVIEW")
        self.assertIn("Prüfung erforderlich", self.pdf_text(generate_anmeldebogen_pdf(borderline)))
        # With a transfer the PDF states the transfer and that the funds cover the amount
        text = self.pdf_text(generate_anmeldebogen_pdf(
            borderline, transfer={"source": "Gebäudeunterhaltung", "amount": 3300.0, "legal_basis": "§ 19 KomHKVO"}
        ))
        self.assertIn("Budgetverschiebung: EUR 3.300,00 aus der Haushaltsposition Gebäudeunterhaltung", text)
        self.assertIn("Die verfügbaren Mittel decken den beantragten Betrag", text)
        self.assertNotIn("Freigabe trotz Budgetüberschreitung", text)

    def test_agent_never_states_a_final_decision(self):
        self.set_dummy_api_key()
        payload = json.dumps({"supplier_name": "TechCorp", "amount": 38000.0, "category": "IT-Ausstattung", "summary": "S."})
        with patch("src.agent.genai.Client", return_value=mock_client_returning(payload)):
            res = evaluate_request("TechCorp server")
        self.assertIn("Agent recommendation: Reject.", res["reasoning"])
        self.assertNotIn("Final Decision", res["reasoning"])

    # --- Accessibility check (Employees table) ---------------------------------------------

    def test_check_accessibility(self):
        it = check_accessibility("IT-Ausstattung")
        self.assertTrue(it["found"])
        self.assertEqual((it["total_employees"], it["employees_with_special_needs"]), (20, 2))
        self.assertEqual(it["warning"], ACCESSIBILITY_WARNING)

        office = check_accessibility("Büromaterial")
        self.assertTrue(office["found"])
        self.assertIsNone(office["warning"])

        self.assertFalse(check_accessibility("Unbekannt")["found"])

    def test_evaluate_request_appends_accessibility_warning(self):
        self.set_dummy_api_key()
        payload = json.dumps({
            "supplier_name": "Dell Technologies",
            "amount": 14500.0,
            "category": "IT-Ausstattung",
            "summary": "10 Dell laptops.",
        })
        with patch("src.agent.genai.Client", return_value=mock_client_returning(payload)):
            res = evaluate_request("10 Dell laptops, EUR 14,500, IT-Ausstattung")
        self.assertEqual(res["decision"], "APPROVED")
        self.assertEqual(res["accessibility_check"]["employees_with_special_needs"], 2)
        self.assertIn(ACCESSIBILITY_WARNING, res["reasoning"])
        self.assertEqual(res["prior_contracts"], [])
        self.assertEqual(res["procurement_type"], "LuD")

    def test_evaluate_request_without_special_needs_has_no_warning(self):
        self.set_dummy_api_key()
        payload = json.dumps({
            "supplier_name": "OfficeDepot Deutschland",
            "amount": 4200.0,
            "category": "Büromaterial",
            "summary": "Office supplies.",
        })
        with patch("src.agent.genai.Client", return_value=mock_client_returning(payload)):
            res = evaluate_request("Office supplies, EUR 4,200, Büromaterial")
        self.assertIsNone(res["accessibility_check"]["warning"])
        self.assertNotIn("WARNING", res["reasoning"])
        self.assertIn("Accessibility Check", res["reasoning"])

    def test_pdf_prints_accessibility_warning_in_sonstige_hinweise(self):
        for procurement_type, section, pages in (("Auftragserweiterung", "11. Sonstige Hinweise", 2), ("LuD", "20. Sonstige Hinweise", 5)):
            data = self.eval_data("Dell Technologies", 14500.0, "IT-Ausstattung", "APPROVED", procurement_type)
            data["accessibility_check"] = check_accessibility("IT-Ausstattung")
            pdf_bytes = generate_anmeldebogen_pdf(data)
            text = self.pdf_text(pdf_bytes)
            self.assertEqual(len(PdfReader(io.BytesIO(pdf_bytes)).pages), pages)
            hinweise = text[text.index(section):]
            self.assertIn("WARNUNG BARRIEREFREIHEIT", hinweise)
            self.assertIn("2 von 20 Beschäftigten", hinweise)
            self.assertIn("Anlagen", hinweise)

        data = self.eval_data("OfficeDepot Deutschland", 4200.0, "Büromaterial", "APPROVED")
        data["accessibility_check"] = check_accessibility("Büromaterial")
        self.assertNotIn("BARRIEREFREIHEIT", self.pdf_text(generate_anmeldebogen_pdf(data)))

    def test_extension_pdf_contains_form_sections(self):
        data = self.eval_data("Dell Technologies", 14500.0, "IT-Ausstattung", "APPROVED", "Auftragserweiterung")
        text = self.pdf_text(generate_anmeldebogen_pdf(data))
        for section in ("9. Fristen", "10. Auftragnehmer", "11. Sonstige Hinweise", "Anlagen",
                        "Angebot/Kostenschätzung", "Nachweis der Haushaltsmittel", "ggf. VA-Beschluss"):
            self.assertIn(section, text)
        self.assertIn("Dell Technologies", text[text.index("10. Auftragnehmer"):])

    def test_extension_pdf_page_one_sections_6_to_8(self):
        data = self.eval_data("Cancom SE", 14500.0, "IT-Ausstattung", "APPROVED", "Auftragserweiterung")
        data["prior_contracts"] = get_prior_contracts("Cancom SE")
        data["accessibility_check"] = check_accessibility("IT-Ausstattung")
        reader = PdfReader(io.BytesIO(generate_anmeldebogen_pdf(data)))
        page1 = " ".join(reader.pages[0].extract_text().split())
        page2 = " ".join(reader.pages[1].extract_text().split())

        # Budget checkboxes appear once; "Haushaltsführung" only in the template sentence (twice)
        self.assertEqual(page1.count("vorsteuerabzugsberechtigt"), 1)
        self.assertEqual(page1.count("Haushaltsführung"), 2)
        self.assertIn("14.500,00 EUR brutto", page1)

        section6 = page1[page1.index("6. Angaben zum ursprünglichen Auftrag"):page1.index("7. Vergabebegründung")]
        self.assertIn("Ursprünglicher Auftragswert: 18.500,00 EUR brutto", section6)
        # The demo order H01 is dated 160 days before the database was seeded
        order_date = (datetime.now() - timedelta(days=160)).strftime("%d.%m.%Y")
        self.assertIn(f"Beauftragte Leistungen: {order_date}: Beschaffung von 20 Arbeitsplatzrechnern", section6)
        self.assertIn("Begründung: Die Erweiterung ist aufgrund des gestiegenen Bedarfs erforderlich.", page1)
        self.assertIn("Rechtsgrundlage: § 8 UVgO (Auftragserweiterung)", page1)
        self.assertIn("8. Begründung der Wirtschaftlichkeit Es werden die Konditionen des Ursprungsauftrags genutzt", page1)

        # The accessibility warning stays in Section 11 on page 2
        self.assertIn("WARNUNG BARRIEREFREIHEIT", page2[page2.index("11. Sonstige Hinweise"):])


if __name__ == "__main__":
    unittest.main()
