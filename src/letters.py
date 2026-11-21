"""Award and rejection letters for the bid evaluation (§ 46 UVgO) and their email links.

The letters are fixed templates filled from a saved evaluation run (see app.build_tender_entry),
so their content is predictable: a rejection letter names the successful bidder and explains
the recipient's own result in words, but never contains the winner's price, any other
bidder's price or any other bidder's score.
"""
from typing import Any, Dict, List
from urllib.parse import quote, urlencode

from fpdf import FPDF

from src.agent import CRITERIA, _pdf_safe

# mailto: links longer than this body are cut by some mail programs (Outlook)
MAILTO_BODY_LIMIT = 1800
CONTACT_PLACEHOLDER = {
    "DE": "[Name, Telefon und E-Mail der Ansprechperson in der Vergabestelle]",
    "EN": "[Name, phone and email of the contact person at the procurement office]",
}
SENDER = {"DE": "Stadt Hildesheim – Zentrale Vergabestelle", "EN": "City of Hildesheim – Central Procurement Office"}

# 0-10 points in words, used for the recipient's own result only
LEVELS = [
    (8.5, {"DE": "sehr gut", "EN": "very good"}),
    (6.5, {"DE": "gut", "EN": "good"}),
    (4.5, {"DE": "befriedigend", "EN": "satisfactory"}),
    (2.0, {"DE": "ausreichend", "EN": "adequate"}),
    (0.0, {"DE": "gering", "EN": "low"}),
]

TEXT = {
    "DE": {
        "award_subject": "Zuschlag – {ref}: {title}",
        "award_body": (
            "Sehr geehrte Damen und Herren,\n\n"
            "wir freuen uns, Ihnen mitzuteilen, dass Ihr Angebot im Vergabeverfahren {ref} ({title}) "
            "den Zuschlag erhält.\n\n"
            "Gegenstand: {item}\nMenge: {quantity}\nZuschlagspreis: {price}\n\n"
            "Mit diesem Schreiben wird der Zuschlag erteilt; damit kommt der Vertrag zustande. "
            "Die Bestellung bzw. der Vertrag mit den Einzelheiten zu Lieferung und Rechnungsstellung "
            "folgt gesondert durch die Stadt Hildesheim.\n\n"
            "Ansprechperson: {contact}\n\n"
            "Mit freundlichen Grüßen\n{sender}"
        ),
        "rejection_subject": "Nichtberücksichtigung Ihres Angebots – {ref}: {title}",
        "rejection_body": (
            "Sehr geehrte Damen und Herren,\n\n"
            "vielen Dank für Ihr Angebot im Vergabeverfahren {ref} ({title}). Gemäß § 46 UVgO teilen "
            "wir Ihnen mit, dass Ihr Angebot nicht berücksichtigt werden kann. Der Zuschlag soll auf "
            "das Angebot von {winner} erteilt werden.\n\n"
            "Gewertet wurde nach den bekannt gegebenen Kriterien {criteria}. Ihr Angebot belegte "
            "Rang {rank} von {count}. Bewertung Ihres Angebots: {own}.\n\n"
            "Das Angebot von {winner} war insgesamt wirtschaftlicher{advantages}.{strengths}\n\n"
            "Wir danken Ihnen für Ihre Teilnahme und würden uns freuen, wenn Sie sich auch an "
            "künftigen Ausschreibungen der Stadt Hildesheim beteiligen.\n\n"
            "Ansprechperson: {contact}\n\n"
            "Mit freundlichen Grüßen\n{sender}"
        ),
        "advantages": ", insbesondere bei {criteria}",
        "strengths": " Bei {criteria} hat Ihr Angebot mindestens ebenso gut abgeschnitten; das hat den Abstand jedoch nicht ausgeglichen.",
        "and": " und ",
        "quantity_unknown": "laut Angebot",
        "short_note": "\n\n[…] Das vollständige Schreiben liegt dieser E-Mail als PDF bei.\n\nMit freundlichen Grüßen\n{sender}",
    },
    "EN": {
        "award_subject": "Award of contract – {ref}: {title}",
        "award_body": (
            "Dear Sir or Madam,\n\n"
            "We are pleased to inform you that your offer in the procurement procedure {ref} ({title}) "
            "has been accepted.\n\n"
            "Item: {item}\nQuantity: {quantity}\nAwarded price: {price}\n\n"
            "This letter awards the contract; the contract is thereby concluded. The order or contract "
            "with the details of delivery and invoicing will follow separately from the City of "
            "Hildesheim.\n\n"
            "Contact person: {contact}\n\n"
            "Kind regards\n{sender}"
        ),
        "rejection_subject": "Your offer was not selected – {ref}: {title}",
        "rejection_body": (
            "Dear Sir or Madam,\n\n"
            "Thank you for your offer in the procurement procedure {ref} ({title}). In accordance with "
            "§ 46 UVgO we inform you that your offer cannot be accepted. The contract is to be awarded "
            "to {winner}.\n\n"
            "Offers were evaluated against the published criteria {criteria}. Your offer ranked "
            "{rank} of {count}. Assessment of your offer: {own}.\n\n"
            "The offer of {winner} was more economical overall{advantages}.{strengths}\n\n"
            "Thank you for taking part. We would be pleased to receive your offers in future tenders "
            "of the City of Hildesheim.\n\n"
            "Contact person: {contact}\n\n"
            "Kind regards\n{sender}"
        ),
        "advantages": ", in particular on {criteria}",
        "strengths": " On {criteria} your offer did at least as well; this did not make up for the difference.",
        "and": " and ",
        "quantity_unknown": "as offered",
        "short_note": "\n\n[…] The full letter is attached to this email as a PDF.\n\nKind regards\n{sender}",
    },
}


def criterion_label(key: str, lang: str) -> str:
    """Label of a criterion in the letter language; the key itself if no label is defined."""
    return CRITERIA.get(key, {}).get("label_de" if lang == "DE" else "label_en") or key


def _join(items: List[str], lang: str) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + TEXT[lang]["and"] + items[-1]


def _level(score: float, lang: str) -> str:
    return next(words[lang] for minimum, words in LEVELS if score >= minimum)


def _format_eur(amount: float, lang: str) -> str:
    text = f"{amount:,.2f}"
    return (text.replace(",", "X").replace(".", ",").replace("X", ".") + " EUR") if lang == "DE" else f"EUR {text}"


def _format_weight(weight: float, lang: str) -> str:
    text = f"{weight:g}"
    return f"{text.replace('.', ',') if lang == 'DE' else text} %"


def _title(run: Dict[str, Any], lang: str) -> str:
    title = run.get("title") or ""
    return title.get(lang) or next(iter(title.values()), "") if isinstance(title, dict) else str(title)


def award_letter(run: Dict[str, Any], bidder: Dict[str, Any], lang: str) -> Dict[str, str]:
    """Zuschlagsschreiben for the recommended supplier."""
    text = TEXT[lang]
    values = {
        "ref": run.get("ref") or "-",
        "title": _title(run, lang),
        "item": bidder.get("item") or _title(run, lang),
        "quantity": bidder.get("quantity") or text["quantity_unknown"],
        "price": _format_eur(bidder["price"], lang),
        "contact": CONTACT_PLACEHOLDER[lang],
        "sender": SENDER[lang],
    }
    return {"subject": text["award_subject"].format(**values), "body": text["award_body"].format(**values)}


def rejection_letter(run: Dict[str, Any], bidder: Dict[str, Any], lang: str) -> Dict[str, str]:
    """Absageschreiben (§ 46 UVgO): the winner's name, the recipient's own result in words and
    the winner's advantages by criterion name only. No prices or scores of other bidders."""
    text = TEXT[lang]
    winner = next(b for b in run["bidders"] if b["rank"] == 1)
    weights = run["weights"]

    def final(b: Dict[str, Any], key: str) -> float:
        return float(b["scores"][key]["committee"])

    behind = [criterion_label(k, lang) for k in weights if final(winner, k) > final(bidder, k)]
    level = [criterion_label(k, lang) for k in weights if final(bidder, k) >= final(winner, k)]
    values = {
        "ref": run.get("ref") or "-",
        "title": _title(run, lang),
        "winner": winner["bidder"],
        "criteria": _join([f"{criterion_label(k, lang)} ({_format_weight(w, lang)})" for k, w in weights.items()], lang),
        "rank": bidder["rank"],
        "count": len(run["bidders"]),
        "own": "; ".join(f"{criterion_label(k, lang)}: {_level(final(bidder, k), lang)}" for k in weights),
        "advantages": text["advantages"].format(criteria=_join(behind, lang)) if behind else "",
        "strengths": text["strengths"].format(criteria=_join(level, lang)) if level else "",
        "contact": CONTACT_PLACEHOLDER[lang],
        "sender": SENDER[lang],
    }
    return {"subject": text["rejection_subject"].format(**values), "body": text["rejection_body"].format(**values)}


def letter_for(run: Dict[str, Any], bidder: Dict[str, Any], lang: str) -> Dict[str, str]:
    return award_letter(run, bidder, lang) if bidder["rank"] == 1 else rejection_letter(run, bidder, lang)


def build_letters(run: Dict[str, Any], generated_at: str) -> Dict[str, Any]:
    """Generates every bidder's letter once, in DE and EN, and stores it in the run (in place).

    The stored text is what is shown and emailed later, so the sent letter matches the saved one.
    """
    for bidder in run["bidders"]:
        texts = {lang: letter_for(run, bidder, lang) for lang in ("DE", "EN")}
        bidder["letter"] = {
            "type": "award" if bidder["rank"] == 1 else "rejection",
            "to": bidder.get("email"),
            "subject_de": texts["DE"]["subject"],
            "subject_en": texts["EN"]["subject"],
            "body_de": texts["DE"]["body"],
            "body_en": texts["EN"]["body"],
            "generated_at": generated_at,
            "sent_at": None,
        }
    return run


def stored_letter(bidder: Dict[str, Any], lang: str) -> Dict[str, str]:
    letter = bidder["letter"]
    suffix = "de" if lang == "DE" else "en"
    return {"subject": letter[f"subject_{suffix}"], "body": letter[f"body_{suffix}"]}


def email_lock_reasons(run: Dict[str, Any], bidder: Dict[str, Any]) -> List[str]:
    """Why the bidder's email cannot be sent yet; empty when it can.

    "approval_missing": the award is not approved yet; the approval unlocks the award letter
    and all rejection letters at once, in any order. "email_missing": no address. Whether a
    letter is marked as sent never locks or unlocks anything.
    """
    reasons = []
    if not (bidder.get("letter") or {}).get("to"):
        reasons.append("email_missing")
    if not run.get("award_approved"):
        reasons.append("approval_missing")
    return reasons


def email_body(letter: Dict[str, str], lang: str, limit: int = MAILTO_BODY_LIMIT) -> Dict[str, Any]:
    """The body for a mailto: link. A letter over the limit is cut after a whole paragraph and
    ends with a note that the full letter is attached as PDF ("shortened": True)."""
    body = letter["body"]
    if len(body) <= limit:
        return {"body": body, "shortened": False}
    note = TEXT[lang]["short_note"].format(sender=SENDER[lang])
    paragraphs, kept = body.split("\n\n"), []
    for paragraph in paragraphs:
        if len("\n\n".join(kept + [paragraph])) + len(note) > limit:
            break
        kept.append(paragraph)
    return {"body": "\n\n".join(kept) + note, "shortened": True}


def mailto_url(to: str, subject: str, body: str) -> str:
    """One recipient only; subject and body URL-encoded with CRLF line breaks (Outlook)."""
    params = f"subject={quote(subject, safe='')}&body={quote(body.replace(chr(10), chr(13) + chr(10)), safe='')}"
    return f"mailto:{quote(to, safe='@')}?{params}"


def gmail_url(to: str, subject: str, body: str) -> str:
    return "https://mail.google.com/mail/?" + urlencode(
        {"view": "cm", "fs": "1", "to": to, "su": subject, "body": body}, quote_via=quote
    )


def letter_pdf(letter: Dict[str, str]) -> bytes:
    """The full letter as a one-file PDF (attachment for a shortened email)."""
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    pdf.set_margins(25, 25, 20)
    pdf.set_xy(25, 25)
    pdf.set_font("Helvetica", "B", 12)
    pdf.multi_cell(0, 6, _pdf_safe(letter["subject"]), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("Helvetica", size=10.5)
    pdf.multi_cell(0, 5.5, _pdf_safe(letter["body"]), new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
