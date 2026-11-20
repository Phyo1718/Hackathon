# Hackathon TODO List: Public Procurement Trust Agent

## 📦 Phase 1: Database & Mock Data (`src/init_db.py`)
- [x] **Task 1:** Create `src/init_db.py` to initialize `data/mock_data.db` with three tables:
  - `Budgets` (`Category`, `Total_Budget`, `Remaining_Budget`)
  - `Suppliers` (`Name`, `Is_Approved`, `Category`)
  - `Audit_Logs` (`Id`, `Timestamp`, `Request_Text`, `Supplier`, `Amount`, `Category`, `Decision`, `Reasoning`)
- [x] **Task 2:** Seed realistic mock data in `src/init_db.py` (e.g., IT Budget: €100,000, Construction Budget: €500,000; Approved IT Suppliers: Apple, Dell; Unapproved: TechCorp) and make sure running the script resets the database cleanly.

## 🧠 Phase 2: The Agent Logic (`src/agent.py`)
- [ ] **Task 3:** Write deterministic database tool functions in `src/agent.py`:
  - `check_budget(request_amount, category)` — returns remaining budget and sufficiency status.
  - `check_supplier(supplier_name)` — verifies whether the supplier exists and is approved.
  - `commit_decision(request_data, decision, reasoning)` — deducts `request_amount` from `Remaining_Budget` (if approved) and writes an entry to `Audit_Logs`.
- [ ] **Task 4:** Implement `evaluate_request(text)` in `src/agent.py` using **Gemini Structured Outputs** (`google-genai` SDK with a Pydantic schema for `supplier_name`, `amount`, `category`, and `summary`) to extract parameters, run the tool checks, and return a decision (`APPROVED`, `REQUIRES_REVIEW`, or `REJECTED`) with step-by-step reasoning.

## 🎨 Phase 3: The User Interface (`app.py`)
- [ ] **Task 5:** Build the Streamlit UI in `app.py` with:
  - A PDF uploader (`st.file_uploader` using `pypdf`) that extracts text directly into the request text area.
  - A text area for pasting/editing procurement requests and an **"Evaluate Request"** button.
  - Live sidebar tables showing current `Budgets` and `Audit_Logs` from `data/mock_data.db`, plus a **"Reset Demo Data"** button.
- [ ] **Task 6:** Display the Agent's decision in a color-coded status banner (Green = Approved, Yellow = Requires Human Review, Red = Rejected) alongside the step-by-step **Reasoning** breakdown.

## 🔗 Phase 4: Integration, Trust & Demo Polish
- [ ] **Task 7:** Connect `app.py` to `src/agent.py` and add **"Approve & Commit to Budget"** / **"Reject"** human-in-the-loop buttons so caseworkers can confirm borderline or valid requests and update `data/mock_data.db` live.
- [ ] **Task 8:** Add 3 one-click **Sample Request** buttons in the UI (1 valid request, 1 unapproved supplier, 1 borderline/over-budget request) and an optional **English / German UI** toggle for the jury demo.

## 🎤 Phase 5: Testing & Pitch Prep
- [ ] **Task 9:** Run end-to-end verification across all 3 sample scenarios + 1 sample PDF upload, confirming live budget updates and audit log entries.
- [ ] **Task 10:** Prepare a crisp 3-minute live demo flow and slide deck highlighting problem understanding, system fit for Hildesheim administration, and live human-in-the-loop validation.