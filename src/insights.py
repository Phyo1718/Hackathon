"""Management insights: pure calculations over budget lines, approved spend and decision history.

No database access and no AI here, so every figure can be checked by a unit test.
"""
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

FORECAST_WINDOW_DAYS = 90
FORECAST_MIN_ORDERS = 2  # fewer approved orders in the window: no projected date
SUPPLIER_SHARE_LIMIT = 0.40


def _day(value: Any) -> date:
    return value.date() if isinstance(value, datetime) else value


def budget_forecast(
    lines: List[Dict[str, Any]],
    approvals: List[Dict[str, Any]],
    today: date,
    window_days: int = FORECAST_WINDOW_DAYS,
    min_orders: int = FORECAST_MIN_ORDERS,
) -> List[Dict[str, Any]]:
    """Committed vs. total per line and the date the line runs out at the recent spending rate.

    status: "forecast" (runout_date set), "exhausted" (nothing left), or "not_enough_data"
    (fewer than min_orders approved orders in the window, so no date is projected).
    """
    start = today - timedelta(days=window_days)
    result = []
    for line in lines:
        recent = [
            a for a in approvals
            if a["category"] == line["category"] and start <= _day(a["timestamp"]) <= today
        ]
        spent = sum(a["amount"] for a in recent)
        total, remaining = line["total"], line["remaining"]
        runout: Optional[date] = None
        if remaining <= 0:
            status = "exhausted"
        elif len(recent) < min_orders or spent <= 0:
            status = "not_enough_data"
        else:
            status = "forecast"
            runout = today + timedelta(days=int(remaining / (spent / window_days)))
        result.append(
            {
                "category": line["category"],
                "department": line.get("department", ""),
                "total": total,
                "committed": total - remaining,
                "remaining": remaining,
                "used_share": (total - remaining) / total if total > 0 else 0.0,
                "recent_orders": len(recent),
                "recent_spend": spent,
                "status": status,
                "runout_date": runout,
            }
        )
    return result


def supplier_shares(approvals: List[Dict[str, Any]], limit: float = SUPPLIER_SHARE_LIMIT) -> List[Dict[str, Any]]:
    """Share of approved spend per supplier within each budget line, largest first per line."""
    per_line: Dict[str, Dict[str, float]] = {}
    for a in approvals:
        suppliers = per_line.setdefault(a["category"], {})
        suppliers[a["supplier"]] = suppliers.get(a["supplier"], 0.0) + a["amount"]
    rows = []
    for category in sorted(per_line):
        line_total = sum(per_line[category].values())
        for supplier, spend in sorted(per_line[category].items(), key=lambda item: -item[1]):
            share = spend / line_total if line_total > 0 else 0.0
            rows.append(
                {"category": category, "supplier": supplier, "spend": spend, "share": share, "above_limit": share > limit}
            )
    return rows


def oversight(requests: List[Dict[str, Any]], transfers: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Agreement between agent recommendation and caseworker decision.

    APPROVED/APPROVED and REJECTED/REJECTED count as agreement. REQUIRES_REVIEW leaves the
    decision to the caseworker: excluded from the rate, listed as deferred. A stored "override"
    flag wins: approving with a budget transfer that resolves a budget-only rejection follows
    the agent's suggestion and is not an override.
    """
    def is_override(r: Dict[str, Any]) -> bool:
        return r["override"] if "override" in r else r["agent_decision"] != r["decision"]

    compared = [r for r in requests if r.get("agent_decision") in ("APPROVED", "REJECTED")]
    overrides = [r for r in compared if is_override(r)]
    return {
        "compared": len(compared),
        "agreed": len(compared) - len(overrides),
        "rate": (len(compared) - len(overrides)) / len(compared) if compared else None,
        "overrides": overrides,
        "deferred": [r for r in requests if r.get("agent_decision") == "REQUIRES_REVIEW"],
        "transfers_proposed": len(transfers),
        "transfers_accepted": sum(1 for t in transfers if t.get("accepted")),
    }


def committee_changes(tenders: List[Dict[str, Any]], tolerance: float = 0.005) -> List[Dict[str, Any]]:
    """Bid scores the evaluation committee changed: the agent proposed a value, the final differs.

    Criteria the agent did not propose (None, e.g. "required" or the seeded demo tender) are
    not changes.
    """
    changes = []
    for run in tenders:
        for bidder in run.get("bidders", []):
            for key, scores in bidder.get("scores", {}).items():
                agent, final = scores.get("agent"), scores.get("committee")
                if agent is not None and final is not None and abs(agent - final) > tolerance:
                    changes.append(
                        {"ref": run.get("ref"), "evaluated_at": run.get("evaluated_at"), "bidder": bidder["bidder"],
                         "criterion": key, "agent": agent, "committee": final}
                    )
    return changes
