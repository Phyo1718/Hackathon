"""Management insights: pure calculations over budget lines, approved spend and decision history.

No database access and no AI here, so every figure can be checked by a unit test.
"""
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

FORECAST_WINDOW_DAYS = 90
FORECAST_MIN_ORDERS = 2  # fewer approved orders in the window: no projection
RUNOUT_SOON_DAYS = 60  # a run-out date within this many days is highlighted

# Supplier concentration: a supplier is flagged only if all of these hold
SUPPLIER_SHARE_LIMIT = 0.40  # share of the budget line's approved spend above this
CONCENTRATION_MIN_LINE_SPEND = 10_000.0  # the line's approved spend is at least this (EUR)
CONCENTRATION_MIN_LINE_ORDERS = 3  # the line has at least this many approved orders
CONCENTRATION_MIN_SUPPLIERS = 2  # ... and at least this many suppliers,
CONCENTRATION_MIN_SUPPLIER_ORDERS = 3  # or at least this many orders from the single supplier


def _day(value: Any) -> date:
    return value.date() if isinstance(value, datetime) else value


def _year_end(today: date) -> date:
    return date(today.year, 12, 31)


def budget_forecast(
    lines: List[Dict[str, Any]],
    approvals: List[Dict[str, Any]],
    today: date,
    window_days: int = FORECAST_WINDOW_DAYS,
    min_orders: int = FORECAST_MIN_ORDERS,
) -> List[Dict[str, Any]]:
    """Committed vs. total per line and the projection to the end of the budget year
    (Haushaltsjahr) at the spending rate of the last window_days.

    status: "runs_out" (runout_date falls in this budget year; runout_soon if within
    RUNOUT_SOON_DAYS), "year_end" (the line lasts the year; year_end_share is the projected
    usage on 31 Dec), "exhausted" (nothing left) or "not_enough_data" (fewer than min_orders
    approved orders in the window, so nothing is projected).
    """
    start = today - timedelta(days=window_days)
    year_end = _year_end(today)
    result = []
    for line in lines:
        recent = [
            a for a in approvals
            if a["category"] == line["category"] and start <= _day(a["timestamp"]) <= today
        ]
        spent = sum(a["amount"] for a in recent)
        total, remaining = line["total"], line["remaining"]
        committed = total - remaining
        runout: Optional[date] = None
        daily_rate: Optional[float] = None
        year_end_committed: Optional[float] = None
        if remaining <= 0:
            status = "exhausted"
        elif len(recent) < min_orders or spent <= 0:
            status = "not_enough_data"
        else:
            daily_rate = spent / window_days
            year_end_committed = committed + daily_rate * (year_end - today).days
            runout = today + timedelta(days=int(remaining / daily_rate))
            if runout <= year_end:
                status = "runs_out"
            else:
                status, runout = "year_end", None
        result.append(
            {
                "category": line["category"],
                "department": line.get("department", ""),
                "total": total,
                "committed": committed,
                "remaining": remaining,
                "used_share": committed / total if total > 0 else 0.0,
                "recent_orders": len(recent),
                "recent_spend": spent,
                "status": status,
                "daily_rate": daily_rate,
                "runout_date": runout,
                "runout_soon": runout is not None and (runout - today).days <= RUNOUT_SOON_DAYS,
                "year_end_committed": year_end_committed,
                "year_end_share": (year_end_committed / total if total > 0 else 0.0) if year_end_committed is not None else None,
            }
        )
    return result


def burnup(line: Dict[str, Any], approvals: List[Dict[str, Any]], today: date) -> Dict[str, Any]:
    """Cumulative committed EUR on one budget line from 1 Jan to today (actual) and, if there is
    enough data, from today to 31 Dec at the 90-day rate (projection). Commitments from before
    this budget year are the starting value on 1 Jan."""
    year_start, year_end = date(today.year, 1, 1), _year_end(today)
    in_year = sorted(
        (a for a in approvals if a["category"] == line["category"] and year_start <= _day(a["timestamp"]) <= today),
        key=lambda a: _day(a["timestamp"]),
    )
    forecast = budget_forecast([line], approvals, today)[0]
    committed = forecast["committed"]
    running = max(0.0, committed - sum(a["amount"] for a in in_year))
    actual = [{"date": year_start, "cumulative": running}]
    for a in in_year:
        running += a["amount"]
        actual.append({"date": _day(a["timestamp"]), "cumulative": running})
    actual.append({"date": today, "cumulative": committed})
    projection = []
    if forecast["daily_rate"]:
        projection = [{"date": today, "cumulative": committed}, {"date": year_end, "cumulative": forecast["year_end_committed"]}]
    return {"category": line["category"], "total": line["total"], "actual": actual, "projection": projection,
            "forecast": forecast}


def supplier_shares(
    approvals: List[Dict[str, Any]],
    limit: float = SUPPLIER_SHARE_LIMIT,
    min_line_spend: float = CONCENTRATION_MIN_LINE_SPEND,
    min_line_orders: int = CONCENTRATION_MIN_LINE_ORDERS,
    min_suppliers: int = CONCENTRATION_MIN_SUPPLIERS,
    min_supplier_orders: int = CONCENTRATION_MIN_SUPPLIER_ORDERS,
) -> List[Dict[str, Any]]:
    """Share of approved spend per supplier within each budget line, largest first per line.

    line_checked: the line has enough spend and orders for a concentration check. above_limit:
    the supplier's share exceeds the limit on a checked line that has several suppliers, or
    several orders from the one supplier (one large order alone is no concentration).
    """
    per_line: Dict[str, Dict[str, Dict[str, float]]] = {}
    for a in approvals:
        entry = per_line.setdefault(a["category"], {}).setdefault(a["supplier"], {"spend": 0.0, "orders": 0})
        entry["spend"] += a["amount"]
        entry["orders"] += 1
    rows = []
    for category in sorted(per_line):
        suppliers = per_line[category]
        line_spend = sum(e["spend"] for e in suppliers.values())
        line_orders = sum(e["orders"] for e in suppliers.values())
        checked = line_spend >= min_line_spend and line_orders >= min_line_orders
        for supplier, e in sorted(suppliers.items(), key=lambda item: -item[1]["spend"]):
            share = e["spend"] / line_spend if line_spend > 0 else 0.0
            flagged = (
                checked and share > limit
                and (len(suppliers) >= min_suppliers or e["orders"] >= min_supplier_orders)
            )
            rows.append(
                {"category": category, "supplier": supplier, "spend": e["spend"], "orders": int(e["orders"]),
                 "share": share, "line_spend": line_spend, "line_orders": int(line_orders),
                 "line_checked": checked, "above_limit": flagged}
            )
    return rows


def supplier_totals(share_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Approved spend per supplier across all budget lines, largest first; flagged if the
    supplier is flagged on any line."""
    totals: Dict[str, Dict[str, Any]] = {}
    for r in share_rows:
        t = totals.setdefault(r["supplier"], {"supplier": r["supplier"], "spend": 0.0, "orders": 0, "lines": [], "flagged": False})
        t["spend"] += r["spend"]
        t["orders"] += r["orders"]
        t["lines"].append(r["category"])
        t["flagged"] = t["flagged"] or r["above_limit"]
    return sorted(totals.values(), key=lambda t: -t["spend"])


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
