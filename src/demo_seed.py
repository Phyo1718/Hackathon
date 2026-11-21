"""Seed data for the demo: the requests queued at startup and the example tender in the bid
history. Used only to initialise the demo state (startup and Reset Demo Data); the live Bid
data table is built exclusively from uploaded PDFs and never reads from this module.
"""

# Pending requests in the queue at startup. "sample" names the request text in the app's
# SAMPLE_REQUESTS. The fields are pre-extracted, so seeding needs no Gemini call; the
# deterministic checks (supplier, budget, history, accessibility) still run as usual.
SEED_REQUESTS = [
    ("VA-2026-0001", "valid", {
        "supplier_name": "Dell Technologies", "amount": 14500.0, "category": "IT-Ausstattung",
        "summary": {"EN": "15 Dell laptops for the digital administration team",
                    "DE": "15 Dell Laptops für das digitale Verwaltungsteam"},
    }),
    ("VA-2026-0002", "unapproved", {
        "supplier_name": "TechCorp", "amount": 38000.0, "category": "IT-Ausstattung",
        "summary": {"EN": "Server infrastructure setup by TechCorp",
                    "DE": "Einrichtung einer Serverinfrastruktur durch TechCorp"},
    }),
    ("VA-2026-0003", "review", {
        "supplier_name": "Stadtwerke Hildesheim", "amount": 76000.0, "category": "Fahrzeuge",
        "summary": {"EN": "Service vehicle for the municipal works department",
                    "DE": "Dienstleistungsfahrzeug für den Bauhof"},
    }),
]

# Example tender pre-seeded in the bid history (official sheet criteria)
SEED_TENDER = {
    "ref": "VA-2025-0412",
    "title": {"EN": "15 laptops for the city administration", "DE": "15 Laptops für die Stadtverwaltung"},
    "evaluated_at": "2025-11-14T10:30:00",
    # Completed: award approved, award and rejection letters sent
    "approved_at": "2025-11-16T15:00:00",
    "award_sent_at": "2025-11-17T09:00:00",
    "rejections_sent_at": "2025-11-17T09:30:00",
    # Email addresses on the reserved .example domain only (no real company is emailed)
    "bids": [
        {"bidder": "Bechtle GmbH", "price": 15200.0, "references_score": 8, "concept_score": 7,
         "item": "15 HP EliteBook Laptops", "quantity": 15, "email": "vergabe@bechtle.example"},
        {"bidder": "Dell Technologies", "price": 14500.0, "references_score": 7, "concept_score": 6,
         "item": "15 Dell Latitude Laptops", "quantity": 15, "email": "angebote@dell.example"},
        {"bidder": "OfficeDepot Deutschland", "price": 16200.0, "references_score": 6, "concept_score": 8,
         "item": "15 Lenovo ThinkPad Laptops", "quantity": 15, "email": "vertrieb@officedepot.example"},
    ],
}

# Budget lines. Konto/Produkt/Auszahlungskonto numbers are demo values. The first three are
# the original lines; the last two give an overrun on "Fahrzeuge" donors of both account
# types in other departments (same type -> § 19 KomHKVO, other type -> § 117 NKomVG).
BUDGET_LINES = [
    {"category": "IT-Ausstattung", "konto": "542900", "total": 150000.0, "produkt": "111080 IT-Service",
     "auszahlungskonto": "742900", "account_type": "Aufwand", "department": "FB 10 Zentrale Dienste"},
    {"category": "Büromaterial", "konto": "543100", "total": 25000.0, "produkt": "111030 Zentrale Dienste",
     "auszahlungskonto": "743100", "account_type": "Aufwand", "department": "FB 10 Zentrale Dienste"},
    {"category": "Fahrzeuge", "konto": "544000", "total": 80000.0, "produkt": "541010 Bauhof",
     "auszahlungskonto": "744000", "account_type": "Aufwand", "department": "FB 66 Tiefbau und Bauhof"},
    {"category": "Gebäudeunterhaltung", "konto": "521100", "total": 60000.0, "produkt": "111060 Gebäudemanagement",
     "auszahlungskonto": "721100", "account_type": "Aufwand", "department": "FB 65 Gebäudemanagement"},
    {"category": "Feuerwehrtechnik", "konto": "072100", "total": 120000.0, "produkt": "126010 Brandschutz",
     "auszahlungskonto": "783100", "account_type": "Investiv", "department": "FB 37 Feuerwehr"},
]

# Decided requests of the last six months (demo history). Dates are relative to the day the
# demo is (re)seeded, so the 90-day forecast always has data. They feed both the audit log
# (budgets, contract-extension detection) and the request history (AI-oversight figures).
# The "H" references keep them out of the numbering of new requests. For the bid evaluation
# of VA-2026-0001 the three demo bidders differ in track record: Bechtle has completed IT
# contracts, Dell is on the approved list only, OfficeDepot is approved for office supplies only.
HISTORICAL_REQUESTS = [
    {"ref": "VA-2026-H01", "days_ago": 160, "supplier": "Cancom SE", "amount": 18500.0, "category": "IT-Ausstattung",
     "text": {"DE": "Beschaffung von 20 Arbeitsplatzrechnern für die Stadtverwaltung.",
              "EN": "Procurement of 20 workstations for the city administration."},
     "agent_decision": "APPROVED", "decision": "APPROVED"},
    {"ref": "VA-2026-H02", "days_ago": 75, "supplier": "Bechtle GmbH", "amount": 7200.0, "category": "IT-Ausstattung",
     "text": {"DE": "Nachbestellung von 12 Monitoren und Dockingstationen für das Rathaus.",
              "EN": "Reorder of 12 monitors and docking stations for the town hall."},
     "agent_decision": "APPROVED", "decision": "APPROVED"},
    {"ref": "VA-2026-H03", "days_ago": 50, "supplier": "OfficeDepot Deutschland", "amount": 3450.0, "category": "Büromaterial",
     "text": {"DE": "Beschaffung von Büromaterial und Verbrauchsmaterial für die Fachbereiche.",
              "EN": "Office supplies and consumables for the departments."},
     "agent_decision": "APPROVED", "decision": "APPROVED"},
    {"ref": "VA-2026-H04", "days_ago": 85, "supplier": "Stadtwerke Hildesheim", "amount": 6400.0, "category": "Fahrzeuge",
     "text": {"DE": "Wartung und Instandhaltung von Dienstfahrzeugen des Bauhofs.",
              "EN": "Maintenance of service vehicles for the municipal works department."},
     "agent_decision": "APPROVED", "decision": "APPROVED"},
    {"ref": "VA-2026-H05", "days_ago": 60, "supplier": "TechCorp", "amount": 38000.0, "category": "IT-Ausstattung",
     "text": {"DE": "Beschaffung von Servernetzwerkkomponenten für das Rechenzentrum.",
              "EN": "Server network components for the data centre."},
     "agent_decision": "REJECTED", "decision": "REJECTED",
     "agent_reason": "Supplier is either unapproved or unknown."},
    {"ref": "VA-2026-H06", "days_ago": 30, "supplier": "Bechtle GmbH", "amount": 9800.0, "category": "IT-Ausstattung",
     "text": {"DE": "Beschaffung von 40 Dockingstationen für mobile Arbeitsplätze.",
              "EN": "40 docking stations for mobile workplaces."},
     "agent_decision": "APPROVED", "decision": "APPROVED"},
    {"ref": "VA-2026-H07", "days_ago": 40, "supplier": "Stadtwerke Hildesheim", "amount": 900.0, "category": "Fahrzeuge",
     "text": {"DE": "Reifenwechsel für die Fahrzeuge des Bauhofs.",
              "EN": "Tyre change for the municipal works vehicles."},
     "agent_decision": "APPROVED", "decision": "APPROVED"},
    # An override: the agent recommended approval, the caseworker rejected it
    {"ref": "VA-2026-H08", "days_ago": 20, "supplier": "OfficeDepot Deutschland", "amount": 4200.0, "category": "Büromaterial",
     "text": {"DE": "Beschaffung von 12 Bürostühlen für das Bürgerbüro.",
              "EN": "12 office chairs for the citizens' office."},
     "agent_decision": "APPROVED", "decision": "REJECTED",
     "note": {"DE": "Bedarf wird über den bestehenden Rahmenvertrag für Büromöbel gedeckt.",
              "EN": "Covered by the existing framework contract for office furniture."}},
]
