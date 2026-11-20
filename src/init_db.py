import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "../data/mock_data.db")

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Drop existing tables to ensure a clean reset
    cursor.execute("DROP TABLE IF EXISTS Audit_Logs;")
    cursor.execute("DROP TABLE IF EXISTS Suppliers;")
    cursor.execute("DROP TABLE IF EXISTS Budgets;")
    
    # Create Budgets table
    cursor.execute("""
    CREATE TABLE Budgets (
        Category TEXT PRIMARY KEY,
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
    
    # Seed mock budgets
    budgets = [
        ("IT", 100000.0, 100000.0),
        ("Construction", 500000.0, 500000.0),
        ("Office Supplies", 25000.0, 25000.0)
    ]
    cursor.executemany("INSERT INTO Budgets (Category, Total_Budget, Remaining_Budget) VALUES (?, ?, ?);", budgets)
    
    # Seed mock suppliers
    suppliers = [
        ("Apple", 1, "IT"),
        ("Dell", 1, "IT"),
        ("TechCorp", 0, "IT"),
        ("BuildCorp", 1, "Construction"),
        ("OfficeDepot", 1, "Office Supplies")
    ]
    cursor.executemany("INSERT INTO Suppliers (Name, Is_Approved, Category) VALUES (?, ?, ?);", suppliers)
    
    conn.commit()
    conn.close()
    print(f"Database successfully initialized and seeded at: {DB_PATH}")

if __name__ == "__main__":
    init_db()
