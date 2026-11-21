import unittest

from helpers import PROJECT_ROOT  # noqa: F401  (adds the project root to sys.path)
from src.agent import calculate_price_score, score_criterion
from src.bid_parser import parse_bid_text
from src.bid_scoring import RUBRIC, explain, item_quantity, item_types, score_bid

REQUEST = {"ref": "VA-2026-0001", "category": "IT-Ausstattung",
           "text": "15 Dell Laptops für das digitale Verwaltungsteam"}
HISTORY = [
    {"ref": "VA-2026-H06", "supplier": "Bechtle GmbH", "category": "IT-Ausstattung",
     "decision": "APPROVED", "decided_at": "2026-10-20T10:00:00"},
    {"ref": "VA-2026-H05", "supplier": "TechCorp", "category": "IT-Ausstattung",
     "decision": "REJECTED", "decided_at": "2026-09-20T10:00:00"},
]
SUPPLIERS = {
    "bechtle gmbh": {"supplier_name": "Bechtle GmbH", "exists": True, "is_approved": True, "category": "IT-Ausstattung"},
    "dell technologies": {"supplier_name": "Dell Technologies", "exists": True, "is_approved": True, "category": "IT-Ausstattung"},
    "techcorp": {"supplier_name": "TechCorp", "exists": True, "is_approved": False, "category": "IT-Ausstattung"},
}


def supplier_db(name):
    return SUPPLIERS.get(name.lower(), {"supplier_name": name, "exists": False, "is_approved": False, "category": None})


def bid(**facts):
    base = {"bidder": None, "item": None, "quantity": None, "price_basis": None, "delivery_days": None,
            "warranty_months": None, "references": [], "on_site_service": False, "validity": None}
    base.update(facts)
    return base


class TestScoreBid(unittest.TestCase):
    def test_full_evidence_gives_ten_points_each(self):
        full = bid(bidder="Bechtle GmbH", item="15 HP EliteBook 840 Laptops", quantity=15, price_basis="net",
                   delivery_days=7, warranty_months=36, validity="31.12.2026",
                   references=["Stadt Hannover", "Landkreis Peine"])
        result = score_bid(full, REQUEST, supplier_db, HISTORY)
        self.assertEqual(result["references"]["score"], 10)
        self.assertEqual(result["concept"]["score"], 10)
        self.assertEqual(
            explain(result["references"], "EN"),
            "+4 previous contract VA-2026-H06 · +3 2 references in bid · +3 warranty 3 years",
        )
        self.assertEqual(
            explain(result["concept"], "EN"),
            "+4 15 laptops as requested (brand not assessed) · +3 delivery 7 days"
            " · +3 stated: price basis, specification, offer validity",
        )

    def test_no_evidence_is_required(self):
        result = score_bid(bid(bidder="Unbekannt Handel GmbH", price_basis="total"), REQUEST, supplier_db, HISTORY)
        for key in ("references", "concept"):
            self.assertIsNone(result[key]["score"])
            self.assertFalse(result[key]["evidence"])
        self.assertEqual(result["references"]["missing_reason"]["EN"], "no track record and none named in bid")

    def test_brand_is_not_rewarded(self):
        # The request names Dell; an equivalent HP or Lenovo laptop is a full match
        scores = {
            item: score_bid(bid(bidder="X", item=item, quantity=15), REQUEST, supplier_db, [])["concept"]["components"][0]
            for item in ("15 Dell Latitude 5450 Laptops", "15 HP EliteBook Laptops", "15 Lenovo ThinkPad E14")
        }
        self.assertEqual({c["points"] for c in scores.values()}, {RUBRIC["concept"]["fit"]["match"]})

    def test_partial_and_no_match(self):
        partial = score_bid(bid(bidder="X", item="10 HP Laptops", quantity=10), REQUEST, supplier_db, [])
        self.assertEqual(partial["concept"]["components"][0]["points"], RUBRIC["concept"]["fit"]["partial"])
        self.assertIn("quantity 10 instead of 15", explain(partial["concept"], "EN"))
        wrong = score_bid(bid(bidder="X", item="15 Bürostühle", quantity=15), REQUEST, supplier_db, [])
        self.assertEqual(wrong["concept"]["components"][0]["points"], 0)
        self.assertTrue(wrong["concept"]["evidence"])

    def test_track_record_levels(self):
        def track(name, history=HISTORY, request=REQUEST):
            return score_bid(bid(bidder=name), request, supplier_db, history)["references"]["components"][0]

        self.assertEqual(track("Bechtle GmbH")["points"], 4)
        self.assertEqual(track("Dell Technologies")["points"], 2)
        self.assertEqual(track("Unbekannt Handel GmbH")["points"], 0)
        self.assertEqual(track("TechCorp")["reason"]["EN"], "listed as not approved")
        # The tender itself is no previous contract, nor is a contract in another category
        self.assertEqual(track("Bechtle GmbH", request={**REQUEST, "ref": "VA-2026-H06"})["points"], 2)
        self.assertEqual(track("Bechtle GmbH", request={**REQUEST, "category": "Büromaterial"})["points"], 0)

    def test_warranty_and_delivery_bands(self):
        def points(**facts):
            result = score_bid(bid(bidder="X", **facts), REQUEST, supplier_db, [])
            return {c["key"]: c["points"] for key in result for c in result[key]["components"]}

        self.assertEqual(points(warranty_months=24)["warranty"], 2)
        self.assertEqual(points(warranty_months=12)["warranty"], 1)
        self.assertEqual(points(on_site_service=True)["warranty"], 3)
        self.assertEqual(points(delivery_days=14)["delivery"], 3)
        self.assertEqual(points(delivery_days=28)["delivery"], 2)
        self.assertEqual(points(delivery_days=42)["delivery"], 1)

    def test_item_facts_from_text(self):
        self.assertEqual(item_types("15 HP EliteBook Laptops"), ["laptop"])
        self.assertEqual(item_types("20 pcs docking stations"), ["docking"])
        self.assertEqual(item_quantity("Beschaffung von 15 Dell Laptops"), 15)
        self.assertIsNone(item_quantity("Server infrastructure setup"))


class TestPriceFormula(unittest.TestCase):
    def test_excel_example(self):
        # Auswertung_Hackathon.XLSX: lowest 50,000 = 10 points, 70,000 = 6 points, 2 x lowest = 0
        self.assertEqual(calculate_price_score(50000.0, 50000.0), 10.0)
        self.assertAlmostEqual(calculate_price_score(70000.0, 50000.0), 6.0)
        self.assertEqual(calculate_price_score(100000.0, 50000.0), 0.0)
        self.assertEqual(calculate_price_score(120000.0, 50000.0), 0.0)
        self.assertEqual(score_criterion("price", [50000.0, 70000.0], ["A", "B"]), [10.0, 6.0])


class TestParserFacts(unittest.TestCase):
    def test_references_service_and_validity(self):
        parsed = parse_bid_text(
            "Supplier: X GmbH\nReferenzen: Stadt Hannover (2024), Landkreis Peine (2023)\n"
            "Service: Vor-Ort-Service am nächsten Werktag\nAngebot gültig bis 31.12.2026\n"
            "Gesamtpreis netto: 1.000,00 EUR"
        )
        self.assertEqual(parsed["references"], ["Stadt Hannover (2024)", "Landkreis Peine (2023)"])
        self.assertTrue(parsed["on_site_service"])
        self.assertEqual(parsed["validity"], "bis 31.12.2026")
        self.assertEqual(parsed["sources"]["references"], "Referenzen: Stadt Hannover (2024), Landkreis Peine (2023)")
        none = parse_bid_text("Supplier: X GmbH\nReferences: none\nTotal: EUR 5")
        self.assertEqual(none["references"], [])
        self.assertFalse(none["on_site_service"])
        self.assertIsNone(none["validity"])


if __name__ == "__main__":
    unittest.main()
