"""Deterministic extraction of bid data from quotation PDFs.

No AI is involved: every value is found by a labelled pattern and returned together with
the source line it came from, so the evaluation committee can verify it. Fields that are
not found stay None; nothing is defaulted.
"""
import io
import re
from typing import Any, Dict, List, Optional, Tuple

from pypdf import PdfReader


class BidExtractionError(RuntimeError):
    """Raised when no text can be extracted from a bid PDF."""


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Returns the text of all pages. Raises BidExtractionError if the PDF is unreadable or has no text."""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        if reader.is_encrypted:
            reader.decrypt("")
        text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    except Exception as e:
        raise BidExtractionError(f"PDF could not be read: {e}") from e
    if not text:
        raise BidExtractionError("PDF contains no extractable text (scanned image?).")
    return text


# --- Amounts ------------------------------------------------------------------------------

_SPACES = "    '"


def normalize_amount(value: Any) -> Optional[float]:
    """Parses a money amount in German or English notation. Returns None if it is not a number.

    "EUR 15200.00", "15.200,00 €", "€15,200.00", "15 200,00", "15.200,-" -> 15200.0
    A single separator followed by exactly three digits ("15.200", "15,200") is read as a
    thousands separator, since prices are not quoted with three decimals.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    text = re.sub(r"(?i)eur(o)?|€", "", text)
    text = re.sub(r"[.,]-+$", "", text.strip())  # "15.200,-"
    for ch in _SPACES:
        text = text.replace(ch, "")
    negative = text.startswith("-")
    text = text.lstrip("+-")
    if not text or not re.fullmatch(r"[\d.,]+", text) or not re.search(r"\d", text):
        return None

    if "." in text and "," in text:
        decimal = "." if text.rfind(".") > text.rfind(",") else ","
        thousands = "," if decimal == "." else "."
        integer, _, fraction = text.rpartition(decimal)
        if not re.fullmatch(rf"\d{{1,3}}(\{thousands}\d{{3}})*|\d+", integer) or not fraction.isdigit():
            return None
        number = float(integer.replace(thousands, "") + "." + fraction)
    elif "." in text or "," in text:
        sep = "." if "." in text else ","
        parts = text.split(sep)
        if len(parts) > 2 or len(parts[-1]) == 3:
            # Thousands separator only: every group after the first has exactly 3 digits
            if not all(len(p) == 3 and p.isdigit() for p in parts[1:]) or not parts[0].isdigit():
                return None
            number = float("".join(parts))
        else:
            if not parts[0].isdigit() or not parts[1].isdigit():
                return None
            number = float(parts[0] + "." + parts[1])
    else:
        number = float(text)
    return -number if negative else number


_NUMBER = r"\d{1,3}(?:[.,  ' ]\d{3})+(?:[.,]\d{1,2})?(?:,-)?|\d+(?:[.,]\d{1,2})?(?:,-)?"
_CURRENCY = r"(?:€|EUR|Euro)"
_AMOUNT_WITH_CURRENCY = re.compile(
    rf"{_CURRENCY}\s*(?P<a>{_NUMBER})|(?P<b>{_NUMBER})\s*{_CURRENCY}", re.IGNORECASE
)
_AMOUNT_ANY = re.compile(rf"(?P<a>{_NUMBER})(?!\s*%)")


def _amount_in_line(line: str) -> Optional[float]:
    """Amount on a line: prefer a number next to a currency sign, else the last number."""
    match = _AMOUNT_WITH_CURRENCY.search(line)
    if match:
        return normalize_amount(match.group("a") or match.group("b"))
    numbers = _AMOUNT_ANY.findall(line)
    return normalize_amount(numbers[-1]) if numbers else None


# --- Field patterns -----------------------------------------------------------------------

_SUPPLIER_LABEL = re.compile(
    r"^\s*(?:supplier|vendor|bidder|company|anbieter|lieferant|bieter|firma|unternehmen|auftragnehmer)"
    r"\s*[:\-]\s*(?P<v>.+)$",
    re.IGNORECASE,
)
_LEGAL_FORM = re.compile(
    r"\b(?:GmbH|AG|SE|KG|KGaA|OHG|GbR|UG|e\.\s?K\.|Ltd\.?|Inc\.?|LLC|Corp\.?|plc|S\.A\.|B\.V\.)(?=\W|$)"
)
_HEADER_WORDS = re.compile(r"\b(quotation|quote|offer|angebot|kostenvoranschlag|rechnung|invoice)\b", re.IGNORECASE)

_PRICE_LABEL = re.compile(
    r"\b(?P<label>grand\s+total|total\s+(?:price|amount|cost)|total|amount\s+due|"
    r"gesamtpreis|gesamtbetrag|gesamtsumme|angebotssumme|angebotspreis|endbetrag|endsumme|"
    r"bruttobetrag|nettobetrag|summe|price|preis)\b",
    re.IGNORECASE,
)
_UNIT_PRICE = re.compile(r"einzelpreis|st(ü|ue)ckpreis|unit\s+price|per\s+unit|je\s+st(ü|ue)ck|pro\s+st(ü|ue)ck|/\s*stk", re.IGNORECASE)
_VAT_LINE = re.compile(r"^\s*(mwst|ust|umsatzsteuer|mehrwertsteuer|vat|tax)\b", re.IGNORECASE)
_GROSS = re.compile(r"brutto|gross|inkl\.?\s*(mwst|ust|vat)|incl\.?\s*vat|including\s+vat", re.IGNORECASE)
_NET = re.compile(r"netto|\bnet\b|zzgl\.?|excl\.?\s*vat|excluding\s+vat|plus\s+vat", re.IGNORECASE)
# Specific total labels outrank a bare "price"/"preis"
_GENERIC_PRICE_LABELS = {"price", "preis"}

_ITEM_LABEL = re.compile(
    r"^\s*(?:item|items|article|product|description|artikel|gegenstand|leistung|beschreibung|produkt|position)"
    r"\s*[:\-]\s*(?P<v>.+)$",
    re.IGNORECASE,
)
_QUANTITY_LABEL = re.compile(r"\b(?:quantity|qty|menge|anzahl|st(ü|ue)ckzahl)\s*[:\-]?\s*(?P<v>\d+)", re.IGNORECASE)
_LEADING_QUANTITY = re.compile(r"^\s*(?P<v>\d+)\s*(?:x\s+|stk\.?\s+|st(ü|ue)ck\s+|pcs\.?\s+|units?\s+)?(?=[A-Za-zÄÖÜäöü])", re.IGNORECASE)

_DELIVERY_LABEL = re.compile(
    r"^\s*(?:delivery(?:\s+time)?|lead\s+time|lieferzeit|lieferung|lieferfrist|liefertermin)\s*[:\-]\s*(?P<v>.+)$",
    re.IGNORECASE,
)
_DURATION = re.compile(
    r"(?P<n>\d+)(?:\s*[-–]\s*(?P<m>\d+))?\s*"
    r"(?P<unit>working\s+days?|business\s+days?|days?|weeks?|months?|years?|"
    r"werktage?n?|arbeitstage?n?|tage?n?|wochen?|monate?n?|jahre?n?)\b",
    re.IGNORECASE,
)
_WARRANTY_WORD = r"(?:warranty|guarantee|garantie|gew(ä|ae)hrleistung)"
_WARRANTY_LABEL = re.compile(rf"\b{_WARRANTY_WORD}\b\s*[:\-]?\s*(?P<v>.+)", re.IGNORECASE)
_WARRANTY_INLINE = re.compile(rf"(?P<v>\d+(?:\s*[-–]\s*\d+)?\s*[A-Za-zä]+)\s*(?:of\s+)?{_WARRANTY_WORD}", re.IGNORECASE)

# Facts for the committee criteria (references/service, concept/quality)
_REFERENCES_LABEL = re.compile(
    r"^\s*(?:references?|referenzen|referenz(?:projekte|kunden)?|reference\s+(?:projects|customers))\s*[:\-]\s*(?P<v>.+)$",
    re.IGNORECASE,
)
_NO_REFERENCES = re.compile(r"^\s*(?:none|keine|n/?a|-)\s*\.?\s*$", re.IGNORECASE)
_SERVICE_LABEL = re.compile(
    r"^\s*(?:service|support|after[\s-]sales(?:\s+service)?|kundendienst|serviceleistungen?|wartung)\s*[:\-]\s*(?P<v>.+)$",
    re.IGNORECASE,
)
_ON_SITE = re.compile(r"on[\s-]?site|vor[\s-]?ort|next\s+business\s+day|n(ä|ae)chster\s+werktag", re.IGNORECASE)
_VALIDITY = re.compile(
    r"\b(?:valid\s+(?:until|for|through)|validity|offer\s+valid|g(ü|ue)ltig\s+(?:bis|f(ü|ue)r)|"
    r"angebot\s+g(ü|ue)ltig|g(ü|ue)ltigkeit|bindefrist|zuschlagsfrist)\b\s*[:\-]?\s*(?P<v>.*)$",
    re.IGNORECASE,
)

_DAYS_PER_UNIT = {"day": 1, "week": 7, "month": 30, "year": 365}


def _duration_unit(unit: str) -> Optional[str]:
    unit = unit.lower()
    for prefix, key in (
        ("working", "day"), ("business", "day"), ("werk", "day"), ("arbeit", "day"), ("day", "day"), ("tag", "day"),
        ("week", "week"), ("woche", "week"), ("month", "month"), ("monat", "month"), ("year", "year"), ("jahr", "year"),
    ):
        if unit.startswith(prefix):
            return key
    return None


def parse_duration_days(text: str) -> Optional[int]:
    """'1 week' -> 7, '5 Werktage' -> 5, '2-3 Wochen' -> 21 (upper bound). None if no duration."""
    match = _DURATION.search(text or "")
    if not match:
        return None
    unit = _duration_unit(match.group("unit"))
    if unit is None:
        return None
    count = int(match.group("m") or match.group("n"))
    return count * _DAYS_PER_UNIT[unit]


def parse_duration_months(text: str) -> Optional[int]:
    """'3 years' -> 36, '24 Monate' -> 24. None if no duration in months or years."""
    match = _DURATION.search(text or "")
    if not match:
        return None
    unit = _duration_unit(match.group("unit"))
    count = int(match.group("m") or match.group("n"))
    if unit == "year":
        return count * 12
    if unit == "month":
        return count
    return None


# --- Bid parsing --------------------------------------------------------------------------


def _find_price(lines: List[str]) -> Dict[str, Any]:
    """Finds the total price. Prefers gross over an unqualified total over net."""
    candidates: List[Tuple[Tuple[int, int, int], float, str, str]] = []
    for index, line in enumerate(lines):
        label = _PRICE_LABEL.search(line)
        if not label or _UNIT_PRICE.search(line) or _VAT_LINE.search(line):
            continue
        amount = _amount_in_line(line[label.end():])
        if amount is None and index + 1 < len(lines):
            # Table layouts put the amount on the line below the label
            amount = _amount_in_line(lines[index + 1])
        if amount is None or amount <= 0:
            continue
        basis = "gross" if _GROSS.search(line) else "net" if _NET.search(line) else "total"
        if label.group("label").lower() == "bruttobetrag":
            basis = "gross"
        elif label.group("label").lower() == "nettobetrag":
            basis = "net"
        basis_rank = {"gross": 0, "total": 1, "net": 2}[basis]
        label_rank = 1 if label.group("label").lower() in _GENERIC_PRICE_LABELS else 0
        candidates.append(((basis_rank, label_rank, -index), amount, basis, line.strip()))

    result = {"price": None, "price_basis": None, "price_net": None, "price_gross": None, "price_source": None}
    if not candidates:
        return result
    for _, amount, basis, _ in candidates:
        if basis == "net" and result["price_net"] is None:
            result["price_net"] = amount
        if basis == "gross" and result["price_gross"] is None:
            result["price_gross"] = amount
    _, amount, basis, source = min(candidates, key=lambda c: c[0])
    result.update(price=amount, price_basis=basis, price_source=source)
    return result


def parse_bid_text(text: str, filename: str = "") -> Dict[str, Any]:
    """Extracts bidder, price, item, quantity, delivery, warranty, references, service terms
    and offer validity from quotation text.

    Every found value has a matching entry in "sources" with the line it was taken from.
    "missing" lists the fields that could not be found.
    """
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    sources: Dict[str, str] = {}
    bid: Dict[str, Any] = {
        "bidder": None,
        "bidder_source": None,
        "item": None,
        "quantity": None,
        "delivery": None,
        "delivery_days": None,
        "warranty": None,
        "warranty_months": None,
        "references": [],
        "service": None,
        "on_site_service": False,
        "validity": None,
    }

    # Bidder: labelled supplier line, then a letterhead line with a legal form, then the filename
    for line in lines:
        match = _SUPPLIER_LABEL.match(line)
        if match:
            bid["bidder"], bid["bidder_source"] = match.group("v").strip(), "pdf"
            sources["bidder"] = line
            break
    if bid["bidder"] is None:
        for line in lines[:8]:
            if _LEGAL_FORM.search(line) and ":" not in line and not _HEADER_WORDS.search(line):
                bid["bidder"], bid["bidder_source"] = line, "letterhead"
                sources["bidder"] = line
                break
    if bid["bidder"] is None and filename:
        stem = re.sub(r"\.pdf$", "", filename, flags=re.IGNORECASE)
        stem = re.sub(r"[_\-\s]*(bid|angebot|quote|quotation|offer)$", "", stem, flags=re.IGNORECASE)
        bid["bidder"], bid["bidder_source"] = stem.replace("_", " ").strip() or filename, "filename"

    price = _find_price(lines)
    bid.update({k: v for k, v in price.items() if k != "price_source"})
    if price["price_source"]:
        sources["price"] = price["price_source"]

    for line in lines:
        match = _ITEM_LABEL.match(line)
        if match:
            bid["item"] = match.group("v").strip()
            sources["item"] = line
            break

    for line in lines:
        match = _QUANTITY_LABEL.search(line)
        if match:
            bid["quantity"] = int(match.group("v"))
            sources["quantity"] = line
            break
    if bid["quantity"] is None and bid["item"]:
        match = _LEADING_QUANTITY.match(bid["item"])
        if match:
            bid["quantity"] = int(match.group("v"))
            sources["quantity"] = sources["item"]

    for line in lines:
        match = _DELIVERY_LABEL.match(line)
        if match:
            bid["delivery"] = match.group("v").strip()
            bid["delivery_days"] = parse_duration_days(bid["delivery"])
            sources["delivery"] = line
            break

    for line in lines:
        match = _WARRANTY_INLINE.search(line) or _WARRANTY_LABEL.search(line)
        if match and parse_duration_months(match.group("v")) is not None:
            bid["warranty"] = match.group("v").strip(" .,;()")
            bid["warranty_months"] = parse_duration_months(match.group("v"))
            sources["warranty"] = line
            break

    for line in lines:
        match = _REFERENCES_LABEL.match(line)
        if match:
            value = match.group("v").strip()
            if not _NO_REFERENCES.match(value):
                # Semicolons separate the references; commas only when there are none
                separator = r"\s*[;|]\s*" if re.search(r"[;|]", value) else r"\s*,\s*"
                bid["references"] = [r.strip(" .") for r in re.split(separator, value) if r.strip(" .")]
            sources["references"] = line
            break

    for line in lines:
        match = _SERVICE_LABEL.match(line)
        if match:
            bid["service"] = match.group("v").strip()
            sources["service"] = line
            break
    bid["on_site_service"] = any(_ON_SITE.search(line) for line in lines)

    for line in lines:
        match = _VALIDITY.search(line)
        if match:
            bid["validity"] = match.group("v").strip(" .,;") or line
            sources["validity"] = line
            break

    bid["sources"] = sources
    bid["missing"] = [
        field
        for field, key in (
            ("bidder", "bidder"), ("price", "price"), ("item", "item"), ("quantity", "quantity"),
            ("delivery", "delivery_days"), ("warranty", "warranty_months"),
        )
        if bid[key] is None or (field == "bidder" and bid["bidder_source"] == "filename")
    ]
    return bid


def parse_bid_pdf(pdf_bytes: bytes, filename: str = "") -> Dict[str, Any]:
    """Extracts text from a bid PDF and parses it. Raises BidExtractionError on unreadable PDFs."""
    return parse_bid_text(extract_pdf_text(pdf_bytes), filename)
