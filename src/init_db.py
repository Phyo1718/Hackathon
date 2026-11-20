import os
import sqlite3

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

    # Create Budgets table
    cursor.execute("""
    CREATE TABLE Budgets (
        Category TEXT PRIMARY KEY,
        Konto TEXT NOT NULL,
        Total_Budget REAL NOT NULL,
        Remaining_Budget REAL NOT NULL
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

    # Realistic municipal budget positions (Haushaltsstellen / Konten)
    budgets = [
        ("IT-Ausstattung", "542900", 150000.0, 150000.0),
        ("Büromaterial", "543100", 25000.0, 25000.0),
        ("Fahrzeuge", "544000", 80000.0, 80000.0),
    ]
    cursor.executemany(
        "INSERT INTO Budgets (Category, Konto, Total_Budget, Remaining_Budget) VALUES (?, ?, ?, ?);",
        budgets,
    )

    # Approved suppliers and one deliberately blocked supplier for the demo
    suppliers = [
        ("Bechtle GmbH", 1, "IT-Ausstattung"),
        ("Dell Technologies", 1, "IT-Ausstattung"),
        ("Stadtwerke Hildesheim", 1, "Fahrzeuge"),
        ("OfficeDepot Deutschland", 1, "Büromaterial"),
        ("TechCorp", 0, "IT-Ausstattung"),
    ]
    cursor.executemany(
        "INSERT INTO Suppliers (Name, Is_Approved, Category) VALUES (?, ?, ?);",
        suppliers,
    )

    # Pre-existing audit history so the agent can identify contract extensions
    audit_history = [
        (
            "2026-09-12T09:15:00",
            "Beschaffung von 20 Arbeitsplatzrechnern (Dell Latitude) für die Stadtverwaltung.",
            "Dell Technologies",
            18500.0,
            "IT-Ausstattung",
            "APPROVED",
            "Geprüft: Lieferant zugelassen, Budget ausreichend. Freigabe erteilt.",
        ),
        (
            "2026-09-28T13:20:00",
            "Nachbestellung von 12 Monitoren und Dockingstationen für das Rathaus.",
            "Bechtle GmbH",
            7200.0,
            "IT-Ausstattung",
            "APPROVED",
            "Geprüft: Lieferant zugelassen, Budget ausreichend. Freigabe erteilt.",
        ),
        (
            "2026-10-05T14:20:00",
            "Beschaffung von Büromaterial und Verbrauchsmaterial für die Fachbereiche.",
            "OfficeDepot Deutschland",
            3450.0,
            "Büromaterial",
            "APPROVED",
            "Geprüft: Lieferant zugelassen, Budget ausreichend. Freigabe erteilt.",
        ),
        (
            "2026-10-19T10:05:00",
            "Wartung und Instandhaltung von Dienstfahrzeugen des Bauhofs.",
            "Stadtwerke Hildesheim",
            6400.0,
            "Fahrzeuge",
            "APPROVED",
            "Geprüft: Lieferant zugelassen, Budget ausreichend. Freigabe erteilt.",
        ),
        (
            "2026-10-28T13:40:00",
            "Beschaffung von Servernetzwerkkomponenten für das Rechenzentrum.",
            "TechCorp",
            38000.0,
            "IT-Ausstattung",
            "REJECTED",
            "Ablehnung: Lieferant ist nicht im zugelassenen Lieferantenverzeichnis registriert.",
        ),
    ]
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
