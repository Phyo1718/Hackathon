import math
import os
import sqlite3
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from fpdf import FPDF

from src.init_db import get_db_path

load_dotenv()


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
    conn = sqlite3.connect(get_db_path())
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

def get_prior_contracts(supplier_name: str) -> List[Dict[str, Any]]:
    """Returns the supplier's APPROVED requests from Audit_Logs, oldest first.

    The comparison is deliberately tolerant so that short names extracted by the AI
    (e.g. "Dell") still match their canonical database entry ("Dell Technologies").
    """
    if not supplier_name or not supplier_name.strip():
        return []

    normalised = supplier_name.strip().lower()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT Timestamp, Request_Text, Amount
            FROM Audit_Logs
            WHERE UPPER(Decision) = 'APPROVED'
              AND (
                    LOWER(TRIM(Supplier)) = ?
                 OR LOWER(TRIM(Supplier)) LIKE ?
                 OR ? LIKE '%' || LOWER(TRIM(Supplier)) || '%'
              )
            ORDER BY Timestamp;
        """, (normalised, f"%{normalised}%", normalised))
        return [
            {"timestamp": row["Timestamp"], "request_text": row["Request_Text"], "amount": float(row["Amount"])}
            for row in cursor.fetchall()
        ]
    finally:
        conn.close()

def check_contract_extension(supplier_name: str) -> bool:
    """Checks Audit_Logs to determine if the supplier already has an APPROVED request in history."""
    return bool(get_prior_contracts(supplier_name))

ACCESSIBILITY_WARNING = (
    "WARNING: This department has employees with special needs. "
    "Ensure procured items (like desks/chairs) are ergonomic and accessible."
)

def check_accessibility(department: str) -> Dict[str, Any]:
    """Looks up the department in the Employees table and flags staff with special needs.

    The warning is advisory: it is added to the reasoning and the Anmeldebogen but does
    not change the procurement decision.
    """
    result = {
        "department": department,
        "found": False,
        "total_employees": 0,
        "employees_with_special_needs": 0,
        "warning": None,
    }
    if not department or not department.strip():
        return result

    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT * FROM Employees WHERE LOWER(Department) = LOWER(?);", (department.strip(),)
        ).fetchone()
    except sqlite3.OperationalError:
        # Database created before the Employees table existed
        row = None
    finally:
        conn.close()

    if not row:
        return result

    special_needs = int(row["Employees_With_Special_Needs"])
    result.update(
        department=row["Department"],
        found=True,
        total_employees=int(row["Total_Employees"]),
        employees_with_special_needs=special_needs,
        warning=ACCESSIBILITY_WARNING if special_needs > 0 else None,
    )
    return result

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

def get_approved_spending() -> List[Dict[str, Any]]:
    """Approved orders from the audit log (date, budget line, supplier, amount); no transfers."""
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT Timestamp, Category, Supplier, Amount FROM Audit_Logs WHERE UPPER(Decision) = 'APPROVED';"
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "timestamp": datetime.fromisoformat(row["Timestamp"]),
            "category": row["Category"],
            "supplier": row["Supplier"],
            "amount": float(row["Amount"]),
        }
        for row in rows
    ]


def get_budget_lines() -> List[Dict[str, Any]]:
    """All budget lines with Produkt, Konto, Auszahlungskonto, account type and department."""
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT * FROM Budgets ORDER BY Category;").fetchall()
    finally:
        conn.close()
    return [
        {
            "category": row["Category"],
            "konto": row["Konto"],
            "total": float(row["Total_Budget"]),
            "remaining": float(row["Remaining_Budget"]),
            "produkt": row["Produkt"],
            "auszahlungskonto": row["Auszahlungskonto"],
            "account_type": row["Account_Type"],
            "department": row["Department"],
        }
        for row in rows
    ]


def suggest_budget_transfers(category: str, shortfall: float, limit: int = 3) -> List[Dict[str, Any]]:
    """Donor lines that can cover a shortfall on `category`: the agent's recommendation only.

    Lines with free funds >= shortfall qualify. Ranked same account type (Aufwand/Investiv)
    first, then by free funds. A same-type transfer is a Mittelverschiebung within the cover
    rules (§ 19 KomHKVO); otherwise approval of over-plan spending is needed (§ 117 NKomVG).
    """
    lines = {line["category"]: line for line in get_budget_lines()}
    need = lines.get(category)
    if need is None or shortfall <= 0:
        return []
    options = []
    for line in lines.values():
        if line["category"] == category or line["remaining"] < shortfall:
            continue
        same_type = line["account_type"] == need["account_type"]
        options.append(
            {
                **line,
                "same_type": same_type,
                "legal_basis": "§ 19 KomHKVO" if same_type else "§ 117 NKomVG",
                "spare_after": line["remaining"] - shortfall,
            }
        )
    options.sort(key=lambda option: (not option["same_type"], -option["remaining"]))
    return options[:limit]


def draft_transfer_justification(
    need: Dict[str, Any], donor: Dict[str, Any], amount: float, measure: str, reference: str
) -> str:
    """German draft of the Begründung for the Antrag auf Mittelverschiebung."""
    text = (
        f"Für die Maßnahme \"{measure}\" ({reference}) reichen die Mittel der Haushaltsposition "
        f"{need['category']} (Produkt {need['produkt']}, Konto {need['konto']}) nicht aus; es verbleiben "
        f"{_format_eur(need['remaining'])}, der Mehrbedarf beträgt {_format_eur(amount)}. "
        f"Die Deckung erfolgt aus der Haushaltsposition {donor['category']} (Produkt {donor['produkt']}, "
        f"Konto {donor['konto']}, {donor['department']}), die nach der Verschiebung noch "
        f"{_format_eur(donor['remaining'] - amount)} frei hat. "
    )
    if donor["account_type"] == need["account_type"]:
        text += (
            f"Beide Positionen sind {need['account_type']}skonten; die Verschiebung erfolgt im Rahmen "
            "der Deckungsfähigkeit gem. § 19 KomHKVO."
        )
    else:
        text += (
            f"Die Positionen haben unterschiedliche Kontenarten ({donor['account_type']} / {need['account_type']}); "
            "beantragt wird die Zustimmung zu überplanmäßigen Aufwendungen/Auszahlungen gem. § 117 NKomVG."
        )
    return text


def _validate_transfer(source: str, target: str, amount: float) -> None:
    if amount <= 0:
        raise ValueError("The transfer amount must be greater than 0.")
    if source == target:
        raise ValueError("Source and target budget line must differ.")
    lines = {line["category"]: line for line in get_budget_lines()}
    if source not in lines or target not in lines:
        raise ValueError(f"Unknown budget line: {source if source not in lines else target}.")
    if lines[source]["remaining"] < amount:
        raise ValueError(
            f"Budget line '{source}' has only {_format_eur(lines[source]['remaining'])} free, "
            f"{_format_eur(amount)} cannot be transferred."
        )


def _apply_transfer(conn, source: str, target: str, amount: float, reference: str, justification: str) -> None:
    """Moves planned and remaining funds from source to target and logs it (caller commits)."""
    conn.execute(
        "UPDATE Budgets SET Total_Budget = Total_Budget - ?, Remaining_Budget = Remaining_Budget - ? WHERE Category = ?;",
        (amount, amount, source),
    )
    conn.execute(
        "UPDATE Budgets SET Total_Budget = Total_Budget + ?, Remaining_Budget = Remaining_Budget + ? WHERE Category = ?;",
        (amount, amount, target),
    )
    conn.execute(
        """INSERT INTO Audit_Logs (Timestamp, Request_Text, Supplier, Amount, Category, Decision, Reasoning)
           VALUES (?, ?, ?, ?, ?, ?, ?);""",
        (
            datetime.now().isoformat(timespec="seconds"),
            f"{reference}: Mittelverschiebung von {source} nach {target}",
            "Mittelverschiebung",
            amount,
            target,
            "TRANSFER",
            justification,
        ),
    )


def commit_budget_transfer(source: str, target: str, amount: float, reference: str, justification: str) -> None:
    """Books a stand-alone transfer: the donor line goes down, the requesting line goes up
    (planned and remaining funds), and the transfer is written to the audit log."""
    amount = float(amount)
    _validate_transfer(source, target, amount)
    conn = get_db_connection()
    try:
        with conn:
            _apply_transfer(conn, source, target, amount, reference, justification)
    finally:
        conn.close()


DRAFT_WATERMARK = "Entwurf – Prüfung und Unterschrift durch Sachbearbeitung"


class _DraftPDF(FPDF):
    """Draws the draft watermark first on every page, so it stays behind the content."""

    def header(self) -> None:
        self.set_text_color(210, 210, 210)
        self.set_font("Helvetica", "B", 22)
        with self.rotation(35, x=105, y=150):
            self.set_xy(5, 145)
            self.cell(200, 10, _pdf_safe(DRAFT_WATERMARK), align="C")
        self.set_text_color(0, 0, 0)
        self.set_xy(self.l_margin, self.t_margin)


def generate_deckungsantrag_pdf(
    need: Dict[str, Any], donor: Dict[str, Any], amount: float, measure: str, reference: str, justification: str
) -> bytes:
    """Pre-filled replica of docs/Antrag_ED_Hackathon.pdf, watermarked as a draft for review."""
    same_type = donor["account_type"] == need["account_type"]
    today = datetime.now()
    pdf = _DraftPDF(format="A4")
    pdf.set_margins(20, 16, 20)
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()
    left, width, line_h = pdf.l_margin, pdf.epw, 4.6

    def write(value: str, x_offset: float = 0, style: str = "", size: float = 10, w: float = 0) -> None:
        pdf.set_font("Helvetica", style, size)
        pdf.set_x(left + x_offset)
        pdf.multi_cell(w or width - x_offset, line_h, _pdf_safe(value), new_x="LMARGIN", new_y="NEXT")

    def field_row(label: str, value: str, suffix: str = "") -> None:
        y = pdf.get_y()
        pdf.set_font("Helvetica", "", 10)
        pdf.set_xy(left, y)
        pdf.cell(62, line_h, _pdf_safe(label))
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(48, line_h, _pdf_safe(value))
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, line_h, _pdf_safe(suffix), new_x="LMARGIN", new_y="NEXT")

    def checkbox(label: str, checked: bool) -> None:
        y = pdf.get_y()
        pdf.set_line_width(0.3)
        pdf.rect(left, y + 0.8, 3.5, 3.5)
        if checked:
            pdf.line(left, y + 0.8, left + 3.5, y + 4.3)
            pdf.line(left, y + 4.3, left + 3.5, y + 0.8)
        pdf.set_xy(left + 12, y)
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(width - 12, line_h, _pdf_safe(label), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

    def line_block(line: Optional[Dict[str, Any]], kind: str, connector: str) -> None:
        """One Produkt/Konto block of the Bedarf or Deckung section; empty if line is None."""
        konto_label = "Aufwands- bzw. Bestandskonto" if kind == "need" else "Aufwand-, Bestands-, Ertragskonto"
        zahl_label = "Auszahlungskonto" if kind == "need" else "Aus- / Einzahlungskonto"
        mass_label = "( für die Investitionsmaßnahme" if kind == "need" else "(aus der Investitionsmaßnahme"
        field_row("Produkt", line["produkt"] if line else "", "auf dem" if kind == "need" else "aus dem")
        field_row(konto_label, line["konto"] if line else "", ", sowie dem dazugehörigen")
        field_row(zahl_label, line["auszahlungskonto"] if line else "")
        field_row(mass_label, "", "Position")
        field_row("Bezeichnung der Maßnahme:", "", ")")
        field_row("in Höhe von", _format_eur(amount) if line else "", connector)
        pdf.ln(2)

    # Header box: Von / Bearbeiter/in / Telefon / Az. / Datum, then An
    pdf.set_line_width(0.3)
    top = pdf.get_y()
    pdf.rect(left, top, width, 18)
    pdf.line(left, top + 11, left + width, top + 11)
    columns = [("Von", 0), ("Bearbeiter/in", 30), ("Tel.", 82), ("Az.", 112), ("Datum", 142)]
    pdf.set_font("Helvetica", "", 9)
    for label, x in columns:
        pdf.set_xy(left + 1.5 + x, top + 0.8)
        pdf.cell(28, 4.5, _pdf_safe(label))
    pdf.set_font("Helvetica", "B", 9)
    for value, x in ((need["department"], 0), (reference, 112), (today.strftime("%d.%m.%Y"), 142)):
        pdf.set_xy(left + 1.5 + x, top + 5.5)
        pdf.cell(28 if x else 29, 4.5, _pdf_safe(value))
    pdf.set_font("Helvetica", "", 9)
    pdf.set_xy(left + 1.5, top + 12.3)
    pdf.cell(20, 4.5, "An")
    pdf.set_y(top + 22)

    checkbox(
        "Antrag auf Zustimmung zu über- / außerplanmäßigen Aufwendungen / Auszahlungen gem. §117 NKomVG",
        checked=not same_type,
    )
    checkbox(
        "Antrag auf Mittelverschiebung im Rahmen der Deckungsfähigkeit gem. §19 KomHKVO (echte "
        "Deckungsfähigkeit) innerhalb eines Budgets oder aufgrund Deckungsfähigkeit per Haushaltsvermerk",
        checked=same_type,
    )
    pdf.set_x(left + 12)
    field_row("            für das Haushaltsjahr:", str(today.year))
    pdf.ln(2)

    write("Bedarf:", style="BU")
    write("Es werden Mittel in dem")
    line_block(need, "need", "und in dem")
    line_block(None, "need", "benötigt.")

    write("Deckung:", style="BU")
    write("Die Deckung soll aus")
    line_block(donor, "donor", "und aus")
    line_block(None, "donor", "erfolgen.")

    write("Begründung:", style="BU")
    write(justification, size=9)
    pdf.ln(10)
    write("_______________________")
    write("Unterschrift", x_offset=8)
    return bytes(pdf.output())


APPROVAL_ISSUE_LABELS_DE = {
    "supplier_unknown": "Lieferant nicht im Lieferantenverzeichnis registriert",
    "supplier_not_approved": "Lieferant nicht zugelassen",
    "budget_unknown": "Haushaltsposition nicht gefunden",
    "budget_exceeded": "Budget um mehr als 5 % überschritten",
}


def approval_issues(
    supplier_check: Dict[str, Any], budget_check: Dict[str, Any], amount: float, transfer_amount: float = 0.0
) -> List[str]:
    """Failed checks for an approval, after any budget transfer included with it.

    Approving despite one of these goes against the agent's recommendation and needs a
    caseworker justification. A borderline overage (at most 5 %) is not a failed check: the
    agent leaves that decision to the caseworker.
    """
    issues = []
    if not supplier_check.get("exists"):
        issues.append("supplier_unknown")
    elif not supplier_check.get("is_approved"):
        issues.append("supplier_not_approved")
    if budget_check.get("error") or "remaining_budget" not in budget_check:
        issues.append("budget_unknown")
    else:
        available = float(budget_check["remaining_budget"]) + float(transfer_amount or 0.0)
        overage = float(amount) - available
        if overage > 0 and not (available > 0 and overage <= available * 0.05):
            issues.append("budget_exceeded")
    return issues


def commit_decision(
    request_text: str,
    supplier: str,
    amount: float,
    category: str,
    decision: str,
    reasoning: str,
    override_reason: str | None = None,
    transfer: Optional[Dict[str, Any]] = None,
) -> None:
    """Records the caseworker's decision; an approval also deducts the amount from the budget.

    The caseworker decides; the agent only recommends. Approvals are re-validated here,
    independently of the UI: approving despite a failed check (see approval_issues) is only
    accepted with a caseworker justification in override_reason.

    transfer = {"source", "amount", "reference", "justification"} books a budget transfer to
    `category` together with the approval, in the same transaction. On a rejection nothing moves.
    """
    decision = decision.upper()
    override_reason = (override_reason or "").strip()

    if decision == "APPROVED":
        transfer_amount = float(transfer["amount"]) if transfer else 0.0
        if transfer:
            _validate_transfer(transfer["source"], category, transfer_amount)
        issues = approval_issues(check_supplier(supplier), check_budget(amount, category), amount, transfer_amount)
        if "budget_unknown" in issues:
            raise ValueError(f"Cannot approve: budget category '{category}' not found.")
        if issues and not override_reason:
            failed = ", ".join(APPROVAL_ISSUE_LABELS_DE[i] for i in issues)
            raise ValueError(
                f"Cannot approve against failed checks ({failed}) without a caseworker justification."
            )
    else:
        transfer = None

    if override_reason:
        reasoning = f"{reasoning}\n\nCaseworker justification: {override_reason}"

    timestamp = datetime.now().isoformat(timespec='seconds')

    conn = get_db_connection()
    try:
        # Transfer, budget deduction and audit entry are written atomically (all or nothing).
        with conn:
            if transfer:
                _apply_transfer(conn, transfer["source"], category, float(transfer["amount"]),
                                transfer.get("reference", ""), transfer.get("justification", ""))
            if decision == "APPROVED":
                conn.execute("""
                    UPDATE Budgets
                    SET Remaining_Budget = Remaining_Budget - ?
                    WHERE LOWER(Category) = LOWER(?);
                """, (amount, category))

            conn.execute("""
                INSERT INTO Audit_Logs (Timestamp, Request_Text, Supplier, Amount, Category, Decision, Reasoning)
                VALUES (?, ?, ?, ?, ?, ?, ?);
            """, (timestamp, request_text, supplier, amount, category, decision, reasoning))
    finally:
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


def _format_number(amount: float) -> str:
    formatted = f"{float(amount):,.2f}"
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def _format_date(timestamp: Any) -> str:
    """ISO timestamp from Audit_Logs -> German date (DD.MM.YYYY)."""
    try:
        return datetime.fromisoformat(str(timestamp)).strftime("%d.%m.%Y")
    except ValueError:
        return str(timestamp or "")


# Fixed wording for Section 7 of the Auftragserweiterung form
EXTENSION_JUSTIFICATION = "Die Erweiterung ist aufgrund des gestiegenen Bedarfs erforderlich."
EXTENSION_LEGAL_BASIS = "§ 8 UVgO (Auftragserweiterung)"


class _FormPDF(FPDF):
    """A4 form with the footer of the official Hildesheim templates.

    Every page reads "Stand: 09/2026"; the last page carries the form name instead.
    """

    def __init__(self, last_page_label: str):
        super().__init__(format="A4")
        self.last_page_label = last_page_label
        self.is_last_page = False

    def footer(self) -> None:
        self.set_y(-14)
        self.set_font("Helvetica", "", 8)
        left = self.last_page_label if self.is_last_page else "Stand: 09/2026"
        self.cell(85, 5, _pdf_safe(left))
        self.cell(0, 5, f"Seite {self.page_no()} von {{nb}}", align="R")


def generate_anmeldebogen_pdf(
    eval_data: Dict[str, Any], override_reason: str | None = None, transfer: Optional[Dict[str, Any]] = None
) -> bytes:
    """Generates the official Anmeldebogen as a 1:1 replica of the templates in docs/.

    Auftragserweiterung -> Anmeldebogen_Auftragserweiterung_Hackathon.pdf (2 pages)
    LuD                 -> Anmeldebogen_LuD_Hackathon.pdf (5 pages)

    Only verified data is filled in: measure, amount, budget account, supplier and the
    agent's check results (in "Sonstige Hinweise", together with any accessibility
    warning). Checkboxes that require a caseworker's judgment are left empty.
    Approving despite a failed check (see approval_issues) needs a caseworker justification;
    without one, or without a valid budget check, no PDF is produced. transfer = {"source",
    "amount", "legal_basis"} is a budget transfer booked together with the approval.
    """
    decision = str(eval_data.get("decision", "")).strip().upper()
    supplier_check = eval_data.get("supplier_check") or {}
    budget_check = eval_data.get("budget_check") or {}
    override_reason = (override_reason or "").strip()
    amount = float(eval_data.get("amount", 0.0) or 0.0)
    transfer_amount = float(transfer["amount"]) if transfer else 0.0
    issues = approval_issues(supplier_check, budget_check, amount, transfer_amount)
    if "budget_unknown" in issues:
        raise ValueError("No Anmeldebogen is generated: no valid budget check result is available.")
    if issues and not override_reason:
        raise ValueError(
            "No Anmeldebogen is generated: approving despite failed checks "
            f"({', '.join(APPROVAL_ISSUE_LABELS_DE[i] for i in issues)}) requires a caseworker justification."
        )

    supplier = eval_data.get("supplier_name", "Unbekannt")
    category = eval_data.get("category", "IT-Ausstattung")
    konto = eval_data.get("konto", "") or budget_check.get("konto", "")
    summary = eval_data.get("summary", "")
    is_extension = eval_data.get("procurement_type", "LuD") == "Auftragserweiterung"
    accessibility = eval_data.get("accessibility_check") or {}
    prior_contracts = eval_data.get("prior_contracts") or []
    today = datetime.now()

    # --- Results of the automated checks, printed under "Sonstige Hinweise" -----------------
    remaining = float(budget_check["remaining_budget"]) + transfer_amount
    overage = amount - remaining
    if not supplier_check.get("exists"):
        supplier_line = f"Lieferantenprüfung: {supplier} ist nicht im Lieferantenverzeichnis registriert."
    elif not supplier_check.get("is_approved"):
        supplier_line = (
            f"Lieferantenprüfung: {supplier_check.get('supplier_name', supplier)} ist im Lieferantenverzeichnis "
            "als nicht zugelassen geführt."
        )
    else:
        supplier_line = (
            f"Lieferantenprüfung: {supplier_check.get('supplier_name', supplier)} ist im Lieferantenverzeichnis "
            f"als zugelassen geführt (Kategorie: {supplier_check.get('category') or 'nicht angegeben'})."
        )
    if overage <= 0:
        budget_result = "Die verfügbaren Mittel decken den beantragten Betrag."
    elif "budget_exceeded" in issues:
        budget_result = f"Der beantragte Betrag überschreitet die verfügbaren Mittel um {_format_eur(overage)} (über der 5%-Toleranz)."
    else:
        budget_result = f"Der beantragte Betrag überschreitet die verfügbaren Mittel um {_format_eur(overage)} (innerhalb der 5%-Toleranz)."
    recommendation = {"APPROVED": "Genehmigen", "REJECTED": "Ablehnen"}.get(decision, "Prüfung erforderlich")
    check_lines = [
        supplier_line,
        f"Budgetprüfung: Haushaltsposition {budget_check.get('category', category)}"
        + (f" (Konto {konto})" if konto else "")
        + f": verfügbar {_format_eur(remaining)}"
        + (f" einschließlich Budgetverschiebung {_format_eur(transfer_amount)}" if transfer else "")
        + f", beantragt {_format_eur(amount)}. "
        + budget_result,
        (
            f"Verfahrensart: Im Audit-Protokoll wurde ein freigegebener Vorauftrag mit {supplier} gefunden; "
            "Einstufung als Auftragserweiterung."
            if is_extension
            else f"Verfahrensart: Im Audit-Protokoll wurde kein freigegebener Vorauftrag mit {supplier} gefunden; "
            "Einstufung als neue Vergabe (Lieferung und Dienstleistung)."
        ),
        f"Empfehlung des Agenten: {recommendation}. Vom Agenten vorgeprüft – Freigabe durch Vergabestelle ausstehend; "
        f"{_format_eur(amount)} wurden auf der Haushaltsposition {category} gebucht "
        f"(verbleibend nach Buchung: {_format_eur(remaining - amount)}).",
    ]
    if transfer:
        check_lines.append(
            f"Budgetverschiebung: {_format_eur(transfer_amount)} aus der Haushaltsposition {transfer['source']} "
            f"({transfer.get('legal_basis', '')}), zusammen mit der Freigabe gebucht."
        )
    if overage > 0:
        check_lines.append(f"Freigabe trotz Budgetüberschreitung um {_format_eur(overage)}.")
    if issues:
        check_lines.append(
            "Freigabe entgegen der Empfehlung des Agenten (fehlgeschlagene Prüfung: "
            f"{', '.join(APPROVAL_ISSUE_LABELS_DE[i] for i in issues)})."
        )
    if override_reason:
        check_lines.append(f"Begründung der Sachbearbeitung: {override_reason}")

    # --- Layout primitives ----------------------------------------------------------------
    pdf = _FormPDF("Beispielanmeldebogen Hackathon" if is_extension else "Anmeldebogen LuD Hackathon")
    pdf.set_margins(20, 16, 20)
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    left, width = pdf.l_margin, pdf.epw
    line_h = 4.6

    def text(value: str, indent: float = 3, style: str = "", size: float = 9, h: float = line_h, align: str = "L") -> None:
        pdf.set_font("Helvetica", style, size)
        pdf.set_x(left + indent)
        pdf.multi_cell(width - indent, h, _pdf_safe(value), align=align, new_x="LMARGIN", new_y="NEXT")

    def gap(mm: float = 2) -> None:
        pdf.ln(mm)

    def heading(value: str, indent: float = 3) -> None:
        gap(1.5)
        text(value, indent=indent, style="B")
        y = pdf.get_y()
        pdf.set_line_width(0.35)
        pdf.line(left + indent, y, left + width, y)
        gap(1.5)

    def checkbox(label: str = "", checked: bool = False, indent: float = 3, style: str = "", size: float = 9) -> None:
        x, y = left + indent, pdf.get_y()
        pdf.set_line_width(0.25)
        pdf.rect(x, y + 0.8, 3, 3)
        if checked:
            pdf.line(x, y + 0.8, x + 3, y + 3.8)
            pdf.line(x, y + 3.8, x + 3, y + 0.8)
        pdf.set_font("Helvetica", style, size)
        pdf.set_xy(x + 4.5, y)
        pdf.multi_cell(width - indent - 4.5, line_h, _pdf_safe(label), new_x="LMARGIN", new_y="NEXT")
        gap(1.2)

    def inline_checkboxes(labels: List[str], spacing: float, indent: float = 3) -> None:
        y = pdf.get_y()
        pdf.set_line_width(0.25)
        pdf.set_font("Helvetica", "", 9)
        for i, label in enumerate(labels):
            x = left + indent + i * spacing
            pdf.rect(x, y + 0.8, 3, 3)
            pdf.set_xy(x + 4.5, y)
            pdf.cell(spacing - 5, line_h, _pdf_safe(label))
        pdf.set_xy(left, y + line_h)
        gap(1)

    def label_value(label: str, value: str = "", indent: float = 3) -> None:
        pdf.set_font("Helvetica", "", 9)
        pdf.set_x(left + indent)
        label_w = pdf.get_string_width(_pdf_safe(label)) + 2
        pdf.cell(label_w, line_h, _pdf_safe(label))
        pdf.set_font("Helvetica", "B", 9)
        pdf.multi_cell(width - indent - label_w, line_h, _pdf_safe(value), new_x="LMARGIN", new_y="NEXT")
        gap(0.8)

    def form_header(title: str, vergabenummer: str, datum_label: str) -> None:
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(width - 40, line_h, _pdf_safe("Fachbereich/Stabstelle:"))
        pdf.cell(40, line_h, _pdf_safe(f"{datum_label} {today.strftime('%d.%m.%Y')}"), align="R", new_x="LMARGIN", new_y="NEXT")
        text("Sachbearbeitung:", indent=0)
        gap(2)
        text("Sachbearbeitung Vergabestelle:", indent=0)
        gap(5)
        text(title, indent=0, style="B", size=14, h=7, align="C")
        gap(3)
        text(f"Vergabenummer:    {vergabenummer}", indent=0)
        y = pdf.get_y()
        pdf.set_line_width(0.6)
        pdf.line(left, y, left + width, y)
        gap(1)

    def budget_rows() -> None:
        columns = [0, 38, 70, 104, 146]
        filled = [
            f"Haushaltsjahr {today.year}",
            "Produkt",
            f"Konto {konto}" if konto else "Konto",
            f"Betrag {_format_number(amount)}",
            "EUR brutto",
        ]
        empty = ["Haushaltsjahr", "Produkt", "Konto", "Betrag", "EUR brutto"]
        for row in (filled, empty, empty):
            y = pdf.get_y()
            pdf.set_font("Helvetica", "", 9)
            for offset, cell in zip(columns, row):
                pdf.set_xy(left + 3 + offset, y)
                pdf.cell(0, line_h, _pdf_safe(cell))
            pdf.set_xy(left, y + line_h)
        gap(1.5)

    def section_5_auftragswert() -> None:
        heading("5. Geschätzter Auftragswert")
        text("EUR netto", indent=8)
        text(f"{_format_number(amount)} EUR brutto", indent=8, style="B")
        gap(2.5)
        text("Die Mittel stehen zur Verfügung (Haushalts-Planzahlen):")
        budget_rows()
        checkbox("Die Stadt Hildesheim ist für diese Vergabe vorsteuerabzugsberechtigt")
        checkbox("Verwendung von Fördermitteln zur (Teil-)Finanzierung der Maßnahme")
        checkbox("Es handelt sich um Fördermittel der EU", indent=12)
        checkbox(
            "Zu Zeiten der vorläufigen Haushaltsführung: Ich versichere, dass die entsprechenden Regelungen "
            "zur vorläufigen Haushaltsführung eingehalten werden."
        )

    def sonstige_hinweise(number: int) -> None:
        heading(f"{number}. Sonstige Hinweise")
        if accessibility.get("warning"):
            # Keep the warning box on one page
            if pdf.get_y() + 32 > pdf.page_break_trigger:
                pdf.add_page()
            y0 = pdf.get_y()
            pdf.set_text_color(160, 0, 0)
            text("WARNUNG BARRIEREFREIHEIT", indent=6, style="B", size=10, h=6)
            pdf.set_text_color(0, 0, 0)
            text(
                f"Im Fachbereich {accessibility.get('department', category)} sind "
                f"{accessibility.get('employees_with_special_needs', 0)} von "
                f"{accessibility.get('total_employees', 0)} Beschäftigten mit besonderen Bedürfnissen tätig. "
                "Es ist sicherzustellen, dass die beschafften Gegenstände (z. B. Tische und Stühle) "
                "ergonomisch und barrierefrei sind.",
                indent=6,
                style="B",
            )
            text(accessibility["warning"], indent=6, size=8)
            gap(1.5)
            pdf.set_draw_color(160, 0, 0)
            pdf.set_line_width(0.8)
            pdf.rect(left + 3, y0 - 1, width - 3, pdf.get_y() - y0 + 1)
            pdf.set_draw_color(0, 0, 0)
            gap(3)
        text("Ergebnis der automatisierten Prüfung (Vergabeassistent):", style="B")
        for line in check_lines:
            text(f"- {line}", indent=5)
        gap(4)
        text("Ort, Datum, Unterschrift Vergabestelle: ______________________________", indent=5)

    def anlagen(items: List[Any]) -> None:
        gap(3)
        text("Anlagen", style="BU")
        gap(2)
        for item in items:
            label, indent = item if isinstance(item, tuple) else (item, 3)
            checkbox(label, indent=indent)

    # --- Anmeldebogen Auftragserweiterung (2 pages) -----------------------------------------
    if is_extension:
        form_header("Anmeldung/Dokumentation einer Auftragserweiterung", "", "Datum:")

        heading("1. Bezeichnung der Maßnahme")
        text(summary or "Keine Beschreibung angegeben.")
        heading("2. Art der Leistung")
        gap(4)
        inline_checkboxes(["Lieferleistung", "Dienstleistung", "freiberufliche Leistung", "Bauleistung"], 40)
        heading("3. Umfang der Leistung")
        gap(4)
        section_5_auftragswert()

        # Section 6: original order, taken from the approved entries in Audit_Logs
        heading("6. Angaben zum ursprünglichen Auftrag")
        text(
            "Der Auftragswert des ursprünglichen Auftrags (inklusive ggf. bereits erfolgter Auftragserweiterungen) "
            "beträgt:"
        )
        gap(1)
        if prior_contracts:
            prior_total = sum(c["amount"] for c in prior_contracts)
            prior_value = f"{_format_number(prior_total)} EUR brutto"
            prior_services = "\n".join(
                f"{_format_date(c.get('timestamp'))}: {c.get('request_text', '')} "
                f"({_format_number(c.get('amount', 0.0))} EUR brutto)"
                for c in prior_contracts
            )
        else:
            prior_value = prior_services = "Keine Angaben im Audit-Protokoll"
        label_value("Ursprünglicher Auftragswert:", prior_value, indent=6)
        text("Es wurden beim Ursprungsauftrag folgende Leistungen beauftragt:")
        gap(1)
        label_value("Beauftragte Leistungen:", prior_services, indent=6)

        heading("7. Vergabebegründung/Begründung der Auftragserweiterung")
        label_value("Begründung:", EXTENSION_JUSTIFICATION, indent=6)
        label_value("Rechtsgrundlage:", EXTENSION_LEGAL_BASIS, indent=6)
        heading("8. Begründung der Wirtschaftlichkeit")
        checkbox(
            "Es werden die Konditionen des Ursprungsauftrags genutzt. Die Wirtschaftlichkeit wurde bereits in "
            "der Ursprungsvergabe geprüft.",
            checked=True,
            indent=6,
        )
        checkbox("Andere Begründung:", indent=6)

        pdf.add_page()
        heading("9. Fristen")
        text("Angebot gültig bis:")
        heading("10. Auftragnehmer")
        label_value("(Name/Sitz der Firma; E-Mail; ggf. Ansprechpartner):", supplier)
        gap(8)
        sonstige_hinweise(11)
        anlagen(["Angebot/Kostenschätzung", "Nachweis der Haushaltsmittel", "ggf. VA-Beschluss", ""])
        gap(4)
        heading("Prüfung/Anmerkungen Öffentliches Auftragswesen", indent=0)

    # --- Anmeldebogen LuD (5 pages) ---------------------------------------------------------
    else:
        form_header("Anmeldung einer Vergabe (LuD)", "(wird im DMS generiert)", "Datum")

        heading("1. Bezeichnung der Maßnahme")
        text(summary or "Keine Beschreibung angegeben.")
        heading("2. Art der Leistung")
        gap(3)
        inline_checkboxes(["Lieferleistung", "Dienstleistung", "freiberufliche Leistung"], 40)
        text("(Wenn mehreres vorliegt, ist nach Schwerpunkt zu entscheiden)", size=7)
        gap(1)
        checkbox("Die Leistung fällt in den Anwendungsbereich des Saubere-Fahrzeuge-Beschaffungsgesetztes")
        heading("3. Umfang der Leistung")
        gap(3)
        checkbox("Rahmenvertrag")
        heading("4. CPV-Code(s) (bitte immer angeben)")
        text("(Taste \"strg\" + linksklick mit der Maus auf -> Suchmaschine für CPV-Codes - cpvcode.de)")
        gap(6)
        section_5_auftragswert()
        heading("6. Wahl und Begründung der Vergabeart")
        text("national", indent=6, style="BU")
        checkbox("Öffentliche Ausschreibung", indent=6, style="B")
        checkbox("Beschränkte Ausschreibung mit Teilnahmewettbewerb", indent=6, style="B")

        pdf.add_page()
        text("(ohne Begründung möglich)", indent=6)
        gap(2)
        checkbox("Beschränkte Ausschreibung ohne Teilnahmewettbewerb", indent=6, style="B")
        text("Begründung:                    (§ 8 UVgO)", indent=10)
        text("Ausführungen zur Begründung, falls § 8 Abs. 3 UVgO gewählt wurde:", indent=10)
        gap(5)
        checkbox("Verhandlungsvergabe", indent=6, style="B")
        checkbox("mit Teilnahmewettbewerb", indent=6)
        text("Begründung:", indent=14)
        checkbox(
            "gem. § 12 Abs. 3 UVgO wird nur ein Unternehmen zur Angebotsabgabe aufgefordert "
            "(nur bei § 8 Abs. 4 Nr. 9-14 möglich).",
            indent=14,
            size=8,
        )
        text("Ausführungen zur Begründung, falls § 8 Abs. 4 UVgO gewählt wurde:", indent=14)
        gap(5)
        text("europaweit", indent=6, style="BU")
        gap(1)
        checkbox("Offenes Verfahren", indent=6, style="B")
        checkbox("Nichtoffenes Verfahren mit Teilnahmewettbewerb", indent=6, style="B")
        text("(ohne Begründung möglich)", indent=6)
        gap(2)
        checkbox("Verhandlungsverfahren", indent=6, style="B")
        checkbox("mit Teilnahmewettbewerb", indent=8)
        text("Begründung:                    (§ 14 VgV)", indent=6)
        gap(1)
        text("Ausführungen zur Begründung:", indent=6)
        gap(4)
        heading("7. Vergabebegründung/Begründung der Maßnahme")
        gap(4)
        heading("8. Loseinteilung")
        checkbox("ja, die Ausschreibung wird wie folgt in Lose aufgeteilt")
        text("(Überschrift, kurze Beschreibung, Menge oder Umfang)", indent=8)
        for lot in ("Los 1:", "Los 2:", "Los 3:"):
            gap(1)
            text(lot, indent=9)
        gap(3)
        text("Angebote sollen eingereicht werden für (Loslimitierung):", indent=0)
        gap(3)
        text("Maximale Anzahl der Lose, auf die geboten werden darf:", indent=1)
        gap(1)
        text("Ein Unternehmen bekommt maximal den Zuschlag für folgende Anzahl an Losen (Zuschlagslimitierung):", indent=0)
        gap(3)
        text(
            "Bedingungen zur Ermittlung derjenigen Lose, für die ein Bieter den Zuschlag erhält, falls sein Angebot "
            "in mehr Losen das wirtschaftlichste ist als der angegebenen Höchstzahl an Losen:",
            indent=1,
        )

        pdf.add_page()
        checkbox("nein, die Ausschreibung wird nicht in Lose aufgeteilt (Begründungspflicht!)")
        checkbox("weil es sich um eine (wirtschaftlich) nicht trenn- oder teilbare Leistung handelt.", indent=8)
        checkbox("weil folgende technische oder wirtschaftliche Gründe dagegensprechen:", indent=8)
        gap(4)
        heading("9. Sonstiges/Bedingungen")
        checkbox("Es werden Kautionen oder Sicherheiten gefordert, und zwar:", indent=6)
        gap(2)
        text("Begründung:", indent=6)
        heading("10. Leistungsort (Offizielle Bezeichnung, Straße, Hausnummer, PLZ, Ort)")
        gap(4)
        heading("11. Ausführungs-/ Anlieferungsfristen")
        text("Beginn:", indent=4)
        gap(1)
        text("Ende:", indent=4)
        gap(1)
        text("Oder sonstige Bestimmungen:", indent=4)
        checkbox("der Auftrag kann wie folgt verlängert werden:", indent=4)
        heading("12. Fristen")
        y = pdf.get_y()
        text("Geplanter Submissionstermin:", indent=4)
        pdf.set_xy(left + 110, y)
        pdf.cell(0, line_h, _pdf_safe("(nur Di bis Fr.)"), new_x="LMARGIN", new_y="NEXT")
        gap(1)
        text("Geplanter Ablauf der Zuschlags-/Bindefrist:", indent=4)
        heading("13. Wertungskriterien (und ggf. Gewichtung)")
        for criterion in ("Preis", "", ""):
            y = pdf.get_y()
            checkbox(criterion, indent=6)
            pdf.set_xy(left + 135, y)
            pdf.cell(0, line_h, _pdf_safe("Gewichtung     %"))
            pdf.set_xy(left, y + line_h + 1.2)
        checkbox("siehe Anlage", indent=6)
        heading("14. Nachweise und Unterlagen")
        checkbox("124 Eigenerklärung zur Eignung (nur bei Öffentlichen Ausschreibungen/Offenen Verfahren)", indent=1, style="B")
        checkbox("Umsatz der letzten 3 Geschäftsjahre ist anzugeben", indent=6, style="B")
        text(
            "Wenn über die Eigenerklärung hinaus oder anstelle der Eigenerklärung Angaben gewünscht sind, so sind "
            "diese bitte hier mit einer konkreten Auflistung aufzuführen, (bspw. Qualifikation des Personals, "
            "Deckungssumme Haftpflichtversicherung, etc.):",
            indent=10,
        )
        gap(2)
        checkbox("Sonstiges:", indent=1, style="B")
        heading("15. Besondere anzufordernde Unterlagen/Proben und Muster", indent=1)
        y = pdf.get_y()
        checkbox("Nachunternehmererklärung", indent=1)
        pdf.set_xy(left + 60, y)
        pdf.cell(0, line_h, _pdf_safe("einzureichen:"))
        pdf.set_xy(left, y + line_h + 1.2)
        checkbox(
            "NKernVO (Stoffe, sonstige Textilwaren, ungebrauchter Naturstein, Tee, Kaffee, Kakao, Blumen, "
            "Spielwaren, Sportbälle)",
            indent=1,
            size=8,
        )
        text("einzureichen: auf Verlangen", indent=1)

        pdf.add_page()
        for label in ("248 Erklärung zur Verwendung von Holzprodukten", "Sonstige:"):
            y = pdf.get_y()
            checkbox(label, indent=1)
            pdf.set_xy(left + 100, y)
            pdf.cell(0, line_h, _pdf_safe("einzureichen: Mit dem Angebot/Auf Verlangen"))
            pdf.set_xy(left, y + line_h + 1.2)
        heading("16. Nachforderung von Unterlagen", indent=0)
        text("Fehlende Unterlagen werden nachgefordert: Ja/Nein", indent=4)
        gap(1)
        text("Wenn teilweise:", indent=4)
        checkbox("folgende Unterlagen:", indent=10)
        checkbox("alle Unterlagen, außer", indent=10)
        heading("17. Hauptangebote")
        text("Mehrere Hauptangebote sind zugelassen/nicht zugelassen")
        heading("18. Nebenangebote", indent=0)
        checkbox("Nebenangebote sind nicht zugelassen", indent=1)
        checkbox(
            "Nebenangebote sind zugelassen (siehe auch Nummer 4 der Bewerbungsbedingungen) - ausgenommen "
            "Nebenangebote, die ausschließlich Preisnachlässe mit Bedingungen beinhalten nur in Verbindung mit "
            "einem Hauptangebot",
            indent=1,
        )
        for label in (
            "für die gesamte Leistung",
            "nur für nachfolgend genannte Bereiche",
            "mit Ausnahme nachfolgend genannter Bereiche",
            "Mindestanforderungen:",
        ):
            gap(1)
            checkbox(label, indent=4)
        heading("19. Bewerberauswahl zur Beteiligung an der Vergabe")
        label_value("Aufzufordernde Firmen (Name/Sitz der Firma; E-Mail; ggf. Ansprechpartner):", supplier, indent=0)
        gap(4)
        checkbox(
            "Die Eignungsprüfung ist im Voraus erfolgt. (nur bei Beschränkten Ausschreibungen und "
            "Verhandlungsvergaben/Freihändigen Vergaben)",
            indent=0,
            style="B",
        )
        text("Das Unternehmen ist geeignet:", indent=0)
        gap(1)
        checkbox("Das Unternehmen ist bekannt, die Eignung wurde in Zusammenhang mit anderen Aufträgen nachgewiesen.", indent=0)
        checkbox(
            "Die Eignung wurde durch eine Eigenerklärung zur Eignung abgefragt, mit den dortigen Angaben ist "
            "die Eignung hinreichend nachgewiesen.",
            indent=0,
        )
        checkbox("", indent=0)
        sonstige_hinweise(20)

        pdf.add_page()
        anlagen(
            [
                "Leistungsbeschreibung (Vergabeunterlagen für extern)",
                ("Anlagen zur Leistungsbeschreibung (z.B. Pläne, Gutachten, etc.)", 8),
                "Kalkulation des geschätzten Auftragswertes",
                "Nachweis der Haushaltsmittel/ Auftragseinbuchung",
                "ggf. VA-Beschluss",
                "ggf. Verpflichtungserklärung für freiberuflich Tätige (Vergabeunterlagen für extern)",
                "",
            ]
        )
        gap(4)
        heading("Prüfung/Anmerkungen FB 13 - Öffentliches Auftragswesen", indent=0)

    # The footer of the final page shows the form name, as in the templates
    pdf.is_last_page = True
    return bytes(pdf.output())

def calculate_price_score(price: float, lowest_price: float) -> float:
    """Price points (0-10) via the interpolation of docs/Auswertung_Hackathon.XLSX, sheet "Übersicht"."""
    if price <= 0 or lowest_price <= 0:
        raise ValueError(f"Bid prices must be greater than 0 (got price={price}, lowest={lowest_price}).")
    # Excel: E7 = 10 points for the lowest bid, D9 = 2 * D7 (fictitious bid with 0 points),
    # E8 = (E7 / D7) * (D9 - D8). Clamped so bids at or above 2 x lowest get 0, never negative.
    points = (10.0 / lowest_price) * (2 * lowest_price - price)
    return max(0.0, min(10.0, points))


# Evaluation criteria. "field" is the bid key holding the value; "kind" selects the scoring rule:
#   lowest_best  - Excel interpolation: best (lowest) value 10 points, twice the best 0 points
#   highest_best - proportional to the best (highest) value
#   committee    - 0-10 score confirmed by the evaluation committee; the agent proposes it
#                  from the extracted facts (src/bid_scoring.py), the committee may overwrite it
CRITERIA = {
    "price": {"field": "price", "kind": "lowest_best", "label_de": "Preis"},
    "delivery": {"field": "delivery_days", "kind": "lowest_best", "label_de": "Lieferzeit"},
    "warranty": {"field": "warranty_months", "kind": "highest_best", "label_de": "Garantie"},
    "references": {"field": "references_score", "kind": "committee", "label_de": "Referenzen / Service"},
    "concept": {"field": "concept_score", "kind": "committee", "label_de": "Konzept / Qualität"},
}

# Weights in percent. The official sheet weights Preis/Referenzen/Konzept with the factors
# 30/30/20 (max. 800 points, no fourth criterion); normalised to 100 % that is 37.5/37.5/25,
# which yields the same ranking (sheet points = total points x 8).
CRITERIA_PRESETS = {
    "sheet": {"price": 37.5, "references": 37.5, "concept": 25.0},
    "goods": {"price": 60.0, "delivery": 20.0, "warranty": 20.0},
}
DEFAULT_WEIGHTS = CRITERIA_PRESETS["sheet"]


def validate_weights(weights: Dict[str, float]) -> Dict[str, float]:
    """Returns the criteria with a weight > 0. Raises ValueError unless the weights sum to 100."""
    unknown = set(weights) - set(CRITERIA)
    if unknown:
        raise ValueError(f"Unknown evaluation criteria: {', '.join(sorted(unknown))}.")
    if any(float(w) < 0 for w in weights.values()):
        raise ValueError("Criterion weights must not be negative.")
    total = sum(float(w) for w in weights.values())
    if abs(total - 100.0) > 0.01:
        raise ValueError(f"Criterion weights must sum to 100 % (got {total:g} %).")
    return {key: float(w) for key, w in weights.items() if float(w) > 0}


def missing_bid_values(bids_data: List[Dict[str, Any]], weights: Dict[str, float]) -> List[Tuple[str, str]]:
    """(bidder, criterion) pairs for which an active criterion has no value. Nothing is defaulted."""
    missing = []
    for b in bids_data:
        for key in validate_weights(weights):
            value = b.get(CRITERIA[key]["field"])
            if value is None or (isinstance(value, float) and math.isnan(value)):
                missing.append((str(b.get("bidder") or "-"), key))
    return missing


def score_criterion(key: str, values: List[float], bidders: List[str]) -> List[float]:
    """0-10 scores of one criterion for all bids, using the criterion's scoring rule."""
    kind = CRITERIA[key]["kind"]
    if kind == "committee":
        for bidder, value in zip(bidders, values):
            if not 0 <= value <= 10:
                raise ValueError(f"Committee score '{key}' for '{bidder}' must be between 0 and 10 (got {value:g}).")
        return values
    if kind == "highest_best":
        best = max(values)
        return [10.0 * v / best if best > 0 else 0.0 for v in values]
    # lowest_best
    if key == "price":
        for bidder, value in zip(bidders, values):
            if value <= 0:
                raise ValueError(f"Bid price for '{bidder}' must be greater than 0 (got {value}).")
        return [calculate_price_score(v, min(values)) for v in values]
    best = min(values)
    if best <= 0:
        return [10.0 if v == best else 0.0 for v in values]
    return [max(0.0, min(10.0, (10.0 / best) * (2 * best - v))) for v in values]


def generate_rejection_letters(
    winner: Dict[str, Any],
    losers: List[Dict[str, Any]],
    weights: Optional[Dict[str, float]] = None,
) -> List[Dict[str, Any]]:
    """Generates a Gemini rejection letter for each loser, in place.

    On failure the loser gets legal_justification = None and letter_error = <message>;
    no template text is substituted.
    """
    weights = validate_weights(weights or DEFAULT_WEIGHTS)
    criteria_text = ", ".join(f"{CRITERIA[k]['label_de']} ({w:g} %)" for k, w in weights.items())

    def points_text(bid: Dict[str, Any]) -> str:
        return ", ".join(f"{CRITERIA[k]['label_de']}: {bid.get(f'{k}_points', 0)} Punkte" for k in weights)

    try:
        client = get_genai_client()
    except Exception as e:
        for loser in losers:
            loser["legal_justification"] = None
            loser["letter_error"] = str(e)
        return losers

    for loser in losers:
        prompt = f"""
        You are a public procurement specialist for the City of Hildesheim under German procurement law (UVgO / GWB).
        Generate a formal, legally binding rejection letter paragraph (Begründung nach § 13 UVgO) explaining why Bidder '{loser['bidder']}' (Price: €{loser['price']:,.2f}, Total Score: {loser['total_points']} of 100 points; {points_text(loser)}) was not selected, and why the winning bidder '{winner['bidder']}' (Price: €{winner['price']:,.2f}, Total Score: {winner['total_points']} of 100 points; {points_text(winner)}) won based on the published evaluation criteria: {criteria_text}.
        Write in professional German.
        """
        try:
            resp = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.2)
            )
            loser["legal_justification"] = resp.text.strip()
            loser["letter_error"] = None
        except Exception as e:
            loser["legal_justification"] = None
            loser["letter_error"] = str(e)
    return losers


def score_bids(bids_data: List[Dict[str, Any]], weights: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """Scores bids with weighted criteria (0-100 points), ranked best first. No letters, no AI.

    Each criterion is scored 0-10 and multiplied by its weight in percent / 10. Raises ValueError
    if the weights do not sum to 100 or any bid lacks a value for an active criterion.
    """
    weights = validate_weights(weights or DEFAULT_WEIGHTS)
    missing = missing_bid_values(bids_data, weights)
    if missing:
        details = "; ".join(f"'{bidder}': {key}" for bidder, key in missing)
        raise ValueError(f"Bid values missing, no evaluation possible: {details}.")

    bidders = [str(b["bidder"]) for b in bids_data]
    evaluated_bids = [{"bidder": b["bidder"], "price": float(b["price"])} for b in bids_data]
    for key, weight in weights.items():
        field = CRITERIA[key]["field"]
        values = [float(b[field]) for b in bids_data]
        scores = score_criterion(key, values, bidders)
        for bid, value, score in zip(evaluated_bids, values, scores):
            bid[field] = value
            bid[f"{key}_score"] = round(score, 2)
            bid[f"{key}_points"] = round(score * weight / 10.0, 2)
    for bid in evaluated_bids:
        bid["total_points"] = round(sum(bid[f"{key}_points"] for key in weights), 2)

    evaluated_bids.sort(key=lambda x: x["total_points"], reverse=True)
    return {
        "winner": evaluated_bids[0],
        "ranked_bids": evaluated_bids,
        "losers": evaluated_bids[1:],
        "weights": weights,
    }


def requests_awaiting_bids(
    request_history: List[Dict[str, Any]], tenders: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Requests for which bids may be collected: approved by a caseworker and not yet evaluated.

    request_history holds one entry per decided request (pending requests are not in it);
    tenders holds the completed bid evaluations, linked by "ref". Archived entries (completed
    procurements, e.g. the demo history) are never offered. Ordered by reference.
    """
    latest = {entry["ref"]: entry for entry in request_history}  # a later decision wins
    evaluated = {tender.get("ref") for tender in tenders}
    return sorted(
        (
            entry for entry in latest.values()
            if entry.get("decision") == "APPROVED" and entry["ref"] not in evaluated and not entry.get("archived")
        ),
        key=lambda entry: entry["ref"],
    )


def evaluate_bids(bids_data: List[Dict[str, Any]], weights: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """Scores bids with weighted criteria (see score_bids) and generates § 13 UVgO rejection letters."""
    if not bids_data:
        return {"error": "No bids provided"}

    result = score_bids(bids_data, weights)
    # Scoring above is deterministic and always returned; letters may fail independently.
    generate_rejection_letters(result["winner"], result["losers"], result["weights"])
    return result

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

    return verify_extracted_request(extracted)


def verify_extracted_request(extracted: ExtractedRequest) -> Dict[str, Any]:
    """Runs the deterministic checks (supplier, budget, contract history, accessibility) on
    already extracted request fields and returns the decision with step-by-step reasoning."""
    # Run deterministic tool checks
    supplier_res = check_supplier(extracted.supplier_name)
    budget_res = check_budget(extracted.amount, extracted.category)
    
    # Check contract extension history in Audit_Logs. Prior contracts are captured now,
    # before this request's own approval is written to the log.
    prior_contracts = get_prior_contracts(supplier_res["supplier_name"] if supplier_res["exists"] else extracted.supplier_name)
    is_extension = bool(prior_contracts)
    procurement_type = "Auftragserweiterung" if is_extension else "LuD"

    # The requesting department is identified by the budget position it procures from
    department = budget_res["category"] if "error" not in budget_res else extracted.category
    accessibility_res = check_accessibility(department)
    
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
        reasoning_steps.append(f"5. **Agent recommendation: Reject.** Reason: Supplier is either unapproved or unknown.")
    else:
        if "error" in budget_res:
            decision = "REJECTED"
            reasoning_steps.append(f"4. **Budget Check:** Category '{extracted.category}' not found in budget database.")
            reasoning_steps.append(f"5. **Agent recommendation: Reject.** Reason: Invalid budget category.")
        else:
            rem_bud = budget_res["remaining_budget"]
            reasoning_steps.append(f"4. **Budget Check:** Category '{extracted.category}' has €{rem_bud:,.2f} remaining budget. Requested: €{extracted.amount:,.2f}.")
            
            if budget_res["sufficient"]:
                decision = "APPROVED"
                reasoning_steps.append(f"5. **Agent recommendation: Approve.** Reason: Supplier is approved and requested amount is fully covered by remaining budget.")
            elif budget_res["borderline"]:
                decision = "REQUIRES_REVIEW"
                reasoning_steps.append(f"5. **Agent recommendation: Review required (the caseworker decides).** Reason: Supplier is approved, but requested amount exceeds remaining budget by ≤5% (borderline overage).")
            else:
                decision = "REJECTED"
                reasoning_steps.append(f"5. **Agent recommendation: Reject.** Reason: Requested amount exceeds remaining budget by >5%.")

    if not accessibility_res["found"]:
        reasoning_steps.append(f"6. **Accessibility Check:** Department '{department}' not found in the `Employees` table; no staff data available.")
    elif accessibility_res["warning"]:
        reasoning_steps.append(
            f"6. **Accessibility Check:** Department '{accessibility_res['department']}' has "
            f"{accessibility_res['employees_with_special_needs']} of {accessibility_res['total_employees']} employees with special needs. "
            f"**{accessibility_res['warning']}**"
        )
    else:
        reasoning_steps.append(
            f"6. **Accessibility Check:** Department '{accessibility_res['department']}' has no employees with special needs "
            f"({accessibility_res['total_employees']} employees). No accessibility requirements."
        )

    full_reasoning = "\n\n".join(reasoning_steps)

    return {
        "supplier_name": supplier_res["supplier_name"] if supplier_res["exists"] else extracted.supplier_name,
        "amount": extracted.amount,
        "category": extracted.category,
        "konto": budget_res.get("konto", ""),
        "summary": extracted.summary,
        "procurement_type": procurement_type,
        "is_extension": is_extension,
        "prior_contracts": prior_contracts,
        "supplier_check": supplier_res,
        "budget_check": budget_res,
        "accessibility_check": accessibility_res,
        "decision": decision,
        "reasoning": full_reasoning
    }
