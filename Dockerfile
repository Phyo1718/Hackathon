# syntax=docker/dockerfile:1
# Public Procurement Assistant (Stadt Hildesheim) – runtime image.
#
# Contains only what the app needs at runtime. The user manual is built locally with
# scripts/build_manual.py (needs Chrome and Node); the image ships the prebuilt PDFs.
# The Gemini API key is never part of the image: it is passed at runtime (docker compose
# env_file / Kubernetes Secret).

# Same Python version as the development environment
FROM python:3.12.0-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PROCUREMENT_DB_PATH=/app/data/mock_data.db \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app

# Dependencies first (cached as long as requirements.txt does not change); all versions pinned
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Non-root user. /app/data holds the SQLite database and history.json (a volume in compose).
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data \
    && chown appuser:appuser /app/data

COPY .streamlit/config.toml .streamlit/config.toml
COPY app.py .
COPY src/ src/
# Self-hosted fonts and illustrations of the UI theme (served at app/static/, see .streamlit/config.toml)
COPY static/ static/
# Prebuilt user manuals (sidebar download) and the overview diagram (Management Insights)
COPY docs/Benutzerhandbuch.pdf docs/User_Manual.pdf docs/
COPY docs/manual/diagrams/1_overview_de.png docs/manual/diagrams/1_overview_en.png docs/manual/diagrams/
# Knowledge of the help assistant (user manual text and the procurement process steps)
COPY docs/manual/user_manual_de.md docs/manual/user_manual_en.md docs/manual/process_steps_de.md docs/manual/

USER appuser
EXPOSE 8501

# python:slim has no curl; the standard library is enough
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=4).status == 200 else 1)"

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
