import base64
import hashlib
import html
import json
import re
import sqlite3
import sys
import unicodedata
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

import altair as alt
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from pypdf import PdfReader

# Streamlit re-runs app.py on every interaction but keeps the imported src/ modules. Without a
# file watcher (watchdog) a server started before a change would run new app code against old
# modules, so they are dropped and re-imported whenever a file in src/ has changed.
_SRC_FINGERPRINT = tuple(sorted((f.name, f.stat().st_mtime_ns) for f in (Path(__file__).parent / "src").glob("*.py")))
if getattr(sys.modules.get("src"), "_fingerprint", _SRC_FINGERPRINT) != _SRC_FINGERPRINT:
    for _name in [n for n in sys.modules if n == "src" or n.startswith("src.")]:
        del sys.modules[_name]
import src  # noqa: E402

src._fingerprint = _SRC_FINGERPRINT

from src.agent import (  # noqa: E402
    CRITERIA,
    CRITERIA_PRESETS,
    ExtractedRequest,
    check_budget,
    approval_issues,
    check_supplier,
    commit_decision,
    draft_transfer_justification,
    evaluate_bids,
    evaluate_request,
    generate_anmeldebogen_pdf,
    generate_deckungsantrag_pdf,
    get_approved_spending,
    get_budget_lines,
    has_api_key,
    requests_awaiting_bids,
    score_bids,
    score_criterion,
    suggest_budget_transfers,
    verify_extracted_request,
)
from src.bid_parser import BidExtractionError, parse_bid_pdf
from src.checklist import STATUS_ICONS, verification_view
from src.help_chat import HelpUnavailable, ask, chat_enabled
from src.bid_scoring import explain, score_bid
from src.letters import (
    build_letters,
    email_body,
    email_lock_reasons,
    gmail_url,
    letter_pdf,
    mailto_url,
    stored_letter,
)
from src import ui_theme as ui  # noqa: E402  (presentation only: CSS, colours, decorative SVG)
from src.demo_seed import HISTORICAL_REQUESTS, SEED_REQUESTS, SEED_TENDER
from src.init_db import get_db_path, init_db
from src.insights import (
    CONCENTRATION_MIN_LINE_ORDERS,
    CONCENTRATION_MIN_LINE_SPEND,
    SUPPLIER_SHARE_LIMIT,
    budget_forecast,
    burnup,
    committee_changes,
    oversight,
    supplier_shares,
    supplier_totals,
)

# Load environment variables
load_dotenv()


def database_needs_init() -> bool:
    """Initialise the database only when it is missing or uses an outdated schema."""
    if not Path(get_db_path()).exists():
        return True
    try:
        with closing(sqlite3.connect(get_db_path())) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(Budgets);")}
            supplier_columns = {row[1] for row in conn.execute("PRAGMA table_info(Suppliers);")}
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table';")}
        return "Account_Type" not in columns or "Email" not in supplier_columns or "Employees" not in tables
    except Exception:
        return True


if database_needs_init():
    try:
        init_db()
    except Exception:
        pass


# ==============================================================================
# BILINGUAL LOCALIZATION (EN / DE) - FORMAL MUNICIPAL ADMINISTRATION THEME
# ==============================================================================

TRANSLATIONS = {
    "EN": {
        "agency": "Stadt Hildesheim | Central Procurement Office",
        "app_name": "Public Procurement Assistant",
        "lang_label": "Language",
        "nav_label": "Navigation",
        "nav_verify": "Request Verification",
        "nav_bids": "Bid Evaluation",
        "nav_add": "Add Procurement Request",
        "nav_insights": "Management Insights",
        # Management Insights
        "insights_desc": "Key figures from the budget database and the decision history. Forecasts are projections, not commitments.",
        "tile_budget": "Budget per line",
        "tile_budget_caption": "Committed vs. total in the current budget year. The projection to 31 Dec uses the spending rate of the last 90 days and needs at least 2 approved orders in that period.",
        "ins_col_line": "Budget line",
        "ins_col_department": "Department",
        "ins_col_committed": "Committed",
        "ins_col_total": "Total",
        "ins_col_used": "Used",
        "ins_col_runout": "Projection to 31.12.",
        "ins_not_enough": "not enough data",
        "ins_exhausted": "exhausted",
        "ins_runs_out": "Runs out ~{date}",
        "ins_year_end": "≈ {share} used by 31.12.",
        "ins_col_orders": "Orders",
        "ins_concentration_skipped": "Too little data for a concentration check: {lines} (needs at least {spend} approved spend and {orders} orders on the line).",
        "chart_line_select": "Budget line in the chart",
        "chart_actual": "Actual",
        "chart_projection": "Projection",
        "chart_total": "Budget {amount}",
        "chart_date": "Date",
        "chart_series": "Series",
        "chart_cumulative": "Committed (cumulative)",
        "chart_share_total": "Share of total",
        "chart_burnup_caption": "Solid: committed so far in this budget year. Dashed: projection to 31 Dec at the 90-day rate. Dotted: budget total of the line.",
        "chart_no_projection": "Not enough orders in the last 90 days for a projection.",
        "chart_supplier": "Supplier",
        "chart_spend": "Approved spend",
        "chart_orders": "Orders",
        "chart_lines": "Budget lines",
        "chart_flag": "above 40 %",
        "chart_suppliers_caption": "Approved spend per supplier across all budget lines. Amber: flagged for concentration on a budget line (see below).",
        "tile_suppliers": "Supplier share of spend",
        "tile_suppliers_caption": "Approved spend per budget line. A supplier with more than 40 % of a line is flagged if the line has at least EUR 10,000 approved spend and 3 orders, and several suppliers or at least 3 orders from that supplier.",
        "ins_col_supplier": "Supplier",
        "ins_col_spend": "Spend",
        "ins_col_share": "Share",
        "ins_supplier_warning": "{line}: {supplier} has {share} of the spend (above 40 %).",
        "ins_no_spend": "No approved spend yet.",
        "tile_oversight": "AI oversight",
        "tile_oversight_caption": "Agreement between the agent's recommendation and the caseworker's decision. 'Review required' recommendations leave the decision to the caseworker and are not counted.",
        "ins_agreement": "Agreement rate",
        "ins_agreement_detail": "{agreed} of {compared} decisions",
        "ins_overrides": "Overrides",
        "ins_deferred": "Left to caseworker",
        "ins_transfers": "Budget transfers proposed / accepted",
        "ins_committee_changes": "Bid scores changed",
        "ins_committee_header": "Committee changes: bid scores different from the agent's proposal",
        "ins_col_bidder": "Bidder",
        "ins_col_criterion": "Criterion",
        "ins_col_proposed": "Agent proposal",
        "ins_col_final": "Final score",
        "ins_overrides_header": "Overrides: the caseworker decided differently",
        "ins_deferred_header": "Review required: the caseworker decided",
        "ins_none": "None.",
        "ins_col_agent": "Agent",
        "ins_col_human": "Caseworker",
        "ins_col_date": "Decided",
        "ins_col_note": "Note",
        "live_state_header": "Administration Live State",
        "live_state_caption": "Live data from the municipal budget database",
        "no_budget_data": "No budget data available.",
        "reset_btn": "Reset Demo Data",
        "chat_button_help": "Help",
        "chat_title": "Help assistant",
        "chat_disclaimer": "Answers are based on the user manual. AI can make mistakes.",
        "chat_placeholder": "Ask a question about this app ...",
        "chat_clear": "Clear chat",
        "chat_unavailable": "The help assistant is unavailable right now. See the user manual (sidebar).",
        "chat_thinking": "Looking it up in the user manual ...",
        "chat_starters": ["How do I override the agent?", "What do References / Service mean?", "Why is the email button disabled?"],
        "manual_btn": "📘 User manual",
        "menu_toggle": "Toggle menu",
        "how_it_works": "How it works",
        "how_it_works_caption": "From the request to Management Insights: the agent prepares, people decide.",
        "reset_success": "Database and request queue reset to the initial demo state.",
        "reset_error": "Database reset failed: {error}",
        # View 1: Request Verification
        "verify_desc": "Pending procurement requests pre-checked by the agent. Select a row to review and decide.",
        "kpi_pending": "Pending",
        "kpi_approved": "Approved",
        "kpi_rejected": "Rejected",
        "queue_header": "Pending requests",
        "queue_empty": "There are no pending requests in the queue.",
        "go_add_btn": "Add procurement request",
        "col_ref": "Reference",
        "col_request": "Request",
        "col_assessment": "Agent assessment",
        "col_accessibility": "Accessibility",
        "accessibility_flag": "Check required",
        "col_received": "Received",
        "assessment_APPROVED": "Compliant",
        "assessment_REQUIRES_REVIEW": "Review required",
        "assessment_REJECTED": "Non-compliant",
        "decision_APPROVED": "Approved",
        "decision_REJECTED": "Rejected",
        "queue_complete": "All pending requests have been processed.",
        # Budget transfer (Deckungsantrag)
        "transfer_header": "Budget transfer possible",
        "transfer_intro": "The request exceeds the funds left on {line} by {shortfall}. The agent proposes these budget lines with enough free funds (same account type first). The transfer is booked only together with an approval; on a rejection nothing moves.",
        "transfer_choose": "Cover from budget line",
        "transfer_option": "{line} · {department} · {type} · {free} free · {basis}",
        "transfer_same_type": "Same account type ({type}): transfer within the cover rules ({basis}).",
        "transfer_other_type": "Different account type ({donor_type} to {need_type}): approval of over-plan spending required ({basis}).",
        "transfer_after": "After the transfer, {line} still has {spare} free.",
        "transfer_pdf_btn": "Download draft application (PDF)",
        "transfer_include": "Include budget transfer from {donor} (application reviewed and signed)",
        "transfer_not_offered": "A budget transfer would only solve the budget issue, so it is not offered while other issues remain.",
        "issues_header": "Open issues",
        "issue_supplier_unknown": "Supplier {supplier} is not registered in the supplier register.",
        "issue_supplier_not_approved": "Supplier {supplier} is not approved.",
        "issue_budget_unknown": "Budget line {line} was not found.",
        "issue_budget_short": "{line}: {shortfall} short of the remaining funds.",
        "rec_APPROVED": "Approve",
        "rec_REJECTED": "Reject",
        "caseworker_note_label": "Caseworker note",
        "caseworker_note_help": "Required (at least 15 characters) when deciding against the agent's recommendation, otherwise optional. Stored in the audit log and the request history.",
        "override_warning": "{action}: You are deciding against the agent's recommendation ({recommendation}). A justification is required for the file (at least 15 characters).",
        "history_override": "Override",
        "transfer_done": "Approved with budget transfer: {amount} from {donor} to {line} ({basis}).",
        "transfer_none": "No budget line has enough free funds to cover the shortfall.",
        "acct_Aufwand": "expense (Aufwand)",
        "acct_Investiv": "investment (Investiv)",
        "history_transfer": "Budget transfer: {amount} from {donor} ({basis})",
        "history_demo": "Demo",
        # History and budget chart
        "history_btn": "History",
        "history_requests_title": "Request history",
        "history_bids_title": "Bid evaluation history",
        "history_filter": "Show",
        "filter_ALL": "All",
        "history_empty": "No decisions recorded yet.",
        "history_tenders_empty": "No bid evaluations recorded yet.",
        "history_decided": "Decided {when}",
        "history_agent_vs_human": "Agent recommendation: {agent} · Caseworker decision: {human}",
        "history_agent_reason": "Agent's reason",
        "history_note": "Caseworker note",
        "history_justification": "Justification for the budget overage",
        "tender_run": "Evaluated {when} · {criteria}",
        "col_rank": "Rank",
        "col_status": "Status",
        "status_recommended": "Recommended supplier",
        "status_award_sent": "Award sent {when}",
        "status_not_selected": "Not selected",
        "status_rejection_sent": "Rejection sent {when}",
        "short_price": "Price (0-10)",
        "short_delivery": "Delivery (0-10)",
        "short_warranty": "Warranty (0-10)",
        "short_references": "Ref./Service",
        "short_concept": "Concept/Quality",
        "col_email": "Email",
        "letters_header": "Award and rejection letters (§ 46 UVgO)",
        "letters_caption": "One email per bidder, never several bidders in one email. Opening the mail program cannot confirm that the email was sent: tick 'Mark as sent' after sending.",
        "award_approval": "Award approved (Freigabe erteilt) – I am authorised to award this contract",
        "award_approval_help": "The award letter concludes the contract. Send only after approval.",
        "rejection_email_help": "Rejection letter (§ 46 UVgO). Unlocked by the award approval; letters can be sent in any order.",
        "letter_award": "Award letter",
        "letter_rejection": "Rejection letter",
        "letter_title": "{bidder} · {kind} · {status}",
        "letter_to": "To",
        "letter_subject": "Subject",
        "email_btn": "✉ Email",
        "gmail_link": "Open in Gmail",
        "letter_pdf": "Full letter (PDF)",
        "letter_shortened": "The email text is shortened; attach the PDF.",
        "mark_sent": "Mark as sent",
        "lock_approval": "Tick 'Award approved' to unlock the emails.",
        "lock_email_missing": "Email address missing",
        "email_input": "Email address",
        "email_send": "✉ Send",
        "email_reopen": "✉ Open again",
        "sent_on": "Sent {when}",
        "no_email": "no email address",
        "breakdown_offer": "Offer: {item} · quantity {quantity} · price basis {basis} · email {email}",
        "breakdown_sources": "Source text from PDF: {text}",
        "meter_total": "Total available: {available} of {total}",
        "meter_left": "{amount} left",
        "meter_over": "{amount} over budget",
        "meter_committed": "{committed} committed of {total}",
        "meter_share": "{pct}%",
        "no_tender_requests": "No approved requests waiting for bids. Approve a request in Request Verification first.",
        "go_verify_requests": "Go to Request Verification",
        "tender_label": "Which request are these bids for?",
        "tender_other": "Other tender (no request)",
        "tender_title_label": "Tender title",
        "tender_title_default": "Tender without request reference",
        "duplicate_bidder": "Bidder names must be unique: {bidders}",
        # Dialog
        "dialog_title": "Request {ref}",
        "dialog_received": "Received {received} · Source: {source}",
        "fact_supplier": "Supplier",
        "fact_amount": "Requested amount",
        "fact_position": "Budget position",
        "fact_available": "Currently available",
        "fact_form": "Official form",
        "fact_staff": "Department staff",
        "staff_value": "{total} employees, {special} with special needs",
        "form_lud": "Anmeldebogen LuD (new award)",
        "form_extension": "Anmeldebogen Auftragserweiterung (contract extension)",
        "banner_APPROVED": "Agent recommendation: Approve – {reason} The caseworker decides.",
        "banner_REQUIRES_REVIEW": "Agent recommendation: Review required – {reason} The caseworker decides.",
        "banner_REJECTED": "Agent recommendation: Reject – {reason} The caseworker decides; approving requires a justification.",
        "reason_approved": "Supplier is approved and the budget covers the amount.",
        "reason_borderline": "The amount exceeds the remaining budget by {short} (within the 5 % tolerance).",
        "reason_supplier_unknown": "Supplier {supplier} is not in the supplier register.",
        "reason_supplier_not_approved": "Supplier {supplier} is not approved.",
        "reason_budget_unknown": "Budget line {category} was not found.",
        "reason_budget_exceeded": "The amount exceeds the remaining budget by {short} (more than 5 %).",
        "check_supplier": "Supplier",
        "check_budget": "Budget",
        "check_form": "Form",
        "check_accessibility": "Accessibility",
        "chk_supplier_ok": "{supplier} · approved",
        "chk_supplier_not_approved": "{supplier} · not approved",
        "chk_supplier_unknown": "{supplier} · not in the supplier register",
        "chk_budget_ok": "{amount} requested · {left} left on {line} → {after} after",
        "chk_budget_borderline": "{amount} requested · {left} left on {line} → {short} short (within 5 %)",
        "chk_budget_short": "{amount} requested · {left} left on {line} → {short} short",
        "chk_budget_unknown": "budget line {category} not found",
        "chk_form_lud": "Anmeldebogen LuD (first contract with this supplier)",
        "chk_form_extension": "Anmeldebogen Auftragserweiterung (previous contract on {date})",
        "chk_access_needs": "{special} of {total} staff have special needs → {hint}",
        "chk_access_none": "no staff with special needs ({total} staff)",
        "chk_access_unknown": "no staff data for {department}",
        "hint_it": "e.g. screen reader support, adjustable display/keyboard",
        "hint_furniture": "e.g. ergonomic, height-adjustable",
        "hint_general": "check that the items are accessible",
        "details_header": "Details (extracted data and full reasoning)",
        "details_extracted": "Extracted data",
        "details_steps": "Full reasoning",
        "detail_extraction": "**Extraction:** supplier **{supplier}**, amount **{amount}**, budget line **{category}** (Konto {konto}).",
        "detail_history_new": "**Procurement history:** Checked the procurement history: no previous contract with {supplier} → new award (Anmeldebogen LuD).",
        "detail_history_extension": "**Procurement history:** Checked the procurement history: {count} previous approved contract(s) with {supplier}, the latest on {date} → contract extension (Anmeldebogen Auftragserweiterung).",
        "detail_supplier_ok": "**Supplier:** {supplier} is in the supplier register and approved.",
        "detail_supplier_not_approved": "**Supplier:** {supplier} is in the supplier register but not approved.",
        "detail_supplier_unknown": "**Supplier:** {supplier} is not in the supplier register.",
        "detail_budget": "**Budget:** {category} (Konto {konto}) had {left} left when the request was checked; requested: {amount}.",
        "detail_budget_unknown": "**Budget:** budget line {category} was not found.",
        "detail_access_needs": "**Accessibility:** {special} of {total} employees in {department} have special needs. The procured items should be ergonomic and accessible; this note is printed in the Anmeldebogen (Sonstige Hinweise).",
        "detail_access_none": "**Accessibility:** no employees with special needs in {department} ({total} employees).",
        "detail_access_unknown": "**Accessibility:** no staff data for {department}.",
        "request_text_header": "Full request text",
        "reasoning_header": "Step-by-step verification",
        "no_reasoning": "No reasoning provided.",
        "approval_header": "Caseworker decision",
        "approval_note": "Approval commits the budget, writes the audit log and generates the Anmeldebogen in one step.",
        "commit_approve_btn": "Approve & Commit to Budget",
        "commit_reject_btn": "Reject",
        "commit_error": "Commit failed: {error}",
        "committed_success": "Approved. The budget has been committed, the audit log has been written and the Anmeldebogen download has started.",
        "committed_reject": "Rejected. The decision has been recorded in the audit log. No budget was committed.",
        "download_form_btn": "Download Anmeldebogen (PDF) again",
        "pdf_error": "The PDF could not be generated: {error}",
        "next_request_btn": "Next Request",
        "close_btn": "Close",
        "remaining_in_queue": "{count} request(s) remaining in the queue.",
        # View 3: Add Procurement Request
        "add_desc": "Submit a quotation PDF or enter the request manually. The agent evaluates it and places it in the verification queue.",
        "pdf_label": "Upload quotation (PDF)",
        "pdf_help": "The extracted text is placed in the request field below, where it can be reviewed before submission.",
        "pdf_extracted": "{count} characters extracted from the PDF.",
        "pdf_extract_warning": "No extractable text was found in the PDF.",
        "pdf_extract_error": "The PDF could not be read: {error}",
        "or_divider": "or enter the request manually",
        "textarea_label": "Procurement request details",
        "textarea_placeholder": "Enter the procurement request, including supplier, amount and budget category.",
        "sample_header": "Sample requests",
        "sample_valid": "Valid IT request (Dell)",
        "sample_unapproved": "Blocked supplier (TechCorp)",
        "sample_review": "Borderline budget (Stadtwerke)",
        "submit_btn": "Submit for Verification",
        "no_input_warning": "Please enter a procurement request or upload a document.",
        "spinner_eval": "Checking the request against budget data and the supplier register...",
        "eval_error": "The request could not be evaluated, so it was not added to the queue: {error}",
        "submitted_success": "Request {ref} was evaluated and added to the verification queue ({count} pending).",
        "go_verify_btn": "Open verification queue",
        "source_manual": "Manual entry",
        "source_pdf": "PDF: {name}",
        "source_sample": "Sample request",
        # View 2: Bid Evaluation
        "bids_desc": "Upload the quotations, check the extracted bid data and the scores proposed by the agent, confirm them as the committee and run the weighted evaluation. Award and rejection letters (§ 46 UVgO) are then prepared for every bidder.",
        "criteria_header": "Evaluation criteria and weights",
        "preset_label": "Criteria set",
        "preset_sheet": "Official sheet (price, references/service, concept/quality)",
        "preset_goods": "Goods purchase (price, delivery, warranty)",
        "preset_sheet_note": "Auswertung_Hackathon.XLSX weights price, references/service and concept/quality with the factors 30/30/20 (max. 800 points, no fourth criterion). Normalised to 100 % this is 37.5/37.5/25 with the same ranking. Use the weights published in the tender documents.",
        "preset_goods_note": "Suggested for standard goods such as laptops: every criterion is an objective value taken from the bids. Example weights; use the weights published in the tender documents.",
        "crit_price": "Price",
        "crit_delivery": "Delivery time",
        "crit_warranty": "Warranty",
        "crit_references": "References / Service",
        "crit_concept": "Concept / Quality",
        "weights_ok": "Weights total {total:g} %.",
        "weights_error": "The weights must total 100 % (currently {total:g} %).",
        "bids_pdfs_label": "Upload quotations (PDF, multiple files)",
        "bids_pdfs_help": "Bidder, price, item, quantity, delivery time, warranty, references, service terms and offer validity are read from each PDF.",
        "bid_extract_error": "{file} could not be read: {error}",
        "bidder_from_filename": "{file}: no supplier name found in the PDF. The bidder name '{bidder}' was taken from the file name; please check it.",
        "bids_upload_hint": "Upload the bidders' quotations (PDF) to extract the bid data.",
        "bids_table_header": "Bid data",
        "bids_table_caption": "Price and scores are read from the PDFs and can be corrected before the evaluation. References / Service and Concept / Quality are proposed by the agent with the same rubric for every bidder; the breakdown and the source text from the PDFs are below the table.",
        "help_references": "Can this supplier be trusted to deliver and support us? Track record with the city, references for comparable deliveries named in the bid, warranty and after-sales service.",
        "help_concept": "How well does this offer fit what was requested? Item type and quantity (brand-neutral), delivery time and completeness of the offer (price basis, specification, validity).",
        "tag_agent": "AI",
        "missing_score": "{bidder}: {criterion} – {reason}",
        "committee_confirm": "The evaluation committee has reviewed and confirmed the scores",
        "committee_confirm_help": "Required before the evaluation. The committee remains responsible for every score, including the ones proposed by the agent.",
        "breakdown_header": "Agent scoring breakdown (same rubric for every bidder)",
        "breakdown_required": "required: {reason}",
        "breakdown_committee": "Committee value: {score}",
        "col_bidder": "Bidder",
        "col_price": "Price (EUR)",
        "col_delivery_days": "Delivery (days)",
        "col_warranty_months": "Warranty (months)",
        "col_references": "References / Service (0-10)",
        "col_concept": "Concept / Quality (0-10)",
        "col_score": "{criterion} (0-10)",
        "col_points": "{criterion} pts",
        "col_total_pts": "Total pts",
        "basis_gross": "gross",
        "basis_net": "net (excl. VAT)",
        "basis_total": "total (VAT not stated)",
        "cell_missing": "required",
        "blocked_header": "Evaluation blocked. Missing values per bidder (scores without any evidence, or values not stated in the bid):",
        "missing_bidder": "Row {row}: bidder name required",
        "eval_bids_btn": "Run Evaluation",
        "invalid_price_error": "Every bid price must be greater than EUR 0. Please correct: {bidders}",
        "spinner_bids": "Calculating the weighted evaluation...",
        "winner_label": "Recommended supplier",
        "winner_points": "Total points (of 100)",
        "winner_price": "Bid price",
        "winner_lead": "Lead over runner-up",
        "matrix_header": "Scoring matrix",
    },
    "DE": {
        "agency": "Stadt Hildesheim | Zentrale Vergabestelle",
        "app_name": "Öffentlicher Vergabeassistent",
        "lang_label": "Sprache",
        "nav_label": "Navigation",
        "nav_verify": "Antragsprüfung",
        "nav_bids": "Angebotswertung",
        "nav_add": "Beschaffungsantrag erfassen",
        "nav_insights": "Management-Übersicht",
        # Management Insights
        "insights_desc": "Kennzahlen aus der Haushaltsdatenbank und dem Entscheidungsverlauf. Prognosen sind Hochrechnungen, keine Zusagen.",
        "tile_budget": "Budget je Haushaltsposition",
        "tile_budget_caption": "Gebunden gegenüber Gesamt. Die Prognose bis 31.12. wird mit der Ausgabenrate der letzten 90 Tage hochgerechnet und setzt mindestens 2 genehmigte Aufträge in diesem Zeitraum voraus.",
        "ins_col_line": "Haushaltsposition",
        "ins_col_department": "Fachbereich",
        "ins_col_committed": "Gebunden",
        "ins_col_total": "Gesamt",
        "ins_col_used": "Ausgeschöpft",
        "ins_col_runout": "Prognose bis 31.12.",
        "ins_not_enough": "zu wenig Daten",
        "ins_exhausted": "ausgeschöpft",
        "ins_runs_out": "Ausgeschöpft ~{date}",
        "ins_year_end": "≈ {share} ausgeschöpft bis 31.12.",
        "ins_col_orders": "Bestellungen",
        "ins_concentration_skipped": "Zu wenig Daten für eine Konzentrationsprüfung: {lines} (nötig sind mindestens {spend} genehmigte Ausgaben und {orders} Bestellungen je Position).",
        "chart_line_select": "Haushaltsposition im Diagramm",
        "chart_actual": "Ist",
        "chart_projection": "Prognose",
        "chart_total": "Budget {amount}",
        "chart_date": "Datum",
        "chart_series": "Verlauf",
        "chart_cumulative": "Gebunden (kumuliert)",
        "chart_share_total": "Anteil am Budget",
        "chart_burnup_caption": "Durchgezogen: im laufenden Haushaltsjahr gebunden. Gestrichelt: Prognose bis 31.12. mit der Rate der letzten 90 Tage. Gepunktet: Gesamtbudget der Position.",
        "chart_no_projection": "Zu wenige Bestellungen in den letzten 90 Tagen für eine Prognose.",
        "chart_supplier": "Lieferant",
        "chart_spend": "Genehmigte Ausgaben",
        "chart_orders": "Bestellungen",
        "chart_lines": "Haushaltspositionen",
        "chart_flag": "über 40 %",
        "chart_suppliers_caption": "Genehmigte Ausgaben je Lieferant über alle Haushaltspositionen. Orange: auffällige Konzentration auf einer Position (siehe unten).",
        "tile_suppliers": "Lieferantenanteil an den Ausgaben",
        "tile_suppliers_caption": "Genehmigte Ausgaben je Haushaltsposition. Ein Lieferant mit mehr als 40 % einer Position wird markiert, wenn die Position mindestens 10.000 € genehmigte Ausgaben und 3 Bestellungen hat und mehrere Lieferanten oder mindestens 3 Bestellungen dieses Lieferanten.",
        "ins_col_supplier": "Lieferant",
        "ins_col_spend": "Ausgaben",
        "ins_col_share": "Anteil",
        "ins_supplier_warning": "{line}: {supplier} hat {share} der Ausgaben (über 40 %).",
        "ins_no_spend": "Noch keine genehmigten Ausgaben.",
        "tile_oversight": "Aufsicht über den Agenten",
        "tile_oversight_caption": "Übereinstimmung zwischen Empfehlung des Agenten und Entscheidung der Sachbearbeitung. Empfehlungen 'Prüfung erforderlich' überlassen die Entscheidung der Sachbearbeitung und werden nicht gezählt.",
        "ins_agreement": "Übereinstimmung",
        "ins_agreement_detail": "{agreed} von {compared} Entscheidungen",
        "ins_overrides": "Abweichungen",
        "ins_deferred": "An Sachbearbeitung übergeben",
        "ins_transfers": "Budgetverschiebungen vorgeschlagen / angenommen",
        "ins_committee_changes": "Geänderte Bieterpunkte",
        "ins_committee_header": "Änderungen der Kommission: Bieterpunkte abweichend vom Vorschlag des Agenten",
        "ins_col_bidder": "Bieter",
        "ins_col_criterion": "Kriterium",
        "ins_col_proposed": "Vorschlag Agent",
        "ins_col_final": "Endwert",
        "ins_overrides_header": "Abweichungen: Die Sachbearbeitung entschied anders",
        "ins_deferred_header": "Prüfung erforderlich: Die Sachbearbeitung entschied",
        "ins_none": "Keine.",
        "ins_col_agent": "Agent",
        "ins_col_human": "Sachbearbeitung",
        "ins_col_date": "Entschieden",
        "ins_col_note": "Vermerk",
        "live_state_header": "Verwaltungsstatus (live)",
        "live_state_caption": "Live-Daten aus der kommunalen Haushaltsdatenbank",
        "no_budget_data": "Keine Budgetdaten verfügbar.",
        "reset_btn": "Demo-Daten zurücksetzen",
        "chat_button_help": "Hilfe",
        "chat_title": "Hilfe-Assistent",
        "chat_disclaimer": "Antworten beruhen auf dem Benutzerhandbuch. KI kann Fehler machen.",
        "chat_placeholder": "Frage zur Anwendung stellen ...",
        "chat_clear": "Chat leeren",
        "chat_unavailable": "Der Hilfe-Assistent ist gerade nicht erreichbar. Siehe Benutzerhandbuch (Seitenleiste).",
        "chat_thinking": "Suche im Benutzerhandbuch ...",
        "chat_starters": ["Wie entscheide ich gegen den Agenten?", "Was bedeutet Referenzen / Service?", "Warum ist der E-Mail-Button gesperrt?"],
        "manual_btn": "📘 Benutzerhandbuch",
        "menu_toggle": "Menü ein-/ausblenden",
        "how_it_works": "So funktioniert der Assistent",
        "how_it_works_caption": "Vom Antrag bis zur Management-Übersicht: Der Agent bereitet vor, Menschen entscheiden.",
        "reset_success": "Datenbank und Antragswarteschlange auf den Demo-Stand zurückgesetzt.",
        "reset_error": "Zurücksetzen der Datenbank fehlgeschlagen: {error}",
        # View 1: Request Verification
        "verify_desc": "Offene, vom Agenten vorgeprüfte Beschaffungsanträge. Wählen Sie eine Zeile zur Prüfung und Entscheidung.",
        "kpi_pending": "Offen",
        "kpi_approved": "Genehmigt",
        "kpi_rejected": "Abgelehnt",
        "queue_header": "Offene Anträge",
        "queue_empty": "In der Warteschlange befinden sich keine offenen Anträge.",
        "go_add_btn": "Beschaffungsantrag erfassen",
        "col_ref": "Aktenzeichen",
        "col_request": "Antrag",
        "col_assessment": "Bewertung des Agenten",
        "col_accessibility": "Barrierefreiheit",
        "accessibility_flag": "Prüfung erforderlich",
        "col_received": "Eingang",
        "assessment_APPROVED": "Regelkonform",
        "assessment_REQUIRES_REVIEW": "Prüfung erforderlich",
        "assessment_REJECTED": "Nicht regelkonform",
        "decision_APPROVED": "Genehmigt",
        "decision_REJECTED": "Abgelehnt",
        "queue_complete": "Alle offenen Anträge wurden bearbeitet.",
        # Budget transfer (Deckungsantrag)
        "transfer_header": "Budgetverschiebung möglich",
        "transfer_intro": "Die Anfrage überschreitet die verfügbaren Mittel der Position {line} um {shortfall}. Der Agent schlägt diese Positionen mit ausreichend freien Mitteln vor (gleiche Kontenart zuerst). Die Verschiebung wird nur zusammen mit einer Genehmigung gebucht; bei einer Ablehnung wird nichts bewegt.",
        "transfer_choose": "Deckung aus Haushaltsposition",
        "transfer_option": "{line} · {department} · {type} · {free} frei · {basis}",
        "transfer_same_type": "Gleiche Kontenart ({type}): Mittelverschiebung im Rahmen der Deckungsfähigkeit ({basis}).",
        "transfer_other_type": "Unterschiedliche Kontenart ({donor_type} zu {need_type}): Zustimmung zu überplanmäßigen Aufwendungen erforderlich ({basis}).",
        "transfer_after": "Nach der Verschiebung verbleiben auf {line} noch {spare}.",
        "transfer_pdf_btn": "Antragsentwurf herunterladen (PDF)",
        "transfer_include": "Budgetverschiebung aus {donor} einbeziehen (Antrag geprüft und unterschrieben)",
        "transfer_not_offered": "Eine Budgetverschiebung würde nur das Budgetproblem lösen und wird daher nicht angeboten, solange weitere Punkte offen sind.",
        "issues_header": "Offene Punkte",
        "issue_supplier_unknown": "Lieferant {supplier} ist nicht im Lieferantenverzeichnis registriert.",
        "issue_supplier_not_approved": "Lieferant {supplier} ist nicht zugelassen.",
        "issue_budget_unknown": "Haushaltsposition {line} wurde nicht gefunden.",
        "issue_budget_short": "{line}: Es fehlen {shortfall} an verfügbaren Mitteln.",
        "rec_APPROVED": "Genehmigen",
        "rec_REJECTED": "Ablehnen",
        "caseworker_note_label": "Vermerk der Sachbearbeitung",
        "caseworker_note_help": "Pflicht (mindestens 15 Zeichen), wenn Sie gegen die Empfehlung des Agenten entscheiden, sonst optional. Wird im Audit-Protokoll und im Antragsverlauf gespeichert.",
        "override_warning": "{action}: Sie entscheiden gegen die Empfehlung des Agenten ({recommendation}). Für die Akte ist eine Begründung erforderlich (mindestens 15 Zeichen).",
        "history_override": "Abweichung",
        "transfer_done": "Genehmigt mit Budgetverschiebung: {amount} von {donor} nach {line} ({basis}).",
        "transfer_none": "Keine Haushaltsposition hat ausreichend freie Mittel für den Mehrbedarf.",
        "acct_Aufwand": "Aufwand",
        "acct_Investiv": "Investiv",
        "history_transfer": "Budgetverschiebung: {amount} aus {donor} ({basis})",
        "history_demo": "Demo",
        # History and budget chart
        "history_btn": "Verlauf",
        "history_requests_title": "Antragsverlauf",
        "history_bids_title": "Verlauf der Angebotswertungen",
        "history_filter": "Anzeigen",
        "filter_ALL": "Alle",
        "history_empty": "Noch keine Entscheidungen erfasst.",
        "history_tenders_empty": "Noch keine Angebotswertungen erfasst.",
        "history_decided": "Entschieden am {when}",
        "history_agent_vs_human": "Empfehlung des Agenten: {agent} · Entscheidung der Sachbearbeitung: {human}",
        "history_agent_reason": "Begründung des Agenten",
        "history_note": "Vermerk der Sachbearbeitung",
        "history_justification": "Begründung der Budgetüberschreitung",
        "tender_run": "Gewertet am {when} · {criteria}",
        "col_rank": "Rang",
        "col_status": "Status",
        "status_recommended": "Empfohlener Bieter",
        "status_award_sent": "Zuschlag versandt {when}",
        "status_not_selected": "Nicht berücksichtigt",
        "status_rejection_sent": "Absage versandt {when}",
        "short_price": "Preis (0-10)",
        "short_delivery": "Lieferzeit (0-10)",
        "short_warranty": "Garantie (0-10)",
        "short_references": "Ref./Service",
        "short_concept": "Konzept/Qualität",
        "col_email": "E-Mail",
        "letters_header": "Zuschlags- und Absageschreiben (§ 46 UVgO)",
        "letters_caption": "Eine E-Mail je Bieter, nie mehrere Bieter in einer E-Mail. Das Öffnen des E-Mail-Programms bestätigt keinen Versand: Nach dem Senden 'Als versandt markieren' anhaken.",
        "award_approval": "Zuschlag freigegeben (Freigabe erteilt) – ich bin berechtigt, diesen Auftrag zu vergeben",
        "award_approval_help": "Das Zuschlagsschreiben schließt den Vertrag. Erst nach Freigabe versenden.",
        "rejection_email_help": "Absageschreiben (§ 46 UVgO). Mit der Freigabe des Zuschlags freigeschaltet; die Schreiben können in beliebiger Reihenfolge versandt werden.",
        "letter_award": "Zuschlagsschreiben",
        "letter_rejection": "Absageschreiben",
        "letter_title": "{bidder} · {kind} · {status}",
        "letter_to": "An",
        "letter_subject": "Betreff",
        "email_btn": "✉ E-Mail",
        "gmail_link": "In Gmail öffnen",
        "letter_pdf": "Vollständiges Schreiben (PDF)",
        "letter_shortened": "Der E-Mail-Text ist gekürzt; bitte die PDF anhängen.",
        "mark_sent": "Als versandt markieren",
        "lock_approval": "Zum Freischalten der E-Mails 'Zuschlag freigegeben' anhaken.",
        "lock_email_missing": "E-Mail-Adresse fehlt",
        "email_input": "E-Mail-Adresse",
        "email_send": "✉ Senden",
        "email_reopen": "✉ Erneut öffnen",
        "sent_on": "Versandt {when}",
        "no_email": "keine E-Mail-Adresse",
        "breakdown_offer": "Angebot: {item} · Menge {quantity} · Preisbasis {basis} · E-Mail {email}",
        "breakdown_sources": "Fundstellen in der PDF: {text}",
        "meter_total": "Insgesamt verfügbar: {available} von {total}",
        "meter_left": "{amount} verfügbar",
        "meter_over": "{amount} über Budget",
        "meter_committed": "{committed} gebunden von {total}",
        "meter_share": "{pct} %",
        "no_tender_requests": "Keine genehmigten Anträge, für die Angebote ausstehen. Genehmigen Sie zuerst einen Antrag in der Antragsprüfung.",
        "go_verify_requests": "Zur Antragsprüfung",
        "tender_label": "Für welchen Antrag sind diese Angebote?",
        "tender_other": "Sonstige Ausschreibung (ohne Antrag)",
        "tender_title_label": "Bezeichnung der Ausschreibung",
        "tender_title_default": "Ausschreibung ohne Antragsbezug",
        "duplicate_bidder": "Bieternamen müssen eindeutig sein: {bidders}",
        # Dialog
        "dialog_title": "Antrag {ref}",
        "dialog_received": "Eingang {received} · Quelle: {source}",
        "fact_supplier": "Lieferant",
        "fact_amount": "Beantragter Betrag",
        "fact_position": "Haushaltsposition",
        "fact_available": "Aktuell verfügbar",
        "fact_form": "Amtliches Formular",
        "fact_staff": "Beschäftigte im Fachbereich",
        "staff_value": "{total} Beschäftigte, davon {special} mit besonderen Bedürfnissen",
        "form_lud": "Anmeldebogen LuD (Neuvergabe)",
        "form_extension": "Anmeldebogen Auftragserweiterung",
        "banner_APPROVED": "Empfehlung des Agenten: Genehmigen – {reason} Die Entscheidung trifft die Sachbearbeitung.",
        "banner_REQUIRES_REVIEW": "Empfehlung des Agenten: Prüfung erforderlich – {reason} Die Entscheidung trifft die Sachbearbeitung.",
        "banner_REJECTED": "Empfehlung des Agenten: Ablehnen – {reason} Die Entscheidung trifft die Sachbearbeitung; eine Genehmigung erfordert eine Begründung.",
        "reason_approved": "Der Lieferant ist zugelassen und das Budget deckt den Betrag.",
        "reason_borderline": "Der Betrag überschreitet das Restbudget um {short} (innerhalb der 5-%-Toleranz).",
        "reason_supplier_unknown": "Lieferant {supplier} ist nicht im Lieferantenverzeichnis.",
        "reason_supplier_not_approved": "Lieferant {supplier} ist nicht zugelassen.",
        "reason_budget_unknown": "Haushaltsposition {category} wurde nicht gefunden.",
        "reason_budget_exceeded": "Der Betrag überschreitet das Restbudget um {short} (mehr als 5 %).",
        "check_supplier": "Lieferant",
        "check_budget": "Budget",
        "check_form": "Formular",
        "check_accessibility": "Barrierefreiheit",
        "chk_supplier_ok": "{supplier} · zugelassen",
        "chk_supplier_not_approved": "{supplier} · nicht zugelassen",
        "chk_supplier_unknown": "{supplier} · nicht im Lieferantenverzeichnis",
        "chk_budget_ok": "{amount} beantragt · {left} frei auf {line} → danach {after}",
        "chk_budget_borderline": "{amount} beantragt · {left} frei auf {line} → {short} zu wenig (innerhalb 5 %)",
        "chk_budget_short": "{amount} beantragt · {left} frei auf {line} → {short} zu wenig",
        "chk_budget_unknown": "Haushaltsposition {category} nicht gefunden",
        "chk_form_lud": "Anmeldebogen LuD (erster Auftrag an diesen Lieferanten)",
        "chk_form_extension": "Anmeldebogen Auftragserweiterung (früherer Auftrag vom {date})",
        "chk_access_needs": "{special} von {total} Beschäftigten mit besonderen Bedürfnissen → {hint}",
        "chk_access_none": "keine Beschäftigten mit besonderen Bedürfnissen ({total} Beschäftigte)",
        "chk_access_unknown": "keine Beschäftigtendaten für {department}",
        "hint_it": "z. B. Screenreader-Unterstützung, verstellbarer Bildschirm/Tastatur",
        "hint_furniture": "z. B. ergonomisch, höhenverstellbar",
        "hint_general": "Barrierefreiheit der Gegenstände prüfen",
        "details_header": "Details (ausgelesene Daten und vollständige Begründung)",
        "details_extracted": "Ausgelesene Daten",
        "details_steps": "Vollständige Begründung",
        "detail_extraction": "**Auslesen:** Lieferant **{supplier}**, Betrag **{amount}**, Haushaltsposition **{category}** (Konto {konto}).",
        "detail_history_new": "**Vergabeverlauf:** Vergabeverlauf geprüft: kein früherer Auftrag an {supplier} → Neuvergabe (Anmeldebogen LuD).",
        "detail_history_extension": "**Vergabeverlauf:** Vergabeverlauf geprüft: {count} frühere(r) genehmigte(r) Auftrag/Aufträge an {supplier}, zuletzt am {date} → Auftragserweiterung (Anmeldebogen Auftragserweiterung).",
        "detail_supplier_ok": "**Lieferant:** {supplier} ist im Lieferantenverzeichnis und zugelassen.",
        "detail_supplier_not_approved": "**Lieferant:** {supplier} ist im Lieferantenverzeichnis, aber nicht zugelassen.",
        "detail_supplier_unknown": "**Lieferant:** {supplier} ist nicht im Lieferantenverzeichnis.",
        "detail_budget": "**Budget:** {category} (Konto {konto}) hatte bei der Prüfung {left} frei; beantragt: {amount}.",
        "detail_budget_unknown": "**Budget:** Haushaltsposition {category} wurde nicht gefunden.",
        "detail_access_needs": "**Barrierefreiheit:** {special} von {total} Beschäftigten im Fachbereich {department} haben besondere Bedürfnisse. Die beschafften Gegenstände sollen ergonomisch und barrierefrei sein; der Hinweis steht im Anmeldebogen (Sonstige Hinweise).",
        "detail_access_none": "**Barrierefreiheit:** keine Beschäftigten mit besonderen Bedürfnissen im Fachbereich {department} ({total} Beschäftigte).",
        "detail_access_unknown": "**Barrierefreiheit:** keine Beschäftigtendaten für {department}.",
        "request_text_header": "Vollständiger Antragstext",
        "reasoning_header": "Schritt-für-Schritt-Prüfprotokoll",
        "no_reasoning": "Keine Begründung vorhanden.",
        "approval_header": "Entscheidung der Sachbearbeitung",
        "approval_note": "Die Genehmigung belastet das Budget, schreibt das Audit-Protokoll und erzeugt den Anmeldebogen in einem Schritt.",
        "commit_approve_btn": "Genehmigen und Budget belasten",
        "commit_reject_btn": "Ablehnen",
        "commit_error": "Verbuchung fehlgeschlagen: {error}",
        "committed_success": "Genehmigt. Das Budget wurde belastet, der Audit-Eintrag geschrieben und der Download des Anmeldebogens gestartet.",
        "committed_reject": "Abgelehnt. Die Entscheidung wurde im Audit-Protokoll gespeichert. Es wurde kein Budget belastet.",
        "download_form_btn": "Anmeldebogen (PDF) erneut herunterladen",
        "pdf_error": "Die PDF konnte nicht erzeugt werden: {error}",
        "next_request_btn": "Nächster Antrag",
        "close_btn": "Schließen",
        "remaining_in_queue": "{count} Antrag/Anträge verbleiben in der Warteschlange.",
        # View 3: Add Procurement Request
        "add_desc": "Reichen Sie ein Angebots-PDF ein oder erfassen Sie den Antrag manuell. Der Agent prüft ihn und stellt ihn in die Prüfwarteschlange.",
        "pdf_label": "Angebot hochladen (PDF)",
        "pdf_help": "Der extrahierte Text wird in das Antragsfeld unten übernommen und kann vor dem Einreichen geprüft werden.",
        "pdf_extracted": "{count} Zeichen aus der PDF extrahiert.",
        "pdf_extract_warning": "In der PDF wurde kein extrahierbarer Text gefunden.",
        "pdf_extract_error": "Die PDF konnte nicht gelesen werden: {error}",
        "or_divider": "oder Antrag manuell erfassen",
        "textarea_label": "Details der Beschaffungsanfrage",
        "textarea_placeholder": "Beschaffungsanfrage mit Lieferant, Betrag und Haushaltsposition eingeben.",
        "sample_header": "Beispielanträge",
        "sample_valid": "Gültige IT-Anfrage (Dell)",
        "sample_unapproved": "Gesperrter Lieferant (TechCorp)",
        "sample_review": "Grenzwertiges Budget (Stadtwerke)",
        "submit_btn": "Zur Prüfung einreichen",
        "no_input_warning": "Bitte geben Sie eine Beschaffungsanfrage ein oder laden Sie ein Dokument hoch.",
        "spinner_eval": "Anfrage wird gegen Haushaltsdaten und Lieferantenregister geprüft...",
        "eval_error": "Die Anfrage konnte nicht geprüft werden und wurde nicht in die Warteschlange aufgenommen: {error}",
        "submitted_success": "Antrag {ref} wurde geprüft und in die Prüfwarteschlange aufgenommen ({count} offen).",
        "go_verify_btn": "Prüfwarteschlange öffnen",
        "source_manual": "Manuelle Erfassung",
        "source_pdf": "PDF: {name}",
        "source_sample": "Beispielantrag",
        # View 2: Bid Evaluation
        "bids_desc": "Laden Sie die Angebote hoch, prüfen Sie die ausgelesenen Angebotsdaten und die vom Agenten vorgeschlagenen Punkte, bestätigen Sie sie als Kommission und starten Sie die gewichtete Wertung. Danach werden Zuschlags- und Absageschreiben (§ 46 UVgO) für alle Bieter vorbereitet.",
        "criteria_header": "Wertungskriterien und Gewichtung",
        "preset_label": "Kriterienset",
        "preset_sheet": "Offizielle Auswertung (Preis, Referenzen/Service, Konzept/Qualität)",
        "preset_goods": "Warenbeschaffung (Preis, Lieferzeit, Garantie)",
        "preset_sheet_note": "Auswertung_Hackathon.XLSX gewichtet Preis, Referenzen/Service und Konzept/Qualität mit den Faktoren 30/30/20 (max. 800 Punkte, kein viertes Kriterium). Auf 100 % normiert ergibt das 37,5/37,5/25 bei gleicher Rangfolge. Verwenden Sie die in den Vergabeunterlagen veröffentlichte Gewichtung.",
        "preset_goods_note": "Empfohlen für Standardwaren wie Laptops: Alle Kriterien sind objektive Werte aus den Angeboten. Beispielgewichtung; verwenden Sie die in den Vergabeunterlagen veröffentlichte Gewichtung.",
        "crit_price": "Preis",
        "crit_delivery": "Lieferzeit",
        "crit_warranty": "Garantie",
        "crit_references": "Referenzen / Service",
        "crit_concept": "Konzept / Qualität",
        "weights_ok": "Summe der Gewichte: {total:g} %.",
        "weights_error": "Die Gewichte müssen zusammen 100 % ergeben (derzeit {total:g} %).",
        "bids_pdfs_label": "Angebote hochladen (PDF, mehrere Dateien)",
        "bids_pdfs_help": "Bieter, Preis, Artikel, Menge, Lieferzeit, Garantie, Referenzen, Serviceleistungen und Bindefrist werden aus jeder PDF ausgelesen.",
        "bid_extract_error": "{file} konnte nicht gelesen werden: {error}",
        "bidder_from_filename": "{file}: In der PDF wurde kein Anbietername gefunden. Der Bietername '{bidder}' wurde aus dem Dateinamen übernommen; bitte prüfen.",
        "bids_upload_hint": "Laden Sie die Angebote der Bieter (PDF) hoch, um die Angebotsdaten auszulesen.",
        "bids_table_header": "Angebotsdaten",
        "bids_table_caption": "Preis und Punkte werden aus den PDFs ausgelesen und können vor der Wertung korrigiert werden. Referenzen / Service und Konzept / Qualität schlägt der Agent nach demselben Raster für alle Bieter vor; Begründung und Fundstellen in den PDFs stehen unter der Tabelle.",
        "help_references": "Kann man sich auf diesen Lieferanten bei Lieferung und Betreuung verlassen? Zusammenarbeit mit der Stadt, im Angebot genannte Referenzen für vergleichbare Lieferungen, Garantie und Service nach dem Kauf.",
        "help_concept": "Wie gut passt das Angebot zur Anfrage? Art und Menge des Gegenstands (markenneutral), Lieferzeit und Vollständigkeit des Angebots (Preisbasis, Spezifikation, Bindefrist).",
        "tag_agent": "KI",
        "missing_score": "{bidder}: {criterion} – {reason}",
        "committee_confirm": "Die Wertungskommission hat die Punkte geprüft und bestätigt",
        "committee_confirm_help": "Vor der Wertung erforderlich. Die Kommission bleibt für jede Bewertung verantwortlich, auch für die vom Agenten vorgeschlagenen.",
        "breakdown_header": "Punktevorschlag des Agenten (gleiches Raster für alle Bieter)",
        "breakdown_required": "erforderlich: {reason}",
        "breakdown_committee": "Wert der Kommission: {score}",
        "col_bidder": "Bieter",
        "col_price": "Preis (EUR)",
        "col_delivery_days": "Lieferzeit (Tage)",
        "col_warranty_months": "Garantie (Monate)",
        "col_references": "Referenzen / Service (0-10)",
        "col_concept": "Konzept / Qualität (0-10)",
        "col_score": "{criterion} (0-10)",
        "col_points": "{criterion}-Pkt.",
        "col_total_pts": "Gesamt-Pkt.",
        "basis_gross": "brutto",
        "basis_net": "netto (zzgl. MwSt.)",
        "basis_total": "Gesamt (MwSt. nicht angegeben)",
        "cell_missing": "erforderlich",
        "blocked_header": "Wertung gesperrt. Fehlende Angaben je Bieter (Bewertungen ohne jede Grundlage oder im Angebot nicht angegebene Werte):",
        "missing_bidder": "Zeile {row}: Bietername erforderlich",
        "eval_bids_btn": "Wertung starten",
        "invalid_price_error": "Jeder Angebotspreis muss größer als 0 EUR sein. Bitte korrigieren: {bidders}",
        "spinner_bids": "Gewichtete Wertung wird berechnet...",
        "winner_label": "Empfohlener Bieter",
        "winner_points": "Gesamtpunkte (von 100)",
        "winner_price": "Angebotspreis",
        "winner_lead": "Vorsprung auf Platz 2",
        "matrix_header": "Wertungsmatrix",
    },
}

SAMPLE_REQUESTS = {
    "EN": {
        "valid": "Procurement of 15 Dell laptops for the digital administration team amounting to EUR 14,500 under the IT-Ausstattung budget.",
        "unapproved": "Server infrastructure setup provided by TechCorp amounting to EUR 38,000 under the IT-Ausstattung budget.",
        "review": "Procurement of a service vehicle for the municipal works department from Stadtwerke Hildesheim amounting to EUR 76,000 under the Fahrzeuge budget.",
    },
    "DE": {
        "valid": "Beschaffung von 15 Dell Laptops für das digitale Verwaltungsteam im Wert von 14.500 Euro für den Bereich IT-Ausstattung.",
        "unapproved": "Einrichtung einer Serverinfrastruktur durch die Firma TechCorp im Wert von 38.000 Euro für den Bereich IT-Ausstattung.",
        "review": "Beschaffung eines Dienstleistungsfahrzeugs für den Bauhof bei den Stadtwerken Hildesheim im Wert von 76.000 Euro für den Bereich Fahrzeuge.",
    },
}

VIEWS = ["verify", "bids", "add", "insights"]
# Decorative button icons for the sample requests (Material Symbols)
SAMPLE_ICONS = {"valid": ":material/computer:", "unapproved": ":material/block:", "review": ":material/local_shipping:"}

# ==============================================================================
# DATABASE ADAPTER FUNCTIONS
# ==============================================================================


def get_budgets_df() -> pd.DataFrame:
    """Reads the municipal budget positions from data/mock_data.db."""
    if not Path(get_db_path()).exists():
        try:
            init_db()
        except Exception:
            pass
    try:
        with closing(sqlite3.connect(get_db_path())) as conn:
            df = pd.read_sql_query(
                "SELECT Category, Konto, Total_Budget, Remaining_Budget FROM Budgets ORDER BY Category",
                conn,
            )
            if not df.empty:
                return df
    except Exception:
        pass
    return pd.DataFrame(
        [
            {"Category": "IT-Ausstattung", "Konto": "542900", "Total_Budget": 150000.0, "Remaining_Budget": 124300.0},
            {"Category": "Büromaterial", "Konto": "543100", "Total_Budget": 25000.0, "Remaining_Budget": 21550.0},
            {"Category": "Fahrzeuge", "Konto": "544000", "Total_Budget": 80000.0, "Remaining_Budget": 73600.0},
        ]
    )


# ==============================================================================
# STREAMLIT UI SETUP (FORMAL MUNICIPAL THEME)
# ==============================================================================

st.set_page_config(
    page_title="Stadt Hildesheim - Procurement Agent",
    layout="wide",
)

# Theme: fonts, colours, components and motion (src/ui_theme.py). Injected before the startup gate,
# so the setup screen is styled too.
st.html(ui.css(VIEWS))

# Startup gate: the agent cannot produce any decision without Gemini, so nothing
# else is rendered until an API key is configured.
if not has_api_key():
    with st.container(key="hzgate"):
        st.html(ui.illustration("key", "blue", "lg"))
        st.error(
            "**Gemini API key missing / Gemini-API-Schlüssel fehlt.**\n\n"
            "This application requires Google Gemini and has no offline mode. To set it up:\n\n"
            "1. Copy `.env.example` to `.env` in the project root.\n"
            "2. Set `GEMINI_API_KEY=<your key>` in `.env` (or export `GEMINI_API_KEY` / `GOOGLE_API_KEY`).\n"
            "3. Restart the app with `streamlit run app.py`.",
            icon=":material/key:",
        )
    st.stop()

# Initialize session state
if "lang" not in st.session_state:
    st.session_state["lang"] = "DE"
# Apply a language switch before anything renders, so the whole run uses the new language
if st.session_state.get("lang_toggle") in ("DE", "EN"):
    st.session_state["lang"] = st.session_state["lang_toggle"]
if "current_view" not in st.session_state:
    st.session_state["current_view"] = "verify"
if "request_queue" not in st.session_state:
    # Each item: ref, text, source, received, evaluation, status (PENDING / APPROVED /
    # REJECTED) and, once approved, the generated Anmeldebogen.
    st.session_state["request_queue"] = []
if "active_request" not in st.session_state:
    st.session_state["active_request"] = None
if "queue_table_nonce" not in st.session_state:
    st.session_state["queue_table_nonce"] = 0
if "form_key" not in st.session_state:
    st.session_state["form_key"] = 0
if "draft_text" not in st.session_state:
    st.session_state["draft_text"] = ""
if "last_uploaded_pdf" not in st.session_state:
    st.session_state["last_uploaded_pdf"] = None
if "bid_upload_nonce" not in st.session_state:
    st.session_state["bid_upload_nonce"] = 0

# The pending reset is applied before any widget is instantiated. This makes it
# safe to clear the text area and the file uploader after a submission.
if st.session_state.pop("_reset_form", False):
    st.session_state["draft_text"] = ""
    st.session_state["last_uploaded_pdf"] = None
    st.session_state["form_key"] += 1


def t(key: str) -> str:
    lang = st.session_state.get("lang", "DE")
    return TRANSLATIONS.get(lang, TRANSLATIONS["DE"]).get(key, key)


def fmt_eur(amount: Any, decimals: int = 2) -> str:
    """Formats an amount in the locale of the active language."""
    try:
        value = float(amount or 0.0)
    except (TypeError, ValueError):
        value = 0.0
    formatted = f"{value:,.{decimals}f}"
    if st.session_state.get("lang", "DE") == "DE":
        return formatted.replace(",", "X").replace(".", ",").replace("X", ".") + " €"
    return "€" + formatted


def normalise_decision(value: Any) -> str:
    decision = str(value or "REQUIRES_REVIEW").strip().upper()
    if decision in ["APPROVED", "APPROVE"]:
        return "APPROVED"
    if decision in ["REQUIRES_REVIEW", "REQUIRES REVIEW", "REVIEW"]:
        return "REQUIRES_REVIEW"
    return "REJECTED"


# ------------------------------------------------------------------------------
# Request queue helpers
# ------------------------------------------------------------------------------


def get_request(ref: Optional[str]) -> Optional[Dict[str, Any]]:
    return next((r for r in st.session_state["request_queue"] if r["ref"] == ref), None)


def pending_requests() -> List[Dict[str, Any]]:
    return [r for r in st.session_state["request_queue"] if r["status"] == "PENDING"]


def next_pending_ref(after_ref: Optional[str]) -> Optional[str]:
    """Next pending request after the given one in queue order, wrapping around."""
    queue = st.session_state["request_queue"]
    start = next((i for i, r in enumerate(queue) if r["ref"] == after_ref), -1) + 1
    for item in queue[start:] + queue[:start]:
        if item["status"] == "PENDING" and item["ref"] != after_ref:
            return item["ref"]
    return None


def short_description(item: Dict[str, Any]) -> str:
    evaluation = item["evaluation"]
    summary = localized(item.get("summary_i18n") or evaluation.get("summary") or item["text"]).strip()
    if len(summary) > 80:
        summary = summary[:77].rstrip() + "..."
    return f"{summary} - {fmt_eur(evaluation.get('amount'))}"


def fmt_dt(iso: Optional[str]) -> str:
    """ISO timestamp -> date and time in the format of the active language."""
    try:
        value = datetime.fromisoformat(str(iso))
    except ValueError:
        return str(iso or "")
    return value.strftime("%d.%m.%Y %H:%M" if st.session_state.get("lang", "DE") == "DE" else "%Y-%m-%d %H:%M")


def localized(value: Any) -> str:
    """Seed data stores titles per language; user data stores plain strings."""
    if isinstance(value, dict):
        return str(value.get(st.session_state.get("lang", "DE")) or next(iter(value.values()), ""))
    return str(value or "")


def all_languages(value: Any) -> str:
    """Every language version of a DE/EN text joined, for matching against bid content."""
    return " ".join(str(v) for v in value.values()) if isinstance(value, dict) else str(value)


def queue_item(ref: str, text: Any, source: str, evaluation: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "ref": ref,
        "text": text,
        "source": source,
        "received": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "evaluation": evaluation,
        "status": "PENDING",
        "pdf": None,
        "pdf_name": None,
        "pdf_error": None,
    }


def next_request_ref() -> str:
    """Next free reference, counting the queue and the saved history (survives a reload)."""
    prefix = f"VA-{datetime.now():%Y}-"
    refs = [r["ref"] for r in st.session_state["request_queue"]] + [e["ref"] for e in history()["requests"]]
    numbers = [int(r[len(prefix):]) for r in refs if r.startswith(prefix) and r[len(prefix):].isdigit()]
    return f"{prefix}{max(numbers, default=0) + 1:04d}"


def submit_request(text: str, source: str) -> Optional[str]:
    """Runs the agent on a request and appends it to the queue. Returns the new reference."""
    try:
        evaluation = evaluate_request(text)
    except Exception as e:
        # No fallback: without a Gemini extraction there is no decision.
        st.error(t("eval_error").format(error=e), icon=":material/error:")
        return None

    ref = next_request_ref()
    st.session_state["request_queue"].append(queue_item(ref, text, source, evaluation))
    return ref


# ------------------------------------------------------------------------------
# History (persisted as JSON next to the database) and demo seeding
# ------------------------------------------------------------------------------


MANUAL_FILES = {
    "DE": Path(__file__).parent / "docs" / "Benutzerhandbuch.pdf",
    "EN": Path(__file__).parent / "docs" / "User_Manual.pdf",
}
DIAGRAM_DIR = Path(__file__).parent / "docs" / "manual" / "diagrams"


@st.cache_data(show_spinner=False)
def _read_pdf(path: str, modified: float) -> bytes:
    return Path(path).read_bytes()


def manual_pdf(lang: str) -> Optional[bytes]:
    """The user manual for the UI language, or None if it is missing or not a PDF."""
    path = MANUAL_FILES.get(lang)
    try:
        data = _read_pdf(str(path), path.stat().st_mtime)
    except (OSError, AttributeError):
        return None
    return data if data.startswith(b"%PDF") else None


def history_path() -> Path:
    return Path(get_db_path()).resolve().parent / "history.json"


def history() -> Dict[str, Any]:
    return st.session_state["history"]


def build_tender_entry(
    ref: str,
    title: Any,
    evaluated_at: str,
    result: Dict[str, Any],
    agent_scores: Dict[str, Dict[str, Optional[float]]],
    agent_reasons: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """One bid evaluation run: every bidder with the agent's proposal and the final (committee)
    score per criterion, plus the agent's reasons where it proposed a committee criterion.
    Item, quantity and email feed the letters, which build_letters() adds once per bidder."""
    weights = result["weights"]
    bidders = []
    for rank, bid in enumerate(result["ranked_bids"], start=1):
        bidders.append(
            {
                "bidder": bid["bidder"],
                "price": bid["price"],
                "rank": rank,
                "total_points": bid["total_points"],
                "item": bid.get("item"),
                "quantity": bid.get("quantity"),
                "email": bid.get("email"),
                "scores": {
                    key: {
                        "agent": agent_scores.get(bid["bidder"], {}).get(key),
                        "committee": bid[f"{key}_score"],
                        **({"reason": (agent_reasons or {})[bid["bidder"]][key]}
                           if key in (agent_reasons or {}).get(bid["bidder"], {}) else {}),
                    }
                    for key in weights
                },
            }
        )
    return {
        "id": uuid4().hex, "ref": ref, "title": title, "evaluated_at": evaluated_at, "weights": weights,
        "bidders": bidders, "award_approved": False, "approved_at": None,
    }


def seed_tender_entry() -> Dict[str, Any]:
    bids = [dict(b) for b in SEED_TENDER["bids"]]
    result = score_bids(bids, CRITERIA_PRESETS["sheet"])
    # Only the price is derived from the bids; references and concept are committee scores
    agent_price = score_criterion("price", [b["price"] for b in bids], [b["bidder"] for b in bids])
    agent_scores = {b["bidder"]: {"price": round(score, 2)} for b, score in zip(bids, agent_price)}
    entry = build_tender_entry(SEED_TENDER["ref"], SEED_TENDER["title"], SEED_TENDER["evaluated_at"], result, agent_scores)
    # A completed procurement: award approved, letters generated and all sent
    build_letters(entry, SEED_TENDER["evaluated_at"])
    entry["award_approved"], entry["approved_at"] = True, SEED_TENDER["approved_at"]
    for bidder in entry["bidders"]:
        bidder["letter"]["sent_at"] = (
            SEED_TENDER["award_sent_at"] if bidder["rank"] == 1 else SEED_TENDER["rejections_sent_at"]
        )
    return entry


def supplier_email(name: Optional[str]) -> Optional[str]:
    """The supplier table's address for a bidder name (PDF ligatures normalised)."""
    return check_supplier(unicodedata.normalize("NFKC", name or "")).get("email")


def complete_tender_runs(data: Dict[str, Any]) -> bool:
    """Adds stored letters to runs saved before letters were stored. The demo tender is re-seeded;
    other runs get the supplier table's addresses and their letters generated once. Returns
    True if anything changed."""
    changed = False
    for index, run in enumerate(data["tenders"]):
        if all("letter" in b for b in run["bidders"]):
            continue
        changed = True
        if run.get("ref") == SEED_TENDER["ref"]:
            data["tenders"][index] = seed_tender_entry()
            continue
        for bidder in run["bidders"]:
            bidder["email"] = bidder.get("email") or supplier_email(bidder["bidder"])
        sent = {b["rank"]: b.pop("sent_at", None) for b in run["bidders"]}
        build_letters(run, run["evaluated_at"])
        for bidder in run["bidders"]:
            bidder["letter"]["sent_at"] = sent.get(bidder["rank"])
        run.setdefault("award_approved", False)
        run.setdefault("approved_at", None)
    return changed


def historical_request_entries() -> List[Dict[str, Any]]:
    """The decided demo requests (src/demo_seed.py), dated relative to today like the audit log."""
    now = datetime.now().replace(microsecond=0)
    return [
        {
            "ref": entry["ref"],
            "text": entry["text"],
            "summary": entry["text"],
            "supplier": entry["supplier"],
            "amount": entry["amount"],
            "category": entry["category"],
            "agent_decision": entry["agent_decision"],
            "decision": entry["decision"],
            "agent_recommendation": entry["agent_decision"],
            "caseworker_decision": entry["decision"],
            "override": entry["agent_decision"] in ("APPROVED", "REJECTED") and entry["agent_decision"] != entry["decision"],
            "decided_at": (now - timedelta(days=entry["days_ago"])).isoformat(),
            "agent_reason": entry.get("agent_reason", ""),
            "note": entry.get("note"),
            "override_reason": None,
            # Completed procurements: never offered for new bids
            "archived": True,
        }
        for entry in sorted(HISTORICAL_REQUESTS, key=lambda e: -e["days_ago"])
    ]


def default_history() -> Dict[str, Any]:
    return {"requests": historical_request_entries(), "tenders": [seed_tender_entry()], "transfers": []}


def save_history() -> None:
    history_path().write_text(json.dumps(history(), ensure_ascii=False, indent=2), encoding="utf-8")


def load_history() -> Dict[str, Any]:
    """Reads the saved history; a missing or unreadable file starts from the demo default."""
    try:
        data = json.loads(history_path().read_text(encoding="utf-8"))
        if isinstance(data.get("requests"), list) and isinstance(data.get("tenders"), list):
            data.setdefault("transfers", [])
            # Histories saved before the supplier was recorded: fill it in for the demo entries
            seeded = {entry["ref"]: entry["supplier"] for entry in HISTORICAL_REQUESTS}
            for entry in data["requests"]:
                if "supplier" not in entry and entry.get("ref") in seeded:
                    entry["supplier"] = seeded[entry["ref"]]
            if complete_tender_runs(data):
                history_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return data
    except (OSError, ValueError, AttributeError):
        pass
    st.session_state["history"] = default_history()
    save_history()
    return st.session_state["history"]


def agent_reason(reasoning: str) -> str:
    """The reason given in the agent's final decision step."""
    for block in reversed(str(reasoning or "").split("\n\n")):
        clean = re.sub(r"[*`]", "", block).strip()
        if "Reason:" in clean:
            return clean.split("Reason:", 1)[1].strip()
    return ""


def record_request_decision(item: Dict[str, Any], decision: str, override: bool, note: Optional[str] = None) -> None:
    """Stores the agent's recommendation next to the caseworker's decision."""
    evaluation = item["evaluation"]
    recommendation = normalise_decision(evaluation.get("decision"))
    history()["requests"].append(
        {
            "ref": item["ref"],
            "text": item["text"],
            "summary": item.get("summary_i18n") or evaluation.get("summary", ""),
            "supplier": evaluation.get("supplier_name", ""),
            "amount": float(evaluation.get("amount") or 0.0),
            "category": evaluation.get("category", ""),
            "agent_decision": recommendation,
            "decision": decision,
            "agent_recommendation": recommendation,
            "caseworker_decision": decision,
            "override": override,
            "decided_at": datetime.now().isoformat(timespec="seconds"),
            "agent_reason": agent_reason(evaluation.get("reasoning", "")),
            "note": (note or "").strip() or None,
            "override_reason": None,
            "transfer": item.get("transfer"),
        }
    )
    save_history()


def seed_requests() -> None:
    """Adds the sample requests to the queue, skipping any already decided in the history."""
    decided = {entry["ref"] for entry in history()["requests"]}
    for ref, sample_key, fields in SEED_REQUESTS:
        if ref in decided or get_request(ref):
            continue
        # The evaluation summary is printed on the (German) Anmeldebogen
        extracted = ExtractedRequest(
            supplier_name=fields["supplier_name"],
            amount=fields["amount"],
            category=fields["category"],
            summary=fields["summary"]["DE"],
        )
        evaluation = verify_extracted_request(extracted)
        # Text and summary are kept in both languages so the queue follows the DE/EN switch
        text = {code: SAMPLE_REQUESTS[code][sample_key] for code in SAMPLE_REQUESTS}
        item = queue_item(ref, text, t("source_sample"), evaluation)
        item["summary_i18n"] = fields["summary"]
        st.session_state["request_queue"].append(item)


# ------------------------------------------------------------------------------
# Navigation and dialog callbacks
# ------------------------------------------------------------------------------


def go_to(view: str) -> None:
    st.session_state["current_view"] = view
    st.session_state.pop("history_view", None)


def open_history(view: str) -> None:
    st.session_state["history_view"] = view


def close_history() -> None:
    st.session_state.pop("history_view", None)


def close_dialog() -> None:
    st.session_state["active_request"] = None
    st.session_state["queue_table_nonce"] += 1


def clear_bid_uploads() -> None:
    """Empties the bid uploader and drops cached extractions and committee entries."""
    st.session_state.pop("bid_extractions", None)
    st.session_state.pop("bid_edits", None)
    st.session_state["bid_upload_nonce"] += 1


def reset_demo() -> None:
    """Initial budgets, empty history (plus the example tender) and the 3 seeded requests."""
    init_db()
    st.session_state["history"] = default_history()
    save_history()
    st.session_state["request_queue"] = []
    st.session_state["active_request"] = None
    st.session_state.pop("history_view", None)
    st.session_state["queue_table_nonce"] += 1
    st.session_state.pop("matrix_result", None)
    clear_bid_uploads()
    st.session_state["_reset_form"] = True
    seed_requests()


# History is loaded and the queue seeded once per session, not on every rerun
if "history" not in st.session_state:
    st.session_state["history"] = load_history()
if not st.session_state.get("requests_seeded"):
    seed_requests()
    st.session_state["requests_seeded"] = True


def render_pdf_download(item: Dict[str, Any], auto_click: bool) -> None:
    """Offers the Anmeldebogen as a base64 data-URI link and optionally clicks it.

    The <a download> link holds the whole PDF, so no server round trip is needed. A link
    rendered by st.markdown cannot click itself, so the one-time click is done by a short
    script in st.html. The visible link remains as a fallback if the browser blocks it.
    """
    b64 = base64.b64encode(item["pdf"]).decode("ascii")
    file_name = html.escape(item.get("pdf_name") or "Anmeldebogen.pdf", quote=True)
    link_id = f"pdf-download-{item['ref']}"
    st.markdown(
        f'<a id="{link_id}" class="pdf-download" href="data:application/pdf;base64,{b64}" '
        f'download="{file_name}">{html.escape(t("download_form_btn"))}</a>',
        unsafe_allow_html=True,
    )
    if auto_click:
        st.html(
            f"""
            <script>
                (function () {{
                    let tries = 0;
                    const timer = setInterval(function () {{
                        const link = document.getElementById("{link_id}");
                        if (link || ++tries > 40) {{
                            clearInterval(timer);
                            if (link) link.click();
                        }}
                    }}, 50);
                }})();
            </script>
            """,
            unsafe_allow_javascript=True,
        )


def record_transfer_proposal(ref: str, options: List[Dict[str, Any]]) -> None:
    """Logs once per request that the agent proposed a transfer (AI-oversight figures)."""
    if any(entry["ref"] == ref for entry in history()["transfers"]):
        return
    history()["transfers"].append(
        {
            "ref": ref,
            "proposed_at": datetime.now().isoformat(timespec="seconds"),
            "options": [option["category"] for option in options],
            "accepted": False,
        }
    )
    save_history()


def render_issues_and_transfer(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Shows the open issues first, then a budget transfer if the budget is the only one.

    Returns the transfer the caseworker included (booked only together with an approval).
    """
    eval_data = item["evaluation"]
    ref = item["ref"]
    category = eval_data.get("category", "")
    amount = float(eval_data.get("amount", 0.0) or 0.0)
    supplier = eval_data.get("supplier_name", "")
    supplier_check = eval_data.get("supplier_check") or {}
    live_budget = check_budget(amount, category) if category else {"error": True}

    issues = []
    if not supplier_check.get("exists"):
        issues.append(t("issue_supplier_unknown").format(supplier=supplier))
    elif not supplier_check.get("is_approved"):
        issues.append(t("issue_supplier_not_approved").format(supplier=supplier_check.get("supplier_name", supplier)))
    budget_short = not live_budget.get("error") and not live_budget.get("sufficient")
    shortfall = round(amount - float(live_budget.get("remaining_budget", 0.0)), 2) if budget_short else 0.0
    if live_budget.get("error"):
        issues.append(t("issue_budget_unknown").format(line=category))
    elif budget_short:
        issues.append(t("issue_budget_short").format(line=category, shortfall=fmt_eur(shortfall)))
    if issues:
        st.markdown(ui.label("report", t("issues_header")), unsafe_allow_html=True)
        st.markdown("\n".join(f"- {issue}" for issue in issues))
    if not budget_short:
        return None
    if len(issues) > 1:
        # A transfer cannot make the request approvable while other checks fail
        st.caption(t("transfer_not_offered"))
        return None

    options = suggest_budget_transfers(category, shortfall)
    with st.container(border=True):
        st.markdown(ui.label("swap_horiz", t("transfer_header")), unsafe_allow_html=True)
        st.caption(t("transfer_intro").format(line=category, shortfall=fmt_eur(shortfall)))
        if not options:
            st.info(t("transfer_none"), icon=":material/info:")
            return None
        record_transfer_proposal(ref, options)

        choice = st.radio(
            t("transfer_choose"),
            list(range(len(options))),
            format_func=lambda i, lang=st.session_state["lang"], opts=options: TRANSLATIONS[lang]["transfer_option"].format(
                line=opts[i]["category"],
                department=opts[i]["department"],
                type=TRANSLATIONS[lang][f"acct_{opts[i]['account_type']}"],
                free=fmt_eur(opts[i]["remaining"], 0),
                basis=opts[i]["legal_basis"],
            ),
            key=f"transfer_choice_{ref}",
        )
        donor = options[choice]
        need = next(line for line in get_budget_lines() if line["category"] == category)
        basis_text = (
            t("transfer_same_type").format(type=t(f"acct_{donor['account_type']}"), basis=donor["legal_basis"])
            if donor["same_type"]
            else t("transfer_other_type").format(
                donor_type=t(f"acct_{donor['account_type']}"),
                need_type=t(f"acct_{need['account_type']}"),
                basis=donor["legal_basis"],
            )
        )
        st.caption(basis_text + " " + t("transfer_after").format(line=donor["category"], spare=fmt_eur(donor["spare_after"])))

        # The application is German: German measure title and German justification
        measure = (item.get("summary_i18n") or {}).get("DE") or eval_data.get("summary", "")
        justification = draft_transfer_justification(need, donor, shortfall, measure, ref)
        st.download_button(
            t("transfer_pdf_btn"),
            data=generate_deckungsantrag_pdf(need, donor, shortfall, measure, ref, justification),
            file_name=f"Antrag_Mittelverschiebung_{ref}.pdf",
            mime="application/pdf",
            key=f"transfer_pdf_{ref}",
            on_click="ignore",
            width="stretch",
            icon=":material/picture_as_pdf:",
        )
        include = st.checkbox(t("transfer_include").format(donor=donor["category"]), key=f"transfer_include_{ref}")
    if not include:
        return None
    return {
        "source": donor["category"],
        "amount": shortfall,
        "reference": ref,
        "justification": justification,
        "legal_basis": donor["legal_basis"],
    }


def render_caseworker_decision(item: Dict[str, Any], transfer: Optional[Dict[str, Any]]) -> None:
    """Approve and Reject are always offered: the agent recommends, the caseworker decides.

    Deciding against the recommendation is an override and needs a note of at least 15
    characters. A transfer that covers the shortfall resolves the budget issue, so approving
    with it follows the agent's suggestion.
    """
    eval_data = item["evaluation"]
    ref = item["ref"]
    reasoning = eval_data.get("reasoning", "")
    amount = float(eval_data.get("amount", 0.0) or 0.0)
    category = eval_data.get("category", "IT-Ausstattung")
    recommendation = normalise_decision(eval_data.get("decision"))
    resolved_by_transfer = bool(transfer) and not approval_issues(
        eval_data.get("supplier_check") or {}, check_budget(amount, category), amount, transfer["amount"]
    )
    approve_follows = recommendation == "APPROVED" or resolved_by_transfer
    approve_is_override = recommendation == "REJECTED" and not resolved_by_transfer
    reject_is_override = recommendation == "APPROVED"

    st.markdown(ui.label("gavel", t("approval_header")), unsafe_allow_html=True)
    st.caption(t("approval_note"))
    note = st.text_area(t("caseworker_note_label"), key=f"caseworker_note_{ref}", help=t("caseworker_note_help"))
    note_ok = len("".join((note or "").split())) >= 15
    if approve_is_override:
        st.warning(t("override_warning").format(action=t("commit_approve_btn"), recommendation=t("rec_REJECTED")),
                   icon=":material/edit_note:")
    if reject_is_override:
        st.warning(t("override_warning").format(action=t("commit_reject_btn"), recommendation=t("rec_APPROVED")),
                   icon=":material/edit_note:")

    hc1, hc2 = st.columns(2)
    with hc1:
        approve_clicked = st.button(
            t("commit_approve_btn"),
            key="approve_btn",
            type="primary" if approve_follows else "secondary",
            width="stretch",
            disabled=approve_is_override and not note_ok,
            icon=":material/check_circle:",
        )
    with hc2:
        reject_clicked = st.button(
            t("commit_reject_btn"),
            key="reject_btn",
            type="primary" if recommendation == "REJECTED" and not resolved_by_transfer else "secondary",
            width="stretch",
            disabled=reject_is_override and not note_ok,
            icon=":material/cancel:",
        )
    note = (note or "").strip()

    if approve_clicked:
        try:
            commit_decision(
                request_text=eval_data.get("summary", ""),
                supplier=eval_data.get("supplier_name", "Unbekannt"),
                amount=amount,
                category=category,
                decision="APPROVED",
                reasoning=str(reasoning),
                override_reason=note or None,
                transfer=transfer,
            )
        except Exception as e:
            st.error(t("commit_error").format(error=e), icon=":material/error:")
            return
        item["status"] = "APPROVED"
        if transfer:
            item["transfer"] = {
                "donor": transfer["source"],
                "amount": transfer["amount"],
                "legal_basis": transfer["legal_basis"],
                "booked_at": datetime.now().isoformat(timespec="seconds"),
            }
            for entry in history()["transfers"]:
                if entry["ref"] == ref:
                    entry.update(accepted=True, **item["transfer"])
        record_request_decision(item, "APPROVED", override=approve_is_override, note=note)
        try:
            # PDF bytes are generated in the same click that commits the budget
            item["pdf"] = generate_anmeldebogen_pdf(eval_data, override_reason=note or None, transfer=transfer)
            item["pdf_name"] = f"Anmeldebogen_{eval_data.get('procurement_type', 'LuD')}_{ref}.pdf"
            item["auto_download"] = True
        except Exception as e:
            item["pdf_error"] = str(e)
        # Full rerun so the sidebar budget and the queue reflect the commit
        st.rerun()

    if reject_clicked:
        try:
            commit_decision(
                request_text=eval_data.get("summary", ""),
                supplier=eval_data.get("supplier_name", "Unbekannt"),
                amount=amount,
                category=category,
                decision="REJECTED",
                reasoning=str(reasoning) + (f"\n\nCaseworker note: {note}" if note else ""),
            )
        except Exception as e:
            st.error(t("commit_error").format(error=e), icon=":material/error:")
            return
        item["status"] = "REJECTED"
        record_request_decision(item, "REJECTED", override=reject_is_override, note=note)
        st.rerun()


BANNER_ICONS = {"APPROVED": ":material/check_circle:", "REQUIRES_REVIEW": ":material/pending:", "REJECTED": ":material/cancel:"}
# Decorative status chip above the banner (icon, tone); its text is the existing assessment label
BANNER_CHIPS = {"APPROVED": ("check_circle", "green"), "REQUIRES_REVIEW": ("pending", "orange"), "REJECTED": ("cancel", "red")}
CHECK_COLOURS = {"pass": "green", "warn": "orange", "fail": "red", "info": "blue"}


def fmt_day(value: Any) -> str:
    """A date (or ISO timestamp) as 14.06.2026 (DE) or 2026-06-14 (EN)."""
    try:
        day = datetime.fromisoformat(str(value)).date() if not isinstance(value, date) else value
    except ValueError:
        return str(value or "-")
    return day.strftime("%d.%m.%Y" if st.session_state.get("lang", "DE") == "DE" else "%Y-%m-%d")


def verification_text(code: str, params: Dict[str, Any]) -> str:
    """DE/EN text for a checklist/detail code; money and dates in the UI language's format."""
    values = dict(params)
    for key in ("amount", "left", "after", "short"):
        if key in values:
            values[key] = fmt_eur(values[key], 0)
    if "date" in values:
        values["date"] = fmt_day(values["date"])
    if "hint" in values:
        values["hint"] = t(f"hint_{values['hint']}")
    return t(code).format(**values)


def render_verification(item: Dict[str, Any], eval_data: Dict[str, Any], decision: str,
                        live_budget: Dict[str, Any], is_extension: bool) -> None:
    """The agent's verification: the recommendation first, one line per check, then the
    extracted data and the full reasoning in an expander. Falls back to the stored reasoning
    text if the evaluation has no structured check results."""
    try:
        view = verification_view(eval_data, live_budget)
    except (KeyError, TypeError, ValueError):
        view = None

    reason = verification_text(f"reason_{view['reason']['code']}", view["reason"]["params"]) if view else ""
    banner = t(f"banner_{decision}").format(reason=reason)
    if not reason:
        banner = banner.replace(" –  ", ". ")
    show = {"APPROVED": st.success, "REQUIRES_REVIEW": st.warning}.get(decision, st.error)
    chip_icon, chip_tone = BANNER_CHIPS.get(decision, BANNER_CHIPS["REJECTED"])
    st.html(ui.status_chip(chip_icon, t(f"assessment_{decision}"), chip_tone))
    show(banner, icon=BANNER_ICONS.get(decision, ":material/cancel:"))

    if view is None:
        st.markdown(ui.label("checklist", t("reasoning_header")), unsafe_allow_html=True)
        with st.container(border=True):
            st.markdown(eval_data.get("reasoning") or t("no_reasoning"))
    else:
        with st.container(border=True):
            st.markdown("  \n".join(
                f":{CHECK_COLOURS[c['status']]}[**{STATUS_ICONS[c['status']]}**] **{t('check_' + c['key'])}** – "
                f"{verification_text('chk_' + c['code'], c['params'])}"
                for c in view["checks"]
            ))

    st.markdown(ui.label("description", t("request_text_header")), unsafe_allow_html=True)
    with st.container(border=True):
        st.text(localized(item["text"]))

    if view is not None:
        accessibility = eval_data.get("accessibility_check") or {}
        category = eval_data.get("category", "")
        konto = eval_data.get("konto") or live_budget.get("konto") or "-"
        facts = [
            (t("fact_supplier"), eval_data.get("supplier_name", "-")),
            (t("fact_amount"), fmt_eur(float(eval_data.get("amount") or 0.0))),
            (t("fact_position"), f"{category} · Konto {konto}"),
            (t("fact_available"), fmt_eur(live_budget.get("remaining_budget")) if not live_budget.get("error") else "-"),
            (t("fact_form"), t("form_extension") if is_extension else t("form_lud")),
            (t("fact_staff"), t("staff_value").format(total=accessibility.get("total_employees", 0),
                                                      special=accessibility.get("employees_with_special_needs", 0))
             if accessibility.get("found") else "-"),
        ]
        with st.expander(t("details_header"), icon=":material/manage_search:"):
            st.markdown(f"**{t('details_extracted')}**")
            st.markdown("\n".join(f"- {label}: **{value}**" for label, value in facts))
            st.markdown(f"**{t('details_steps')}**")
            st.markdown("\n".join(
                f"{number}. {verification_text(step['code'], step['params'])}"
                for number, step in enumerate(view["details"], start=1)
            ))


def render_request_dialog(ref: str) -> None:
    """Body of the review popup for a single queued request."""
    item = get_request(ref)
    if item is None:
        return

    eval_data = item["evaluation"]
    decision = normalise_decision(eval_data.get("decision"))
    amount = float(eval_data.get("amount", 0.0) or 0.0)
    category = eval_data.get("category", "")
    is_extension = eval_data.get("procurement_type") == "Auftragserweiterung"

    st.caption(t("dialog_received").format(received=item["received"], source=item["source"]))

    # Budget figures are re-read live, since they may have changed after queueing
    live_budget = check_budget(amount, category) if category else {"error": "no category"}
    st.html(ui.step(1, "blue"))
    render_verification(item, eval_data, decision, live_budget, is_extension)

    if item["status"] == "PENDING":
        transfer = render_issues_and_transfer(item)
        st.html(ui.step(2, "orange"))  # in place of the divider: decoration only
        render_caseworker_decision(item, transfer)
        return

    st.html(ui.step(2, "orange"))  # in place of the divider: decoration only

    # Decision recorded: offer the form and move on to the next request
    if item["status"] == "APPROVED":
        st.html(ui.illustration("task_alt", "green", "sm", paper=False))
        st.success(t("committed_success"), icon=":material/check_circle:")
        if item.get("transfer"):
            transfer = item["transfer"]
            st.success(
                t("transfer_done").format(
                    amount=fmt_eur(transfer["amount"]),
                    donor=transfer["donor"],
                    line=eval_data.get("category", ""),
                    basis=transfer["legal_basis"],
                ),
                icon=":material/swap_horiz:",
            )
        if item.get("pdf_error"):
            st.error(t("pdf_error").format(error=item["pdf_error"]), icon=":material/error:")
        if item.get("pdf"):
            # Consumed here, so the automatic download fires exactly once per approval
            render_pdf_download(item, auto_click=item.pop("auto_download", False))
    else:
        st.warning(t("committed_reject"), icon=":material/cancel:")

    next_ref = next_pending_ref(ref)
    remaining = len(pending_requests())
    if next_ref:
        st.caption(t("remaining_in_queue").format(count=remaining))
        if st.button(t("next_request_btn"), key="next_request_btn", type="primary", width="stretch",
                     icon=":material/skip_next:"):
            st.session_state["active_request"] = next_ref
            st.rerun()
    else:
        st.caption(t("queue_complete"))
        if st.button(t("close_btn"), key="close_dialog_btn", width="stretch", icon=":material/close:"):
            close_dialog()
            st.rerun()


def open_request_dialog(ref: str) -> None:
    item = get_request(ref)
    if item is None:
        st.session_state["active_request"] = None
        return
    dialog = st.dialog(
        t("dialog_title").format(ref=ref),
        width="large",
        on_dismiss=close_dialog,
    )(render_request_dialog)
    dialog(ref)


# ------------------------------------------------------------------------------
# Budget chart and history dialogs
# ------------------------------------------------------------------------------

# Meter colours (src/ui_theme.py): green below 80 % used, orange from 80 %, red when over budget
METER_OK = ui.METER["ok"]
METER_WARN = ui.METER["warn"]
METER_OVER = ui.METER["over"]


def budget_meters_html(budgets_df: pd.DataFrame) -> str:
    """One meter per budget position (name, remaining, committed share), plus a total line.

    Built as flat HTML without leading indentation, which markdown would read as code.
    """
    total_all = float(budgets_df["Total_Budget"].sum())
    remaining_all = float(budgets_df["Remaining_Budget"].sum())
    parts = [
        '<div class="budget-total">'
        + html.escape(t("meter_total").format(available=fmt_eur(remaining_all, 0), total=fmt_eur(total_all, 0)))
        + "</div>"
    ]
    for _, budget in budgets_df.iterrows():
        name = str(budget["Category"])
        total = float(budget["Total_Budget"])
        remaining = float(budget["Remaining_Budget"])
        committed = total - remaining
        share = committed / total * 100 if total > 0 else 0.0
        colour, state = (METER_OK, "ok") if share < 80 else ((METER_WARN, "warn") if share <= 100 else (METER_OVER, "over"))
        if remaining >= 0:
            right, right_class = t("meter_left").format(amount=fmt_eur(remaining, 0)), "budget-meter-left"
        else:
            right, right_class = t("meter_over").format(amount=fmt_eur(-remaining, 0)), "budget-meter-left over"
        caption = t("meter_committed").format(committed=fmt_eur(committed, 0), total=fmt_eur(total, 0))
        parts.append(
            '<div class="budget-meter">'
            '<div class="budget-meter-head">'
            f'<span class="budget-meter-icon" aria-hidden="true">{ui.BUDGET_ICONS.get(name, "account_balance")}</span>'
            f'<span class="budget-meter-name">{html.escape(name)}</span>'
            f'<span class="{right_class}">{html.escape(right)}</span></div>'
            f'<div class="budget-meter-track" role="progressbar" aria-label="{html.escape(name, quote=True)}" '
            f'aria-valuemin="0" aria-valuemax="100" aria-valuenow="{share:.0f}">'
            f'<div class="budget-meter-fill {state}" style="width: {min(share, 100.0):.1f}%; background-color: {colour};"></div></div>'
            f'<div class="budget-meter-caption"><span>{html.escape(caption)}</span>'
            f'<span>{html.escape(t("meter_share").format(pct=round(share)))}</span></div>'
            "</div>"
        )
    return "".join(parts)


def render_request_history() -> None:
    entries = list(reversed(history()["requests"]))
    selected = st.segmented_control(
        t("history_filter"),
        ["ALL", "APPROVED", "REJECTED"],
        format_func=lambda f, lang=st.session_state["lang"]: TRANSLATIONS[lang]["filter_ALL" if f == "ALL" else f"decision_{f}"],
        default="ALL",
        required=True,
        key="history_filter",
    ) or "ALL"
    if selected != "ALL":
        entries = [e for e in entries if e["decision"] == selected]
    if not entries:
        st.html(ui.illustration("history", "blue", "sm"))
        st.caption(t("history_empty"))
        return

    for entry in entries:
        with st.container(border=True):
            head, badge_col = st.columns([4, 1], vertical_alignment="center")
            with head:
                st.markdown(f"**{entry['ref']}** · {fmt_eur(entry['amount'])} · {entry['category']}")
            with badge_col:
                approved = entry["decision"] == "APPROVED"
                st.badge(t(f"decision_{entry['decision']}"), color="green" if approved else "red")
                if entry.get("override"):
                    st.badge(t("history_override"), color="orange")
                if entry.get("archived"):
                    st.badge(t("history_demo"), color="gray")
            st.caption(
                t("history_decided").format(when=fmt_dt(entry["decided_at"]))
                + " · "
                + t("history_agent_vs_human").format(
                    agent=t(f"assessment_{entry['agent_decision']}"),
                    human=t(f"decision_{entry['decision']}"),
                )
            )
            text = localized(entry.get("text", ""))
            if len(text) > 160:
                st.text(text[:157].rstrip() + "...")
                with st.expander(t("request_text_header"), icon=":material/description:"):
                    st.text(text)
            else:
                st.text(text)
            if entry["decision"] == "REJECTED" and entry.get("agent_reason"):
                st.markdown(f"**{t('history_agent_reason')}:** {entry['agent_reason']}")
            if entry.get("note"):
                st.markdown(f"**{t('history_note')}:** {localized(entry['note'])}")
            if entry.get("transfer"):
                transfer = entry["transfer"]
                st.markdown(
                    t("history_transfer").format(
                        amount=fmt_eur(transfer["amount"]), donor=transfer["donor"], basis=transfer["legal_basis"]
                    )
                )
            if entry.get("override_reason"):
                st.markdown(f"**{t('history_justification')}:** {entry['override_reason']}")


def letter_sent_at(bidder: Dict[str, Any]) -> Optional[str]:
    return (bidder.get("letter") or {}).get("sent_at")


def bidder_status(bidder: Dict[str, Any]) -> str:
    sent = letter_sent_at(bidder)
    if bidder["rank"] == 1:
        return t("status_award_sent").format(when=fmt_dt(sent)) if sent else t("status_recommended")
    return t("status_rejection_sent").format(when=fmt_dt(sent)) if sent else t("status_not_selected")


def find_run(run_id: Optional[str]) -> Optional[Dict[str, Any]]:
    return next((r for r in history()["tenders"] if r["id"] == run_id), None)


def find_bidder(run_id: str, rank: int) -> Optional[Dict[str, Any]]:
    run = find_run(run_id)
    return next((b for b in run["bidders"] if b["rank"] == rank), None) if run else None


def set_award_approved(run_id: str, key: str) -> None:
    run = find_run(run_id)
    if run is not None:
        run["award_approved"] = bool(st.session_state[key])
        run["approved_at"] = datetime.now().isoformat(timespec="seconds") if run["award_approved"] else None
        save_history()


def set_sent(run_id: str, rank: int, key: str) -> None:
    bidder = find_bidder(run_id, rank)
    if bidder is not None:
        bidder["letter"]["sent_at"] = datetime.now().isoformat(timespec="seconds") if st.session_state[key] else None
        save_history()


def set_email(run_id: str, rank: int, key: str) -> None:
    bidder = find_bidder(run_id, rank)
    if bidder is not None:
        address = (st.session_state[key] or "").strip() or None
        bidder["email"] = bidder["letter"]["to"] = address
        save_history()


def render_approval(run: Dict[str, Any], place: str) -> None:
    """The award approval checkbox. Its state always mirrors the stored run, so approving on the
    Bid Evaluation page and in the history stays in sync. The approval unlocks all emails; until
    then one caption under the checkbox says so (not one per row)."""
    key = f"{place}_approved_{run['id']}"
    st.session_state[key] = bool(run.get("award_approved"))
    st.checkbox(
        t("award_approval"),
        key=key,
        help=t("award_approval_help"),
        on_change=set_award_approved,
        args=(run["id"], key),
    )
    if not run.get("award_approved"):
        st.caption(t("lock_approval"))


def render_email_actions(run: Dict[str, Any], bidder: Dict[str, Any], place: str, compact: bool = False) -> None:
    """Email button for the stored letter, an address input if it is missing, and "Mark as sent"
    (status only: it never locks or unlocks a button).

    compact (history): "Send" for an unsent letter, the sent date and "Open again" for a sent one.
    """
    lang = st.session_state["lang"]
    letter = stored_letter(bidder, lang)
    mail = email_body(letter, lang)
    to = bidder["letter"].get("to")
    reasons = email_lock_reasons(run, bidder)
    sent = bidder["letter"].get("sent_at")
    widget = f"{place}_{run['id']}_{bidder['rank']}"
    is_award = bidder["rank"] == 1

    if compact and sent:
        st.caption(t("sent_on").format(when=fmt_dt(sent)))
    label = t("email_btn") if not compact else (t("email_reopen") if sent else t("email_send"))
    st.link_button(
        label,
        mailto_url(to, letter["subject"], mail["body"]) if not reasons else "mailto:",
        type="primary" if is_award and not sent else "secondary",
        disabled=bool(reasons),
        help=t("award_approval_help") if is_award else t("rejection_email_help"),
        width="stretch",
    )
    # Missing approval is explained once under the approval checkbox; a missing address per row
    if "email_missing" in reasons:
        st.caption(t("lock_email_missing"))
        email_key = f"email_{widget}"
        st.text_input(
            t("email_input"), key=email_key, placeholder="name@firma.example", label_visibility="collapsed",
            on_change=set_email, args=(run["id"], bidder["rank"], email_key),
        )
    if reasons:
        return
    if not compact:
        st.markdown(f"[{t('gmail_link')}]({gmail_url(to, letter['subject'], mail['body'])})")
        if mail["shortened"]:
            st.caption(t("letter_shortened"))
            st.download_button(
                t("letter_pdf"),
                letter_pdf(letter),
                file_name=f"{'Zuschlag' if is_award else 'Absage'}_{bidder['bidder']}.pdf".replace(" ", "_"),
                mime="application/pdf",
                key=f"pdf_{widget}",
                icon=":material/picture_as_pdf:",
            )
    sent_key = f"sent_{widget}"
    st.session_state[sent_key] = bool(sent)
    st.checkbox(t("mark_sent"), key=sent_key, on_change=set_sent, args=(run["id"], bidder["rank"], sent_key))


def render_letters(run: Dict[str, Any]) -> None:
    """One row per bidder: the stored letter (expander) and the email actions on the right.
    The approval checkbox sits directly above the award row."""
    lang = st.session_state["lang"]
    for bidder in sorted(run["bidders"], key=lambda b: b["rank"]):
        is_award = bidder["rank"] == 1
        if is_award:
            render_approval(run, "bids")
        letter = stored_letter(bidder, lang)
        title = t("letter_title").format(
            bidder=bidder["bidder"],
            kind=t("letter_award" if is_award else "letter_rejection"),
            status=bidder_status(bidder),
        )
        letter_col, action_col = st.columns([5, 1.5])
        with letter_col:
            with st.expander(title, icon=":material/mail:"):
                to = bidder["letter"].get("to")
                st.caption(f"{t('letter_to')}: {to or t('no_email')} · {t('letter_subject')}: {letter['subject']}")
                st.markdown(html.escape(letter["body"]).replace("\n", "  \n"))
        with action_col:
            render_email_actions(run, bidder, "bids")


HISTORY_WIDTHS = {"rank": 0.45, "bidder": 1.9, "price": 1.15, "score": 0.95, "total": 0.8, "status": 1.5, "email": 1.6}


def render_history_rows(run: Dict[str, Any]) -> None:
    """The run as rows of columns (fits the dialog): one final value per criterion, the status
    and per row the email action for the stored letter."""
    keys = list(run["weights"])
    widths = [HISTORY_WIDTHS[c] for c in ("rank", "bidder", "price")] + [HISTORY_WIDTHS["score"]] * len(keys) + [
        HISTORY_WIDTHS[c] for c in ("total", "status", "email")
    ]
    headers = [t("col_rank"), t("col_bidder"), t("col_price"), *(t(f"short_{k}") for k in keys),
               t("col_total_pts"), t("col_status"), t("col_email")]
    for column, header in zip(st.columns(widths, vertical_alignment="bottom"), headers):
        # Allow a line break after "/" ("Concept/Quality") instead of inside a word
        column.caption(f"**{header.replace('/', '/' + chr(0x200B))}**")
    for bidder in sorted(run["bidders"], key=lambda b: b["rank"]):
        with st.container(border=True):
            cells = st.columns(widths, vertical_alignment="center")
            strong = "**" if bidder["rank"] == 1 else ""
            values = [str(bidder["rank"]), f"{strong}{bidder['bidder']}{strong}", fmt_eur(bidder["price"]),
                      *(f"{bidder['scores'].get(k, {}).get('committee', 0):.2f}" for k in keys),
                      f"{strong}{bidder['total_points']:.2f}{strong}", bidder_status(bidder)]
            for cell, value in zip(cells, values):
                cell.markdown(value)
            with cells[-1]:
                render_email_actions(run, bidder, "hist", compact=True)


def render_bid_history() -> None:
    runs = sorted(history()["tenders"], key=lambda r: r["evaluated_at"], reverse=True)
    if not runs:
        st.html(ui.illustration("receipt_long", "orange", "sm"))
        st.caption(t("history_tenders_empty"))
        return

    # Group the runs by tender (request reference), newest tender first
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for run in runs:
        groups.setdefault(run["ref"], []).append(run)
    for index, (ref, tender_runs) in enumerate(groups.items()):
        latest = tender_runs[0]
        title = f"{ref} · {localized(latest['title'])} · {fmt_dt(latest['evaluated_at'])}"
        with st.expander(title, expanded=index == 0, icon=":material/receipt_long:"):
            for run in tender_runs:
                criteria = " · ".join(f"{t(f'crit_{k}')} {w:g} %" for k, w in run["weights"].items())
                st.caption(t("tender_run").format(when=fmt_dt(run["evaluated_at"]), criteria=criteria))
                winner = next(b for b in run["bidders"] if b["rank"] == 1)
                st.markdown(f"{t('winner_label')}: **{winner['bidder']}** ({winner['total_points']:.2f} / 100)")
                # Not approved yet: the award can be approved later from here
                if not run.get("award_approved"):
                    render_approval(run, "hist")
                render_history_rows(run)


# Chart colours (src/ui_theme.py): brand blue for series, orange for flags, ink for text
CHART_BLUE = ui.CHART["blue"]
CHART_ORANGE = ui.CHART["orange"]
CHART_ORANGE_INK = ui.CHART["orange_ink"]
CHART_INK = ui.CHART["ink"]
CHART_MUTED = ui.CHART["muted"]
CHART_GRID = ui.CHART["grid"]
MONTHS_DE = "['Jan','Feb','Mär','Apr','Mai','Jun','Jul','Aug','Sep','Okt','Nov','Dez']"


def chart_eur_axis() -> alt.Axis:
    """EUR axis labels in the UI language (12.000 € / €12,000)."""
    expr = ("replace(format(datum.value, ',.0f'), /,/g, '.') + ' €'" if st.session_state["lang"] == "DE"
            else "'€' + format(datum.value, ',.0f')")
    return alt.Axis(labelExpr=expr, labelColor=CHART_MUTED, gridColor=CHART_GRID, gridDash=[2, 4], domain=False, ticks=False, tickCount=5,
                    title=None)


def burnup_chart(data: Dict[str, Any], fmt_date, fmt_share) -> alt.LayerChart:
    """Cumulative committed spend of one budget line in the current budget year: actual (solid),
    projection to 31 Dec (dashed) and the line's budget total (dotted rule with a label)."""
    total = data["total"]
    rows = []
    for kind, points in (("actual", data["actual"]), ("projection", data["projection"])):
        for point in points:
            rows.append({
                "date": pd.Timestamp(point["date"]), "cumulative": point["cumulative"], "kind": t(f"chart_{kind}"),
                "line": data["category"], "date_label": fmt_date(point["date"]),
                "amount_label": fmt_eur(point["cumulative"], 0),
                "share_label": fmt_share(point["cumulative"] / total) if total > 0 else "–",
            })
    frame = pd.DataFrame(rows)
    year = date.today().year
    month_axis = (alt.Axis(labelExpr=f"{MONTHS_DE}[month(datum.value)]", tickCount="month") if st.session_state["lang"] == "DE"
                  else alt.Axis(format="%b", tickCount="month"))
    month_axis.labelColor, month_axis.grid, month_axis.title, month_axis.domainColor = CHART_MUTED, False, None, CHART_GRID
    x = alt.X("date:T", scale=alt.Scale(domain=[f"{year}-01-01T00:00:00", f"{year}-12-31T23:59:59"]), axis=month_axis)
    top = max([total] + [r["cumulative"] for r in rows]) * 1.12
    y = alt.Y("cumulative:Q", scale=alt.Scale(domain=[0, top]), axis=chart_eur_axis())
    tooltip = [
        alt.Tooltip("date_label:N", title=t("chart_date")),
        alt.Tooltip("line:N", title=t("ins_col_line")),
        alt.Tooltip("kind:N", title=t("chart_series")),
        alt.Tooltip("amount_label:N", title=t("chart_cumulative")),
        alt.Tooltip("share_label:N", title=t("chart_share_total")),
    ]
    actual = frame[frame["kind"] == t("chart_actual")]
    projection = frame[frame["kind"] == t("chart_projection")]
    layers = [
        alt.Chart(actual).mark_line(interpolate="step-after", color=CHART_BLUE, strokeWidth=2.5, tooltip=False).encode(x=x, y=y),
        alt.Chart(actual).mark_circle(size=64, color=CHART_BLUE, opacity=1).encode(x=x, y=y, tooltip=tooltip),
    ]
    if not projection.empty:
        layers += [
            alt.Chart(projection).mark_line(color=CHART_BLUE, strokeWidth=2.5, strokeDash=[6, 4], tooltip=False).encode(x=x, y=y),
            alt.Chart(projection.tail(1)).mark_circle(size=64, color="#FFFFFF", stroke=CHART_BLUE, strokeWidth=2, opacity=1)
            .encode(x=x, y=y, tooltip=tooltip),
        ]
    budget = pd.DataFrame({"total": [total], "date": [pd.Timestamp(f"{year}-01-01")],
                           "label": [t("chart_total").format(amount=fmt_eur(total, 0))]})
    layers += [
        # Only the data points carry a tooltip (Streamlit would add raw ones to every mark)
        alt.Chart(budget).mark_rule(color=CHART_MUTED, strokeWidth=1, strokeDash=[2, 3], tooltip=False).encode(y="total:Q"),
        alt.Chart(budget).mark_text(align="left", baseline="bottom", dx=4, dy=-4, color=CHART_MUTED, fontSize=12, tooltip=False)
        .encode(x="date:T", y="total:Q", text="label:N"),
    ]
    return ui.style_chart(alt.layer(*layers).properties(height=260).configure_view(strokeWidth=0))


def supplier_chart(totals: List[Dict[str, Any]]) -> alt.Chart:
    """Approved spend per supplier, largest first; flagged suppliers in orange with a text label."""
    frame = pd.DataFrame([
        {
            "supplier": row["supplier"], "spend": row["spend"], "orders": row["orders"],
            "lines": ", ".join(row["lines"]), "flagged": row["flagged"], "spend_label": fmt_eur(row["spend"], 0),
            "label": fmt_eur(row["spend"], 0) + (f" · {t('chart_flag')}" if row["flagged"] else ""),
        }
        for row in totals
    ])
    longest = max(row["spend"] for row in totals)
    base = alt.Chart(frame).encode(
        y=alt.Y("supplier:N", sort="-x", title=None,
                axis=alt.Axis(labelColor=CHART_INK, labelLimit=240, ticks=False, domain=False, labelFontSize=13)),
        x=alt.X("spend:Q", title=None, axis=None, scale=alt.Scale(domain=[0, longest * 1.45])),
        tooltip=[
            alt.Tooltip("supplier:N", title=t("chart_supplier")),
            alt.Tooltip("spend_label:N", title=t("chart_spend")),
            alt.Tooltip("orders:Q", title=t("chart_orders")),
            alt.Tooltip("lines:N", title=t("chart_lines")),
        ],
    )
    bars = base.mark_bar(cornerRadiusEnd=10, height=20).encode(
        color=alt.condition("datum.flagged", alt.value(CHART_ORANGE), alt.value(CHART_BLUE))
    )
    labels = base.mark_text(align="left", dx=6, color=CHART_INK, fontSize=12).encode(text="label:N")
    return ui.style_chart((bars + labels).properties(height=max(120, 36 * len(frame))).configure_view(strokeWidth=0))


def open_history_dialog(view: str) -> None:
    title = t("history_requests_title") if view == "verify" else t("history_bids_title")
    body = render_request_history if view == "verify" else render_bid_history
    st.dialog(title, width="large", on_dismiss=close_history)(body)()


# ==============================================================================
# SIDEBAR: LANGUAGE, NAVIGATION, LIVE ADMINISTRATION STATE
# ==============================================================================

with st.sidebar:
    # Brand block: decorative circles, agency kicker and app name (the language is already applied above)
    with st.container(key="hzbrand"):
        st.html(ui.brand_mark())
        st.markdown(f'<div class="gov-meta">{t("agency")}</div>', unsafe_allow_html=True)
        st.markdown(f"**{t('app_name')}**")

    lang_choice = st.segmented_control(
        t("lang_label"),
        ["DE", "EN"],
        default=st.session_state.get("lang", "DE"),
        required=True,
        key="lang_toggle",
        width="stretch",
    )
    st.session_state["lang"] = lang_choice or "DE"

    # The active view is rendered as a primary button; CSS turns it into the highlighted list item
    with st.container(key="sidebar_nav"):
        for view in VIEWS:
            st.button(
                t(f"nav_{view}"),
                key=f"nav_{view}",
                type="primary" if st.session_state["current_view"] == view else "secondary",
                width="stretch",
                on_click=go_to,
                args=(view,),
                icon=f":material/{ui.VIEW_ART[view]['icon']}:",
            )

    st.divider()
    st.markdown(ui.label("account_balance", t("live_state_header")), unsafe_allow_html=True)
    st.caption(t("live_state_caption"))
    budgets_df = get_budgets_df()
    if not budgets_df.empty:
        # Rebuilt from the database on every rerun, so an approval shows up immediately
        st.markdown(budget_meters_html(budgets_df), unsafe_allow_html=True)
    else:
        st.info(t("no_budget_data"), icon=":material/info:")

    if st.button(t("reset_btn"), key="reset_btn", width="stretch", icon=":material/restart_alt:"):
        try:
            reset_demo()
            st.toast(t("reset_success"), icon=":material/restart_alt:")
            st.rerun()
        except Exception as e:
            st.error(t("reset_error").format(error=e), icon=":material/error:")

    # User manual (built by scripts/build_manual.py) in the UI language; hidden if not built yet
    manual = manual_pdf(st.session_state["lang"])
    if manual is not None:
        st.download_button(
            t("manual_btn"),
            manual,
            file_name=MANUAL_FILES[st.session_state["lang"]].name,
            mime="application/pdf",
            key="manual_btn",
            width="stretch",
        )

    # Localised label for the sidebar toggle (Streamlit's own button; only aria-label/title change).
    # Placed last in the sidebar, so the empty element cannot shift any content.
    st.html(
        f"""
        <script>
            (function () {{
                window.__menuToggleLabel = {json.dumps(t("menu_toggle"))};
                const apply = function () {{
                    document.querySelectorAll(
                        '[data-testid="stSidebarCollapseButton"] button, button[data-testid="stExpandSidebarButton"]'
                    ).forEach(function (button) {{
                        if (button.getAttribute("aria-label") !== window.__menuToggleLabel) {{
                            button.setAttribute("aria-label", window.__menuToggleLabel);
                            button.setAttribute("title", window.__menuToggleLabel);
                        }}
                    }});
                }};
                apply();
                if (!window.__menuToggleObserver) {{
                    window.__menuToggleObserver = new MutationObserver(apply);
                    window.__menuToggleObserver.observe(document.body, {{childList: true, subtree: true}});
                }}
            }})();
        </script>
        """,
        unsafe_allow_javascript=True,
    )


current_view = st.session_state["current_view"]

# Main page header: History (verification and bid evaluation) above the title
if current_view in ("verify", "bids"):
    st.button(
        t("history_btn"),
        key=f"history_btn_{current_view}",
        icon=":material/history:",
        on_click=open_history,
        args=(current_view,),
    )
# View header: kicker, title and description, with decorative circles and the view's icon on the right
VIEW_DESC = {"verify": "verify_desc", "bids": "bids_desc", "add": "add_desc", "insights": "insights_desc"}
with st.container(key=f"hzhero_{current_view}"):
    st.html(ui.hero_art(current_view))
    st.markdown(f'<div class="gov-meta">{t("agency")}</div>', unsafe_allow_html=True)
    st.title(t(f"nav_{current_view}"))
    st.caption(t(VIEW_DESC[current_view]))


# ==============================================================================
# VIEW 1: REQUEST VERIFICATION
# ==============================================================================

if current_view == "verify":
    queue = st.session_state["request_queue"]
    pending = pending_requests()

    k1, k2, k3 = st.columns(3)
    with k1:
        with st.container(border=True, key="hzm_pending"):
            st.metric(t("kpi_pending"), len(pending))
    with k2:
        with st.container(border=True, key="hzm_approved"):
            st.metric(t("kpi_approved"), sum(1 for r in queue if r["status"] == "APPROVED"))
    with k3:
        with st.container(border=True, key="hzm_rejected"):
            st.metric(t("kpi_rejected"), sum(1 for r in queue if r["status"] == "REJECTED"))

    q_head, q_add = st.columns([3, 1], vertical_alignment="bottom")
    with q_head:
        with st.container(key="hzsec_queue"):
            st.subheader(t("queue_header"))
    with q_add:
        st.button(t("go_add_btn"), key="go_add_btn", width="stretch", on_click=go_to, args=("add",),
                  icon=":material/add_circle:")
    if pending:
        queue_df = pd.DataFrame(
            [
                {
                    "ref": r["ref"],
                    "request": short_description(r),
                    "assessment": t(f"assessment_{normalise_decision(r['evaluation'].get('decision'))}"),
                    "accessibility": (
                        t("accessibility_flag")
                        if (r["evaluation"].get("accessibility_check") or {}).get("warning")
                        else "-"
                    ),
                    "received": r["received"],
                }
                for r in pending
            ]
        )
        selection = st.dataframe(
            queue_df,
            hide_index=True,
            width="stretch",
            on_select="rerun",
            selection_mode="single-row",
            key=f"queue_table_{st.session_state['queue_table_nonce']}",
            column_config={
                "ref": st.column_config.TextColumn(t("col_ref"), width="small"),
                "request": st.column_config.TextColumn(t("col_request"), width="large"),
                "assessment": st.column_config.TextColumn(t("col_assessment"), width="small"),
                "accessibility": st.column_config.TextColumn(t("col_accessibility"), width="small"),
                "received": st.column_config.TextColumn(t("col_received"), width="small"),
            },
        )
        selected_rows = selection.selection.rows if selection else []
        if selected_rows:
            st.session_state["active_request"] = pending[selected_rows[0]]["ref"]
            # A fresh table key clears the row selection, so dismissing the
            # dialog does not reopen it on the next rerun.
            st.session_state["queue_table_nonce"] += 1
    else:
        with st.container(border=True, key="hzcard_empty_queue"):
            st.html(ui.illustration("inbox", "blue", "md"))
            st.caption(t("queue_empty"))

    # One dialog per run: the history takes precedence over the request popup
    if st.session_state.get("history_view") == "verify":
        open_history_dialog("verify")
    elif st.session_state.get("active_request"):
        open_request_dialog(st.session_state["active_request"])


# ==============================================================================
# VIEW 2: BID EVALUATION
# ==============================================================================

elif current_view == "bids":
    # --- Which request (tender) the bids belong to --------------------------------------
    st.html(ui.step(1, "blue"))
    # Same source of truth as the request history: approved and not yet evaluated
    open_requests = requests_awaiting_bids(history()["requests"], history()["tenders"])
    tender_ready = bool(open_requests)
    tender_ref, tender_title = None, None
    if tender_ready:
        tender_titles = {entry["ref"]: entry.get("summary") or entry.get("text", "") for entry in open_requests}
        tender_options = [entry["ref"] for entry in open_requests] + ["__other__"]
        # A request evaluated in the meantime is no longer an option; fall back to the first one
        if st.session_state.get("bid_tender_ref") not in tender_options:
            st.session_state.pop("bid_tender_ref", None)
        tender_ref = st.selectbox(
            t("tender_label"),
            tender_options,
            format_func=lambda ref, lang=st.session_state["lang"], titles=tender_titles: (
                TRANSLATIONS[lang]["tender_other"] if ref == "__other__"
                else f"{ref} · {(titles[ref].get(lang, '') if isinstance(titles[ref], dict) else titles[ref])[:70]}"
            ),
            key="bid_tender_ref",
        )
        if tender_ref == "__other__":
            tender_title = st.text_input(t("tender_title_label"), key="bid_tender_title").strip() or t("tender_title_default")
        else:
            tender_title = tender_titles[tender_ref]
    else:
        with st.container(border=True, key="hzcard_no_tender"):
            st.html(ui.illustration("fact_check", "orange", "sm"))
            st.info(t("no_tender_requests"), icon=":material/info:")
            st.button(t("go_verify_requests"), key="go_verify_from_bids", on_click=go_to, args=("verify",),
                      icon=":material/fact_check:")

    # --- Quotation upload: the bid table is derived only from the current uploads --------
    # Switching to another request starts with an empty uploader and no cached rows
    if "bid_tender_for" in st.session_state and st.session_state["bid_tender_for"] != tender_ref:
        clear_bid_uploads()
    st.session_state["bid_tender_for"] = tender_ref

    st.html(ui.step(2, "orange"))
    bid_pdfs = st.file_uploader(
        t("bids_pdfs_label"),
        type=["pdf"],
        accept_multiple_files=True,
        help=t("bids_pdfs_help"),
        key=f"bid_pdfs_{st.session_state['bid_upload_nonce']}",
        disabled=not tender_ready,
    )

    # Extraction results are cached per file content (name + size + hash) and pruned to the
    # files currently uploaded, so a removed or replaced file leaves no stale row behind.
    extractions = st.session_state.setdefault("bid_extractions", {})
    bid_edits = st.session_state.setdefault("bid_edits", {})
    upload_keys = []
    for pdf_file in bid_pdfs or []:
        data = pdf_file.getvalue()
        file_key = f"{pdf_file.name}:{len(data)}:{hashlib.sha1(data).hexdigest()[:12]}"
        if file_key in upload_keys:
            continue
        upload_keys.append(file_key)
        if file_key not in extractions:
            try:
                extractions[file_key] = {"file": pdf_file.name, "bid": parse_bid_pdf(data, pdf_file.name)}
            except BidExtractionError as e:
                extractions[file_key] = {"file": pdf_file.name, "error": str(e)}
    for stale in set(extractions) - set(upload_keys):
        extractions.pop(stale)
    for stale in set(bid_edits) - set(upload_keys):
        bid_edits.pop(stale)

    for file_key in upload_keys:
        extraction = extractions[file_key]
        if "error" in extraction:
            st.error(t("bid_extract_error").format(file=extraction["file"], error=extraction["error"]),
                     icon=":material/error:")
        elif extraction["bid"]["bidder_source"] == "filename":
            st.warning(t("bidder_from_filename").format(file=extraction["file"], bidder=extraction["bid"]["bidder"]),
                       icon=":material/badge:")
    row_keys = [k for k in upload_keys if "bid" in extractions[k]]

    if tender_ready and not bid_pdfs:
        st.html(ui.illustration("upload_file", "blue", "sm"))
        st.caption(t("bids_upload_hint"))

    if row_keys:
        # --- Criteria and weights (must total 100 %) ------------------------------------
        st.html(ui.step(3, "teal"))
        with st.container(border=True):
            st.markdown(ui.label("tune", t("criteria_header")), unsafe_allow_html=True)
            preset = st.segmented_control(
                t("preset_label"),
                list(CRITERIA_PRESETS),
                format_func=lambda p, lang=st.session_state["lang"]: TRANSLATIONS[lang][f"preset_{p}"],
                default="sheet",
                required=True,
                key="criteria_preset",
            ) or "sheet"
            st.caption(t(f"preset_{preset}_note"))
            weights = {}
            for weight_col, key in zip(st.columns(len(CRITERIA)), CRITERIA):
                with weight_col:
                    # Keyed per preset, so switching the set restores its weights
                    weights[key] = st.number_input(
                        f"{t(f'crit_{key}')} (%)",
                        min_value=0.0,
                        max_value=100.0,
                        step=5.0,
                        value=float(CRITERIA_PRESETS[preset].get(key, 0.0)),
                        key=f"weight_{preset}_{key}",
                    )
            weights_total = sum(weights.values())
            weights_ok = abs(weights_total - 100.0) <= 0.01
            if weights_ok:
                st.caption(t("weights_ok").format(total=weights_total))
            else:
                st.error(t("weights_error").format(total=weights_total), icon=":material/percent:")
        active_criteria = [key for key, weight in weights.items() if weight > 0]

        # --- Bid data: one row per uploaded PDF -------------------------------------------
        # The agent proposes References / Service and Concept / Quality from the extracted
        # facts with one fixed rubric (src/bid_scoring.py); the committee may overwrite them.
        tender_entry = next((e for e in open_requests if e["ref"] == tender_ref), None)
        score_request = {
            "ref": tender_ref,
            "category": (tender_entry or {}).get("category"),
            "text": " ".join(
                all_languages(value) for value in (
                    (tender_entry or {}).get("summary"), (tender_entry or {}).get("text"), tender_title,
                ) if value
            ),
        }
        proposals = {
            file_key: score_bid(extractions[file_key]["bid"], score_request, check_supplier, history()["requests"])
            for file_key in row_keys
        }
        lang = st.session_state["lang"]
        score_keys = [key for key in CRITERIA if CRITERIA[key]["kind"] == "committee"]

        bid_columns = ["bidder", "price", "delivery_days", "warranty_months", "references_score", "concept_score"]
        editable_columns = list(bid_columns)
        rows = []
        for file_key in row_keys:
            bid = extractions[file_key]["bid"]
            rows.append(
                {
                    "bidder": bid["bidder"],
                    "price": bid["price"],
                    "delivery_days": bid["delivery_days"],
                    "warranty_months": bid["warranty_months"],
                    "references_score": proposals[file_key]["references"]["score"],
                    "concept_score": proposals[file_key]["concept"]["score"],
                }
            )
        # Values exactly as read from the PDFs and proposed by the agent (used for the history)
        extracted_df = pd.DataFrame(rows, columns=bid_columns, index=row_keys)
        for numeric in ("price", "delivery_days", "warranty_months", "references_score", "concept_score"):
            extracted_df[numeric] = pd.to_numeric(extracted_df[numeric], errors="coerce")
        # Committee entries and corrections survive when other files are added or removed
        table_df = extracted_df.copy()
        for file_key in row_keys:
            for column, value in bid_edits.get(file_key, {}).items():
                table_df.at[file_key, column] = value

        st.html(ui.step(4, "orange"))
        st.markdown(ui.label("table_chart", t("bids_table_header")), unsafe_allow_html=True)
        st.caption(t("bids_table_caption"))
        files_hash = hashlib.sha1("|".join(row_keys).encode()).hexdigest()[:12]
        committee_confirmed = st.checkbox(
            t("committee_confirm"),
            key=f"committee_confirmed_{files_hash}",
            help=t("committee_confirm_help"),
            disabled=not tender_ready,
        )
        criteria_fields = [CRITERIA[key]["field"] for key in active_criteria if key != "price"]
        bids_df = st.data_editor(
            table_df,
            key=f"bid_editor_{st.session_state['bid_upload_nonce']}_{files_hash}",
            hide_index=True,
            width="stretch",
            placeholder=t("cell_missing"),
            disabled=not tender_ready,
            column_order=["bidder", "price", *criteria_fields],
            column_config={
                "bidder": st.column_config.TextColumn(t("col_bidder"), required=True),
                "price": st.column_config.NumberColumn(t("col_price"), min_value=0.0, format="%.2f"),
                "delivery_days": st.column_config.NumberColumn(t("col_delivery_days"), min_value=0, step=1),
                "warranty_months": st.column_config.NumberColumn(t("col_warranty_months"), min_value=0, step=1),
                "references_score": st.column_config.NumberColumn(
                    t("col_references"), min_value=0, max_value=10, step=1, help=t("help_references")
                ),
                "concept_score": st.column_config.NumberColumn(
                    t("col_concept"), min_value=0, max_value=10, step=1, help=t("help_concept")
                ),
            },
        )
        for file_key, row in bids_df.iterrows():
            bid_edits[file_key] = {c: (None if pd.isna(row[c]) else row[c]) for c in editable_columns}
        # Email per bid: from the PDF, otherwise from the supplier table. A missing address is
        # asked for in the letters section, not here.
        bid_emails = {
            file_key: extractions[file_key]["bid"].get("email")
            or supplier_email(row["bidder"] if pd.notna(row["bidder"]) else None)
            or supplier_email(extractions[file_key]["bid"]["bidder"])
            for file_key, row in bids_df.iterrows()
        }

        # Agent breakdown and the source text per bidder (details behind the table)
        active_score_keys = [key for key in score_keys if key in active_criteria]
        with st.expander(t("breakdown_header"), icon=":material/smart_toy:"):
            for file_key, row in bids_df.iterrows():
                bid = extractions[file_key]["bid"]
                st.markdown(f"**{row['bidder'] or extractions[file_key]['file']}**")
                lines = []
                for key in active_score_keys:
                    proposal = proposals[file_key][key]
                    value = row[CRITERIA[key]["field"]]
                    if proposal["score"] is None:
                        line = f"- {t(f'crit_{key}')}: {t('breakdown_required').format(reason=proposal['missing_reason'][lang])}"
                    else:
                        line = (f"- {t(f'crit_{key}')}: **{proposal['score']:g}** ({t('tag_agent')}) – "
                                f"{explain(proposal, lang)}")
                    if pd.notna(value) and (proposal["score"] is None or float(value) != float(proposal["score"])):
                        line += f" · {t('breakdown_committee').format(score=f'{float(value):g}')}"
                    lines.append(line)
                lines.append("- " + t("breakdown_offer").format(
                    item=bid["item"] or "–",
                    quantity=bid["quantity"] or "–",
                    basis=t(f"basis_{bid['price_basis']}") if bid["price_basis"] else "–",
                    email=bid_emails[file_key] or "–",
                ))
                snippets = " | ".join(dict.fromkeys(bid["sources"].values())) or "–"
                lines.append("- " + t("breakdown_sources").format(text=f"{extractions[file_key]['file']}: {snippets}"))
                st.markdown("\n".join(lines))

        # --- Validation: nothing is defaulted; missing values block the evaluation --------
        bids_input, bid_file_keys, problems, invalid_prices = [], [], [], []
        required_criteria = ["price", *(key for key in active_criteria if key != "price")]
        for row_number, (file_key, row) in enumerate(bids_df.iterrows(), start=1):
            bidder = str(row["bidder"]).strip() if pd.notna(row["bidder"]) else ""
            if not bidder:
                problems.append(t("missing_bidder").format(row=row_number))
            extracted_bid = extractions[file_key]["bid"]
            bid = {
                "bidder": bidder or f"#{row_number}",
                "item": extracted_bid["item"],
                "quantity": extracted_bid["quantity"],
                "email": bid_emails[file_key],
            }
            missing = []
            for key in required_criteria:
                field = CRITERIA[key]["field"]
                if pd.isna(row[field]):
                    reason = proposals[file_key][key]["missing_reason"] if key in score_keys else None
                    if reason:
                        problems.append(t("missing_score").format(
                            bidder=bid["bidder"], criterion=t(f"crit_{key}"), reason=reason[lang]
                        ))
                    else:
                        missing.append(t(f"crit_{key}"))
                    bid[field] = None
                else:
                    bid[field] = float(row[field])
            if missing:
                problems.append(f"{bid['bidder']}: {', '.join(missing)}")
            if bid.get("price") is not None and bid["price"] <= 0:
                invalid_prices.append(bid["bidder"])
            bids_input.append(bid)
            bid_file_keys.append(file_key)

        names = [b["bidder"] for b in bids_input]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        if duplicates:
            problems.append(t("duplicate_bidder").format(bidders=", ".join(duplicates)))

        if problems:
            st.warning(t("blocked_header") + "\n\n" + "\n".join(f"- {p}" for p in problems), icon=":material/block:")
        if invalid_prices:
            st.error(t("invalid_price_error").format(bidders=", ".join(invalid_prices)), icon=":material/euro:")

        can_evaluate = (
            tender_ready and weights_ok and committee_confirmed and bool(bids_input) and not problems and not invalid_prices
        )
        if st.button(t("eval_bids_btn"), key="eval_bids_btn", type="primary", width="stretch", disabled=not can_evaluate,
                     icon=":material/calculate:"):
            with st.spinner(t("spinner_bids")):
                try:
                    result = evaluate_bids(bids_input, {k: weights[k] for k in active_criteria})
                except ValueError as e:
                    st.session_state.pop("matrix_result", None)
                    st.error(str(e), icon=":material/error:")
                else:
                    # Agent scores: the same scoring rule applied to the values as read from the
                    # PDFs, before any correction by the committee; for References / Service and
                    # Concept / Quality the rubric proposal with its reasons.
                    bidder_names = [b["bidder"] for b in bids_input]
                    agent_scores: Dict[str, Dict[str, Optional[float]]] = {name: {} for name in bidder_names}
                    agent_reasons: Dict[str, Dict[str, Dict[str, str]]] = {name: {} for name in bidder_names}
                    for key in result["weights"]:
                        if CRITERIA[key]["kind"] == "committee":
                            for name, file_key in zip(bidder_names, bid_file_keys):
                                proposal = proposals[file_key][key]
                                agent_scores[name][key] = proposal["score"]
                                agent_reasons[name][key] = (
                                    {code: explain(proposal, code) for code in ("DE", "EN")}
                                    if proposal["score"] is not None else proposal["missing_reason"]
                                )
                            continue
                        extracted = extracted_df[CRITERIA[key]["field"]].tolist()
                        if any(pd.isna(v) for v in extracted) or (key == "price" and any(v <= 0 for v in extracted)):
                            continue
                        for name, score in zip(bidder_names, score_criterion(key, [float(v) for v in extracted], bidder_names)):
                            agent_scores[name][key] = round(score, 2)
                    entry = build_tender_entry(
                        tender_ref if tender_ref != "__other__" else "-",
                        tender_title,
                        datetime.now().isoformat(timespec="seconds"),
                        result,
                        agent_scores,
                        agent_reasons,
                    )
                    # The letters are generated once and stored with the run (what is sent later
                    # is exactly this text)
                    build_letters(entry, entry["evaluated_at"])
                    history()["tenders"].append(entry)
                    save_history()
                    result["history_id"] = entry["id"]
                    st.session_state["matrix_result"] = result

    if st.session_state.get("matrix_result"):
        res = st.session_state["matrix_result"]
        winner = res["winner"]
        ranked = res["ranked_bids"]
        losers = res["losers"]
        result_weights = res.get("weights") or {}

        st.html(ui.step(5, "blue"))  # in place of the divider: decoration only
        with st.container(border=True, key="hzcard_winner"):
            st.caption(t("winner_label"))
            st.subheader(winner["bidder"])
        runner_up_points = losers[0]["total_points"] if losers else winner["total_points"]
        w1, w2, w3 = st.columns(3)
        with w1:
            with st.container(border=True, key="hzm_points"):
                st.metric(t("winner_points"), f"{winner['total_points']:.2f}")
        with w2:
            with st.container(border=True, key="hzm_price"):
                st.metric(t("winner_price"), fmt_eur(winner["price"]))
        with w3:
            with st.container(border=True, key="hzm_lead"):
                st.metric(t("winner_lead"), f"+{winner['total_points'] - runner_up_points:.2f}")

        with st.container(key="hzsec_matrix"):
            st.subheader(t("matrix_header"))
        st.caption(" · ".join(f"{t(f'crit_{k}')} {w:g} %" for k, w in result_weights.items()))
        matrix_config = {
            "bidder": st.column_config.TextColumn(t("col_bidder")),
            "price": st.column_config.NumberColumn(t("col_price"), format="%.2f"),
            "total_points": st.column_config.NumberColumn(t("col_total_pts"), format="%.2f"),
        }
        matrix_order = ["bidder", "price"]
        for key in result_weights:
            label = t(f"crit_{key}")
            matrix_config[f"{key}_score"] = st.column_config.NumberColumn(t("col_score").format(criterion=label), format="%.2f")
            matrix_config[f"{key}_points"] = st.column_config.NumberColumn(t("col_points").format(criterion=label), format="%.2f")
            matrix_order += [f"{key}_score", f"{key}_points"]
        st.dataframe(
            pd.DataFrame(ranked),
            hide_index=True,
            width="stretch",
            column_order=matrix_order + ["total_points"],
            column_config=matrix_config,
        )

        with st.container(key="hzsec_letters"):
            st.subheader(t("letters_header"))
        st.caption(t("letters_caption"))
        run = find_run(res.get("history_id"))
        if run is not None:
            render_letters(run)

    if st.session_state.get("history_view") == "bids":
        open_history_dialog("bids")


# ==============================================================================
# VIEW 4: MANAGEMENT INSIGHTS
# ==============================================================================

elif current_view == "insights":
    # The end-to-end overview from the user manual (docs/manual/diagrams), if it has been built
    overview = DIAGRAM_DIR / f"1_overview_{st.session_state['lang'].lower()}.png"
    if overview.exists():
        with st.expander(t("how_it_works"), icon=":material/schema:"):
            st.image(str(overview), caption=t("how_it_works_caption"))
    lines = get_budget_lines()
    approvals = get_approved_spending()

    def fmt_date(value: date) -> str:
        return value.strftime("%d.%m.%Y" if st.session_state.get("lang", "DE") == "DE" else "%Y-%m-%d")

    def fmt_share(share: float) -> str:
        pct = f"{share * 100:.0f}"
        return f"{pct} %" if st.session_state.get("lang", "DE") == "DE" else f"{pct}%"

    # --- Tile 1: budget per line, burn-up chart and projection to 31 Dec -------------------
    with st.container(border=True, key="hzcard_tile_budget"):
        st.subheader(t("tile_budget"))
        st.caption(t("tile_budget_caption"))
        forecast = budget_forecast(lines, approvals, date.today())
        if lines:
            # One line at a time: the lines differ by a factor of six, so a shared axis would hide the small ones
            default = max(range(len(lines)), key=lambda i: forecast[i]["committed"])
            chosen = st.selectbox(
                t("chart_line_select"), [line["category"] for line in lines], index=default, key="burnup_line"
            )
            data = burnup(next(line for line in lines if line["category"] == chosen), approvals, date.today())
            st.altair_chart(burnup_chart(data, fmt_date, fmt_share), width="stretch")
            st.caption(t("chart_burnup_caption") + ("" if data["projection"] else " " + t("chart_no_projection")))
        forecast_rows = []
        for row in forecast:
            if row["status"] == "runs_out":
                runout = t("ins_runs_out").format(date=fmt_date(row["runout_date"]))
            elif row["status"] == "year_end":
                runout = t("ins_year_end").format(share=fmt_share(row["year_end_share"]))
            elif row["status"] == "exhausted":
                runout = t("ins_exhausted")
            else:
                runout = t("ins_not_enough")
            forecast_rows.append(
                {
                    "line": row["category"],
                    "department": row["department"],
                    "committed": fmt_eur(row["committed"], 0),
                    "total": fmt_eur(row["total"], 0),
                    "used": round(row["used_share"] * 100, 1),
                    "runout": runout,
                }
            )
        soon = [row["runout_soon"] for row in forecast]
        styled = pd.DataFrame(forecast_rows).style.apply(
            lambda column: [f"color: {CHART_ORANGE_INK}; font-weight: 600" if flag else "" for flag in soon],
            subset=["runout"],
        )
        st.dataframe(
            styled,
            hide_index=True,
            width="stretch",
            column_config={
                "line": st.column_config.TextColumn(t("ins_col_line")),
                "department": st.column_config.TextColumn(t("ins_col_department")),
                "committed": st.column_config.TextColumn(t("ins_col_committed")),
                "total": st.column_config.TextColumn(t("ins_col_total")),
                "used": st.column_config.ProgressColumn(t("ins_col_used"), format="%.0f%%", min_value=0, max_value=100),
                "runout": st.column_config.TextColumn(t("ins_col_runout")),
            },
        )

    # --- Tile 2: spend per supplier and concentration per line --------------------------------
    with st.container(border=True, key="hzcard_tile_suppliers"):
        st.subheader(t("tile_suppliers"))
        st.caption(t("tile_suppliers_caption"))
        shares = supplier_shares(approvals, SUPPLIER_SHARE_LIMIT)
        if not shares:
            st.caption(t("ins_no_spend"))
        else:
            st.altair_chart(supplier_chart(supplier_totals(shares)), width="stretch")
            st.caption(t("chart_suppliers_caption"))
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "line": r["category"],
                            "supplier": r["supplier"],
                            "spend": fmt_eur(r["spend"], 0),
                            "orders": r["orders"],
                            "share": round(r["share"] * 100, 1),
                        }
                        for r in shares
                    ]
                ),
                hide_index=True,
                width="stretch",
                column_config={
                    "line": st.column_config.TextColumn(t("ins_col_line")),
                    "supplier": st.column_config.TextColumn(t("ins_col_supplier")),
                    "spend": st.column_config.TextColumn(t("ins_col_spend")),
                    "orders": st.column_config.NumberColumn(t("ins_col_orders"), format="%d"),
                    "share": st.column_config.ProgressColumn(t("ins_col_share"), format="%.0f%%", min_value=0, max_value=100),
                },
            )
            warnings = [
                t("ins_supplier_warning").format(line=r["category"], supplier=r["supplier"], share=fmt_share(r["share"]))
                for r in shares
                if r["above_limit"]
            ]
            if warnings:
                st.warning("\n".join(f"- {w}" for w in warnings), icon=":material/pie_chart:")
            unchecked = sorted({r["category"] for r in shares if not r["line_checked"]})
            if unchecked:
                st.caption(t("ins_concentration_skipped").format(
                    lines=", ".join(unchecked), spend=fmt_eur(CONCENTRATION_MIN_LINE_SPEND, 0),
                    orders=CONCENTRATION_MIN_LINE_ORDERS,
                ))

    # --- Tile 3: AI oversight ---------------------------------------------------------------
    with st.container(border=True, key="hzcard_tile_oversight"):
        st.subheader(t("tile_oversight"))
        st.caption(t("tile_oversight_caption"))
        stats = oversight(history()["requests"], history()["transfers"])
        bid_changes = committee_changes(history()["tenders"])
        m1, m2, m3, m4, m5 = st.columns(5)
        with m1, st.container(key="hzm_agreement"):
            st.metric(
                t("ins_agreement"),
                fmt_share(stats["rate"]) if stats["rate"] is not None else "–",
                help=t("ins_agreement_detail").format(agreed=stats["agreed"], compared=stats["compared"]),
            )
            st.caption(t("ins_agreement_detail").format(agreed=stats["agreed"], compared=stats["compared"]))
        with m2, st.container(key="hzm_overrides"):
            st.metric(t("ins_overrides"), len(stats["overrides"]))
        with m3, st.container(key="hzm_deferred"):
            st.metric(t("ins_deferred"), len(stats["deferred"]))
        with m4, st.container(key="hzm_transfers"):
            st.metric(t("ins_transfers"), f"{stats['transfers_proposed']} / {stats['transfers_accepted']}")
        with m5, st.container(key="hzm_committee"):
            st.metric(t("ins_committee_changes"), len(bid_changes))

        def decisions_table(entries: List[Dict[str, Any]]) -> None:
            if not entries:
                st.caption(t("ins_none"))
                return
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "ref": e["ref"],
                            "request": localized(e.get("summary") or e.get("text", ""))[:70],
                            "agent": t(f"assessment_{e['agent_decision']}"),
                            "human": t(f"decision_{e['decision']}"),
                            "date": fmt_dt(e["decided_at"]),
                            "note": localized(e.get("note") or e.get("override_reason") or ""),
                        }
                        for e in sorted(entries, key=lambda e: e["decided_at"], reverse=True)
                    ]
                ),
                hide_index=True,
                width="stretch",
                column_config={
                    "ref": st.column_config.TextColumn(t("col_ref")),
                    "request": st.column_config.TextColumn(t("col_request")),
                    "agent": st.column_config.TextColumn(t("ins_col_agent")),
                    "human": st.column_config.TextColumn(t("ins_col_human")),
                    "date": st.column_config.TextColumn(t("ins_col_date")),
                    "note": st.column_config.TextColumn(t("ins_col_note")),
                },
            )

        st.markdown(ui.label("swap_horiz", t("ins_overrides_header")), unsafe_allow_html=True)
        decisions_table(stats["overrides"])
        st.markdown(ui.label("person", t("ins_deferred_header")), unsafe_allow_html=True)
        decisions_table(stats["deferred"])
        st.markdown(ui.label("groups", t("ins_committee_header")), unsafe_allow_html=True)
        if bid_changes:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "ref": c["ref"],
                            "bidder": c["bidder"],
                            "criterion": t(f"crit_{c['criterion']}"),
                            "agent": f"{c['agent']:g}",
                            "final": f"{c['committee']:g}",
                            "date": fmt_dt(c["evaluated_at"]),
                        }
                        for c in sorted(bid_changes, key=lambda c: c["evaluated_at"] or "", reverse=True)
                    ]
                ),
                hide_index=True,
                width="stretch",
                column_config={
                    "ref": st.column_config.TextColumn(t("col_ref")),
                    "bidder": st.column_config.TextColumn(t("ins_col_bidder")),
                    "criterion": st.column_config.TextColumn(t("ins_col_criterion")),
                    "agent": st.column_config.TextColumn(t("ins_col_proposed")),
                    "final": st.column_config.TextColumn(t("ins_col_final")),
                    "date": st.column_config.TextColumn(t("ins_col_date")),
                },
            )
        else:
            st.caption(t("ins_none"))


# ==============================================================================
# VIEW 3: ADD PROCUREMENT REQUEST
# ==============================================================================

else:
    form_key = st.session_state["form_key"]
    text_widget_key = f"request_text_{form_key}"
    if text_widget_key not in st.session_state:
        st.session_state[text_widget_key] = st.session_state.get("draft_text", "")

    with st.container(border=True):
        st.html(ui.step(1, "blue"))
        uploaded_pdf = st.file_uploader(
            t("pdf_label"),
            type=["pdf"],
            key=f"pdf_upload_{form_key}",
            help=t("pdf_help"),
        )

        if uploaded_pdf is not None:
            uploaded_pdf.seek(0)
            if st.session_state.get("last_uploaded_pdf") != uploaded_pdf.name:
                try:
                    reader = PdfReader(uploaded_pdf)
                    extracted_pages = []
                    for page in reader.pages:
                        page_text = page.extract_text()
                        if page_text:
                            extracted_pages.append(page_text)
                    extracted_text = "\n\n".join(extracted_pages).strip()

                    if extracted_text:
                        st.session_state["draft_text"] = extracted_text
                        st.session_state[text_widget_key] = extracted_text
                        st.session_state["last_uploaded_pdf"] = uploaded_pdf.name
                        st.toast(t("pdf_extracted").format(count=len(extracted_text)), icon=":material/upload_file:")
                    else:
                        st.warning(t("pdf_extract_warning"), icon=":material/upload_file:")
                except Exception as e:
                    st.error(t("pdf_extract_error").format(error=e), icon=":material/error:")

        st.html(ui.step(2, "orange"))
        st.caption(t("or_divider"))

        st.markdown(ui.label("lightbulb", t("sample_header")), unsafe_allow_html=True)
        for sample_col, sample_key in zip(st.columns(3), ["valid", "unapproved", "review"]):
            with sample_col:
                if st.button(t(f"sample_{sample_key}"), key=f"sample_{sample_key}", width="stretch",
                             icon=SAMPLE_ICONS[sample_key]):
                    st.session_state["draft_text"] = SAMPLE_REQUESTS[st.session_state["lang"]][sample_key]
                    st.session_state[text_widget_key] = SAMPLE_REQUESTS[st.session_state["lang"]][sample_key]
                    st.rerun()

        request_text = st.text_area(
            t("textarea_label"),
            key=text_widget_key,
            height=180,
            placeholder=t("textarea_placeholder"),
        )
        st.session_state["draft_text"] = request_text or ""

        st.html(ui.step(3, "teal"))
        submit_clicked = st.button(t("submit_btn"), key="submit_btn", type="primary", width="stretch",
                                   icon=":material/send:")

    if submit_clicked:
        current_input = (request_text or "").strip()
        if not current_input:
            st.warning(t("no_input_warning"), icon=":material/edit_note:")
        else:
            source = (
                t("source_pdf").format(name=st.session_state["last_uploaded_pdf"])
                if st.session_state.get("last_uploaded_pdf")
                else t("source_manual")
            )
            with st.spinner(t("spinner_eval")):
                new_ref = submit_request(current_input, source)
            if new_ref:
                st.session_state["last_submitted"] = new_ref
                st.session_state["_reset_form"] = True
                st.rerun()

    last_submitted = st.session_state.pop("last_submitted", None)
    if last_submitted:
        st.html(ui.illustration("task_alt", "green", "sm", paper=False))
        st.success(t("submitted_success").format(ref=last_submitted, count=len(pending_requests())),
                   icon=":material/check_circle:")
        st.button(t("go_verify_btn"), key="go_verify_btn", on_click=go_to, args=("verify",),
                  icon=":material/fact_check:")


# ==============================================================================
# HELP ASSISTANT (floating button on every page; ENABLE_CHAT=false hides it)
# ==============================================================================


def clear_help_chat() -> None:
    st.session_state["help_chat_messages"] = []


def render_help_chat(page: str) -> None:
    """Chat panel answering questions from the user manual. It only receives the question,
    this session's chat history and the page name; it cannot change anything in the app."""
    messages = st.session_state.setdefault("help_chat_messages", [])
    with st.container(key="help_chat"):
        with st.popover("💬", help=t("chat_button_help")):
            with st.container(key="help_chat_panel"):
                st.markdown(f"**{t('chat_title')}**")
                st.caption(t("chat_disclaimer"))
                # Placeholders: the history appears only once there is a conversation, and the
                # starter questions disappear in the same run as the first question
                history_slot, starter_slot = st.empty(), st.empty()
                starter = None
                if not messages:
                    with starter_slot.container():
                        for index, text in enumerate(t("chat_starters")):
                            if st.button(text, key=f"help_chat_starter_{index}", width="stretch"):
                                starter = text
                question = st.chat_input(t("chat_placeholder"), key="help_chat_input", max_chars=1000) or starter
                if question:
                    messages.append({"role": "user", "content": question})
                    starter_slot.empty()
                if messages:
                    with history_slot.container(height=260, border=False):
                        for message in messages:
                            with st.chat_message(message["role"]):
                                st.markdown(message["content"])
                        if question:
                            with st.chat_message("assistant"):
                                try:
                                    with st.spinner(t("chat_thinking")):
                                        answer = {"role": "assistant", "content": ask(
                                            question, messages[:-1], st.session_state["lang"], page)}
                                except HelpUnavailable:
                                    answer = {"role": "assistant", "content": t("chat_unavailable"), "error": True}
                                st.markdown(answer["content"])
                            messages.append(answer)
                if messages:
                    st.button(t("chat_clear"), key="help_chat_clear", type="tertiary", on_click=clear_help_chat)


if chat_enabled():
    render_help_chat(t(f"nav_{current_view}"))
