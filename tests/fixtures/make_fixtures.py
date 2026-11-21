"""Regenerates the bid PDF fixtures. Run: .venv/bin/python tests/fixtures/make_fixtures.py"""
from pathlib import Path

from fpdf import FPDF

FIXTURES = {
    "Bechtle_bid.pdf": [
        "OFFICIAL QUOTATION",
        "Supplier: Bechtle GmbH",
        "Item: 15 HP EliteBook Laptops (3 years warranty)",
        "Total Price: EUR 15200.00",
        "Delivery: 1 week",
    ],
    # Stand-ins for the other two demo quotations (English and German layout)
    "dell_bid.pdf": [
        "QUOTATION",
        "Supplier: Dell Technologies",
        "Item: 15 Dell Latitude 5450 Laptops (3 years warranty)",
        "Total Price: EUR 14,500.00",
        "Delivery: 2 weeks",
        "Contact: angebote@dell.example",
    ],
    "OfficeDepot_bid.pdf": [
        "ANGEBOT",
        "Anbieter: OfficeDepot Deutschland GmbH",
        "Artikel: 15 Lenovo ThinkPad E14 Laptops",
        "Gesamtpreis brutto: 16.200,00 EUR",
        "Lieferzeit: 3 Wochen",
        "Garantie: 24 Monate",
    ],
}


def write_fixture(path: Path, lines) -> None:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    for line in lines:
        pdf.cell(0, 8, line, new_x="LMARGIN", new_y="NEXT")
    path.write_bytes(bytes(pdf.output()))


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    for name, lines in FIXTURES.items():
        write_fixture(here / name, lines)
        print("wrote", here / name)
