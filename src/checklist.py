"""The agent's verification of a request as a short, scannable summary.

Built from the structured check results of agent.verify_extracted_request (no AI): the
recommendation with one reason, one line per check, and the detailed steps. Everything is
returned as codes with parameters; the app turns them into DE/EN text.
"""
from typing import Any, Dict, List, Optional

# Check status -> icon shown in front of the line
STATUS_ICONS = {"pass": "✓", "warn": "⚠", "fail": "✗", "info": "ℹ"}

# Accessibility hint per budget line (the requesting department); others get the general hint
ACCESSIBILITY_HINTS = {"IT-Ausstattung": "it", "Büromaterial": "furniture"}

REQUIRED_FIELDS = ("supplier_check", "budget_check", "decision")


def _line(key: str, status: str, code: str, **params: Any) -> Dict[str, Any]:
    return {"key": key, "status": status, "code": code, "params": params}


def recommendation_reason(evaluation: Dict[str, Any]) -> Dict[str, Any]:
    """The one reason behind the agent's recommendation (from the checks it was based on)."""
    decision = evaluation["decision"]
    supplier = evaluation["supplier_check"]
    budget = evaluation["budget_check"]
    name = supplier.get("supplier_name") or evaluation.get("supplier_name", "")
    if decision == "APPROVED":
        return {"code": "approved", "params": {}}
    short = max(0.0, float(evaluation.get("amount") or 0.0) - float(budget.get("remaining_budget") or 0.0))
    if decision == "REQUIRES_REVIEW":
        return {"code": "borderline", "params": {"short": short}}
    if not supplier.get("exists"):
        return {"code": "supplier_unknown", "params": {"supplier": name}}
    if not supplier.get("is_approved"):
        return {"code": "supplier_not_approved", "params": {"supplier": name}}
    if budget.get("error"):
        return {"code": "budget_unknown", "params": {"category": evaluation.get("category", "")}}
    return {"code": "budget_exceeded", "params": {"short": short}}


def verification_view(evaluation: Dict[str, Any], live_budget: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Recommendation, reason, checklist and detail steps for one evaluated request.

    live_budget: the budget check re-read now (the amounts may have changed since the request
    was queued); the checklist uses it, the detail steps keep the values the agent saw.
    Raises KeyError if the evaluation lacks the structured check results.
    """
    for field in REQUIRED_FIELDS:
        if field not in evaluation:
            raise KeyError(field)
    supplier = evaluation["supplier_check"]
    budget = evaluation["budget_check"]
    live = live_budget if live_budget is not None else budget
    accessibility = evaluation.get("accessibility_check") or {}
    prior = evaluation.get("prior_contracts") or []
    amount = float(evaluation.get("amount") or 0.0)
    category = evaluation.get("category", "")
    name = supplier.get("supplier_name") or evaluation.get("supplier_name", "")
    konto = evaluation.get("konto") or live.get("konto") or budget.get("konto") or "-"

    checks: List[Dict[str, Any]] = []
    # Supplier register
    if supplier.get("exists") and supplier.get("is_approved"):
        checks.append(_line("supplier", "pass", "supplier_ok", supplier=name))
    elif supplier.get("exists"):
        checks.append(_line("supplier", "fail", "supplier_not_approved", supplier=name))
    else:
        checks.append(_line("supplier", "fail", "supplier_unknown", supplier=name))

    # Budget (current figures)
    if live.get("error"):
        checks.append(_line("budget", "fail", "budget_unknown", category=category))
    else:
        left = float(live.get("remaining_budget") or 0.0)
        params = {"amount": amount, "left": left, "after": left - amount, "short": amount - left, "line": category}
        if live.get("sufficient"):
            checks.append(_line("budget", "pass", "budget_ok", **params))
        elif live.get("borderline"):
            checks.append(_line("budget", "warn", "budget_borderline", **params))
        else:
            checks.append(_line("budget", "fail", "budget_short", **params))

    # Official form (new award or contract extension)
    if evaluation.get("procurement_type") == "Auftragserweiterung" and prior:
        checks.append(_line("form", "pass", "form_extension", date=prior[-1].get("timestamp"), count=len(prior)))
    else:
        checks.append(_line("form", "pass", "form_lud"))

    # Accessibility (information only; never blocks)
    department = accessibility.get("department") or category
    if not accessibility.get("found"):
        checks.append(_line("accessibility", "info", "access_unknown", department=department))
    elif accessibility.get("employees_with_special_needs", 0) > 0:
        checks.append(_line(
            "accessibility", "info", "access_needs",
            special=accessibility["employees_with_special_needs"], total=accessibility.get("total_employees", 0),
            hint=ACCESSIBILITY_HINTS.get(category, "general"),
        ))
    else:
        checks.append(_line("accessibility", "pass", "access_none", total=accessibility.get("total_employees", 0)))

    # Detailed steps: what the agent checked, with the values it used
    details: List[Dict[str, Any]] = [
        {"code": "detail_extraction", "params": {"supplier": evaluation.get("supplier_name", name), "amount": amount,
                                                 "category": category, "konto": konto}},
    ]
    if evaluation.get("procurement_type") == "Auftragserweiterung" and prior:
        details.append({"code": "detail_history_extension",
                        "params": {"supplier": name, "count": len(prior), "date": prior[-1].get("timestamp")}})
    else:
        details.append({"code": "detail_history_new", "params": {"supplier": name}})
    supplier_code = ("detail_supplier_ok" if supplier.get("exists") and supplier.get("is_approved")
                     else "detail_supplier_not_approved" if supplier.get("exists") else "detail_supplier_unknown")
    details.append({"code": supplier_code, "params": {"supplier": name}})
    if budget.get("error"):
        details.append({"code": "detail_budget_unknown", "params": {"category": category}})
    else:
        details.append({"code": "detail_budget", "params": {"category": category, "konto": konto, "amount": amount,
                                                             "left": float(budget.get("remaining_budget") or 0.0)}})
    if not accessibility.get("found"):
        details.append({"code": "detail_access_unknown", "params": {"department": department}})
    elif accessibility.get("employees_with_special_needs", 0) > 0:
        details.append({"code": "detail_access_needs", "params": {
            "department": department, "special": accessibility["employees_with_special_needs"],
            "total": accessibility.get("total_employees", 0)}})
    else:
        details.append({"code": "detail_access_none", "params": {"department": department,
                                                                  "total": accessibility.get("total_employees", 0)}})

    return {
        "recommendation": evaluation["decision"],
        "reason": recommendation_reason(evaluation),
        "checks": checks,
        "details": details,
    }
