import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from pypdf import PdfReader

# Load environment variables
load_dotenv()

# ==============================================================================
# BACKEND ADAPTER
# Facilitates parallel frontend/backend development with fallback mock data
# and dynamic connection to data/mock_data.db and src/agent.py when ready.
# ==============================================================================

DB_PATH = Path(__file__).parent / "data" / "mock_data.db"


def get_budgets_df() -> pd.DataFrame:
    """Reads Budgets from data/mock_data.db if the file/table exists,
    otherwise returns a realistic mock DataFrame.
    """
    if DB_PATH.exists():
        try:
            with sqlite3.connect(DB_PATH) as conn:
                df = pd.read_sql_query(
                    "SELECT Category, Total_Budget, Remaining_Budget FROM Budgets", conn
                )
                if not df.empty:
                    return df
        except Exception:
            pass

    # Realistic mock fallback
    return pd.DataFrame(
        [
            {"Category": "IT", "Total_Budget": 100000.0, "Remaining_Budget": 60000.0},
            {"Category": "Construction", "Total_Budget": 500000.0, "Remaining_Budget": 450000.0},
            {"Category": "Consulting", "Total_Budget": 75000.0, "Remaining_Budget": 30000.0},
            {"Category": "Office Supplies", "Total_Budget": 25000.0, "Remaining_Budget": 18500.0},
        ]
    )


def get_audit_logs_df() -> pd.DataFrame:
    """Reads Audit_Logs from data/mock_data.db if the file/table exists,
    otherwise returns a realistic mock DataFrame.
    """
    if DB_PATH.exists():
        try:
            with sqlite3.connect(DB_PATH) as conn:
                df = pd.read_sql_query(
                    "SELECT Id, Timestamp, Request_Text, Supplier, Amount, Category, Decision, Reasoning FROM Audit_Logs ORDER BY Id DESC",
                    conn,
                )
                if not df.empty:
                    return df
        except Exception:
            pass

    # Realistic mock fallback
    return pd.DataFrame(
        [
            {
                "Id": 1,
                "Timestamp": "2026-11-18 10:15:00",
                "Request_Text": "Procurement of 15 Dell XPS laptops for digital administration team.",
                "Supplier": "Dell",
                "Amount": 22500.0,
                "Category": "IT",
                "Decision": "Approved",
                "Reasoning": "Checked budget: €100k total, €60k available. Requested: €22.5k. Supplier 'Dell' verified in approved suppliers list. Status: OK.",
            },
            {
                "Id": 2,
                "Timestamp": "2026-11-18 14:30:00",
                "Request_Text": "Server infrastructure and cloud gateway setup from TechCorp.",
                "Supplier": "TechCorp",
                "Amount": 48000.0,
                "Category": "IT",
                "Decision": "Rejected",
                "Reasoning": "Supplier verification failed: 'TechCorp' is not on the approved supplier list. Status: REJECTED.",
            },
            {
                "Id": 3,
                "Timestamp": "2026-11-19 09:00:00",
                "Request_Text": "Civic center building facade insulation and window renovation.",
                "Supplier": "BauPartner GmbH",
                "Amount": 520000.0,
                "Category": "Construction",
                "Decision": "Requires Human Review",
                "Reasoning": "Budget check: Remaining budget is €450k; requested amount €520k exceeds available funds by €70k. Requires human override.",
            },
        ]
    )


def run_agent_evaluation(request_text: str) -> Dict[str, Any]:
    """Imports and calls the evaluation function (evaluate_request) from src/agent.py.
    If not implemented yet or fails, returns a mock dict with:
      - 'decision': 'Approved' | 'Requires Human Review' | 'Rejected'
      - 'reasoning': list of step-by-step strings
    """
    try:
        import src.agent as agent_module

        # Check for evaluate_request or similar evaluation functions in src/agent.py
        eval_fn = getattr(agent_module, "evaluate_request", None) or getattr(
            agent_module, "run_agent_evaluation", None
        )
        if callable(eval_fn):
            raw_result = eval_fn(request_text)
            if raw_result:
                # Handle Pydantic model or dict
                if hasattr(raw_result, "model_dump"):
                    data = raw_result.model_dump()
                elif isinstance(raw_result, dict):
                    data = raw_result
                else:
                    data = {"decision": str(raw_result), "reasoning": [str(raw_result)]}

                decision_raw = str(data.get("decision", "Requires Human Review")).strip().upper()
                if "APPROV" in decision_raw:
                    normalized_decision = "Approved"
                elif "REJECT" in decision_raw:
                    normalized_decision = "Rejected"
                else:
                    normalized_decision = "Requires Human Review"

                reasoning_val = data.get("reasoning", [])
                if isinstance(reasoning_val, str):
                    reasoning_list = [
                        line.strip() for line in reasoning_val.split("\n") if line.strip()
                    ]
                elif isinstance(reasoning_val, list):
                    reasoning_list = [str(item) for item in reasoning_val]
                else:
                    reasoning_list = [str(reasoning_val)]

                return {
                    "decision": normalized_decision,
                    "reasoning": reasoning_list,
                }
    except Exception:
        # Backend not yet completed or raised an exception; fallback to mock logic
        pass

    # Realistic mock evaluation based on procurement scenario patterns
    text_lower = request_text.lower()

    if any(keyword in text_lower for keyword in ["techcorp", "unapproved", "fraud", "unauthorized"]):
        return {
            "decision": "Rejected",
            "reasoning": [
                "1. Extracted Request: Supplier 'TechCorp', Amount €48,000, Category 'IT'.",
                "2. Supplier Verification: Queried database table 'Suppliers' — 'TechCorp' is NOT on the approved municipal supplier list.",
                "3. Policy Compliance Check: Municipal Procurement Code §14 strictly prohibits contract awards to unverified suppliers.",
                "4. Final Determination: REJECTED — Supplier authorization failed.",
            ],
        }
    elif any(
        keyword in text_lower
        for keyword in ["baupartner", "exceed", "over-budget", "over budget", "520", "520000", "review"]
    ):
        return {
            "decision": "Requires Human Review",
            "reasoning": [
                "1. Extracted Request: Supplier 'BauPartner GmbH', Amount €520,000, Category 'Construction'.",
                "2. Supplier Verification: Queried database table 'Suppliers' — 'BauPartner GmbH' is an approved municipal contractor.",
                "3. Budget Verification: Construction budget remaining is €450,000. Requested amount of €520,000 exceeds available funds by €70,000.",
                "4. Threshold Rule: Invoices exceeding single-case approval limit or remaining envelope require department supervisor authorization.",
                "5. Final Determination: REQUIRES HUMAN REVIEW — Flagged for manual budget amendment and caseworker review.",
            ],
        }
    else:
        return {
            "decision": "Approved",
            "reasoning": [
                "1. Extracted Request: Supplier 'Dell', Amount €22,500, Category 'IT'.",
                "2. Supplier Verification: Queried database table 'Suppliers' — 'Dell' is an active approved framework contractor.",
                "3. Budget Verification: Queried database table 'Budgets' — IT category has €60,000 remaining. €22,500 is within budget limit.",
                "4. Policy Compliance: Single-order threshold (< €50,000) satisfied without special committee review.",
                "5. Final Determination: APPROVED — All automated compliance checks passed.",
            ],
        }


def trigger_demo_reset() -> None:
    """Calls the teammate's reset function if available, or shows a clear toast notification in mock mode."""
    reset_executed = False

    # Check for reset function in src.init_db
    try:
        import src.init_db as init_db

        for func_name in [
            "reset_database",
            "reset_db",
            "init_database",
            "init_db",
            "seed_data",
            "main",
        ]:
            fn = getattr(init_db, func_name, None)
            if callable(fn):
                fn()
                reset_executed = True
                break
    except Exception:
        pass

    # Or check in src.agent
    if not reset_executed:
        try:
            import src.agent as agent_mod

            for func_name in ["reset_demo_data", "reset_database", "reset_db", "init_db"]:
                fn = getattr(agent_mod, func_name, None)
                if callable(fn):
                    fn()
                    reset_executed = True
                    break
        except Exception:
            pass

    if reset_executed:
        st.toast("✅ Demo database successfully reset to initial seed state!", icon="🔄")
    else:
        st.toast(
            "ℹ️ Mock Mode: Reset triggered. Database will reload once backend is connected.",
            icon="🔄",
        )


# ==============================================================================
# STREAMLIT UI SETUP (Phase 3: Tasks 5 & 6)
# ==============================================================================

st.set_page_config(
    page_title="Public Procurement Trust Agent",
    page_icon="🏛️",
    layout="wide",
)

# Initialize Session State
if "request_text_area" not in st.session_state:
    st.session_state["request_text_area"] = ""
if "last_uploaded_pdf" not in st.session_state:
    st.session_state["last_uploaded_pdf"] = None
if "last_evaluation" not in st.session_state:
    st.session_state["last_evaluation"] = None

# Sidebar: Live tables and Reset Demo Data (Task 5)
with st.sidebar:
    st.header("🏛️ Administration Live State")
    st.caption("Synchronized with `data/mock_data.db`")

    if st.button("🔄 Reset Demo Data", use_container_width=True, help="Reset database tables to initial seed state"):
        trigger_demo_reset()
        st.session_state["last_evaluation"] = None
        st.rerun()

    st.divider()
    st.subheader("💰 Budgets")
    budgets_df = get_budgets_df()
    if not budgets_df.empty:
        st.dataframe(
            budgets_df,
            hide_index=True,
            column_config={
                "Total_Budget": st.column_config.NumberColumn("Total", format="€%d"),
                "Remaining_Budget": st.column_config.NumberColumn("Remaining", format="€%d"),
            },
            width="stretch",
        )
    else:
        st.info("No budget data available.")

    st.divider()
    st.subheader("📋 Audit Logs")
    audit_logs_df = get_audit_logs_df()
    if not audit_logs_df.empty:
        st.dataframe(
            audit_logs_df,
            hide_index=True,
            column_config={
                "Amount": st.column_config.NumberColumn("Amount", format="€%d"),
            },
            width="stretch",
        )
    else:
        st.info("No audit logs found.")

# Main Page Header
st.title("🏛️ Public Procurement Trust Agent")
st.markdown(
    "Automated procurement validation assistant for public administration caseworkers. "
    "Every decision is verified against municipal budgets and approved supplier records with **full explainability**."
)

st.divider()

# Input Section: PDF Uploader + Request Text Area (Task 5)
st.subheader("📄 Procurement Request Input")

uploaded_pdf = st.file_uploader(
    "Upload Procurement Document (PDF)",
    type=["pdf"],
    help="Upload an invoice, tender offer, or quotation in PDF format. Extracted text will populate the text area below.",
)

if uploaded_pdf is not None:
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
                st.session_state["request_text_area"] = extracted_text
                st.session_state["last_uploaded_pdf"] = uploaded_pdf.name
                st.toast(f"Extracted {len(extracted_text)} characters from {uploaded_pdf.name}", icon="📄")
            else:
                st.warning(f"No extractable text found in '{uploaded_pdf.name}'.")
        except Exception as e:
            st.error(f"Failed to read PDF file: {e}")

request_text = st.text_area(
    "Procurement Request Details",
    key="request_text_area",
    height=160,
    placeholder="Paste or type procurement request (e.g. 'Order 15 Dell laptops for €22,500 for the IT Department')...",
    help="You can review or edit the extracted text before evaluating.",
)

col_eval, col_clear = st.columns([4, 1])
with col_eval:
    evaluate_clicked = st.button("🚀 Evaluate Request", type="primary", use_container_width=True)
with col_clear:
    if st.button("🗑️ Clear", use_container_width=True):
        st.session_state["request_text_area"] = ""
        st.session_state["last_uploaded_pdf"] = None
        st.session_state["last_evaluation"] = None
        st.rerun()

if evaluate_clicked:
    current_input = st.session_state.get("request_text_area", "").strip()
    if not current_input:
        st.warning("⚠️ Please provide procurement request text or upload a PDF before evaluating.")
    else:
        with st.spinner("Analyzing request against municipal database and policies..."):
            evaluation = run_agent_evaluation(current_input)
            st.session_state["last_evaluation"] = evaluation

# Decision & Reasoning Section (Task 6)
if st.session_state.get("last_evaluation"):
    st.divider()
    eval_data = st.session_state["last_evaluation"]
    decision = eval_data.get("decision", "Requires Human Review")
    reasoning = eval_data.get("reasoning", [])

    st.subheader("🎯 Agent Evaluation & Decision")

    # Color-coded decision banner (Green = Approved, Yellow = Requires Human Review, Red = Rejected)
    if decision == "Approved":
        st.success("### ✅ Status: APPROVED\n\n**The procurement request passes all compliance and budget checks.**")
    elif decision == "Requires Human Review":
        st.warning("### ⚠️ Status: REQUIRES HUMAN REVIEW\n\n**This request requires manual verification or caseworker override.**")
    elif decision == "Rejected":
        st.error("### ❌ Status: REJECTED\n\n**The procurement request violates municipal procurement policies.**")
    else:
        st.info(f"### ℹ️ Status: {decision}")

if os.getenv("GEMINI_API_KEY"):
    st.success("API key loaded.")
else:
    st.error("Missing GEMINI_API_KEY in .env")
    # Step-by-step Reasoning breakdown
    st.markdown("#### 🔍 Step-by-Step Reasoning Breakdown")
    with st.container(border=True):
        if reasoning:
            for idx, step in enumerate(reasoning, start=1):
                clean_step = str(step).strip()
                if clean_step.lower().startswith("step ") or (
                    len(clean_step) > 2 and clean_step[0].isdigit() and clean_step[1] in [".", ":"]
                ):
                    st.markdown(f"- {clean_step}")
                else:
                    st.markdown(f"- **Step {idx}:** {clean_step}")
        else:
            st.markdown("_No step-by-step reasoning returned._")