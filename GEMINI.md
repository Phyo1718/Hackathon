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
- **Backend/Database:** Python 3.12+, SQLite (using built-in `sqlite3`)
- **AI Framework:** Official Google GenAI SDK (from google import genai, using client = genai.Client()) — do NOT use deprecated google.generativeai or LangChain.
- **Runtime:** Always execute scripts and tests using the project virtual environment's interpreter: `.venv\Scripts\python` on Windows, `.venv/bin/python` on macOS/Linux.

## 📜 Permanent Rules & Constraints
1. **Explainability is Mandatory:** Every decision (Approve, Reject, or Escalate) MUST be accompanied by a clear, step-by-step reasoning block (e.g., "Checked budget: €50k available. Requested: €40k. Status: OK.").
2. **Keep it Simple:** Do not over-engineer. No complex vector databases. Stick to SQLite and standard Python. We are on a hackathon time limit.
3. **Separation of Concerns:** UI code stays in `app.py`. Database queries and AI logic stay in `src/agent.py`.
4. **Mock Data Only:** Do not attempt to connect to real government APIs. All data must be mock data stored in the local SQLite database.
5. **Human-in-the-Loop Action:** When a caseworker clicks "Approve" in the UI, commit the budget deduction and audit log entry to data/mock_data.db so the database state updates live during the demo.

# Reference Documents (Hildesheim Procurement)
Located in the `docs/` folder. Use these documents as the absolute source of truth for formatting outputs, understanding the workflow, and applying legal rules.

1. `Challange 1 Beschreibung Routineprozesse.pdf`: The master process document. It explains the manual pain points of the Hildesheim administration. Use this to understand the "System Fit" and the steps a caseworker must take.
2. `Anmeldebogen_LuD_Hackathon.pdf`: The official 5-page registration form for a NEW procurement (Lieferung und Dienstleistung). Use this template when generating a new procurement document.
3. `Anmeldebogen_Auftragserweiterung_Hackathon.pdf`: The official form for a CONTRACT EXTENSION. If a user requests more of the same item from an already approved supplier, use this shorter form instead of the LuD form.
4. `Antrag_ED_Hackathon.pdf`: The form for budget reallocations (Etat-Deckung). Use this if a request exceeds a specific budget and needs funds moved from another account.
5. `Auswertung_Hackathon.XLSX`: The official Excel scoring matrix. It uses a specific interpolation formula for Price (30%), References (30%), and Concept (20%). Use this logic if evaluating multiple suppliers.

**Key Rules for the Agent:**
- If a request is for a brand new item/supplier, generate a draft based on `Anmeldebogen_LuD`.
- If a request says "extend" or "buy 5 more of the same," generate a draft based on `Anmeldebogen_Auftragserweiterung`.
- Always cite which official form you are generating so the caseworker knows.