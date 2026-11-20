import os
import sqlite3
from datetime import datetime
from typing import Dict, Any, Optional
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

load_dotenv()

DB_PATH = os.path.join(os.path.dirname(__file__), "../data/mock_data.db")

class ExtractedRequest(BaseModel):
    supplier_name: str = Field(description="Name of the supplier or vendor mentioned in the procurement request.")
    amount: float = Field(description="Total monetary amount requested in Euros (€).")
    category: str = Field(description="Procurement category, must be one of: IT, Construction, Office Supplies.")
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
    
    # 2. If not found, fetch all suppliers and do fuzzy substring matching (e.g. 'Dell Technologies' matches 'Dell')
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

def check_budget(request_amount: float, category: str) -> Dict[str, Any]:
    """Returns remaining budget, sufficiency status, and borderline 5% tolerance check."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Case-insensitive or exact category lookup
    cursor.execute("SELECT * FROM Budgets WHERE LOWER(Category) = LOWER(?);", (category.strip(),))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return {
            "category": category,
            "total_budget": 0.0,
            "remaining_budget": 0.0,
            "sufficient": False,
            "borderline": False,
            "error": "Category not found in budget database"
        }
    
    total_budget = float(row["Total_Budget"])
    remaining_budget = float(row["Remaining_Budget"])
    sufficient = remaining_budget >= request_amount
    
    # Borderline check: if not strictly sufficient, but overage is <= 5% of remaining budget (or total budget)
    borderline = False
    if not sufficient and remaining_budget > 0:
        overage = request_amount - remaining_budget
        tolerance = remaining_budget * 0.05
        if overage <= tolerance:
            borderline = True

    return {
        "category": row["Category"],
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
    
    # If decision is APPROVED, deduct amount from budget
    if decision.upper() == "APPROVED":
        cursor.execute("""
            UPDATE Budgets 
            SET Remaining_Budget = Remaining_Budget - ? 
            WHERE LOWER(Category) = LOWER(?);
        """, (amount, category))
    
    # Insert audit log entry
    cursor.execute("""
        INSERT INTO Audit_Logs (Timestamp, Request_Text, Supplier, Amount, Category, Decision, Reasoning)
        VALUES (?, ?, ?, ?, ?, ?, ?);
    """, (timestamp, request_text, supplier, amount, category, decision.upper(), reasoning))
    
    conn.commit()
    conn.close()

def evaluate_request(text: str) -> Dict[str, Any]:
    """
    Extracts parameters using Gemini Structured Outputs, runs deterministic tool checks,
    determines the decision (APPROVED, REQUIRES_REVIEW, REJECTED), and returns step-by-step reasoning.
    """
    client = genai.Client(http_options=types.HttpOptions(timeout=120000))
    
    prompt = f"""
    Analyze the following public procurement request text and extract the required fields:
    - supplier_name
    - amount (numeric value in Euros)
    - category (IT, Construction, or Office Supplies)
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
        return {
            "supplier_name": "Unknown",
            "amount": 0.0,
            "category": "IT",
            "summary": "Failed to parse procurement request due to model unavailability.",
            "supplier_check": {"exists": False, "is_approved": False},
            "budget_check": {"sufficient": False, "remaining_budget": 0.0},
            "decision": "REJECTED",
            "reasoning": f"Error during AI parameter extraction across models: {str(last_exception)}"
        }
    
    try:
        extracted = ExtractedRequest.model_validate_json(response.text)
    except Exception as e:
        return {
            "supplier_name": "Unknown",
            "amount": 0.0,
            "category": "IT",
            "summary": "Failed to parse JSON response into schema.",
            "supplier_check": {"exists": False, "is_approved": False},
            "budget_check": {"sufficient": False, "remaining_budget": 0.0},
            "decision": "REJECTED",
            "reasoning": f"Error validating structured output: {str(e)}"
        }
    
    # Run deterministic tool checks
    supplier_res = check_supplier(extracted.supplier_name)
    budget_res = check_budget(extracted.amount, extracted.category)
    
    # Decision logic & Reasoning steps
    reasoning_steps = []
    reasoning_steps.append(f"1. **Extraction:** Extracted Supplier: **{extracted.supplier_name}**, Amount: **€{extracted.amount:,.2f}**, Category: **{extracted.category}**.")
    
    decision = "APPROVED"
    
    # Supplier validation
    if not supplier_res["exists"]:
        supplier_status = "❌ Not found in approved supplier database."
        decision = "REJECTED"
    elif not supplier_res["is_approved"]:
        supplier_status = "❌ Found in database, but flagged as **UNAPPROVED**."
        decision = "REJECTED"
    else:
        supplier_status = "✅ Found and **APPROVED** in supplier database."
    
    reasoning_steps.append(f"2. **Supplier Verification:** Checked supplier '{extracted.supplier_name}': {supplier_status}")
    
    # Budget validation (if supplier check passed)
    if decision == "REJECTED":
        reasoning_steps.append(f"3. **Budget Check:** Skipped due to supplier rejection.")
        reasoning_steps.append(f"4. **Final Decision:** **REJECTED**. Reason: Supplier is either unapproved or unknown.")
    else:
        if "error" in budget_res:
            decision = "REJECTED"
            reasoning_steps.append(f"3. **Budget Check:** ❌ Category '{extracted.category}' not found in budget database.")
            reasoning_steps.append(f"4. **Final Decision:** **REJECTED**. Reason: Invalid budget category.")
        else:
            rem_bud = budget_res["remaining_budget"]
            reasoning_steps.append(f"3. **Budget Check:** Category '{extracted.category}' has €{rem_bud:,.2f} remaining budget. Requested: €{extracted.amount:,.2f}.")
            
            if budget_res["sufficient"]:
                decision = "APPROVED"
                reasoning_steps.append(f"4. **Final Decision:** **APPROVED**. Reason: Supplier is approved and requested amount is fully covered by remaining budget.")
            elif budget_res["borderline"]:
                decision = "REQUIRES_REVIEW"
                reasoning_steps.append(f"4. **Final Decision:** **REQUIRES_REVIEW**. Reason: Supplier is approved, but requested amount exceeds remaining budget by ≤5% (borderline overage requiring caseworker sign-off).")
            else:
                decision = "REJECTED"
                reasoning_steps.append(f"4. **Final Decision:** **REJECTED**. Reason: Requested amount exceeds remaining budget by >5%.")

    full_reasoning = "\n\n".join(reasoning_steps)
    
    return {
        "supplier_name": extracted.supplier_name,
        "amount": extracted.amount,
        "category": extracted.category,
        "summary": extracted.summary,
        "supplier_check": supplier_res,
        "budget_check": budget_res,
        "decision": decision,
        "reasoning": full_reasoning
    }
