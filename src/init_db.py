import os
import sqlite3
from datetime import datetime, timedelta

from src.demo_seed import BUDGET_LINES, HISTORICAL_REQUESTS

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "../data/mock_data.db")


def get_db_path() -> str:
    """Database location; override with the PROCUREMENT_DB_PATH environment variable."""
    return os.environ.get("PROCUREMENT_DB_PATH") or DEFAULT_DB_PATH


def init_db():
    db_path = get_db_path()
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Drop existing tables to ensure a clean reset
    cursor.execute("DROP TABLE IF EXISTS Audit_Logs;")
    cursor.execute("DROP TABLE IF EXISTS Suppliers;")
    cursor.execute("DROP TABLE IF EXISTS Budgets;")
    cursor.execute("DROP TABLE IF EXISTS Employees;")

    # Create Budgets table
    cursor.execute("""
    CREATE TABLE Budgets (
        Category TEXT PRIMARY KEY,
        Konto TEXT NOT NULL,
        Total_Budget REAL NOT NULL,
        Remaining_Budget REAL NOT NULL,
        Produkt TEXT NOT NULL,
        Auszahlungskonto TEXT NOT NULL,
        Account_Type TEXT NOT NULL,
        Department TEXT NOT NULL
    );
    """)

    # Create Suppliers table
    cursor.execute("""
    CREATE TABLE Suppliers (
        Name TEXT PRIMARY KEY,
        Is_Approved INTEGER NOT NULL,
        Category TEXT NOT NULL
    );
    """)

    # Create Audit_Logs table
    cursor.execute("""
    CREATE TABLE Audit_Logs (
        Id INTEGER PRIMARY KEY AUTOINCREMENT,
        Timestamp TEXT NOT NULL,
        Request_Text TEXT NOT NULL,
        Supplier TEXT NOT NULL,
        Amount REAL NOT NULL,
        Category TEXT NOT NULL,
        Decision TEXT NOT NULL,
        Reasoning TEXT NOT NULL
    );
    """)

    # Create Employees table (staff per department, used for the accessibility check)
    cursor.execute("""
    CREATE TABLE Employees (
        Department TEXT PRIMARY KEY,
        Total_Employees INTEGER NOT NULL,
        Employees_With_Special_Needs INTEGER NOT NULL
    );
    """)

    # Departments are keyed by the budget position they procure from
    employees = [
        ("IT-Ausstattung", 20, 2),
        ("Büromaterial", 10, 0),
        ("Fahrzeuge", 15, 0),
    ]
    cursor.executemany(
        "INSERT INTO Employees (Department, Total_Employees, Employees_With_Special_Needs) VALUES (?, ?, ?);",
        employees,
    )

    # Municipal budget positions (Haushaltsstellen / Konten), see src/demo_seed.py
    cursor.executemany(
        """INSERT INTO Budgets (Category, Konto, Total_Budget, Remaining_Budget, Produkt, Auszahlungskonto,
                               Account_Type, Department)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?);""",
        [
            (b["category"], b["konto"], b["total"], b["total"], b["produkt"], b["auszahlungskonto"],
             b["account_type"], b["department"])
            for b in BUDGET_LINES
        ],
    )

    # Approved suppliers and one deliberately blocked supplier for the demo
    suppliers = [
        ("Bechtle GmbH", 1, "IT-Ausstattung"),
        ("Dell Technologies", 1, "IT-Ausstattung"),
        ("Cancom SE", 1, "IT-Ausstattung"),
        ("Stadtwerke Hildesheim", 1, "Fahrzeuge"),
        ("OfficeDepot Deutschland", 1, "Büromaterial"),
        ("TechCorp", 0, "IT-Ausstattung"),
    ]
    cursor.executemany(
        "INSERT INTO Suppliers (Name, Is_Approved, Category) VALUES (?, ?, ?);",
        suppliers,
    )

    # Demo history of decided requests (relative dates), also used to detect contract extensions
    now = datetime.now().replace(microsecond=0)
    audit_history = []
    for entry in HISTORICAL_REQUESTS:
        reasoning = (
            "Geprüft: Lieferant zugelassen, Budget ausreichend. Freigabe erteilt."
            if entry["decision"] == "APPROVED"
            else "Ablehnung: " + (entry.get("agent_reason") or (entry.get("note") or {}).get("DE", ""))
        )
        audit_history.append(
            (
                (now - timedelta(days=entry["days_ago"])).isoformat(),
                entry["text"]["DE"],
                entry["supplier"],
                entry["amount"],
                entry["category"],
                entry["decision"],
                reasoning,
            )
        )
    cursor.executemany("""
        INSERT INTO Audit_Logs (Timestamp, Request_Text, Supplier, Amount, Category, Decision, Reasoning)
        VALUES (?, ?, ?, ?, ?, ?, ?);
    """, audit_history)

    # Deduct the already approved historical commitments from the budget
    for log in audit_history:
        if log[5].upper() == "APPROVED":
            cursor.execute(
                "UPDATE Budgets SET Remaining_Budget = Remaining_Budget - ? WHERE Category = ?;",
                (log[3], log[4]),
            )

    conn.commit()
    conn.close()
    print(f"Database successfully initialized and seeded with realistic municipal data at: {db_path}")


if __name__ == "__main__":
    init_db()
