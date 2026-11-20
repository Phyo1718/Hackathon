# Public Procurement Trust Agent

Streamlit + Google Gemini + SQLite prototype that checks municipal procurement requests
against a mock budget and supplier register. See `GEMINI.md` for the project rules.

## Run locally

Requires **Python 3.12+** and a Google Gemini API key. The app has no offline mode and
shows only a setup error if no key is configured.

Windows (PowerShell):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env   # then set GEMINI_API_KEY=<your key> in .env
streamlit run app.py
```

macOS / Linux:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then set GEMINI_API_KEY=<your key> in .env
streamlit run app.py
```

The SQLite database (`data/mock_data.db`) is created on first start. Use **Reset Demo Data**
in the sidebar, or `python -m src.init_db`, to restore the seed data. Set
`PROCUREMENT_DB_PATH` to use a different database file.

## Run the tests

```bash
python -m unittest discover -s tests -v
```

The tests mock Gemini and use a temporary database, so they need no API key or network
access and never modify `data/mock_data.db`.
