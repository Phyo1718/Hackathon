import os
import sys
import unittest
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.init_db import init_db
from src.agent import check_supplier, check_budget, commit_decision, evaluate_bids, generate_anmeldebogen_pdf, check_contract_extension

class TestProcurementAgent(unittest.TestCase):
    def setUp(self):
        init_db()

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

    def test_evaluate_bids(self):
        bids = [
            {"bidder": "Dell Technologies", "price": 14500.0, "references_score": 8, "concept_score": 8},
            {"bidder": "Bechtle GmbH", "price": 15200.0, "references_score": 7, "concept_score": 7}
        ]
        res = evaluate_bids(bids)
        self.assertIn("winner", res)
        self.assertIn("ranked_bids", res)
        self.assertIn("losers", res)
        self.assertEqual(res["winner"]["bidder"], "Dell Technologies")

    def test_generate_anmeldebogen_pdf(self):
        eval_data = {
            "supplier_name": "Dell Technologies",
            "amount": 14500.0,
            "category": "IT-Ausstattung",
            "summary": "Procurement of laptops",
            "procurement_type": "Auftragserweiterung"
        }
        pdf_bytes = generate_anmeldebogen_pdf(eval_data)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertGreater(len(pdf_bytes), 100)

if __name__ == "__main__":
    unittest.main()
