import json
import os
import re
import sqlite3
import unittest
from unittest.mock import patch

from fpdf import FPDF
from streamlit.testing.v1 import AppTest

from helpers import PROJECT_ROOT, IsolatedTestCase
from src.agent import ExtractionError, check_accessibility, check_budget, check_supplier

APP_PATH = str(PROJECT_ROOT / "app.py")
SEEDED_REFS = ["VA-2026-0001", "VA-2026-0002", "VA-2026-0003"]
SEEDED = len(SEEDED_REFS)
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"
BID_FIXTURES = ("Bechtle_bid.pdf", "dell_bid.pdf", "OfficeDepot_bid.pdf")


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

    def submit_requests(self, *evaluations, side_effect=None):
        """Submits requests through the Add view with evaluate_request mocked."""
        self.set_dummy_api_key()
        with patch("src.agent.evaluate_request", side_effect=side_effect or list(evaluations)), \
                patch("src.agent.genai.Client") as client_cls:
            at = AppTest.from_file(APP_PATH, default_timeout=60)
            at.run()
            at.button(key="nav_add").click().run()
            for form_key in range(max(len(evaluations), 1)):
                at.text_area(key=f"request_text_{form_key}").input("Some procurement request")
                at.button(key="submit_btn").click().run()
            client_cls.assert_not_called()
        self.assertFalse(at.exception)
        return at

    def open_request(self, at, index=SEEDED):
        """Switches to the verification view and opens the popup for a queued request.

        The queue starts with the seeded requests, so the default is the first submitted one.
        """
        at.button(key="nav_verify").click().run()
        at.session_state["active_request"] = at.session_state["request_queue"][index]["ref"]
        at.run()
        self.assertFalse(at.exception)
        return at

    @staticmethod
    def button_keys(at):
        return [b.key for b in at.button]

    def latest_audit(self):
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute("SELECT Decision, Reasoning FROM Audit_Logs ORDER BY Id DESC LIMIT 1;").fetchone()
        finally:
            conn.close()

    def remaining_budget(self, category):
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute("SELECT Remaining_Budget FROM Budgets WHERE Category = ?;", (category,)).fetchone()[0]
        finally:
            conn.close()

    @staticmethod
    def decided(requests):
        """Requests decided in the test, without the archived demo history."""
        return [entry for entry in requests if not entry.get("archived")]

    def saved_history(self):
        with open(os.path.join(os.path.dirname(self.db_path), "history.json"), encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def budget_meters(at):
        """Sidebar budget meters as {position: (right-hand text, caption)}."""
        html = next(m.value for m in at.sidebar.markdown if "budget-meter" in m.value)
        return {
            name: (right, caption)
            for name, right, caption in re.findall(
                r'budget-meter-name">([^<]+)</span><span class="[^"]+">([^<]+)</span>.*?'
                r'budget-meter-caption"><span>([^<]+)</span>',
                html,
            )
        }

    @staticmethod
    def upload_bids(at, *names):
        """Sets the bid uploader to exactly these fixture files (none = remove all)."""
        files = [(name, (FIXTURES / name).read_bytes(), "application/pdf") for name in names]
        at.file_uploader(key=f"bid_pdfs_{at.session_state['bid_upload_nonce']}").set_value(files).run()

    @staticmethod
    def confirm_scores(at, value=True):
        """Ticks the committee confirmation above the bid table."""
        box = next(c for c in at.checkbox if c.key.startswith("committee_confirmed_"))
        box.set_value(value).run()

    def approve(self, at, ref):
        """Approves a queued request through its popup on the Request Verification page."""
        at.button(key="nav_verify").click().run()
        at.session_state["active_request"] = ref
        at.run()
        at.button(key="approve_btn").click().run()
        at.session_state["active_request"] = None
        self.assertFalse(at.exception)

    def start_app(self):
        self.set_dummy_api_key()
        at = AppTest.from_file(APP_PATH, default_timeout=60)
        at.run()
        self.assertFalse(at.exception)
        return at

    def test_no_api_key_shows_only_setup_error(self):
        at = AppTest.from_file(APP_PATH, default_timeout=60)
        at.run()
        self.assertFalse(at.exception)
        self.assertEqual(len(at.error), 1)
        self.assertIn("GEMINI_API_KEY", at.error[0].value)
        self.assertNotIn("nav_verify", self.button_keys(at))
        self.assertEqual(len(at.button), 0)
        self.assertEqual(len(at.text_area), 0)

    def test_all_views_render_in_both_languages(self):
        self.set_dummy_api_key()
        at = AppTest.from_file(APP_PATH, default_timeout=60)
        at.run()
        for lang in ["DE", "EN"]:
            at.segmented_control(key="lang_toggle").set_value(lang).run()
            for view in ["verify", "bids", "add", "insights"]:
                at.button(key=f"nav_{view}").click().run()
                self.assertFalse(at.exception, f"{lang}/{view}")

    def test_submitted_request_is_queued(self):
        at = self.submit_requests(self.make_eval("Dell Technologies", 14500.0, "IT-Ausstattung", "APPROVED"))
        queue = at.session_state["request_queue"]
        self.assertEqual(len(queue), SEEDED + 1)
        self.assertEqual(queue[SEEDED]["status"], "PENDING")
        self.assertEqual(queue[SEEDED]["ref"], "VA-2026-0004")

    def test_both_buttons_offered_and_recommended_one_is_primary(self):
        at = self.open_request(self.submit_requests(self.make_eval("TechCorp", 38000.0, "IT-Ausstattung", "REJECTED")))
        # Agent recommends Reject: both buttons, Reject highlighted, Approve needs a note
        self.assertEqual(at.button(key="reject_btn").proto.type, "primary")
        self.assertEqual(at.button(key="approve_btn").proto.type, "secondary")
        self.assertFalse(at.button(key="reject_btn").disabled)
        self.assertTrue(at.button(key="approve_btn").disabled)
        self.assertTrue(any("gegen die Empfehlung des Agenten" in w.value for w in at.warning))

        at.button(key="reject_btn").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state["request_queue"][SEEDED]["status"], "REJECTED")
        entry = self.decided(self.saved_history()["requests"])[0]
        self.assertEqual((entry["agent_recommendation"], entry["caseworker_decision"], entry["override"]),
                         ("REJECTED", "REJECTED", False))

    def test_agent_reject_caseworker_approve_with_note_is_override(self):
        at = self.open_request(self.submit_requests(self.make_eval("TechCorp", 38000.0, "IT-Ausstattung", "REJECTED")))
        ref = at.session_state["request_queue"][SEEDED]["ref"]
        # The note is mandatory for an override: 14 characters are not enough
        at.text_area(key=f"caseworker_note_{ref}").input("  too    short  1234  ").run()
        self.assertTrue(at.button(key="approve_btn").disabled)
        note = "Sole supplier for the existing server platform."
        at.text_area(key=f"caseworker_note_{ref}").input(note).run()
        self.assertFalse(at.button(key="approve_btn").disabled)
        at.button(key="approve_btn").click().run()
        self.assertFalse(at.exception)

        entry = self.decided(self.saved_history()["requests"])[0]
        self.assertEqual((entry["agent_recommendation"], entry["caseworker_decision"], entry["override"], entry["note"]),
                         ("REJECTED", "APPROVED", True, note))
        decision, reasoning = self.latest_audit()
        self.assertEqual(decision, "APPROVED")
        self.assertIn(f"Caseworker justification: {note}", reasoning)
        self.assertEqual(self.remaining_budget("IT-Ausstattung"), 114500.0 - 38000.0)

    def test_agent_approve_caseworker_reject_needs_note(self):
        at = self.start_app()
        at.session_state["active_request"] = "VA-2026-0001"
        at.run()
        self.assertEqual(at.button(key="approve_btn").proto.type, "primary")
        self.assertTrue(at.button(key="reject_btn").disabled)
        note = "Demand already covered by the framework contract."
        at.text_area(key="caseworker_note_VA-2026-0001").input(note).run()
        at.button(key="reject_btn").click().run()
        self.assertFalse(at.exception)
        entry = self.decided(self.saved_history()["requests"])[0]
        self.assertEqual((entry["ref"], entry["override"], entry["note"]), ("VA-2026-0001", True, note))
        self.assertEqual(self.remaining_budget("IT-Ausstattung"), 114500.0)

        # Request history shows the Override badge; AI oversight lists it with the note
        at.session_state["active_request"] = None
        at.button(key="history_btn_verify").click().run()
        self.assertTrue(any("Abweichung" in str(b.proto) for b in at.get("badge")) or
                        any(":orange-badge[Abweichung]" in m.value for m in at.markdown))
        at.session_state["history_view"] = None
        at.button(key="nav_insights").click().run()
        overrides = at.dataframe[2].value
        self.assertIn("VA-2026-0001", overrides["ref"].tolist())
        self.assertIn(note, overrides["note"].tolist())
        self.assertEqual(at.metric[1].value, "2")

    def test_requires_review_both_decisions_allowed_note_optional(self):
        at = self.open_request(
            self.submit_requests(self.make_eval("Stadtwerke Hildesheim", 76000.0, "Fahrzeuge", "REQUIRES_REVIEW"))
        )
        self.assertFalse(at.button(key="approve_btn").disabled)
        self.assertFalse(at.button(key="reject_btn").disabled)
        self.assertFalse(any("gegen die Empfehlung des Agenten" in w.value for w in at.warning))
        at.button(key="approve_btn").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(self.remaining_budget("Fahrzeuge"), 72700.0 - 76000.0)
        entry = self.decided(self.saved_history()["requests"])[0]
        self.assertEqual((entry["agent_recommendation"], entry["override"]), ("REQUIRES_REVIEW", False))

    def test_approve_offers_pdf_and_next_request_opens_next_in_queue(self):
        at = self.open_request(
            self.submit_requests(
                self.make_eval("Dell Technologies", 14500.0, "IT-Ausstattung", "APPROVED"),
                self.make_eval("TechCorp", 38000.0, "IT-Ausstattung", "REJECTED"),
            )
        )
        queue = at.session_state["request_queue"]
        at.button(key="approve_btn").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state["request_queue"][SEEDED]["status"], "APPROVED")
        self.assertEqual(self.latest_audit()[0], "APPROVED")

        # The PDF is offered as a base64 <a download> link and clicked once automatically
        links = [m.value for m in at.markdown if "data:application/pdf;base64," in m.value]
        self.assertEqual(len(links), 1)
        self.assertIn('download="Anmeldebogen_LuD_', links[0])
        self.assertTrue(any("link.click()" in h.proto.body for h in at.get("html")))
        self.assertNotIn("auto_download", at.session_state["request_queue"][SEEDED])

        at.button(key="next_request_btn").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state["active_request"], queue[SEEDED + 1]["ref"])
        self.assertIn("reject_btn", self.button_keys(at))

    def test_accessibility_warning_shown_in_dialog_and_queue(self):
        evaluation = self.make_eval("Dell Technologies", 14500.0, "IT-Ausstattung", "APPROVED")
        evaluation["accessibility_check"] = check_accessibility("IT-Ausstattung")
        at = self.submit_requests(evaluation)
        at.button(key="nav_verify").click().run()
        self.assertIn("accessibility", at.dataframe[0].value.columns)
        self.assertNotEqual(at.dataframe[0].value["accessibility"][SEEDED], "-")

        at = self.open_request(at)
        self.assertTrue(any("2" in w.value and "20" in w.value for w in at.warning))

    def test_bid_upload_prefills_agent_scores_and_needs_committee_confirmation(self):
        at = self.start_app()
        self.approve(at, "VA-2026-0001")
        at.button(key="nav_bids").click().run()
        self.upload_bids(at, "Bechtle_bid.pdf")
        self.assertFalse(at.exception)
        self.assertEqual(len(at.error), 0)

        row = at.data_editor[0].value.iloc[0]
        self.assertEqual(row["bidder"], "Bechtle GmbH")
        self.assertEqual(row["price"], 15200.0)
        self.assertEqual(row["quantity"], 15)
        self.assertEqual(row["delivery_days"], 7)
        self.assertEqual(row["warranty_months"], 36)
        self.assertTrue(row["item"].startswith("15 HP EliteBook"))
        self.assertIn("Total Price: EUR 15200.00", row["evidence"])
        # References / Service and Concept / Quality are proposed by the agent, with reasons
        self.assertEqual(row["references_score"], 7)
        self.assertEqual(row["concept_score"], 8)
        self.assertEqual(
            row["references_basis"],
            "KI · +4 früherer Auftrag VA-2026-H06 (+1 weitere) · +3 Garantie 3 Jahre · Referenzen: keine im Angebot",
        )
        self.assertTrue(row["concept_basis"].startswith("KI · +4 15 Laptops wie angefragt (Marke nicht bewertet)"))
        self.assertEqual(len(at.warning), 0)

        # Run Evaluation needs the committee's confirmation, not hand-typed scores
        self.assertTrue(at.button(key="eval_bids_btn").disabled)
        self.confirm_scores(at)
        self.assertFalse(at.button(key="eval_bids_btn").disabled)
        at.segmented_control(key="criteria_preset").set_value("goods").run()
        self.assertFalse(at.button(key="eval_bids_btn").disabled)

    def test_bid_without_any_evidence_stays_required(self):
        at = self.start_app()
        self.approve(at, "VA-2026-0001")
        at.button(key="nav_bids").click().run()
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)
        for line in ("ANGEBOT", "Anbieter: Unbekannt Handel GmbH", "Gesamtpreis: 13.900,00 EUR"):
            pdf.cell(0, 8, line, new_x="LMARGIN", new_y="NEXT")
        uploader = at.file_uploader(key=f"bid_pdfs_{at.session_state['bid_upload_nonce']}")
        uploader.set_value([("unknown_bid.pdf", bytes(pdf.output()), "application/pdf")]).run()
        self.assertFalse(at.exception)

        row = at.data_editor[0].value.iloc[0]
        self.assertTrue(row[["references_score", "concept_score"]].isna().all())
        self.assertTrue(row["references_basis"].startswith("erforderlich"))
        warning = next(w.value for w in at.warning)
        self.assertIn(
            "- Unbekannt Handel GmbH: Referenzen / Service – keine Zusammenarbeit bekannt und keine Referenzen im Angebot",
            warning,
        )
        self.assertIn("- Unbekannt Handel GmbH: Konzept / Qualität –", warning)
        self.confirm_scores(at)
        self.assertTrue(at.button(key="eval_bids_btn").disabled)

    def test_committee_change_is_stored_and_counted(self):
        at = self.start_app()
        self.approve(at, "VA-2026-0001")
        at.button(key="nav_bids").click().run()
        self.upload_bids(at, *BID_FIXTURES)
        table = at.data_editor[0].value.set_index("bidder")
        self.assertEqual(table["references_score"].to_dict(),
                         {"Bechtle GmbH": 7, "Dell Technologies": 5, "OfficeDepot Deutschland GmbH": 2})
        self.assertTrue(table.loc["OfficeDepot Deutschland GmbH", "references_basis"].endswith(
            "kein Auftrag in IT-Ausstattung (zugelassen nur für Büromaterial) · Referenzen: keine im Angebot"))

        # The committee lowers Dell's References / Service from 5 to 4
        edits = at.session_state["bid_edits"]
        dell_key = next(k for k in edits if k.startswith("dell_bid.pdf:"))
        edits[dell_key]["references_score"] = 4.0
        at.session_state["bid_edits"] = edits
        at.run()
        table = at.data_editor[0].value.set_index("bidder")
        self.assertEqual(table.loc["Dell Technologies", "references_basis"].split(" · ")[0], "Kommission (KI-Vorschlag 5)")

        self.confirm_scores(at)
        at.button(key="eval_bids_btn").click().run()
        self.assertFalse(at.exception)
        run = self.saved_history()["tenders"][-1]
        scores = {b["bidder"]: b["scores"] for b in run["bidders"]}
        self.assertEqual(scores["Dell Technologies"]["references"]["agent"], 5)
        self.assertEqual(scores["Dell Technologies"]["references"]["committee"], 4.0)
        self.assertEqual(scores["Bechtle GmbH"]["references"]["agent"], scores["Bechtle GmbH"]["references"]["committee"])
        self.assertIn("früherer Auftrag", scores["Bechtle GmbH"]["references"]["reason"]["DE"])

        at.button(key="nav_insights").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(next(m.value for m in at.metric if m.label == "Geänderte Bieterpunkte"), "1")

    def test_bid_weights_not_totalling_100_block_evaluation(self):
        at = self.start_app()
        self.approve(at, "VA-2026-0001")
        at.button(key="nav_bids").click().run()
        self.upload_bids(at, "Bechtle_bid.pdf")
        self.confirm_scores(at)
        at.segmented_control(key="criteria_preset").set_value("goods").run()
        self.assertFalse(at.button(key="eval_bids_btn").disabled)
        at.number_input(key="weight_goods_price").set_value(50.0).run()
        self.assertTrue(any("90" in e.value for e in at.error))
        self.assertTrue(at.button(key="eval_bids_btn").disabled)

    def test_no_uploads_no_bid_rows_and_table_follows_uploads(self):
        at = self.start_app()
        self.approve(at, "VA-2026-0001")
        at.button(key="nav_bids").click().run()

        # (a) No uploads: uploader and hint only; no table, no blocked box, no scoring inputs
        self.assertEqual(len(at.data_editor), 0)
        self.assertEqual(len(at.warning), 0)
        self.assertEqual(len(at.number_input), 0)
        self.assertNotIn("eval_bids_btn", self.button_keys(at))
        self.assertTrue(any("Laden Sie die Angebote der Bieter (PDF) hoch" in c.value for c in at.caption))
        self.assertFalse(at.session_state["bid_extractions"])

        # (b) One upload: one row with the real source text
        self.upload_bids(at, "Bechtle_bid.pdf")
        table = at.data_editor[0].value
        self.assertEqual(table["bidder"].tolist(), ["Bechtle GmbH"])
        self.assertTrue(table["evidence"].iloc[0].startswith("Bechtle_bid.pdf: Supplier: Bechtle GmbH"))
        self.assertNotIn("Demo", " ".join(table["evidence"]))

        # A committee score for Bechtle is kept when other files are added or removed
        edits = at.session_state["bid_edits"]
        bechtle_key = next(k for k in edits if k.startswith("Bechtle_bid.pdf:"))
        edits[bechtle_key]["references_score"] = 8.0
        at.session_state["bid_edits"] = edits

        # (c) Three uploads: three rows
        self.upload_bids(at, *BID_FIXTURES)
        table = at.data_editor[0].value.set_index("bidder")
        self.assertEqual(sorted(table.index), ["Bechtle GmbH", "Dell Technologies", "OfficeDepot Deutschland GmbH"])
        self.assertEqual(table.loc["Bechtle GmbH", "references_score"], 8.0)

        # (d) Remove one: two rows, its cached extraction is gone
        self.upload_bids(at, "Bechtle_bid.pdf", "dell_bid.pdf")
        self.assertEqual(sorted(at.data_editor[0].value["bidder"]), ["Bechtle GmbH", "Dell Technologies"])
        self.assertFalse(any(k.startswith("OfficeDepot_bid.pdf:") for k in at.session_state["bid_extractions"]))
        self.assertEqual(at.data_editor[0].value.set_index("bidder").loc["Bechtle GmbH", "references_score"], 8.0)

        # (e) Remove all: empty state again
        self.upload_bids(at)
        self.assertEqual(len(at.data_editor), 0)
        self.assertNotIn("eval_bids_btn", self.button_keys(at))
        self.assertFalse(at.session_state["bid_extractions"])
        self.assertFalse(at.session_state["bid_edits"])

        # Changing the selected request empties the uploader and the cache
        self.upload_bids(at, "Bechtle_bid.pdf")
        nonce = at.session_state["bid_upload_nonce"]
        at.selectbox(key="bid_tender_ref").set_value("__other__").run()
        self.assertEqual(at.session_state["bid_upload_nonce"], nonce + 1)
        self.assertEqual(len(at.data_editor), 0)

        # Reset Demo Data clears it as well
        at.selectbox(key="bid_tender_ref").set_value("VA-2026-0001").run()
        self.upload_bids(at, "Bechtle_bid.pdf")
        at.button(key="reset_btn").click().run()
        self.assertEqual(len(at.data_editor), 0)
        self.assertFalse(at.session_state["bid_extractions"])

    def test_evaluation_error_shows_error_and_queues_nothing(self):
        at = self.submit_requests(side_effect=ExtractionError("Gemini extraction failed for all models: 503"))
        self.assertTrue(any("503" in e.value for e in at.error))
        self.assertEqual([r["ref"] for r in at.session_state["request_queue"]], SEEDED_REFS)

    # --- Seeded queue, budget chart, history, reset -----------------------------------------

    def test_three_requests_seeded_at_startup_without_gemini(self):
        with patch("src.agent.genai.Client") as client_cls:
            at = self.start_app()
        client_cls.assert_not_called()
        queue = at.session_state["request_queue"]
        self.assertEqual([r["ref"] for r in queue], SEEDED_REFS)
        self.assertEqual([r["status"] for r in queue], ["PENDING"] * 3)
        self.assertEqual(
            [r["evaluation"]["decision"] for r in queue], ["APPROVED", "REJECTED", "REQUIRES_REVIEW"]
        )
        self.assertEqual(len(at.dataframe[0].value), 3)
        keys = self.button_keys(at)
        self.assertNotIn("load_samples_btn", keys)
        self.assertIn("go_add_btn", keys)

        # Seeding happens once per session, not on every rerun
        at.button(key="nav_bids").click().run()
        at.button(key="nav_verify").click().run()
        self.assertEqual(len(at.session_state["request_queue"]), 3)

    def test_approval_updates_chart_history_and_reset_restores_seeded_state(self):
        at = self.start_app()
        before = self.budget_meters(at)
        self.assertEqual(
            list(before), ["Büromaterial", "Fahrzeuge", "Feuerwehrtechnik", "Gebäudeunterhaltung", "IT-Ausstattung"]
        )
        # The demo history already commits 18,500 + 7,200 + 9,800 on IT-Ausstattung
        self.assertEqual(before["IT-Ausstattung"], ("114.500 € verfügbar", "35.500 € gebunden von 150.000 €"))
        at.session_state["active_request"] = "VA-2026-0001"
        at.run()
        at.button(key="approve_btn").click().run()
        self.assertFalse(at.exception)

        # Meter: committed amount of the position goes up by the approved amount (14,500)
        after = self.budget_meters(at)
        self.assertEqual(after["IT-Ausstattung"], ("100.000 € verfügbar", "50.000 € gebunden von 150.000 €"))
        self.assertEqual(after["Fahrzeuge"], before["Fahrzeuge"])

        # History: in session state and in the JSON file
        entry = self.decided(self.saved_history()["requests"])[0]
        self.assertEqual((entry["ref"], entry["decision"], entry["agent_decision"]), ("VA-2026-0001", "APPROVED", "APPROVED"))
        self.assertEqual(entry["amount"], 14500.0)
        self.assertEqual(self.decided(at.session_state["history"]["requests"])[0]["ref"], "VA-2026-0001")

        # Request history dialog lists the decision
        at.session_state["active_request"] = None
        at.button(key="history_btn_verify").click().run()
        self.assertFalse(at.exception)
        self.assertTrue(any("VA-2026-0001" in m.value for m in at.markdown))

        # Reset Demo Data: 3 pending requests, initial budget, history cleared (seeded tender kept)
        at.button(key="reset_btn").click().run()
        self.assertFalse(at.exception)
        self.assertEqual([r["ref"] for r in at.session_state["request_queue"]], SEEDED_REFS)
        self.assertEqual([r["status"] for r in at.session_state["request_queue"]], ["PENDING"] * 3)
        self.assertEqual(self.remaining_budget("IT-Ausstattung"), 114500.0)
        self.assertEqual(self.budget_meters(at), before)
        saved = self.saved_history()
        self.assertEqual(self.decided(saved["requests"]), [])
        self.assertEqual(len(saved["requests"]), 8)  # the archived demo history
        self.assertEqual(saved["transfers"], [])
        self.assertEqual([t["ref"] for t in saved["tenders"]], ["VA-2025-0412"])

    def test_rejection_reason_and_note_recorded(self):
        at = self.start_app()
        at.session_state["active_request"] = "VA-2026-0002"
        at.run()
        at.text_area(key="caseworker_note_VA-2026-0002").input("Supplier blocked by the procurement office.")
        at.button(key="reject_btn").click().run()
        self.assertFalse(at.exception)
        entry = self.decided(self.saved_history()["requests"])[0]
        self.assertEqual(entry["decision"], "REJECTED")
        self.assertEqual(entry["note"], "Supplier blocked by the procurement office.")
        self.assertIn("unapproved or unknown", entry["agent_reason"])
        self.assertIn("Caseworker note: Supplier blocked", self.latest_audit()[1])

    def test_history_survives_reload_and_decided_seeds_are_not_requeued(self):
        at = self.start_app()
        at.session_state["active_request"] = "VA-2026-0001"
        at.run()
        at.button(key="approve_btn").click().run()

        # A new session (page reload) reads the JSON file
        reloaded = self.start_app()
        self.assertEqual(self.decided(reloaded.session_state["history"]["requests"])[0]["ref"], "VA-2026-0001")
        self.assertEqual([r["ref"] for r in reloaded.session_state["request_queue"]], SEEDED_REFS[1:])

    def test_bid_history_has_seeded_tender_and_records_runs_per_request(self):
        at = self.start_app()
        at.button(key="nav_bids").click().run()
        at.button(key="history_btn_bids").click().run()
        self.assertFalse(at.exception)
        self.assertTrue(any("VA-2025-0412" in e.label for e in at.expander))
        seeded = at.session_state["history"]["tenders"][0]
        self.assertEqual(seeded["bidders"][0]["bidder"], "Bechtle GmbH")
        self.assertEqual(seeded["bidders"][0]["status"], "winner")
        self.assertIsNone(seeded["bidders"][0]["scores"]["references"]["agent"])
        self.assertIsNotNone(seeded["bidders"][0]["scores"]["price"]["agent"])

        # A run with three uploaded quotations for VA-2026-0001 (letters fail: no real Gemini in tests)
        at.session_state["history_view"] = None
        self.approve(at, "VA-2026-0001")
        at.button(key="nav_bids").click().run()
        at.selectbox(key="bid_tender_ref").set_value("VA-2026-0001").run()
        self.upload_bids(at, *BID_FIXTURES)
        self.confirm_scores(at)
        at.segmented_control(key="criteria_preset").set_value("goods").run()
        at.button(key="eval_bids_btn").click().run()
        self.assertFalse(at.exception)
        run = self.saved_history()["tenders"][-1]
        self.assertEqual(run["ref"], "VA-2026-0001")
        self.assertEqual(run["weights"], {"price": 60.0, "delivery": 20.0, "warranty": 20.0})
        self.assertEqual([b["rank"] for b in run["bidders"]], [1, 2, 3])
        self.assertEqual(run["bidders"][0]["status"], "winner")
        self.assertEqual({b["status"] for b in run["bidders"][1:]}, {"failed"})
        for bidder in run["bidders"]:
            for key in run["weights"]:
                # No committee corrections: agent and committee scores agree
                self.assertEqual(bidder["scores"][key]["agent"], bidder["scores"][key]["committee"])

        at.button(key="history_btn_bids").click().run()
        self.assertFalse(at.exception)
        self.assertTrue(any("VA-2026-0001" in e.label for e in at.expander))

    def test_bid_dropdown_lists_only_approved_requests_without_evaluation(self):
        at = self.start_app()
        at.button(key="nav_bids").click().run()
        # Nothing approved yet: info box instead of a dropdown, upload and evaluation disabled
        self.assertEqual(len(at.selectbox), 0)
        self.assertTrue(any("Antragsprüfung" in i.value for i in at.info))
        self.assertNotIn("eval_bids_btn", self.button_keys(at))
        self.assertTrue(at.file_uploader(key=f"bid_pdfs_{at.session_state['bid_upload_nonce']}").proto.disabled)
        at.button(key="go_verify_from_bids").click().run()
        self.assertEqual(at.session_state["current_view"], "verify")

        # Approve 0001, reject 0002 and 0003: only 0001 and "Other tender" are offered
        self.approve(at, "VA-2026-0001")
        for ref in ("VA-2026-0002", "VA-2026-0003"):
            at.session_state["active_request"] = ref
            at.run()
            at.button(key="reject_btn").click().run()
        at.session_state["active_request"] = None
        at.button(key="nav_bids").click().run()
        self.assertEqual(at.selectbox(key="bid_tender_ref").options[0].split(" · ")[0], "VA-2026-0001")
        self.assertEqual(len(at.selectbox(key="bid_tender_ref").options), 2)
        self.assertEqual(at.selectbox(key="bid_tender_ref").options[-1], "Sonstige Ausschreibung (ohne Antrag)")

        # After its evaluation is saved, the request leaves the dropdown and the info box returns
        self.upload_bids(at, *BID_FIXTURES)
        self.confirm_scores(at)
        at.segmented_control(key="criteria_preset").set_value("goods").run()
        at.button(key="eval_bids_btn").click().run()
        self.assertEqual(self.saved_history()["tenders"][-1]["ref"], "VA-2026-0001")
        at.run()
        self.assertEqual(len(at.selectbox), 0)
        self.assertNotIn("eval_bids_btn", self.button_keys(at))
        self.assertEqual(len(at.data_editor), 0)

        # Reset Demo Data: nothing approved again
        at.button(key="reset_btn").click().run()
        self.assertEqual(len(at.selectbox), 0)

    def test_budget_meters_follow_language(self):
        at = self.start_app()
        at.segmented_control(key="lang_toggle").set_value("EN").run()
        meters = self.budget_meters(at)
        self.assertEqual(meters["IT-Ausstattung"], ("€114,500 left", "€35,500 committed of €150,000"))
        self.assertTrue(any("Total available: €388,750 of €435,000" in m.value for m in at.sidebar.markdown))

    # --- Budget transfer (Deckungsantrag) ---------------------------------------------------

    def test_approve_with_transfer_updates_both_lines(self):
        at = self.start_app()
        at.session_state["active_request"] = "VA-2026-0003"
        at.run()
        self.assertFalse(at.exception)
        # Fahrzeuge has 72,700 left; 76,000 needs 3,300 more. Same account type first, most funds first.
        options = at.radio(key="transfer_choice_VA-2026-0003").options
        self.assertEqual([o.split(" · ")[0] for o in options], ["IT-Ausstattung", "Gebäudeunterhaltung", "Büromaterial"])
        self.assertTrue(all("§ 19 KomHKVO" in o for o in options))
        self.assertEqual(len(at.get("download_button")), 1)
        self.assertEqual(at.session_state["history"]["transfers"][0]["ref"], "VA-2026-0003")

        # Nothing moves until the caseworker approves with the transfer included
        at.radio(key="transfer_choice_VA-2026-0003").set_value(1).run()
        at.checkbox(key="transfer_include_VA-2026-0003").check().run()
        self.assertEqual(self.remaining_budget("Fahrzeuge"), 72700.0)
        self.assertEqual(at.button(key="approve_btn").proto.type, "primary")
        at.button(key="approve_btn").click().run()
        self.assertFalse(at.exception)

        # Fahrzeuge: +3,300 transfer, -76,000 order; Gebäudeunterhaltung: -3,300
        self.assertEqual(self.remaining_budget("Fahrzeuge"), 0.0)
        self.assertEqual(self.remaining_budget("Gebäudeunterhaltung"), 56700.0)
        meters = self.budget_meters(at)
        self.assertEqual(meters["Fahrzeuge"], ("0 € verfügbar", "83.300 € gebunden von 83.300 €"))
        self.assertEqual(meters["Gebäudeunterhaltung"], ("56.700 € verfügbar", "0 € gebunden von 56.700 €"))
        transfer = self.saved_history()["transfers"][0]
        self.assertTrue(transfer["accepted"])
        self.assertEqual((transfer["donor"], transfer["amount"], transfer["legal_basis"]), ("Gebäudeunterhaltung", 3300.0, "§ 19 KomHKVO"))
        entry = self.decided(self.saved_history()["requests"])[0]
        self.assertEqual((entry["caseworker_decision"], entry["override"]), ("APPROVED", False))
        self.assertEqual(entry["transfer"]["donor"], "Gebäudeunterhaltung")
        self.assertTrue(any("Budgetverschiebung" in s.value for s in at.success))

        # Reset Demo Data restores the budgets and clears the transfer
        at.session_state["active_request"] = None
        at.button(key="reset_btn").click().run()
        self.assertEqual(self.remaining_budget("Fahrzeuge"), 72700.0)
        self.assertEqual(self.remaining_budget("Gebäudeunterhaltung"), 60000.0)
        self.assertEqual(self.saved_history()["transfers"], [])

    def test_reject_with_transfer_ticked_moves_nothing(self):
        at = self.start_app()
        at.session_state["active_request"] = "VA-2026-0003"
        at.run()
        at.checkbox(key="transfer_include_VA-2026-0003").check().run()
        at.button(key="reject_btn").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(self.remaining_budget("Fahrzeuge"), 72700.0)
        self.assertEqual(self.remaining_budget("IT-Ausstattung"), 114500.0)
        self.assertFalse(self.saved_history()["transfers"][0]["accepted"])
        self.assertNotEqual(self.latest_audit()[0], "TRANSFER")

    def test_no_transfer_offered_when_budget_suffices_or_supplier_blocked(self):
        at = self.start_app()
        for ref in ("VA-2026-0001", "VA-2026-0002"):
            at.session_state["active_request"] = ref
            at.run()
            self.assertFalse(at.exception)
            self.assertEqual(len(at.radio), 0, ref)
        self.assertEqual(at.session_state["history"]["transfers"], [])

    # --- Management Insights ---------------------------------------------------------------

    def test_insights_tiles_from_demo_history(self):
        at = self.start_app()
        at.button(key="nav_insights").click().run()
        self.assertFalse(at.exception)

        budget = at.dataframe[0].value.set_index("line")
        # IT-Ausstattung: 2 orders (7,200 + 9,800) in the last 90 days -> a projected date
        self.assertNotIn(budget.loc["IT-Ausstattung", "runout"], ("zu wenig Daten", "ausgeschöpft"))
        # Büromaterial: only one approved order in the window -> no invented date
        self.assertEqual(budget.loc["Büromaterial", "runout"], "zu wenig Daten")
        self.assertEqual(budget.loc["Feuerwehrtechnik", "runout"], "zu wenig Daten")

        shares = at.dataframe[1].value
        it = shares[shares["line"] == "IT-Ausstattung"].set_index("supplier")
        self.assertAlmostEqual(it.loc["Cancom SE", "share"], 52.1)  # 18,500 of 35,500
        self.assertTrue(any("über 40 %" in w.value for w in at.warning))

        # 7 of 8 demo decisions agree; VA-2026-H08 is the override
        self.assertEqual(at.metric[0].value, "88 %")
        self.assertEqual(at.metric[1].value, "1")
        overrides = at.dataframe[2].value
        self.assertEqual(overrides["ref"].tolist(), ["VA-2026-H08"])
        self.assertEqual(at.metric[3].value, "0 / 0")

        at.segmented_control(key="lang_toggle").set_value("EN").run()
        self.assertFalse(at.exception)
        self.assertEqual(at.dataframe[0].value.set_index("line").loc["Büromaterial", "runout"], "not enough data")
        self.assertEqual(at.metric[0].value, "88%")

    def test_insights_count_transfers_proposed_and_accepted(self):
        at = self.start_app()
        at.session_state["active_request"] = "VA-2026-0003"
        at.run()
        at.checkbox(key="transfer_include_VA-2026-0003").check().run()
        at.button(key="approve_btn").click().run()
        at.session_state["active_request"] = None
        at.button(key="nav_insights").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.metric[3].value, "1 / 1")


if __name__ == "__main__":
    unittest.main()
