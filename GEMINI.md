# Project: Public Procurement Trust Agent
This project is a hackathon prototype for Challenge (AI Agents for Public Administration). 
It is an AI agent that assists caseworkers by validating procurement requests (tenders) against a mock budget and approved supplier database.

## 🎯 Core Objective
To reduce the workload of public administration caseworkers by automatically checking routine procurement requests. The agent must be **trustworthy**, meaning it must explain its reasoning clearly so a human caseworker can verify it.

## 🏗️ Architecture & File Structure
- `app.py`: The Streamlit frontend UI. Handles user input and displays the agent's output (including reasoning).
- `src/agent.py`: The backend agent logic. It takes the user's request, queries the database, applies validation rules, and returns the decision.
- `data/mock_data.db`: A SQLite database containing mock budgets and suppliers.
- `.env`: Contains the `GEMINI_API_KEY`.

## 🛠️ Tech Stack
- **Frontend:** Streamlit (Python)
- **Backend/Database:** Python 3.10+, SQLite (using built-in `sqlite3`)
- **AI Framework:** Official Google GenAI SDK (from google import genai, using client = genai.Client()) — do NOT use deprecated google.generativeai or LangChain.
- **Runtime:** Always execute scripts and tests using .venv/bin/python.

## 📜 Permanent Rules & Constraints
1. **Explainability is Mandatory:** Every decision (Approve, Reject, or Escalate) MUST be accompanied by a clear, step-by-step reasoning block (e.g., "Checked budget: €50k available. Requested: €40k. Status: OK.").
2. **Keep it Simple:** Do not over-engineer. No complex vector databases. Stick to SQLite and standard Python. We are on a hackathon time limit.
3. **Separation of Concerns:** UI code stays in `app.py`. Database queries and AI logic stay in `src/agent.py`.
4. **Mock Data Only:** Do not attempt to connect to real government APIs. All data must be mock data stored in the local SQLite database.
5. **Human-in-the-Loop Action:** When a caseworker clicks "Approve" in the UI, commit the budget deduction and audit log entry to data/mock_data.db so the database state updates live during the demo.