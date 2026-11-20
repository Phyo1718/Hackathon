import os
import sqlite3
from datetime import datetime
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from fpdf import FPDF

load_dotenv()

DB_PATH = os.path.join(os.path.dirname(__file__), "../data/mock_data.db")


class MissingApiKeyError(RuntimeError):
    """Raised when neither GEMINI_API_KEY nor GOOGLE_API_KEY is configured."""


class ExtractionError(RuntimeError):
    """Raised when Gemini cannot extract a valid procurement request."""


def has_api_key() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))


def get_genai_client() -> genai.Client:
    """Shared Gemini client factory. Fails fast, before any network call, if no key is set."""
    if not has_api_key():
        raise MissingApiKeyError(
            "No Gemini API key configured. Create a .env file with GEMINI_API_KEY=<your key> "
            "(see .env.example) or set GEMINI_API_KEY / GOOGLE_API_KEY in the environment."
        )
    return genai.Client(http_options=types.HttpOptions(timeout=120000))


class ExtractedRequest(BaseModel):
    supplier_name: str = Field(description="Name of the supplier or vendor mentioned in the procurement request.")
    amount: float = Field(description="Total monetary amount requested in Euros (€).")
    category: str = Field(description="Procurement category, must be one of: IT-Ausstattung, Büromaterial, Fahrzeuge.")
    summary: str = Field(description="Brief 1-sentence summary of the procurement request.")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def check_supplier(supplier_name: str) -> Dict[str, Any]:
    """Verifies whether the supplier exists and is approved in the database with fuzzy substring matching."""
    if not supplier_name:
        return {
            "supplier_name": supplier_name,
            "exists": False,
            "is_approved": False,
            "category": None
        }
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Try exact lookup first
    cursor.execute("SELECT * FROM Suppliers WHERE LOWER(Name) = LOWER(?);", (supplier_name.strip(),))
    row = cursor.fetchone()
    
    # 2. If not found, fetch all suppliers and do fuzzy substring matching
    if not row:
        cursor.execute("SELECT * FROM Suppliers;")
        all_suppliers = cursor.fetchall()
        clean_input = supplier_name.strip().lower()
        
        for s in all_suppliers:
            s_name = s["Name"].lower()
            if s_name in clean_input or clean_input in s_name:
                row = s
                break
                
    conn.close()
    
    if not row:
        return {
            "supplier_name": supplier_name,
            "exists": False,
            "is_approved": False,
            "category": None
        }
    
    return {
        "supplier_name": row["Name"],
        "exists": True,
        "is_approved": bool(row["Is_Approved"]),
        "category": row["Category"]
    }

def check_contract_extension(supplier_name: str) -> bool:
    """Checks Audit_Logs to determine if the supplier already has an APPROVED request in history.

    The comparison is deliberately tolerant so that short names extracted by the AI
    (e.g. "Dell") still match their canonical database entry ("Dell Technologies").
    """
    if not supplier_name or not supplier_name.strip():
        return False

    normalised = supplier_name.strip().lower()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) AS cnt
            FROM Audit_Logs
            WHERE UPPER(Decision) = 'APPROVED'
              AND (
                    LOWER(TRIM(Supplier)) = ?
                 OR LOWER(TRIM(Supplier)) LIKE ?
                 OR ? LIKE '%' || LOWER(TRIM(Supplier)) || '%'
              );
        """, (normalised, f"%{normalised}%", normalised))
        row = cursor.fetchone()
        return bool(row and row["cnt"] > 0)
    finally:
        conn.close()

def check_budget(request_amount: float, category: str) -> Dict[str, Any]:
    """Returns remaining budget, sufficiency status, and borderline 5% tolerance check."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM Budgets WHERE LOWER(Category) = LOWER(?);", (category.strip(),))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return {
            "category": category,
            "konto": "",
            "total_budget": 0.0,
            "remaining_budget": 0.0,
            "sufficient": False,
            "borderline": False,
            "error": "Category not found in budget database"
        }
    
    total_budget = float(row["Total_Budget"])
    remaining_budget = float(row["Remaining_Budget"])
    konto = row["Konto"] if "Konto" in row.keys() else ""
    sufficient = remaining_budget >= request_amount
    
    borderline = False
    if not sufficient and remaining_budget > 0:
        overage = request_amount - remaining_budget
        tolerance = remaining_budget * 0.05
        if overage <= tolerance:
            borderline = True

    return {
        "category": row["Category"],
        "konto": konto,
        "total_budget": total_budget,
        "remaining_budget": remaining_budget,
        "sufficient": sufficient,
        "borderline": borderline
    }

def commit_decision(request_text: str, supplier: str, amount: float, category: str, decision: str, reasoning: str) -> None:
    """Deduct request_amount from Remaining_Budget (if approved) and write an audit log entry."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    timestamp = datetime.now().isoformat(timespec='seconds')
    
    if decision.upper() == "APPROVED":
        cursor.execute("""
            UPDATE Budgets 
            SET Remaining_Budget = Remaining_Budget - ? 
            WHERE LOWER(Category) = LOWER(?);
        """, (amount, category))
    
    cursor.execute("""
        INSERT INTO Audit_Logs (Timestamp, Request_Text, Supplier, Amount, Category, Decision, Reasoning)
        VALUES (?, ?, ?, ?, ?, ?, ?);
    """, (timestamp, request_text, supplier, amount, category, decision.upper(), reasoning))
    
    conn.commit()
    conn.close()

def _pdf_safe(value: Any) -> str:
    """Normalises text for the PDF core fonts (Latin-1) so generation never crashes."""
    text = str(value if value is not None else "")
    replacements = {
        "€": "EUR",
        "–": "-",
        "—": "-",
        "„": '"',
        "“": '"',
        "”": '"',
        "‚": "'",
        "‘": "'",
        "’": "'",
        "\u00a0": " ",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text.encode("latin-1", "replace").decode("latin-1")


def _format_eur(amount: float) -> str:
    formatted = f"{float(amount):,.2f}"
    return "EUR " + formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def generate_anmeldebogen_pdf(eval_data: Dict[str, Any]) -> bytes:
    """Generates a real, printable Anmeldebogen PDF using fpdf2."""
    proc_type = eval_data.get("procurement_type", "LuD")
    supplier = eval_data.get("supplier_name", "Unbekannt")
    amount = float(eval_data.get("amount", 0.0) or 0.0)
    category = eval_data.get("category", "IT-Ausstattung")
    konto = eval_data.get("konto", "")
    summary = eval_data.get("summary", "")

    is_extension = proc_type == "Auftragserweiterung"
    title_text = (
        "Anmeldung einer Auftragserweiterung"
        if is_extension
        else "Anmeldung einer Vergabe (Lieferung und Dienstleistung)"
    )

    pdf = FPDF()
    pdf.set_margins(18, 18, 18)
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=18)

    # Municipal letterhead
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 9, _pdf_safe("STADT HILDESHEIM"), new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(
        0, 5,
        _pdf_safe("Zentrale Vergabestelle - Öffentliches Auftragswesen"),
        new_x="LMARGIN", new_y="NEXT", align="C",
    )
    pdf.cell(
        0, 5,
        _pdf_safe("Markt 1 - 31134 Hildesheim"),
        new_x="LMARGIN", new_y="NEXT", align="C",
    )
    pdf.ln(4)

    pdf.set_draw_color(30, 58, 95)
    pdf.set_line_width(0.6)
    pdf.line(18, pdf.get_y(), 192, pdf.get_y())
    pdf.ln(8)

    # Document title and reference
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, _pdf_safe(title_text), new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", "", 9)
    reference = f"VA-{datetime.now().strftime('%Y')}-{datetime.now().strftime('%m%d-%H%M')}"
    pdf.cell(
        0, 6,
        _pdf_safe(f"Datum: {datetime.now().strftime('%d.%m.%Y')}  |  Vergabenummer: {reference}"),
        new_x="LMARGIN", new_y="NEXT", align="C",
    )
    pdf.ln(8)

    def section(heading: str, content: str) -> None:
        pdf.set_font("Helvetica", "B", 10)
        pdf.multi_cell(0, 6, _pdf_safe(heading), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 6, _pdf_safe(content), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

    section("1. Bezeichnung der Maßnahme", summary or "Keine Beschreibung angegeben.")
    konto_line = f"Produktbereich: {category}"
    if konto:
        konto_line += f"  |  Haushaltskonto: {konto}"
    section("2. Art der Leistung und Produktbereich", konto_line)
    section("3. Geschätzter Auftragswert (brutto)", _format_eur(amount))

    if is_extension:
        section(
            "4. Grundlage der Auftragserweiterung",
            "Es wird auf einen bereits freigegebenen Auftrag zurückgegriffen. "
            "Die frühere Freigabe ist im Audit-Protokoll der Stadt Hildesheim dokumentiert.",
        )
        section(
            "5. Begründung der Wirtschaftlichkeit",
            "Die Konditionen des Ursprungsauftrags werden fortgeführt. Eine erneute "
            "Markterkundung ist aus wirtschaftlichen Gründen nicht erforderlich.",
        )
    else:
        section(
            "4. Verfahrensart",
            "Direktvergabe beziehungsweise beschränkte Ausschreibung nach UVgO. "
            "Die vergaberechtlichen Voraussetzungen wurden geprüft.",
        )
        section(
            "5. Vergaberechtliche Prüfung",
            "Der Auftragnehmer ist im zugelassenen Lieferantenverzeichnis registriert. "
            "Die Haushaltsmittel stehen zur Verfügung.",
        )

    section("6. Auftragnehmer / Lieferant", supplier)

    pdf.ln(6)
    pdf.set_font("Helvetica", "B", 10)
    pdf.multi_cell(
        0, 6,
        _pdf_safe("7. Prüfung und Freigabe durch die Sachbearbeitung"),
        new_x="LMARGIN", new_y="NEXT",
    )
    pdf.set_font("Helvetica", "", 9)
    pdf.multi_cell(
        0, 6,
        _pdf_safe(
            "Status: Freigegeben und im Haushalt verbucht. "
            "Der Vorgang wurde im Audit-Protokoll der Stadt Hildesheim erfasst."
        ),
        new_x="LMARGIN", new_y="NEXT",
    )
    pdf.ln(12)
    pdf.cell(0, 6, _pdf_safe("Ort, Datum: Hildesheim, " + datetime.now().strftime('%d.%m.%Y')), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(10)
    pdf.cell(0, 6, _pdf_safe("Unterschrift Sachbearbeitung: ______________________________"), new_x="LMARGIN", new_y="NEXT")

    return bytes(pdf.output())

def calculate_price_score(price: float, lowest_price: float) -> float:
    """Price points (0-10) via the interpolation of docs/Auswertung_Hackathon.XLSX, sheet "Übersicht"."""
    if price <= 0 or lowest_price <= 0:
        raise ValueError(f"Bid prices must be greater than 0 (got price={price}, lowest={lowest_price}).")
    # Excel: E7 = 10 points for the lowest bid, D9 = 2 * D7 (fictitious bid with 0 points),
    # E8 = (E7 / D7) * (D9 - D8). Clamped so bids at or above 2 x lowest get 0, never negative.
    points = (10.0 / lowest_price) * (2 * lowest_price - price)
    return max(0.0, min(10.0, points))


def evaluate_bids(bids_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Evaluates multiple bids using the 30/30/20 scoring matrix and generates § 13 UVgO legal rejections."""
    if not bids_data:
        return {"error": "No bids provided"}

    for b in bids_data:
        if float(b["price"]) <= 0:
            raise ValueError(f"Bid price for '{b['bidder']}' must be greater than 0 (got {b['price']}).")

    min_price = min(float(b["price"]) for b in bids_data)

    evaluated_bids = []
    for b in bids_data:
        price = float(b["price"])
        ref_score = float(b.get("references_score", 5))
        concept_score = float(b.get("concept_score", 5))

        price_score = calculate_price_score(price, min_price)
        price_pts = price_score * 30.0
        ref_pts = ref_score * 30.0
        concept_pts = concept_score * 20.0
        total_pts = price_pts + ref_pts + concept_pts

        evaluated_bids.append({
            "bidder": b["bidder"],
            "price": price,
            "price_score": round(price_score, 2),
            "references_score": ref_score,
            "concept_score": concept_score,
            "price_points": round(price_pts, 2),
            "reference_points": round(ref_pts, 2),
            "concept_points": round(concept_pts, 2),
            "total_points": round(total_pts, 2)
        })
    
    evaluated_bids.sort(key=lambda x: x["total_points"], reverse=True)
    winner = evaluated_bids[0]
    losers = evaluated_bids[1:]
    
    client = genai.Client(http_options=types.HttpOptions(timeout=120000))
    
    for loser in losers:
        prompt = f"""
        You are a public procurement specialist for the City of Hildesheim under German procurement law (UVgO / GWB).
        Generate a formal, legally binding rejection letter paragraph (Begründung nach § 13 UVgO) explaining why Bidder '{loser['bidder']}' (Price: €{loser['price']:,.2f}, Total Score: {loser['total_points']} points) was not selected, and why the winning bidder '{winner['bidder']}' (Price: €{winner['price']:,.2f}, Total Score: {winner['total_points']} points) won based on price (30%), references (30%), and concept (20%).
        Write in professional German.
        """
        try:
            resp = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.2)
            )
            loser["legal_justification"] = resp.text.strip()
        except Exception:
            loser["legal_justification"] = f"Gemäß § 13 UVgO wird Ihr Angebot nicht berücksichtigt, da Ihr Gesamtscore von {loser['total_points']} Punkten unter dem des ausgewählten Bieters {winner['bidder']} ({winner['total_points']} Punkte) liegt."
            
    return {
        "winner": winner,
        "ranked_bids": evaluated_bids,
        "losers": losers
    }

def evaluate_request(text: str) -> Dict[str, Any]:
    """Extracts parameters, verifies supplier and audit history, checks budget, and returns decision.

    Raises MissingApiKeyError if no API key is set and ExtractionError if Gemini fails.
    There is deliberately no offline fallback: without Gemini there is no decision.
    """
    client = get_genai_client()
    
    prompt = f"""
    Analyze the following public procurement request text and extract the required fields:
    - supplier_name
    - amount (numeric value in Euros)
    - category (IT-Ausstattung, Büromaterial, or Fahrzeuge)
    - summary (1-sentence summary)
    
    Request Text:
    """ + text
    
    models_to_try = ["gemini-3.5-flash-lite", "gemini-3.8-flash"]
    response = None
    last_exception = None
    
    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ExtractedRequest,
                    temperature=0.1
                ),
            )
            break
        except Exception as e:
            last_exception = e
            continue
            
    if response is None:
        raise ExtractionError(
            f"Gemini extraction failed for all models ({', '.join(models_to_try)}): {last_exception}"
        ) from last_exception

    try:
        extracted = ExtractedRequest.model_validate_json(response.text)
    except Exception as e:
        raise ExtractionError(f"Gemini response did not match the expected schema: {e}") from e
    
    # Run deterministic tool checks
    supplier_res = check_supplier(extracted.supplier_name)
    budget_res = check_budget(extracted.amount, extracted.category)
    
    # Check contract extension history in Audit_Logs
    is_extension = check_contract_extension(supplier_res["supplier_name"] if supplier_res["exists"] else extracted.supplier_name)
    procurement_type = "Auftragserweiterung" if is_extension else "LuD"
    
    # Decision logic & Reasoning steps
    reasoning_steps = []
    reasoning_steps.append(f"1. **Extraction:** Extracted Supplier: **{extracted.supplier_name}**, Amount: **€{extracted.amount:,.2f}**, Category: **{extracted.category}**.")
    reasoning_steps.append(f"2. **Procurement Type Detection:** Queried the `Audit_Logs` table for previous approved contracts with '{extracted.supplier_name}': {'Found an approved contract -> Classified as **Auftragserweiterung**.' if is_extension else 'No previous approved contract found -> Classified as new **LuD** (Lieferungen und Dienstleistungen).'}")
    
    decision = "APPROVED"
    
    # Supplier validation
    if not supplier_res["exists"]:
        supplier_status = "Not found in approved supplier database."
        decision = "REJECTED"
    elif not supplier_res["is_approved"]:
        supplier_status = "Found in database, but flagged as UNAPPROVED."
        decision = "REJECTED"
    else:
        supplier_status = "Found and APPROVED in supplier database."
    
    reasoning_steps.append(f"3. **Supplier Verification:** Checked supplier '{extracted.supplier_name}': {supplier_status}")
    
    # Budget validation
    if decision == "REJECTED":
        reasoning_steps.append(f"4. **Budget Check:** Skipped due to supplier rejection.")
        reasoning_steps.append(f"5. **Final Decision:** **REJECTED**. Reason: Supplier is either unapproved or unknown.")
    else:
        if "error" in budget_res:
            decision = "REJECTED"
            reasoning_steps.append(f"4. **Budget Check:** Category '{extracted.category}' not found in budget database.")
            reasoning_steps.append(f"5. **Final Decision:** **REJECTED**. Reason: Invalid budget category.")
        else:
            rem_bud = budget_res["remaining_budget"]
            reasoning_steps.append(f"4. **Budget Check:** Category '{extracted.category}' has €{rem_bud:,.2f} remaining budget. Requested: €{extracted.amount:,.2f}.")
            
            if budget_res["sufficient"]:
                decision = "APPROVED"
                reasoning_steps.append(f"5. **Final Decision:** **APPROVED**. Reason: Supplier is approved and requested amount is fully covered by remaining budget.")
            elif budget_res["borderline"]:
                decision = "REQUIRES_REVIEW"
                reasoning_steps.append(f"5. **Final Decision:** **REQUIRES_REVIEW**. Reason: Supplier is approved, but requested amount exceeds remaining budget by ≤5% (borderline overage requiring caseworker sign-off).")
            else:
                decision = "REJECTED"
                reasoning_steps.append(f"5. **Final Decision:** **REJECTED**. Reason: Requested amount exceeds remaining budget by >5%.")

    full_reasoning = "\n\n".join(reasoning_steps)
    
    return {
        "supplier_name": supplier_res["supplier_name"] if supplier_res["exists"] else extracted.supplier_name,
        "amount": extracted.amount,
        "category": extracted.category,
        "konto": budget_res.get("konto", ""),
        "summary": extracted.summary,
        "procurement_type": procurement_type,
        "is_extension": is_extension,
        "supplier_check": supplier_res,
        "budget_check": budget_res,
        "decision": decision,
        "reasoning": full_reasoning
    }
