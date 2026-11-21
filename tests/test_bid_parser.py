import unittest
from pathlib import Path

from fpdf import FPDF

from helpers import PROJECT_ROOT  # noqa: F401  (adds the project root to sys.path)
from src.bid_parser import (
    BidExtractionError,
    extract_pdf_text,
    normalize_amount,
    parse_bid_pdf,
    parse_bid_text,
    parse_duration_days,
    parse_duration_months,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class TestNormalizeAmount(unittest.TestCase):
    def test_german_formats(self):
        for text, expected in (
            ("15.200,00 €", 15200.0),
            ("15.200,00", 15200.0),
            ("EUR 15.200,00", 15200.0),
            ("15200,00", 15200.0),
            ("15200,5", 15200.5),
            ("15.200", 15200.0),
            ("15.200,-", 15200.0),
            ("1.234.567,89", 1234567.89),
            ("15 200,00 €", 15200.0),
            ("15 200,00", 15200.0),
            ("-1.000,00", -1000.0),
        ):
            with self.subTest(text=text):
                self.assertEqual(normalize_amount(text), expected)

    def test_english_formats(self):
        for text, expected in (
            ("EUR 15200.00", 15200.0),
            ("€15,200.00", 15200.0),
            ("15,200.00 EUR", 15200.0),
            ("15200.00", 15200.0),
            ("15,200", 15200.0),
            ("1,234,567.89", 1234567.89),
            ("0.99", 0.99),
            ("15200", 15200.0),
        ):
            with self.subTest(text=text):
                self.assertEqual(normalize_amount(text), expected)

    def test_invalid_values_return_none(self):
        for text in (None, "", "abc", "EUR", "12.34.56", "1,2,3", "15.20.00"):
            with self.subTest(text=text):
                self.assertIsNone(normalize_amount(text))

    def test_numbers_pass_through(self):
        self.assertEqual(normalize_amount(15200), 15200.0)
        self.assertEqual(normalize_amount(15200.5), 15200.5)


class TestDurations(unittest.TestCase):
    def test_delivery_days(self):
        for text, expected in (
            ("1 week", 7), ("2 weeks", 14), ("5 Werktage", 5), ("10 days", 10),
            ("2-3 Wochen", 21), ("1 Monat", 30), ("sofort", None),
        ):
            with self.subTest(text=text):
                self.assertEqual(parse_duration_days(text), expected)

    def test_warranty_months(self):
        for text, expected in (("3 years", 36), ("24 Monate", 24), ("2 Jahre", 24), ("6 weeks", None)):
            with self.subTest(text=text):
                self.assertEqual(parse_duration_months(text), expected)


class TestBidParsing(unittest.TestCase):
    def test_bechtle_fixture_pdf(self):
        bid = parse_bid_pdf((FIXTURES / "Bechtle_bid.pdf").read_bytes(), "Bechtle_bid.pdf")
        self.assertEqual(bid["bidder"], "Bechtle GmbH")
        self.assertEqual(bid["bidder_source"], "pdf")
        self.assertEqual(bid["price"], 15200.0)
        self.assertEqual(bid["price_basis"], "total")
        self.assertEqual(bid["item"], "15 HP EliteBook Laptops (3 years warranty)")
        self.assertEqual(bid["quantity"], 15)
        self.assertEqual(bid["warranty_months"], 36)
        self.assertEqual(bid["delivery"], "1 week")
        self.assertEqual(bid["delivery_days"], 7)
        self.assertEqual(bid["missing"], [])
        self.assertEqual(bid["sources"]["price"], "Total Price: EUR 15200.00")

    def test_other_fixture_pdfs(self):
        dell = parse_bid_pdf((FIXTURES / "dell_bid.pdf").read_bytes(), "dell_bid.pdf")
        self.assertEqual((dell["bidder"], dell["price"], dell["delivery_days"], dell["warranty_months"]),
                         ("Dell Technologies", 14500.0, 14, 36))
        office = parse_bid_pdf((FIXTURES / "OfficeDepot_bid.pdf").read_bytes(), "OfficeDepot_bid.pdf")
        self.assertEqual((office["bidder"], office["price"], office["price_basis"], office["delivery_days"]),
                         ("OfficeDepot Deutschland GmbH", 16200.0, "gross", 21))
        self.assertEqual(office["warranty_months"], 24)

    def test_german_quote_prefers_gross_and_ignores_unit_price(self):
        bid = parse_bid_text(
            "Muster IT-Systeme GmbH\n"
            "Angebot Nr. 4711\n"
            "Artikel: 20 Stück Monitore\n"
            "Einzelpreis: 250,00 €\n"
            "Nettobetrag 5.000,00 €\n"
            "MwSt 19 %: 950,00 €\n"
            "Gesamtpreis brutto: 5.950,00 €\n"
            "Lieferzeit: 2-3 Wochen\n"
            "Gewährleistung: 24 Monate\n",
            "angebot.pdf",
        )
        self.assertEqual(bid["bidder"], "Muster IT-Systeme GmbH")
        self.assertEqual(bid["bidder_source"], "letterhead")
        self.assertEqual((bid["price"], bid["price_basis"]), (5950.0, "gross"))
        self.assertEqual((bid["price_net"], bid["price_gross"]), (5000.0, 5950.0))
        self.assertEqual(bid["quantity"], 20)
        self.assertEqual(bid["delivery_days"], 21)
        self.assertEqual(bid["warranty_months"], 24)

    def test_price_labels(self):
        for text, expected, basis in (
            ("Anbieter: X GmbH\nGesamtpreis: 15.200,00 €", 15200.0, "total"),
            ("Supplier: X Ltd\nTotal Price: €15,200.00", 15200.0, "total"),
            ("Anbieter: X GmbH\nSumme netto: 10.000,00 EUR", 10000.0, "net"),
            ("Anbieter: X GmbH\nGesamtsumme\n12.345,67 €", 12345.67, "total"),
            ("Supplier: X Inc\nTotal (gross): EUR 11,900.00", 11900.0, "gross"),
        ):
            with self.subTest(text=text):
                bid = parse_bid_text(text)
                self.assertEqual((bid["price"], bid["price_basis"]), (expected, basis))

    def test_bidder_falls_back_to_filename_only_when_nothing_found(self):
        bid = parse_bid_text("OFFICIAL QUOTATION\nTotal Price: EUR 900.00", "dell_bid.pdf")
        self.assertEqual(bid["bidder"], "dell")
        self.assertEqual(bid["bidder_source"], "filename")
        self.assertIn("bidder", bid["missing"])

    def test_missing_fields_are_none_not_defaults(self):
        bid = parse_bid_text("Supplier: Bechtle GmbH\nTotal Price: EUR 15200.00")
        for key in ("item", "quantity", "delivery_days", "warranty_months"):
            self.assertIsNone(bid[key])
        self.assertEqual(set(bid["missing"]), {"item", "quantity", "delivery", "warranty"})

    def test_pdf_without_text_raises(self):
        pdf = FPDF()
        pdf.add_page()
        with self.assertRaises(BidExtractionError):
            extract_pdf_text(bytes(pdf.output()))
        with self.assertRaises(BidExtractionError):
            extract_pdf_text(b"not a pdf")


if __name__ == "__main__":
    unittest.main()
