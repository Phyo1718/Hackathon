"""Agent proposals for the committee criteria of the bid evaluation.

The PDF parser (or Gemini) only extracts facts; score_bid turns them into points with one fixed
rubric that applies to every bidder alike. Each point comes with its reason, so the committee
can check the proposal and overwrite it. Criterion 2 "References / Service" asks whether the
supplier can be trusted to deliver and support us; criterion 3 "Concept / Quality" asks how
well the offer fits what was requested (official sheet: "Service" and "Qualität").
"""
import re
from typing import Any, Callable, Dict, List, Optional

# --- Rubric: all points in one place --------------------------------------------------------

RUBRIC = {
    "references": {
        # Track record with the city (approved-supplier list and request history)
        "track_record": {"contract": 4, "approved": 2, "unknown": 0},
        # References for comparable deliveries named in the bid
        "named_references": {"two_or_more": 3, "one": 2, "none": 0},
        # Warranty / after-sales service
        "warranty": {"three_years_or_on_site": 3, "two_years": 2, "one_year": 1, "not_stated": 0},
    },
    "concept": {
        # Item type and quantity against the request. Brands are never compared.
        "fit": {"match": 4, "partial": 2, "no_match": 0},
        # Delivery time in days: up to 14 / up to 28 / longer
        "delivery": {"up_to_14_days": 3, "up_to_28_days": 2, "longer": 1, "not_stated": 0},
        # Price basis (net/gross), specification and offer validity stated: points by count
        "completeness": {3: 3, 2: 2, 1: 1, 0: 0},
    },
}
MAX_POINTS = 10

# Item types recognised in requests and bids. Model families count as their type, so an
# HP EliteBook, a Lenovo ThinkPad and a Dell Latitude are all laptops (product neutrality).
ITEM_TYPES = {
    "laptop": ("laptop", "notebook", "elitebook", "probook", "thinkpad", "latitude", "macbook"),
    "desktop": ("desktop", "arbeitsplatzrechner", "workstation", "pc"),
    "monitor": ("monitor", "bildschirm", "display"),
    "docking": ("docking", "dockingstation"),
    "printer": ("printer", "drucker"),
    "server": ("server",),
    "tablet": ("tablet", "ipad"),
    "smartphone": ("smartphone", "handy", "mobiltelefon"),
    "chair": ("chair", "stuhl", "bürostuhl", "bürostühle"),
    "vehicle": ("vehicle", "fahrzeug", "transporter"),
}
ITEM_TYPE_LABELS = {
    "laptop": {"DE": "Laptops", "EN": "laptops"},
    "desktop": {"DE": "Arbeitsplatzrechner", "EN": "desktop computers"},
    "monitor": {"DE": "Monitore", "EN": "monitors"},
    "docking": {"DE": "Dockingstationen", "EN": "docking stations"},
    "printer": {"DE": "Drucker", "EN": "printers"},
    "server": {"DE": "Server", "EN": "servers"},
    "tablet": {"DE": "Tablets", "EN": "tablets"},
    "smartphone": {"DE": "Smartphones", "EN": "smartphones"},
    "chair": {"DE": "Bürostühle", "EN": "office chairs"},
    "vehicle": {"DE": "Fahrzeuge", "EN": "vehicles"},
}

# Reason texts per rubric outcome (DE/EN), filled with the facts found
REASONS = {
    "contract": {"DE": "früherer Auftrag {ref}", "EN": "previous contract {ref}"},
    "contract_more": {"DE": "früherer Auftrag {ref} (+{more} weitere)", "EN": "previous contract {ref} (+{more} more)"},
    "approved": {"DE": "zugelassener Lieferant, kein früherer Auftrag", "EN": "approved supplier, no previous contract"},
    "not_approved": {"DE": "als nicht zugelassen geführt", "EN": "listed as not approved"},
    "other_category": {"DE": "kein Auftrag in {category} (zugelassen nur für {listed})",
                       "EN": "no track record in {category} (approved for {listed} only)"},
    "unknown": {"DE": "keine Zusammenarbeit mit der Stadt bekannt", "EN": "no track record with the city"},
    "references_many": {"DE": "{count} Referenzen im Angebot", "EN": "{count} references in bid"},
    "references_one": {"DE": "1 Referenz im Angebot ({name})", "EN": "1 reference in bid ({name})"},
    "references_none": {"DE": "Referenzen: keine im Angebot", "EN": "references: none in bid"},
    "warranty_on_site": {"DE": "Vor-Ort-Service", "EN": "on-site service"},
    "warranty_years": {"DE": "Garantie {years:g} Jahre", "EN": "warranty {years:g} years"},
    "warranty_short": {"DE": "Garantie {months} Monate", "EN": "warranty {months} months"},
    "warranty_none": {"DE": "Garantie: nicht angegeben", "EN": "warranty: not stated"},
    "fit_match": {"DE": "{quantity} {type} wie angefragt (Marke nicht bewertet)",
                  "EN": "{quantity} {type} as requested (brand not assessed)"},
    "fit_quantity": {"DE": "{type} wie angefragt, Menge {bid_quantity} statt {quantity}",
                     "EN": "{type} as requested, quantity {bid_quantity} instead of {quantity}"},
    "fit_no_quantity": {"DE": "{type} wie angefragt, Menge nicht vergleichbar",
                        "EN": "{type} as requested, quantity not comparable"},
    "fit_no_match": {"DE": "Gegenstand passt nicht zur Anfrage ({type})", "EN": "item does not match the request ({type})"},
    "fit_unknown": {"DE": "Passung: nicht prüfbar", "EN": "fit to request: cannot be checked"},
    "delivery": {"DE": "Lieferung {days} Tage", "EN": "delivery {days} days"},
    "delivery_none": {"DE": "Lieferzeit: nicht angegeben", "EN": "delivery: not stated"},
    "completeness": {"DE": "Angaben: {stated}", "EN": "stated: {stated}"},
    "completeness_none": {"DE": "Preisbasis, Spezifikation, Bindefrist: nicht angegeben",
                          "EN": "price basis, specification, validity: not stated"},
    "price_basis": {"DE": "Preisbasis", "EN": "price basis"},
    "specification": {"DE": "Spezifikation", "EN": "specification"},
    "validity": {"DE": "Bindefrist", "EN": "offer validity"},
}

# Short reasons for the "required" note when there is no evidence at all
NO_EVIDENCE = {
    "references": {"DE": "keine Zusammenarbeit bekannt und keine Referenzen im Angebot",
                   "EN": "no track record and none named in bid"},
    "concept": {"DE": "Angebot nicht mit der Anfrage vergleichbar, keine Lieferzeit und keine Angaben",
                "EN": "offer not comparable with the request, no delivery time and no details"},
}


def _reason(code: str, **params: Any) -> Dict[str, str]:
    return {lang: text.format(**params) for lang, text in REASONS[code].items()}


def _component(key: str, points: int, evidence: bool, reason: Dict[str, str]) -> Dict[str, Any]:
    return {"key": key, "points": points, "evidence": evidence, "reason": reason}


# --- Facts from free text -------------------------------------------------------------------


def item_types(text: str) -> List[str]:
    """Item types named in a text, e.g. '15 HP EliteBook Laptops' -> ['laptop']."""
    words = re.findall(r"[a-zäöüß]+", (text or "").lower())

    def named(keyword: str) -> bool:
        # Short keywords ("pc") must match whole words, so "pcs" (pieces) is no PC
        return any(w == keyword or (len(keyword) >= 5 and w.startswith(keyword)) for w in words)

    return [kind for kind, keywords in ITEM_TYPES.items() if any(named(k) for k in keywords)]


def item_quantity(text: str) -> Optional[int]:
    """The number in front of the first item word: '15 Dell Laptops' -> 15."""
    keywords = "|".join(k for keywords in ITEM_TYPES.values() for k in keywords)
    match = re.search(rf"\b(\d+)\s+(?:[^\s\d]+\s+){{0,3}}?(?:{keywords})", (text or "").lower())
    return int(match.group(1)) if match else None


def _same_supplier(a: str, b: str) -> bool:
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    return bool(a and b) and (a == b or a in b or b in a)


# --- Criteria --------------------------------------------------------------------------------


def _track_record(bid, request, supplier_db, history) -> Dict[str, Any]:
    points = RUBRIC["references"]["track_record"]
    supplier = supplier_db(bid.get("bidder") or "")
    name = supplier["supplier_name"] if supplier.get("exists") else bid.get("bidder") or ""
    category = request.get("category")
    contracts = [
        entry for entry in history
        if entry.get("decision") == "APPROVED"
        and entry.get("ref") != request.get("ref")
        and _same_supplier(entry.get("supplier", ""), name)
        and (not category or entry.get("category") == category)
    ]
    if supplier.get("exists") and not supplier.get("is_approved"):
        return _component("track_record", points["unknown"], True, _reason("not_approved"))
    if contracts:
        latest = max(contracts, key=lambda e: e.get("decided_at", ""))
        reason = (_reason("contract_more", ref=latest["ref"], more=len(contracts) - 1)
                  if len(contracts) > 1 else _reason("contract", ref=latest["ref"]))
        return _component("track_record", points["contract"], True, reason)
    if supplier.get("exists") and category and supplier.get("category") != category:
        return _component("track_record", points["unknown"], False,
                          _reason("other_category", category=category, listed=supplier.get("category")))
    if supplier.get("exists"):
        return _component("track_record", points["approved"], True, _reason("approved"))
    return _component("track_record", points["unknown"], False, _reason("unknown"))


def _named_references(bid) -> Dict[str, Any]:
    points = RUBRIC["references"]["named_references"]
    references = bid.get("references") or []
    if len(references) >= 2:
        return _component("named_references", points["two_or_more"], True, _reason("references_many", count=len(references)))
    if references:
        return _component("named_references", points["one"], True, _reason("references_one", name=references[0]))
    return _component("named_references", points["none"], False, _reason("references_none"))


def _warranty(bid) -> Dict[str, Any]:
    points = RUBRIC["references"]["warranty"]
    months = bid.get("warranty_months")
    if bid.get("on_site_service"):
        return _component("warranty", points["three_years_or_on_site"], True, _reason("warranty_on_site"))
    if months is None:
        return _component("warranty", points["not_stated"], False, _reason("warranty_none"))
    reason = _reason("warranty_years", years=months / 12) if months % 12 == 0 else _reason("warranty_short", months=months)
    if months >= 36:
        return _component("warranty", points["three_years_or_on_site"], True, reason)
    if months >= 24:
        return _component("warranty", points["two_years"], True, reason)
    if months >= 12:
        return _component("warranty", points["one_year"], True, reason)
    return _component("warranty", points["not_stated"], True, reason)


def _type_label(kinds: List[str]) -> Dict[str, str]:
    return {lang: ", ".join(ITEM_TYPE_LABELS[k][lang] for k in kinds) for lang in ("DE", "EN")}


def _fit(bid, request) -> Dict[str, Any]:
    points = RUBRIC["concept"]["fit"]
    request_text = request.get("text") or ""
    wanted, offered = item_types(request_text), item_types(bid.get("item") or "")
    if not wanted or not bid.get("item"):
        return _component("fit", points["no_match"], False, _reason("fit_unknown"))
    common = [k for k in wanted if k in offered]
    if not common:
        label = _type_label(offered) if offered else {"DE": bid["item"], "EN": bid["item"]}
        return _component("fit", points["no_match"], True,
                          {lang: REASONS["fit_no_match"][lang].format(type=label[lang]) for lang in label})
    label = _type_label(common)
    quantity = request.get("quantity") or item_quantity(request_text)
    bid_quantity = bid.get("quantity") or item_quantity(bid.get("item") or "")
    if quantity and bid_quantity == quantity:
        key, value = "fit_match", points["match"]
    elif quantity and bid_quantity:
        key, value = "fit_quantity", points["partial"]
    else:
        key, value = "fit_no_quantity", points["partial"]
    reason = {
        lang: REASONS[key][lang].format(type=label[lang], quantity=quantity, bid_quantity=bid_quantity)
        for lang in label
    }
    return _component("fit", value, True, reason)


def _delivery(bid) -> Dict[str, Any]:
    points = RUBRIC["concept"]["delivery"]
    days = bid.get("delivery_days")
    if days is None:
        return _component("delivery", points["not_stated"], False, _reason("delivery_none"))
    value = points["up_to_14_days"] if days <= 14 else points["up_to_28_days"] if days <= 28 else points["longer"]
    return _component("delivery", value, True, _reason("delivery", days=int(days)))


def _completeness(bid) -> Dict[str, Any]:
    stated = [
        key for key, present in (
            ("price_basis", bid.get("price_basis") in ("gross", "net")),
            ("specification", bool(bid.get("item"))),
            ("validity", bool(bid.get("validity"))),
        ) if present
    ]
    value = RUBRIC["concept"]["completeness"][len(stated)]
    if not stated:
        return _component("completeness", value, False, _reason("completeness_none"))
    reason = {lang: REASONS["completeness"][lang].format(stated=", ".join(REASONS[k][lang] for k in stated))
              for lang in ("DE", "EN")}
    return _component("completeness", value, True, reason)


def _criterion(key: str, components: List[Dict[str, Any]]) -> Dict[str, Any]:
    evidence = any(c["evidence"] for c in components)
    return {
        "score": min(MAX_POINTS, sum(c["points"] for c in components)) if evidence else None,
        "evidence": evidence,
        "components": components,
        "missing_reason": None if evidence else NO_EVIDENCE[key],
    }


def score_bid(
    bid: Dict[str, Any],
    request: Dict[str, Any],
    supplier_db: Callable[[str], Dict[str, Any]],
    history: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Proposed 0-10 points for "references" and "concept", with the reason for each point.

    bid: facts as extracted (bid_parser.parse_bid_text). request: ref, category, text and
    optionally quantity. supplier_db: the approved-supplier check (agent.check_supplier).
    history: decided requests with ref, supplier, category, decision and decided_at; approved
    ones other than this request count as previous contracts. A criterion without any evidence
    has score None ("required"): the committee has to enter it.
    """
    return {
        "references": _criterion("references", [
            _track_record(bid, request, supplier_db, history), _named_references(bid), _warranty(bid),
        ]),
        "concept": _criterion("concept", [_fit(bid, request), _delivery(bid), _completeness(bid)]),
    }


def explain(criterion: Dict[str, Any], lang: str) -> str:
    """'+4 previous contract VA-2026-H06 · +3 warranty 3 years · references: none in bid'."""
    parts = [
        f"+{c['points']} {c['reason'][lang]}" if c["points"] else c["reason"][lang]
        for c in sorted(criterion["components"], key=lambda c: -c["points"])
    ]
    return " · ".join(parts)
