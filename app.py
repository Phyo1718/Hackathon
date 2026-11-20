import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from pypdf import PdfReader

from src.agent import (
    commit_decision,
    evaluate_bids,
    evaluate_request,
    generate_anmeldebogen_pdf,
    has_api_key,
)
from src.init_db import DB_PATH, init_db

# Load environment variables
load_dotenv()


def database_needs_init() -> bool:
    """Initialise the database only when it is missing or uses an outdated schema."""
    if not Path(DB_PATH).exists():
        return True
    try:
        with sqlite3.connect(DB_PATH) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(Budgets);")}
        return "Konto" not in columns
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
        "title": "Public Procurement Assistant",
        "subtitle": "Verification portal for municipal procurement requests, budget commitments and audit documentation.",
        "sidebar_header": "Administration Status",
        "sidebar_caption": "Live data from data/mock_data.db",
        "reset_btn": "Reset Demo Data",
        "reset_success": "Database reset to the initial demo state.",
        "reset_error": "Database reset failed: {error}",
        "budgets_header": "Municipal Budgets",
        "col_category": "Position",
        "col_konto": "Account",
        "col_total": "Total",
        "col_available": "Available",
        "no_budget_data": "No budget data available.",
        "audit_header": "Audit Logs",
        "col_id": "ID",
        "col_timestamp": "Timestamp",
        "col_supplier": "Supplier",
        "col_amount": "Amount",
        "col_decision": "Decision",
        "no_audit_data": "No audit entries available.",
        "input_header": "Procurement Request Intake",
        "pdf_label": "Upload procurement document (PDF)",
        "pdf_help": "Upload a quotation or invoice as PDF. The extracted text is placed in the request field.",
        "pdf_extracted": "{count} characters extracted from the PDF.",
        "pdf_extract_warning": "No extractable text was found in the PDF.",
        "pdf_extract_error": "The PDF could not be read: {error}",
        "sample_header": "Preset Requests",
        "sample_1": "Valid IT request (Dell)",
        "sample_2": "Blocked supplier (TechCorp)",
        "sample_3": "Borderline budget (Stadtwerke)",
        "textarea_label": "Procurement request details",
        "textarea_placeholder": "Enter the procurement request, including supplier, amount and budget category.",
        "evaluate_btn": "Evaluate Request",
        "clear_btn": "Clear Form",
        "next_request_btn": "Process Next Request",
        "no_input_warning": "Please enter a procurement request or upload a document.",
        "spinner_eval": "Checking the request against budget data and the supplier register...",
        "eval_error": "The request could not be evaluated, so no decision was made: {error}",
        "decision_header": "Agent Evaluation and Decision",
        "status_approved": "Status: APPROVED\n\nThe procurement request complies with the municipal budget and supplier regulations.",
        "status_review": "Status: REQUIRES REVIEW\n\nThis request requires manual verification due to a borderline budget overage.",
        "status_rejected": "Status: REJECTED\n\nThe procurement request violates municipal procurement rules.",
        "reasoning_header": "Step-by-Step Verification",
        "no_reasoning": "No reasoning provided.",
        "approval_header": "Caseworker Approval",
        "approval_note": "The Anmeldebogen is generated only after approval. Budget commitment and audit logging occur at the same time.",
        "commit_approve_btn": "Approve & Commit to Budget",
        "commit_reject_btn": "Reject Request",
        "commit_error": "Commit failed: {error}",
        "committed_success": "Status: APPROVED. The budget has been committed, the audit log has been written and the Anmeldebogen is ready for download.",
        "committed_reject": "Status: REJECTED. The decision has been recorded in the audit log. No budget was committed.",
        "form_header": "Official Procurement Form",
        "form_note": "The PDF was generated from the approved request and can be downloaded directly.",
        "download_form_btn": "Download Anmeldebogen (PDF)",
        "pdf_error": "The PDF could not be generated:",
        "tab_single": "Single Request Verification",
        "tab_matrix": "Bid Evaluation Matrix (§ 13 UVgO)",
        "matrix_header": "Multi-Bid Evaluation and 30/30/20 Scoring Matrix",
        "matrix_desc": "Upload multiple quotation PDFs or configure bids to calculate the scoring and generate the mandatory legal rejection letters under § 13 UVgO.",
        "matrix_pdfs_label": "Upload quotation PDFs (optional)",
        "matrix_pdfs_help": "Upload one or more quotation documents.",
        "bidder_config_header": "Bidder configuration for scoring",
        "bidder_1": "Bidder 1",
        "bidder_2": "Bidder 2",
        "bidder_3": "Bidder 3",
        "name_label": "Name",
        "price_label": "Price (EUR)",
        "references_label": "References (0-10)",
        "concept_label": "Concept (0-10)",
        "eval_bids_btn": "Run 30/30/20 Bid Evaluation",
        "invalid_price_error": "Every bid price must be greater than EUR 0. Please correct: {bidders}",
        "spinner_bids": "Calculating the 30/30/20 matrix and preparing rejection letters under § 13 UVgO...",
        "matrix_winner_header": "Recommended award:",
        "matrix_winner_success": "Most economical bid with **{points}** total points (bid price: {price}).",
        "matrix_ranking_header": "Bidder ranking (scoring matrix)",
        "matrix_rejections_header": "Legal rejection reasons (§ 13 UVgO)",
        "matrix_rejections_desc": "Mandatory reasons to avoid procurement review proceedings.",
        "matrix_rejections_expander": "Rejection reasons for unsuccessful bidders under § 13 UVgO",
        "matrix_rejection_title": "Rejection to {bidder} ({price} | {points} points)",
        "matrix_no_reason": "No reason available.",
    },
    "DE": {
        "agency": "Stadt Hildesheim | Zentrale Vergabestelle",
        "title": "Öffentlicher Vergabeassistent",
        "subtitle": "Prüfungsportal für Beschaffungsanträge, Haushaltsbindungen und Auditdokumentation der Stadtverwaltung.",
        "sidebar_header": "Verwaltungsstatus",
        "sidebar_caption": "Live-Daten aus data/mock_data.db",
        "reset_btn": "Demo-Daten zurücksetzen",
        "reset_success": "Datenbank auf den initialen Demo-Stand zurückgesetzt.",
        "reset_error": "Zurücksetzen der Datenbank fehlgeschlagen: {error}",
        "budgets_header": "Haushaltsbudgets",
        "col_category": "Position",
        "col_konto": "Konto",
        "col_total": "Gesamt",
        "col_available": "Verfügbar",
        "no_budget_data": "Keine Budgetdaten verfügbar.",
        "audit_header": "Audit-Protokolle",
        "col_id": "ID",
        "col_timestamp": "Zeitstempel",
        "col_supplier": "Lieferant",
        "col_amount": "Betrag",
        "col_decision": "Entscheidung",
        "no_audit_data": "Keine Audit-Einträge vorhanden.",
        "input_header": "Eingang der Beschaffungsanfrage",
        "pdf_label": "Beschaffungsdokument hochladen (PDF)",
        "pdf_help": "Laden Sie ein Angebot oder eine Rechnung als PDF hoch. Der extrahierte Text wird in das Antragsfeld übernommen.",
        "pdf_extracted": "{count} Zeichen aus der PDF extrahiert.",
        "pdf_extract_warning": "In der PDF wurde kein extrahierbarer Text gefunden.",
        "pdf_extract_error": "Die PDF konnte nicht gelesen werden: {error}",
        "sample_header": "Vorkonfigurierte Anfragen",
        "sample_1": "Gültige IT-Anfrage (Dell)",
        "sample_2": "Gesperrter Lieferant (TechCorp)",
        "sample_3": "Grenzwertiges Budget (Stadtwerke)",
        "textarea_label": "Details der Beschaffungsanfrage",
        "textarea_placeholder": "Beschaffungsanfrage mit Lieferant, Betrag und Haushaltsposition eingeben.",
        "evaluate_btn": "Anfrage prüfen",
        "clear_btn": "Formular zurücksetzen",
        "next_request_btn": "Nächste Anfrage bearbeiten",
        "no_input_warning": "Bitte geben Sie eine Beschaffungsanfrage ein oder laden Sie ein Dokument hoch.",
        "spinner_eval": "Anfrage wird gegen Haushaltsdaten und Lieferantenregister geprüft...",
        "eval_error": "Die Anfrage konnte nicht geprüft werden, es wurde keine Entscheidung getroffen: {error}",
        "decision_header": "Prüfergebnis und Entscheidung",
        "status_approved": "Status: GENEHMIGT\n\nDer Beschaffungsantrag erfüllt die haushalts- und vergaberechtlichen Vorgaben.",
        "status_review": "Status: PRÜFUNG ERFORDERLICH\n\nDie Anfrage erfordert eine manuelle Prüfung aufgrund einer geringfügigen Budgetüberschreitung.",
        "status_rejected": "Status: ABGELEHNT\n\nDer Beschaffungsantrag verstößt gegen die kommunalen Vergabevorschriften.",
        "reasoning_header": "Schritt-für-Schritt-Prüfprotokoll",
        "no_reasoning": "Keine Begründung vorhanden.",
        "approval_header": "Freigabe durch die Sachbearbeitung",
        "approval_note": "Der Anmeldebogen wird erst nach der Freigabe erzeugt. Budgetbindung und Audit-Protokollierung erfolgen zeitgleich.",
        "commit_approve_btn": "Genehmigen und Budget belasten",
        "commit_reject_btn": "Anfrage ablehnen",
        "commit_error": "Verbuchung fehlgeschlagen: {error}",
        "committed_success": "Status: GENEHMIGT. Das Budget wurde belastet, der Audit-Eintrag geschrieben und der Anmeldebogen steht zum Download bereit.",
        "committed_reject": "Status: ABGELEHNT. Die Entscheidung wurde im Audit-Protokoll gespeichert. Es wurde kein Budget belastet.",
        "form_header": "Amtliches Beschaffungsformular",
        "form_note": "Die PDF-Datei wurde aus der freigegebenen Anfrage erzeugt und kann direkt heruntergeladen werden.",
        "download_form_btn": "Anmeldebogen (PDF) herunterladen",
        "pdf_error": "Die PDF konnte nicht erzeugt werden:",
        "tab_single": "Einzelantrag-Prüfung",
        "tab_matrix": "Angebotswertung (§ 13 UVgO)",
        "matrix_header": "Multi-Bieter-Auswertung und 30/30/20-Scoring-Matrix",
        "matrix_desc": "Laden Sie mehrere Angebots-PDFs hoch oder konfigurieren Sie Bieter, um die Wertung zu berechnen und rechtssichere Absageschreiben nach § 13 UVgO zu erstellen.",
        "matrix_pdfs_label": "Angebots-PDFs hochladen (optional)",
        "matrix_pdfs_help": "Laden Sie ein oder mehrere Angebotsdokumente hoch.",
        "bidder_config_header": "Bieterkonfiguration für die Wertung",
        "bidder_1": "Bieter 1",
        "bidder_2": "Bieter 2",
        "bidder_3": "Bieter 3",
        "name_label": "Name",
        "price_label": "Preis (EUR)",
        "references_label": "Referenzen (0-10)",
        "concept_label": "Konzept (0-10)",
        "eval_bids_btn": "30/30/20-Angebotswertung starten",
        "invalid_price_error": "Jeder Angebotspreis muss größer als 0 EUR sein. Bitte korrigieren: {bidders}",
        "spinner_bids": "30/30/20-Matrix wird berechnet und Absageschreiben nach § 13 UVgO werden erstellt...",
        "matrix_winner_header": "Empfohlener Zuschlagsträger:",
        "matrix_winner_success": "Wirtschaftlichstes Angebot mit **{points}** Gesamtpunkten (Angebotspreis: {price}).",
        "matrix_ranking_header": "Rangliste der Bieter (Scoring-Matrix)",
        "matrix_rejections_header": "Rechtssichere Ablehnungsbegründungen (§ 13 UVgO)",
        "matrix_rejections_desc": "Zwingend erforderliche Begründungen zur Vermeidung von Vergabeverfahrensklagen.",
        "matrix_rejections_expander": "Begründungen für abgelehnte Bieter nach § 13 UVgO",
        "matrix_rejection_title": "Absage an {bidder} ({price} | {points} Punkte)",
        "matrix_no_reason": "Keine Begründung vorhanden.",
    },
}

SAMPLE_REQUESTS = {
    "EN": {
        "valid": "Procurement of 10 Dell laptops for the digital administration team amounting to EUR 14,500 under the IT-Ausstattung budget.",
        "unapproved": "Server infrastructure setup provided by TechCorp amounting to EUR 38,000 under the IT-Ausstattung budget.",
        "review": "Procurement of a service vehicle for the municipal works department from Stadtwerke Hildesheim amounting to EUR 76,000 under the Fahrzeuge budget.",
    },
    "DE": {
        "valid": "Beschaffung von 10 Dell Laptops für das digitale Verwaltungsteam im Wert von 14.500 Euro für den Bereich IT-Ausstattung.",
        "unapproved": "Einrichtung einer Serverinfrastruktur durch die Firma TechCorp im Wert von 38.000 Euro für den Bereich IT-Ausstattung.",
        "review": "Beschaffung eines Dienstleistungsfahrzeugs für den Bauhof bei den Stadtwerken Hildesheim im Wert von 76.000 Euro für den Bereich Fahrzeuge.",
    },
}


# ==============================================================================
# DATABASE ADAPTER FUNCTIONS
# ==============================================================================


def get_budgets_df() -> pd.DataFrame:
    """Reads the municipal budget positions from data/mock_data.db."""
    if not Path(DB_PATH).exists():
        try:
            init_db()
        except Exception:
            pass
    try:
        with sqlite3.connect(DB_PATH) as conn:
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


def get_audit_logs_df() -> pd.DataFrame:
    """Reads the latest audit entries from data/mock_data.db."""
    if not Path(DB_PATH).exists():
        try:
            init_db()
        except Exception:
            pass
    try:
        with sqlite3.connect(DB_PATH) as conn:
            df = pd.read_sql_query(
                "SELECT Id, Timestamp, Supplier, Category, Amount, Decision FROM Audit_Logs ORDER BY Id DESC LIMIT 20",
                conn,
            )
            if not df.empty:
                return df
    except Exception:
        pass
    return pd.DataFrame()


# ==============================================================================
# STREAMLIT UI SETUP (FORMAL MUNICIPAL THEME)
# ==============================================================================

st.set_page_config(
    page_title="Stadt Hildesheim - Procurement Agent",
    layout="wide",
)

# Startup gate: the agent cannot produce any decision without Gemini, so nothing
# else is rendered until an API key is configured.
if not has_api_key():
    st.error(
        "**Gemini API key missing / Gemini-API-Schlüssel fehlt.**\n\n"
        "This application requires Google Gemini and has no offline mode. To set it up:\n\n"
        "1. Copy `.env.example` to `.env` in the project root.\n"
        "2. Set `GEMINI_API_KEY=<your key>` in `.env` (or export `GEMINI_API_KEY` / `GOOGLE_API_KEY`).\n"
        "3. Restart the app with `streamlit run app.py`."
    )
    st.stop()

st.markdown(
    """
    <style>
        .gov-meta {
            color: #9fb3c8;
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            margin-bottom: 0.25rem;
        }
        div[data-testid="stSidebar"] {
            border-right: 1px solid #24384c;
        }
        div.stButton > button {
            border-radius: 3px;
            font-weight: 600;
        }
        div[data-testid="stTabs"] button {
            font-weight: 600;
        }
        h1, h2, h3 {
            letter-spacing: 0.01em;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# Initialize session state
if "lang" not in st.session_state:
    st.session_state["lang"] = "DE"
if "form_key" not in st.session_state:
    st.session_state["form_key"] = 0
if "draft_text" not in st.session_state:
    st.session_state["draft_text"] = ""
if "last_uploaded_pdf" not in st.session_state:
    st.session_state["last_uploaded_pdf"] = None
if "last_evaluation" not in st.session_state:
    st.session_state["last_evaluation"] = None
if "committed" not in st.session_state:
    st.session_state["committed"] = False
if "committed_decision" not in st.session_state:
    st.session_state["committed_decision"] = None
if "approved_pdf" not in st.session_state:
    st.session_state["approved_pdf"] = None
if "approved_pdf_name" not in st.session_state:
    st.session_state["approved_pdf_name"] = None

# The pending reset is applied before any widget is instantiated. This makes it
# safe to clear the text area and the file uploader after an evaluation.
if st.session_state.pop("_reset_form", False):
    st.session_state["draft_text"] = ""
    st.session_state["last_uploaded_pdf"] = None
    st.session_state["form_key"] += 1
    st.session_state["committed"] = False
    st.session_state["committed_decision"] = None
    st.session_state["approved_pdf"] = None
    st.session_state["approved_pdf_name"] = None
    st.session_state.pop("pdf_error", None)


def t(key: str) -> str:
    lang = st.session_state.get("lang", "DE")
    return TRANSLATIONS.get(lang, TRANSLATIONS["DE"]).get(key, key)


def reset_decision_state() -> None:
    st.session_state["last_evaluation"] = None
    st.session_state["committed"] = False
    st.session_state["committed_decision"] = None
    st.session_state["approved_pdf"] = None
    st.session_state["approved_pdf_name"] = None
    st.session_state.pop("pdf_error", None)


def clear_form() -> None:
    """Callback that clears the current request and forces fresh widgets."""
    reset_decision_state()
    st.session_state["_reset_form"] = True


# Sidebar: language selection, reset action and live administration data
with st.sidebar:
    lang_choice = st.radio(
        "Sprache / Language",
        ["Deutsch (DE)", "English (EN)"],
        index=0 if st.session_state.get("lang", "DE") == "DE" else 1,
        horizontal=True,
    )
    st.session_state["lang"] = "DE" if lang_choice.startswith("Deutsch") else "EN"

    st.header(t("sidebar_header"))
    st.caption(t("sidebar_caption"))

    if st.button(t("reset_btn"), use_container_width=True):
        try:
            init_db()
            clear_form()
            st.toast(t("reset_success"))
            st.rerun()
        except Exception as e:
            st.error(t("reset_error").format(error=e))

    st.divider()
    st.subheader(t("budgets_header"))
    budgets_df = get_budgets_df()
    if not budgets_df.empty:
        st.dataframe(
            budgets_df,
            hide_index=True,
            column_config={
                "Category": st.column_config.TextColumn(t("col_category")),
                "Konto": st.column_config.TextColumn(t("col_konto")),
                "Total_Budget": st.column_config.NumberColumn(t("col_total"), format="€%d"),
                "Remaining_Budget": st.column_config.NumberColumn(t("col_available"), format="€%d"),
            },
            width="stretch",
        )
    else:
        st.info(t("no_budget_data"))

    st.divider()
    st.subheader(t("audit_header"))
    audit_logs_df = get_audit_logs_df()
    if not audit_logs_df.empty:
        st.dataframe(
            audit_logs_df,
            hide_index=True,
            column_config={
                "Id": st.column_config.NumberColumn(t("col_id"), format="%d"),
                "Timestamp": st.column_config.TextColumn(t("col_timestamp")),
                "Supplier": st.column_config.TextColumn(t("col_supplier")),
                "Category": st.column_config.TextColumn(t("col_category")),
                "Amount": st.column_config.NumberColumn(t("col_amount"), format="€%d"),
                "Decision": st.column_config.TextColumn(t("col_decision")),
            },
            width="stretch",
            height=240,
        )
    else:
        st.info(t("no_audit_data"))


# Main page header
st.markdown(f'<div class="gov-meta">{t("agency")}</div>', unsafe_allow_html=True)
st.title(t("title"))
st.caption(t("subtitle"))
st.divider()

# Main tabs: single request verification and bid evaluation matrix
tab_single, tab_matrix = st.tabs([t("tab_single"), t("tab_matrix")])

with tab_single:
    st.subheader(t("input_header"))

    form_key = st.session_state["form_key"]
    text_widget_key = f"request_text_{form_key}"
    if text_widget_key not in st.session_state:
        st.session_state[text_widget_key] = st.session_state.get("draft_text", "")

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
                    reset_decision_state()
                    st.session_state["draft_text"] = extracted_text
                    st.session_state[text_widget_key] = extracted_text
                    st.session_state["last_uploaded_pdf"] = uploaded_pdf.name
                    st.toast(t("pdf_extracted").format(count=len(extracted_text)))
                else:
                    st.warning(t("pdf_extract_warning"))
            except Exception as e:
                st.error(t("pdf_extract_error").format(error=e))

    st.markdown(f"**{t('sample_header')}**")
    s_col1, s_col2, s_col3 = st.columns(3)
    with s_col1:
        if st.button(t("sample_1"), use_container_width=True):
            reset_decision_state()
            st.session_state["draft_text"] = SAMPLE_REQUESTS[st.session_state["lang"]]["valid"]
            st.session_state[text_widget_key] = SAMPLE_REQUESTS[st.session_state["lang"]]["valid"]
            st.rerun()
    with s_col2:
        if st.button(t("sample_2"), use_container_width=True):
            reset_decision_state()
            st.session_state["draft_text"] = SAMPLE_REQUESTS[st.session_state["lang"]]["unapproved"]
            st.session_state[text_widget_key] = SAMPLE_REQUESTS[st.session_state["lang"]]["unapproved"]
            st.rerun()
    with s_col3:
        if st.button(t("sample_3"), use_container_width=True):
            reset_decision_state()
            st.session_state["draft_text"] = SAMPLE_REQUESTS[st.session_state["lang"]]["review"]
            st.session_state[text_widget_key] = SAMPLE_REQUESTS[st.session_state["lang"]]["review"]
            st.rerun()

    request_text = st.text_area(
        t("textarea_label"),
        key=text_widget_key,
        height=160,
        placeholder=t("textarea_placeholder"),
    )
    st.session_state["draft_text"] = request_text or ""

    col_eval, col_clear = st.columns([4, 1])
    with col_eval:
        evaluate_clicked = st.button(t("evaluate_btn"), type="primary", use_container_width=True)
    with col_clear:
        st.button(t("clear_btn"), use_container_width=True, on_click=clear_form)

    if evaluate_clicked:
        current_input = (request_text or "").strip()
        if not current_input:
            st.warning(t("no_input_warning"))
        else:
            evaluation = None
            with st.spinner(t("spinner_eval")):
                try:
                    evaluation = evaluate_request(current_input)
                except Exception as e:
                    # No fallback: without a Gemini extraction there is no decision.
                    reset_decision_state()
                    st.error(t("eval_error").format(error=e))

            if evaluation is not None:
                st.session_state["last_evaluation"] = evaluation
                st.session_state["committed"] = False
                st.session_state["committed_decision"] = None
                st.session_state["approved_pdf"] = None
                st.session_state["approved_pdf_name"] = None
                st.session_state.pop("pdf_error", None)
                st.session_state["_reset_form"] = True
                st.rerun()

    # Decision and reasoning section
    if st.session_state.get("last_evaluation"):
        st.divider()
        eval_data = st.session_state["last_evaluation"]
        decision = str(eval_data.get("decision", "REQUIRES_REVIEW")).strip().upper()
        reasoning = eval_data.get("reasoning", "")

        st.subheader(t("decision_header"))

        if decision in ["APPROVED", "APPROVE"]:
            st.success(t("status_approved"))
        elif decision in ["REQUIRES_REVIEW", "REQUIRES REVIEW", "REVIEW"]:
            st.warning(t("status_review"))
        else:
            st.error(t("status_rejected"))

        st.markdown(f"#### {t('reasoning_header')}")
        with st.container(border=True):
            if reasoning:
                st.markdown(reasoning)
            else:
                st.caption(t("no_reasoning"))

        st.divider()

        # Human-in-the-loop action. The PDF is generated only inside the approval
        # branch, after the budget and audit log have been committed.
        if not st.session_state.get("committed", False):
            st.subheader(t("approval_header"))
            st.caption(t("approval_note"))
            hc1, hc2 = st.columns(2)
            with hc1:
                if st.button(t("commit_approve_btn"), type="primary", use_container_width=True):
                    try:
                        commit_decision(
                            request_text=eval_data.get("summary", ""),
                            supplier=eval_data.get("supplier_name", "Unbekannt"),
                            amount=float(eval_data.get("amount", 0.0)),
                            category=eval_data.get("category", "IT-Ausstattung"),
                            decision="APPROVED",
                            reasoning=str(reasoning),
                        )
                    except Exception as e:
                        st.error(t("commit_error").format(error=e))
                    else:
                        st.session_state["committed"] = True
                        st.session_state["committed_decision"] = "APPROVED"
                        try:
                            pdf_bytes = generate_anmeldebogen_pdf(eval_data)
                            st.session_state["approved_pdf"] = pdf_bytes
                            st.session_state["approved_pdf_name"] = (
                                f"Anmeldebogen_{eval_data.get('procurement_type', 'LuD')}_"
                                f"{datetime.now().strftime('%Y%m%d')}.pdf"
                            )
                            st.session_state.pop("pdf_error", None)
                        except Exception as e:
                            st.session_state["approved_pdf"] = None
                            st.session_state["pdf_error"] = str(e)
                        st.rerun()
            with hc2:
                if st.button(t("commit_reject_btn"), use_container_width=True):
                    try:
                        commit_decision(
                            request_text=eval_data.get("summary", ""),
                            supplier=eval_data.get("supplier_name", "Unbekannt"),
                            amount=float(eval_data.get("amount", 0.0)),
                            category=eval_data.get("category", "IT-Ausstattung"),
                            decision="REJECTED",
                            reasoning=str(reasoning),
                        )
                    except Exception as e:
                        st.error(t("commit_error").format(error=e))
                    else:
                        st.session_state["committed"] = True
                        st.session_state["committed_decision"] = "REJECTED"
                        st.session_state["approved_pdf"] = None
                        st.session_state["approved_pdf_name"] = None
                        st.session_state.pop("pdf_error", None)
                        st.rerun()
        else:
            if st.session_state.get("committed_decision") == "APPROVED":
                st.success(t("committed_success"))

                if st.session_state.get("pdf_error"):
                    st.error(f"{t('pdf_error')} {st.session_state['pdf_error']}")

                pdf_bytes = st.session_state.get("approved_pdf")
                if pdf_bytes:
                    st.subheader(t("form_header"))
                    st.caption(t("form_note"))
                    st.download_button(
                        label=t("download_form_btn"),
                        data=pdf_bytes,
                        file_name=st.session_state.get("approved_pdf_name") or "Anmeldebogen.pdf",
                        mime="application/pdf",
                        type="primary",
                        use_container_width=True,
                    )
            else:
                st.warning(t("committed_reject"))

        st.divider()
        st.button(t("next_request_btn"), use_container_width=True, on_click=clear_form)


# Bid evaluation matrix tab
with tab_matrix:
    st.subheader(t("matrix_header"))
    st.caption(t("matrix_desc"))

    st.file_uploader(
        t("matrix_pdfs_label"),
        type=["pdf"],
        accept_multiple_files=True,
        help=t("matrix_pdfs_help"),
    )

    st.markdown(f"#### {t('bidder_config_header')}")

    col_b1, col_b2, col_b3 = st.columns(3)
    with col_b1:
        bid1_name = st.text_input(t("bidder_1"), "Dell Technologies")
        bid1_price = st.number_input(t("price_label"), value=14500.0, key="b1_price")
        bid1_ref = st.slider(t("references_label"), 0, 10, 8, key="b1_ref")
        bid1_con = st.slider(t("concept_label"), 0, 10, 8, key="b1_con")
    with col_b2:
        bid2_name = st.text_input(t("bidder_2"), "Bechtle GmbH")
        bid2_price = st.number_input(t("price_label"), value=15200.0, key="b2_price")
        bid2_ref = st.slider(t("references_label"), 0, 10, 7, key="b2_ref")
        bid2_con = st.slider(t("concept_label"), 0, 10, 7, key="b2_con")
    with col_b3:
        bid3_name = st.text_input(t("bidder_3"), "OfficeDepot Deutschland")
        bid3_price = st.number_input(t("price_label"), value=16200.0, key="b3_price")
        bid3_ref = st.slider(t("references_label"), 0, 10, 6, key="b3_ref")
        bid3_con = st.slider(t("concept_label"), 0, 10, 6, key="b3_con")

    if st.button(t("eval_bids_btn"), type="primary", use_container_width=True):
        bids_input = [
            {"bidder": bid1_name, "price": bid1_price, "references_score": bid1_ref, "concept_score": bid1_con},
            {"bidder": bid2_name, "price": bid2_price, "references_score": bid2_ref, "concept_score": bid2_con},
            {"bidder": bid3_name, "price": bid3_price, "references_score": bid3_ref, "concept_score": bid3_con},
        ]

        invalid_bidders = [b["bidder"] for b in bids_input if b["price"] <= 0]
        if invalid_bidders:
            st.session_state.pop("matrix_result", None)
            st.error(t("invalid_price_error").format(bidders=", ".join(invalid_bidders)))
        else:
            with st.spinner(t("spinner_bids")):
                try:
                    eval_matrix_res = evaluate_bids(bids_input)
                except ValueError as e:
                    st.session_state.pop("matrix_result", None)
                    st.error(str(e))
                else:
                    st.session_state["matrix_result"] = eval_matrix_res

    if st.session_state.get("matrix_result"):
        res = st.session_state["matrix_result"]
        winner = res["winner"]
        ranked = res["ranked_bids"]
        losers = res["losers"]

        st.divider()
        st.markdown(f"### {t('matrix_winner_header')} **{winner['bidder']}**")
        st.success(
            t("matrix_winner_success").format(
                points=winner["total_points"],
                price=f"€{winner['price']:,.2f}",
            )
        )

        st.markdown(f"#### {t('matrix_ranking_header')}")
        df_ranked = pd.DataFrame(ranked)
        st.dataframe(df_ranked, width="stretch", hide_index=True)

        st.divider()
        st.markdown(f"### {t('matrix_rejections_header')}")
        st.caption(t("matrix_rejections_desc"))

        with st.expander(t("matrix_rejections_expander"), expanded=True):
            for loser in losers:
                st.markdown(
                    f"#### "
                    + t("matrix_rejection_title").format(
                        bidder=loser["bidder"],
                        price=f"€{loser['price']:,.2f}",
                        points=loser["total_points"],
                    )
                )
                st.info(loser.get("legal_justification", t("matrix_no_reason")))
                st.divider()
