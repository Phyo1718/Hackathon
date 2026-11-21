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

**Help assistant.** A chat button at the bottom right answers questions about using the app.
It knows only the user manual (`docs/manual/user_manual_de.md` / `_en.md`) and the procurement
steps from the challenge description (`docs/manual/process_steps_de.md`). It receives only the
question, the chat history of the session and the name of the current page, and it cannot
change anything. Set `ENABLE_CHAT=false` in `.env` to hide it.

The SQLite database (`data/mock_data.db`) is created on first start. Use **Reset Demo Data**
in the sidebar, or `python -m src.init_db`, to restore the seed data. Set
`PROCUREMENT_DB_PATH` to use a different database file.

## Run with Docker

Requires Docker Desktop (or another Docker engine with Compose v2) and a Google Gemini API key.

1. Copy the example environment file and add your key:

   ```bash
   cp .env.example .env          # then set GEMINI_API_KEY=<your key> in .env
   ```

2. Build and start the app:

   ```bash
   docker compose up --build
   ```

3. Open <http://localhost:8501>.

The key is read from `.env` when the container starts. It is not copied into the image
(`.dockerignore` excludes `.env`) and the app never prints it. `docker compose ps` shows the
container as `healthy` once Streamlit answers on `/_stcore/health`.

**Data.** The SQLite database and `history.json` (decisions, bid evaluations, letters) live
in the named volume `procurement-data`, mounted at `/app/data`. They survive
`docker compose down` and `docker compose up`.

**Reset the demo data.**
- In the app: **Reset Demo Data** in the sidebar.
- Or remove the volume; the app reseeds the demo data on the next start:

  ```bash
  docker compose down -v
  ```

**Stop the app.**
- `Ctrl+C` in the terminal running `docker compose up`.
- Or, from another terminal, `docker compose down`. This keeps the data.

**Check that no secret is in the image.** Both commands must print nothing (`grep` exits with 1):

```bash
docker history --no-trunc procurement-assistant:latest | grep -i -E "GEMINI|GOOGLE_API"
docker run --rm --entrypoint sh procurement-assistant:latest -c "ls -a /app" | grep -x ".env"
```

**Build for Intel and Apple Silicon.** On an Apple Silicon Mac, `docker compose up --build`
builds an `arm64` image. To build one image for both `linux/amd64` (Intel, Windows) and
`linux/arm64`, push it to a registry:

```bash
docker buildx create --name multiarch --use    # once
docker buildx build --platform linux/amd64,linux/arm64 \
  -t <registry>/procurement-assistant:1.0 --push .
```

To build only the Intel variant locally (for example, to hand it to a Windows machine):

```bash
docker buildx build --platform linux/amd64 -t procurement-assistant:amd64 --load .
docker save procurement-assistant:amd64 | gzip > procurement-assistant-amd64.tar.gz
```

**What the image contains.**
- Included: `app.py`, `src/`, the Streamlit theme, the two prebuilt user manuals (`docs/*.pdf`)
  and the overview diagram. It runs as the non-root user `appuser` on Python 3.12.0.
- Not included: tests, the manual build tooling (Chrome, Node, `scripts/`) and local data.
- The manuals are rebuilt locally with `python scripts/build_manual.py`, then the image is
  rebuilt.

`k8s/` holds a minimal Kubernetes example (Deployment with a volume for the data, Service,
Secret for the key). It is an untested example, not a supported setup.

## Run the tests

```bash
python -m unittest discover -s tests -v
```

The tests mock Gemini and use a temporary database, so they need no API key or network
access and never modify `data/mock_data.db`.
