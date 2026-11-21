import re
import unittest
from urllib.parse import parse_qs, unquote, urlparse

from helpers import PROJECT_ROOT  # noqa: F401  (adds the project root to sys.path)
from src.agent import CRITERIA_PRESETS
from src.letters import (
    MAILTO_BODY_LIMIT,
    award_letter,
    build_letters,
    criterion_label,
    email_lock_reasons,
    email_body,
    gmail_url,
    letter_for,
    letter_pdf,
    mailto_url,
    rejection_letter,
)


def scores(price, references, concept):
    return {key: {"agent": None, "committee": value}
            for key, value in (("price", price), ("references", references), ("concept", concept))}


RUN = {
    "ref": "VA-2026-0001",
    "title": {"DE": "15 Dell Laptops für das digitale Verwaltungsteam", "EN": "15 Dell laptops for the team"},
    "weights": {"price": 37.5, "references": 37.5, "concept": 25.0},
    "bidders": [
        {"bidder": "Bechtle GmbH", "price": 15200.0, "rank": 1, "total_points": 81.94, "item": "15 HP EliteBook Laptops",
         "quantity": 15, "email": "vergabe@bechtle.example", "scores": scores(9.52, 7.0, 8.0)},
        {"bidder": "Dell Technologies", "price": 14500.0, "rank": 2, "total_points": 72.5, "item": "15 Dell Latitude",
         "quantity": 15, "email": "angebote@dell.example", "scores": scores(10.0, 4.0, 8.0)},
        {"bidder": "OfficeDepot Deutschland GmbH", "price": 16200.0, "rank": 3, "total_points": 60.6,
         "item": "15 Lenovo ThinkPad", "quantity": 15, "email": "vertrieb@officedepot.example",
         "scores": scores(8.83, 2.0, 8.0)},
    ],
}
WINNER, DELL, OFFICE = RUN["bidders"]


class TestLetters(unittest.TestCase):
    def test_award_letter_has_reference_item_quantity_price_and_next_steps(self):
        letter = award_letter(RUN, WINNER, "DE")
        self.assertEqual(letter["subject"], "Zuschlag – VA-2026-0001: 15 Dell Laptops für das digitale Verwaltungsteam")
        for part in ("Gegenstand: 15 HP EliteBook Laptops", "Menge: 15", "Zuschlagspreis: 15.200,00 EUR",
                     "folgt gesondert durch die Stadt Hildesheim", "[Name, Telefon und E-Mail der Ansprechperson"):
            self.assertIn(part, letter["body"])
        english = award_letter(RUN, WINNER, "EN")
        self.assertIn("Awarded price: EUR 15,200.00", english["body"])
        self.assertTrue(english["subject"].startswith("Award of contract – VA-2026-0001"))

    def test_rejection_letter_names_winner_and_reasons_without_other_prices_or_scores(self):
        for lang in ("DE", "EN"):
            for loser in (DELL, OFFICE):
                letter = rejection_letter(RUN, loser, lang)
                body = letter["body"]
                self.assertIn("Bechtle GmbH", body)
                self.assertIn("§ 46 UVgO", body)
                # No prices at all, no scores or totals of other bidders
                self.assertNotRegex(body, r"\d+[.,]\d{2}")
                self.assertNotIn("EUR", body)
                for other in RUN["bidders"]:
                    self.assertNotIn(f"{other['total_points']}", body)
        dell = rejection_letter(RUN, DELL, "DE")["body"]
        self.assertIn("Rang 2 von 3", dell)
        self.assertIn("Bewertung Ihres Angebots: Preis: sehr gut; Referenzen / Service: ausreichend; Konzept / Qualität: gut", dell)
        self.assertIn("insbesondere bei Referenzen / Service.", dell)
        self.assertIn("Bei Preis und Konzept / Qualität hat Ihr Angebot mindestens ebenso gut abgeschnitten", dell)
        self.assertIn("in particular on references / service", rejection_letter(RUN, DELL, "EN")["body"])

    def test_letter_for_picks_award_or_rejection(self):
        self.assertTrue(letter_for(RUN, WINNER, "EN")["subject"].startswith("Award"))
        self.assertTrue(letter_for(RUN, OFFICE, "EN")["subject"].startswith("Your offer was not selected"))

    def test_mailto_is_encoded_for_one_recipient(self):
        letter = rejection_letter(RUN, DELL, "DE")
        url = mailto_url("angebote@dell.example", letter["subject"], letter["body"])
        self.assertTrue(url.startswith("mailto:angebote@dell.example?subject="))
        self.assertNotIn(" ", url)
        self.assertNotIn("cc=", url.lower())
        self.assertIn("%0D%0A", url)
        query = parse_qs(urlparse(url).query)
        self.assertEqual(query["subject"][0], letter["subject"])
        self.assertEqual(query["body"][0].replace("\r\n", "\n"), letter["body"])
        gmail = parse_qs(urlparse(gmail_url("angebote@dell.example", letter["subject"], letter["body"])).query)
        self.assertEqual((gmail["view"][0], gmail["to"][0], gmail["su"][0]), ("cm", "angebote@dell.example", letter["subject"]))

    def test_long_letter_is_shortened_with_pdf_note(self):
        letter = award_letter(RUN, WINNER, "DE")
        self.assertFalse(email_body(letter, "DE")["shortened"])
        long_letter = {"subject": "S", "body": "\n\n".join(["Absatz " + "x" * 500] * 6)}
        short = email_body(long_letter, "DE")
        self.assertTrue(short["shortened"])
        self.assertLessEqual(len(short["body"]), MAILTO_BODY_LIMIT)
        self.assertIn("als PDF bei", short["body"])
        self.assertTrue(letter_pdf(long_letter).startswith(b"%PDF"))


class TestCriteriaSetsAndLocks(unittest.TestCase):
    def run_for(self, preset):
        weights = CRITERIA_PRESETS[preset]
        bidders = []
        for rank, (name, base) in enumerate((("A GmbH", 9.0), ("B AG", 6.0)), start=1):
            bidders.append({"bidder": name, "price": 1000.0 * rank, "rank": rank, "total_points": base * 10,
                            "item": "15 Laptops", "quantity": 15, "email": f"{rank}@x.example",
                            "scores": {k: {"agent": None, "committee": base} for k in weights}})
        return {"ref": "VA-1", "title": "Laptops", "weights": weights, "bidders": bidders}

    def test_letters_for_both_criteria_sets_in_both_languages(self):
        for preset in ("sheet", "goods"):
            run = self.run_for(preset)
            for lang in ("DE", "EN"):
                self.assertIn("A GmbH", rejection_letter(run, run["bidders"][1], lang)["body"])
                self.assertIn("15 Laptops", award_letter(run, run["bidders"][0], lang)["body"])
        goods = rejection_letter(self.run_for("goods"), self.run_for("goods")["bidders"][1], "EN")["body"]
        self.assertIn("price (60 %), delivery time (20 %) and warranty (20 %)", goods)

    def test_criterion_label_falls_back_to_key(self):
        self.assertEqual(criterion_label("references", "DE"), "Referenzen / Service")
        self.assertEqual(criterion_label("references", "EN"), "references / service")
        self.assertEqual(criterion_label("unknown_criterion", "EN"), "unknown_criterion")

    def test_build_letters_stores_both_languages_once(self):
        run = build_letters(self.run_for("sheet"), "2026-11-21T10:00:00")
        letter = run["bidders"][0]["letter"]
        self.assertEqual(set(letter), {"type", "to", "subject_de", "subject_en", "body_de", "body_en",
                                       "generated_at", "sent_at"})
        self.assertEqual((letter["type"], letter["to"], letter["sent_at"]), ("award", "1@x.example", None))
        self.assertEqual(run["bidders"][1]["letter"]["type"], "rejection")

    def test_email_lock_reasons(self):
        run = build_letters(self.run_for("sheet"), "2026-11-21T10:00:00")
        award, rejection = run["bidders"]
        # Not approved: every letter locked, award and rejections alike
        self.assertEqual(email_lock_reasons(run, award), ["approval_missing"])
        self.assertEqual(email_lock_reasons(run, rejection), ["approval_missing"])
        # Approved and an address: award and rejections enabled at once, in any order
        run["award_approved"] = True
        self.assertEqual(email_lock_reasons(run, award), [])
        self.assertEqual(email_lock_reasons(run, rejection), [])
        # "Mark as sent" never locks or unlocks anything
        rejection["letter"]["sent_at"] = "2026-11-21T10:15:00"
        self.assertEqual((email_lock_reasons(run, award), email_lock_reasons(run, rejection)), ([], []))
        # No address: disabled with that reason
        award["letter"]["to"] = None
        self.assertEqual(email_lock_reasons(run, award), ["email_missing"])

if __name__ == "__main__":
    unittest.main()
