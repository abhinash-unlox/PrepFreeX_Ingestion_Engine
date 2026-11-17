# Windows Setup (PowerShell)

Prerequisites: Python 3.11+, Docker Desktop, and (recommended for scanned PDFs) Tesseract OCR with English language data.

```powershell
cd PrepFreeX
Copy-Item .env.example .env
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[test]"
docker compose up -d
qbank migrate
qbank seed-taxonomy --persist
```

Run the supplied MathonGo pilot:

```powershell
qbank ingest "data\input\Alternating Current - JEE Main 2026 (Jan) - MathonGo.pdf" --taxonomy "db\seeds\jee_main_2027_taxonomy.json" --persist
```

Start the local upload API:

```powershell
uvicorn prepfreex_ingest.api:app --reload
```

Open `http://127.0.0.1:8000/docs` and upload a PDF through `POST /api/ingestion/upload`.
