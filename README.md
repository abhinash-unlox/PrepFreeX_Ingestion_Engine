# PrepFreeX — Autonomous JEE Main Assessment & Embibe-Inspired Ingestion Platform

PrepFreeX is an enterprise-grade, local-first assessment platform and autonomous question synthesis engine built specifically for NTA JEE Main examination preparation. It combines high-throughput historical PDF question extraction, strict curriculum alignment (64 units / 256 subtopics), local MinIO S3-compatible diagram storage, and an **Embibe-inspired dual-agent parametric variant synthesis engine** with blind-solver parity verification.

---

## 1. System Architecture

```
                                  PREPFREEX SYSTEM ARCHITECTURE
                                  
  ┌────────────────────────────────┐            ┌────────────────────────────────┐
  │   Next.js 14 Student Client    │            │     Streamlit Admin Portal     │
  │     (v0-prepfreex-frontend)    │            │       (apps/admin:8501)        │
  │      http://localhost:3000     │            │   (Teacher / Reviewer Portal)  │
  └───────────────┬────────────────┘            └───────────────┬────────────────┘
                  │                                             │
                  │              REST API (JSON / Bearer)       │
                  └───────────────────────┬─────────────────────┘
                                          │
                                          ▼
                         ┌─────────────────────────────────┐
                         │        FastAPI Core API         │
                         │         (apps/api:8000)         │
                         │  - /api/v1/assessments          │
                         │  - /api/v1/staging              │
                         │  - /api/v1/questions            │
                         └──────────────┬──────────────────┘
                                        │
                 ┌──────────────────────┴──────────────────────┐
                 │                                             │
                 ▼                                             ▼
  ┌───────────────────────────────┐             ┌───────────────────────────────┐
  │   PostgreSQL 18.6 Database    │             │   MinIO S3 Object Storage     │
  │  (jee_mains_assesment_work)   │             │       (127.0.0.1:9000)        │
  │   - public.completed_questions│             │   - Diagram Assets & Figures  │
  │     (4,872 Clean Eligible Qs) │             │   - question-assets/ bucket   │
  │   - public.staged_questions   │             └───────────────────────────────┘
  │     (Air-gapped verification) │
  │   - public.pdf_manifest       │
  │     (801 tracked PDFs)        │
  └───────────────────────────────┘
                 ▲                                             ▲
                 │ (Promote Verified)                          │ (Store Crop Figures)
                 │                                             │
  ┌──────────────┴─────────────────────────────────────────────┴────────────────┐
  │                   Safe 4-Layer PDF Question Ingestion Pipeline              │
  │                   (engines/ingestion/full_test_ingestor.py)                 │
  │                                                                             │
  │  [Raw Full-Length Test PDF] ──► [Layer 1: Academic Guardrails (0 Tokens)]   │
  │                                             │                               │
  │                         ┌───────────────────┴───────────────────┐           │
  │                         ▼ (Passed)                              ▼ (Failed)  │
  │           [Layer 2: 3-Tier Classifier]                  [REJECTED in DB]    │
  │               (Subject → Unit → Subtopic)                                   │
  │                         │                                                   │
  │                         ▼                                                   │
  │           [Layer 3: AIR-1 Blind Solver]                                     │
  │             (Solves from 1st principles)                                    │
  │                         │                                                   │
  │        ┌────────────────┴────────────────┐                                  │
  │        ▼ (Solver == Official Key)        ▼ (Discrepancy)                    │
  │  [APPROVED & Auto-Promote]        [PENDING_REVIEW in Staging]               │
  │   ──► completed_questions          ──► Reviewed via UI at :3000              │
  └─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Safe Question Ingestion & 4-Layer Verification Pipeline

To ingest hundreds of official JEE Main past papers without ever risking database pollution or LLM hallucinations, PrepFreeX implements a strict **4-layer air-gapped staging architecture**.

```
[Raw Shift PDF + Official Key Table]
                  │
                  ▼
┌─────────────────────────────────────────────────────────┐
│ Layer 1: Zero-Token Academic Guardrails                 │
│ (engines/ingestion/guardrails.py)                       │
│ - 0 LLM tokens spent. Deterministic regex & AST filter. │
│ - Checks: Stripped exponents (1010), dangling           │
│   punctuation ("strain of ."), empty options, missing   │
│   figures, coaching watermarks, unbalanced LaTeX.       │
└──────────────────────────┬──────────────────────────────┘
                           │ Passed (Clean question stem & 4 options)
                           ▼
┌─────────────────────────────────────────────────────────┐
│ Layer 2: Autonomous CurriculumEngine                    │
│ (engines/ingestion/curriculum_engine.py)                │
│ - Deterministic regex scoring across Math/Physics/Chem. │
│ - Model: openai/gpt-oss-20b with rotating Groq keys.    │
│ - Maps: Subject ──► Canonical Unit ──► Subtopic Code    │
│   (e.g., CHEM_U23_T03, PHYS_U02_T02, MATH_U04_T01).    │
│ - Database foreign-key validated vs public.chapter_topics│
└──────────────────────────┬──────────────────────────────┘
                           │ Structured Classification
                           ▼
┌─────────────────────────────────────────────────────────┐
│ Layer 3: AIR-1 Blind Solver & Parity Arbiter            │
│ (engines/ingestion/blind_solver.py)                     │
│ - Model: openai/gpt-oss-120b.                           │
│ - Solves independently from first principles WITHOUT    │
│   seeing the official answer key.                       │
│ - Generates step-by-step mathematical/chemical LaTeX    │
│   derivation and outputs computed option/numeric value. │
└──────────────────────────┬──────────────────────────────┘
                           │
             ┌─────────────┴─────────────┐
             ▼                           ▼
[Parity MATCHED: Solver == Key]  [Parity DISCREPANCY / Uncertain]
             │                           │
             ▼                           ▼
┌───────────────────────────────┐ ┌───────────────────────────────┐
│ Status: APPROVED              │ │ Status: PENDING_REVIEW        │
│ Auto-promoted immediately to  │ │ Held in public.staged_        │
│ public.completed_questions    │ │ questions for teacher/human   │
│ (assessment_status='ELIGIBLE')│ │ inspection via UI.            │
└───────────────────────────────┘ └───────────────────────────────┘
```

### Database Tables & Quarantine Separation

1. **`public.staged_questions` (Air-Gapped Ingestion Area):**
   - Stores all incoming questions alongside raw PDF coordinates, page numbers, extracted options, official keys, solver derivations, and exact token logs.
   - Statuses: `APPROVED`, `PENDING_REVIEW`, `REJECTED`, `PROMOTED`.
   - Never exposed directly to students or test-generation endpoints.
2. **`public.completed_questions` (Production Question Bank):**
   - Active, live student repository (**4,872 clean eligible questions** across 64 canonical units).
   - Only receives questions that are either **auto-promoted after 100% blind parity verification** or manually approved by an educator in the UI.
   - Enforces `assessment_status = 'ELIGIBLE'`.
3. **`public.pdf_ingestion_manifest` (Manifest Tracker):**
   - Catalogs all 801 discovered raw PDFs across Physics, Chemistry, Mathematics, and Full Tests.
   - Tracks real-time status (`PENDING`, `IN_PROGRESS`, `COMPLETED`, `FAILED`), question counts, guardrail rejections, and tokens consumed.

---

## 3. Staging Review UI & Human-in-the-Loop Management

The interactive Review Dashboard is integrated directly into the Next.js frontend at **`http://localhost:3000`** under the **Staging Review** tab (`v0-prepfreex-frontend/components/staging-review.tsx`).

### Core UI Capabilities

1. **Live KPI Metric Cards:**
   - **Total Staged:** Total questions captured across all processed PDFs.
   - **Approved:** Questions passing guardrails and verified by solver parity.
   - **Pending Review:** Questions with answer key discrepancies flagged for educator review.
   - **Rejected:** Malformed or broken questions pruned by 0-token guardrails.
   - **Promoted Live:** Questions actively merged into `completed_questions`.
   - **Tokens Used:** Real-time token consumption tracked across Qwen and GPT models.
2. **Interactive Clickable Option Cards:**
   - Reviewers can click directly on any option ($A, B, C, D$) to override or correct the answer key.
   - Selecting an option updates the solver parity status and automatically moves the card to `APPROVED`.
3. **Step-by-Step Solver Proof Accordion:**
   - Expand the **"View AIR-1 Blind Solver Derivation"** toggle on any card to inspect the model's full mathematical and physical reasoning rendered in KaTeX.
4. **Autonomous Ingestion Controls:**
   - **`[⚡ Extract Next Questions from PDF]` Button:** Triggers the backend pipeline (`POST /api/v1/staging/ingest-next`) to pick the next pending PDF, run guardrails, classify, solve, and refresh the UI.
   - **`[↗ Promote Approved to Live]` Button:** Atomically promotes all approved staging questions into `public.completed_questions` using idempotent SQL (`ON CONFLICT (question_uid) DO UPDATE`).
   - **PDF Ingestion Tracker Tab:** Search and inspect all 801 PDFs with individual `Extract Now` action triggers.

---

## 4. How Extraction Works from Raw Test Papers

The extraction engine (`engines/ingestion/full_test_ingestor.py`) automates complete 90-question JEE Main shift papers (e.g. ExamGoal PYQs):

1. **Answer Key Table Parsing:** Parses the official tabular answer key on the final pages (`Chemistry Q1-Q21`, `Maths Q22-Q43`, `Physics Q44-Q90`).
2. **Question Block Segmentation:** Cleans header/footer watermarks (`ExamGOAL`, `Open solution`, `Keep practising...`) and splits blocks using regex boundaries (`\n(?=Q\d+\.)`).
3. **Stem & Option Extraction:** Extracts clean LaTeX stems and choices ($A, B, C, D$) or numeric targets.
4. **Subject Mapping:** Maps section question numbers to official subjects (`1..21` $\to$ Chemistry, `22..43` $\to$ Mathematics, `44..90` $\to$ Physics).
5. **CLI Batch Commands:**
   ```bash
   # Ingest a specific full test paper
   python -u scripts/run_automated_full_test_ingestion.py --pdf "data/raw/jee_dataset/full_tests/JEE Main 2022 (Online) 24th June Morning Shift Question Paper with Answer Key.pdf"

   # Ingest a slice of questions (e.g. Q16 to Q45)
   python -u scripts/run_automated_full_test_ingestion.py --start 16 --limit 30

   # Batch automate across multiple pending full-length shift papers
   python -u scripts/run_automated_full_test_ingestion.py --num-pdfs 3
   ```

---

## 5. Embibe-Inspired Architecture (Dual-Agent Synthesis)

Standard LLM generators frequently hallucinate arithmetic, miscalculate intermediate exponents, or leave outdated answer keys when altering numericals. PrepFreeX solves this by implementing Embibe's patented authoring methodology: **an unassisted blind solver must solve the candidate question from first principles and agree with the author before any question touches the database**.

### Pipeline Stages (`engines/synthesis/embibe_variant_engine.py`)
1. **Seed Selection:** Clean canonical exemplar questions are retrieved from `public.completed_questions`.
2. **Agent 1 — SME Author Generator:** Mutates variables, geometries, or chemical variants while preserving the core syllabus concept. Solves the modified problem and defines four distinct options (`A`, `B`, `C`, `D`).
3. **Agent 2 — AIR-1 Blind Solver:** The candidate question stem and options are presented to an independent solver model with **zero access** to the author's solution, key, or internal scratchpad.
4. **Parity Arbiter:** Compares the Author's key with the Blind Solver's derived key:
   - **MCQs:** Exact string match (`Author == Solver`).
   - **Numerical Questions:** Relative floating-point tolerance within $\pm 1\%$.
   - **Mismatch:** Automatically raises `BlindSolveParityError`, discarding the candidate.
5. **Database Sequence Ingestion:** Verified questions are assigned sequential IDs via `completed_questions_id_seq` and ingested with `academic_status = 'EMBIBE_VERIFIED'` and `assessment_status = 'ELIGIBLE'`.

---

## 6. Clean Project Directory Structure

```
PrepFreeX_Ingestion_Engine/
├── apps/
│   ├── api/                              # FastAPI core backend service (Port 8000)
│   │   ├── main.py                       # Application entrypoint & CORS configuration
│   │   ├── db.py                         # Connection pool & cursor context managers
│   │   ├── routes/                       # REST endpoints (assessments, staging, questions, auth)
│   │   │   ├── assessment_engine.py      # Assessment delivery, timing, cooldown & backfill
│   │   │   ├── assessment.py             # NTA scoring evaluations (+4/-1)
│   │   │   ├── staging.py                # Staging Review API (/summary, /manifest, /answer, /promote)
│   │   │   ├── questions.py              # Question catalog browsing & filtering
│   │   │   ├── auth.py                   # JWT authentication & student profile
│   │   │   ├── images.py                 # MinIO diagram presigning & proxying
│   │   │   └── taxonomy.py               # Canonical 64 chapters & 256 subtopics API
│   │   └── services/                     # Background AI explainer & variant services
│   └── admin/                            # Streamlit Reviewer & Admin Portal (Port 8501)
├── v0-prepfreex-frontend/                # Production Next.js 14 CBT Client (Port 3000)
│   ├── app/                              # App router pages & layouts
│   ├── components/                       # UI components (KaTeX, exam palette, timer)
│   │   ├── staging-review.tsx            # Air-gapped Staging Review & Verification UI
│   │   ├── assessment-client.tsx         # Live CBT Exam Engine (NTA simulation)
│   │   └── prepfreex-app.tsx             # Master navigation & application shell
│   └── lib/                              # API client, canonical taxonomy, and data contracts
├── engines/
│   ├── ingestion/                        # 4-Layer Safe Ingestion Pipeline
│   │   ├── full_test_ingestor.py         # Full-length shift paper parser (Q1-Q90 + Answer Keys)
│   │   ├── guardrails.py                 # Layer 1: 0-Token deterministic academic validator
│   │   ├── hierarchical_classifier.py    # Layer 2: 3-Tier Subject -> Unit -> Subtopic classifier
│   │   ├── blind_solver.py               # Layer 3: AIR-1 Blind Solver parity arbiter (120B)
│   │   ├── safe_ingestor.py              # Master orchestration & token logging
│   │   └── pdf_extractor.py              # PyMuPDF text & diagram rasterizer
│   ├── synthesis/                        # Embibe dual-agent variant synthesis engine
│   │   └── embibe_variant_engine.py      # SME generator, Blind Solver & Parity Arbiter
│   ├── assessment/                       # NTA scoring rules, timing models, psychometrics
│   ├── shared/                           # MinIO storage client, AssetManager, config & Groq rotator
│   └── variation/                        # Deterministic mathematical validator & variations
├── db/
│   ├── migrations/                       # Versioned SQL migrations (0001 - 0012)
│   └── seeds/                            # Official curriculum taxonomy seed files
├── reports/                              # Authoritative master project reports
│   ├── 01_CURRICULUM_AND_TAXONOMY_REPORT.md         # 64-chapter & 256-subtopic coverage
│   ├── 02_DATABASE_AUDIT_AND_QUARANTINE_LOG.md      # 539 quarantined defects forensic audit
│   ├── 03_EMBIBE_PARAMETRIC_SYNTHESIS_ARCHITECTURE.md # Technical synthesis blueprint
│   ├── 04_ASSESSMENT_ENGINE_AND_API_SPECIFICATION.md  # API spec, assessment modes & NTA scoring
│   ├── PrepFreeX_Ready_Questions_Review.csv         # 3,001 clean eligible questions catalog
│   └── PrepFreeX_Subtopic_Question_Counts.csv       # Live question counts per subtopic
├── scripts/                              # Core operational automation tools
│   ├── run_automated_full_test_ingestion.py         # Automated full test paper ingestion CLI
│   ├── safe_ingest.py                               # General safe ingestion batch runner
│   ├── export_updated_catalog_and_counts.py         # Regenerates official review CSVs
│   ├── run_embibe_synthesis_batch.py                # Batch CLI for dual-agent synthesis
│   ├── clean_and_upload_all_diagrams.py             # MinIO diagram cleaner and uploader
│   └── test_all_assessments_e2e.py                  # End-to-end assessment verification test
├── tests/                                # Comprehensive Pytest suite
│   ├── test_embibe_engine.py             # Embibe dual-agent verification tests
│   ├── test_admin_api.py                 # Admin API integration tests
│   ├── test_assessment_scoring.py        # NTA scoring logic tests
│   ├── test_taxonomy.py                  # Taxonomy hierarchy tests
│   └── test_deterministic.py             # Mathematical SymPy verification tests
├── data/                                 # Official reference syllabus & raw test PDFs
│   └── raw/jee_dataset/full_tests/       # 24 official ExamGoal JEE Main 2022 full test papers
├── pyproject.toml                        # Project dependencies & metadata
└── README.md                             # Primary technical documentation
```

---

## 7. Database Model & Integrity Guarantees

PrepFreeX operates under strict data separation to guarantee that student testing never corrupts canonical records:
- **`jee_mains_assesment` (Port 5432):** Master historical database (**100% Read-Only, Unaltered**).
- **`jee_mains_assesment_work` (Port 5432):** Active working database for all live assessments, staging verification, quarantine updates, and variant ingestions.

### Key Production Tables:
- **`public.completed_questions`:**
  - **`assessment_status = 'ELIGIBLE'`:** **3,070 clean, academically verified questions**.
  - **`assessment_status = 'BROKEN'`:** **539 permanently quarantined questions** (OCR drops, watermarks, stripped equations).
  - **Primary Key Sequence:** `completed_questions_id_seq` automatically assigns IDs to newly promoted questions.
  - **Serving Guarantee:** All student assessment queries enforce `WHERE assessment_status = 'ELIGIBLE'`.
- **`public.staged_questions`:** Air-gapped staging quarantine area logging exact tokens, guardrail flaws, and solver derivations.
- **`public.pdf_ingestion_manifest`:** Real-time state of all 801 raw PDFs discovered across the repository.

---

## 8. Assessment Modes & CBT Delivery

The platform supports 6 distinct assessment types adhering to the official NTA JEE Main pattern:
1. **Topic Practice (5 Qs, 15 min):** Focused conceptual drill on a single syllabus subtopic.
2. **Chapter Test (20 Qs, 60 min):** Comprehensive exam covering all 4 subtopics of a canonical chapter.
3. **Mixed-topic Test (20–60 Qs):** Multi-chapter customized test.
4. **Sectional Assessment (25 Qs, 60 min):** Timed single-subject exam (Physics, Chemistry, or Math).
5. **Full-length Mock (75 Qs, 180 min):** Exact JEE Main Paper 1 simulation (25 Physics, 25 Chemistry, 25 Math).
6. **Image Test (47 Qs, 60 min):** Specialized exam targeting questions with MinIO diagram figures.

### Dynamic Engine Protections
- **Anti-Repetition Exposure Cooldown:** Questions seen recently by a student are deprioritized.
- **Automatic Sparse Topic Backfill:** If a selected subtopic has fewer than 5 eligible questions, the engine seamlessly backfills from the same canonical chapter so exams always reach full length.
- **NTA Scoring Engine:** $+4$ for correct, $-1$ for incorrect, $0$ for unattempted.

---

## 9. Quickstart & How to Run the Platform

Follow these steps to set up and run the entire PrepFreeX platform locally from scratch.

### Prerequisites
- **Python 3.11+ / 3.12+**
- **Node.js 18+** & **pnpm** (`npm install -g pnpm`)
- **PostgreSQL 15+** (Running locally on port `5432`)
- **MinIO Object Storage** (Or local S3-compatible service on port `9000`)
- **Groq API Key(s)** (Free tier supported; multi-key rotation recommended)

---

### Step 1: Clone the Repository
```bash
git clone https://github.com/gauravsinghtanwar1/PrepFreeX_Ingestion_Engine.git
cd PrepFreeX_Ingestion_Engine
```

---

### Step 2: Configure Environment Variables
Copy the template configuration file:
```bash
cp .env.example .env
```
Edit `.env` with your local database credentials and Groq API keys:
```env
# PostgreSQL
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_DB=jee_mains_assesment_work
POSTGRES_USER=prepfreex_user
POSTGRES_PASSWORD=YourPasswordHere
DATABASE_URL=postgresql://prepfreex_user:YourPasswordHere@127.0.0.1:5432/jee_mains_assesment_work

# Groq LLM Key Rotation (Supports single or multiple comma-separated keys)
LLM_PROVIDER=groq
GROQ_MODEL=openai/gpt-oss-20b
GROQ_API_KEYS=gsk_key1,gsk_key2,gsk_key3,gsk_key4

# MinIO S3 Asset Storage
OBJECT_STORAGE_BACKEND=minio
MINIO_ENDPOINT=http://127.0.0.1:9000
MINIO_BUCKET=prepfreex-question-assets
MINIO_ACCESS_KEY=your_minio_access_key
MINIO_SECRET_KEY=your_minio_secret_key
MINIO_USE_SSL=false
```

---

### Step 3: Initialize PostgreSQL Database
Create the database and apply the schema migrations:
```powershell
# In PostgreSQL CLI (psql)
CREATE DATABASE jee_mains_assesment_work;

# Apply migrations sequentially
psql -U prepfreex_user -d jee_mains_assesment_work -f db/migrations/0001_initial_schema.sql
psql -U prepfreex_user -d jee_mains_assesment_work -f db/migrations/0002_add_quarantine_tables.sql
# ... (or apply all migrations in db/migrations/)
```

---

### Step 4: Start Services (3 Terminal Windows)

#### Terminal 1: Start MinIO Object Storage
```powershell
# If using the preconfigured MinIO script:
powershell -File "C:\tools\prepfreex-minio\start-minio.ps1"

# Or standard MinIO server:
minio server C:\PrepFreeX\minio-data --address ":9000" --console-address ":9001"
```

#### Terminal 2: Start FastAPI Core Backend
```powershell
# From project root:
python -m pip install -r requirements.txt
python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --reload
```
API Documentation and Swagger UI will be available at **`http://127.0.0.1:8000/docs`**.

#### Terminal 3: Start Next.js Frontend
```powershell
cd v0-prepfreex-frontend
pnpm install
pnpm dev
```
The student testing platform and reviewer UI will be live at **`http://localhost:3000`**.

---

### Step 5: Explore & Use the Platform

1. **Student CBT Exam Simulation:**
   - Open **`http://localhost:3000`** in your browser.
   - Login with demo credentials: `arjun.sharma@prepfreex.com` / `Password@123`.
   - Practice full-length mocks, sectional tests, or topic-level drills with official NTA timer and $+4/-1$ scoring.
2. **Staging Review & Ingestion UI:**
   - Click the **Staging Review** tab in the navigation bar.
   - Click **`[⚡ Extract Next Questions from PDF]`** to run the 4-layer autonomous ingestion pipeline.
   - View Qwen-extracted questions side-by-side with the AIR-1 Blind Solver mathematical derivations.
   - Click any option card to override keys or click **`[↗ Promote Approved to Live]`** to merge verified questions directly into the production question bank.
3. **Database Remediation Sweep:**
   - Run the curriculum remediation engine across any legacy questions:
     ```bash
     python -u scripts/remediate_all_taxonomy.py
     ```

---

## 10. Running Automated Ingestion & Embibe Synthesis CLI

### Automated Full-Length Test Ingestion
```bash
# Ingest single complete test paper with parity verification
python -u scripts/run_automated_full_test_ingestion.py --pdf "data/raw/jee_dataset/full_tests/JEE Main 2022 (Online) 24th June Morning Shift Question Paper with Answer Key.pdf"

# Ingest next N pending papers in batch
python -u scripts/run_automated_full_test_ingestion.py --num-pdfs 3
```

### Embibe Parametric Variant Synthesis
To synthesize verified question variants for a specific sparse subtopic:
```bash
python -m scripts.run_embibe_synthesis_batch --topic PHYS_U01_T01 --count 5
```

To automatically scan and backfill all sparse topics across the curriculum:
```bash
python -m scripts.run_embibe_synthesis_batch --fill-sparse --min-count 5
```

To regenerate the official catalog CSV exports:
```bash
python -m scripts.export_updated_catalog_and_counts
```

---

## 11. Test Suite & Verification

Run the test suite with Pytest:
```bash
# Run Embibe dual-agent generator & blind-solver parity test
pytest tests/test_embibe_engine.py -v

# Run full core test suite
pytest tests/test_assessment_scoring.py tests/test_taxonomy.py tests/test_deterministic.py -v
```

---

## 12. Contributors & Team

- **Gaurav Singh Tanwar** ([@gauravsinghtanwar1](https://github.com/gauravsinghtanwar1)) — *Lead Architecture & Development*
- **Sai Mallela** (`sai.mallela@unloxacademy.com`) — *Core Contributor*

