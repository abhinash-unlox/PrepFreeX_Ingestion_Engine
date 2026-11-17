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
                         └──────────────┬──────────────────┘
                                        │
                 ┌──────────────────────┴──────────────────────┐
                 │                                             │
                 ▼                                             ▼
  ┌───────────────────────────────┐             ┌───────────────────────────────┐
  │   PostgreSQL 18.6 Database    │             │   MinIO S3 Object Storage     │
  │  (jee_mains_assesment_work)   │             │       (127.0.0.1:9000)        │
  │   - 3,001 Clean Eligible Qs   │             │   - Diagram Assets & Figures  │
  │   - 539 Quarantined Broken Qs │             │   - question-assets/ bucket   │
  └───────────────────────────────┘             └───────────────────────────────┘
                 ▲
                 │ (Sequence-backed Ingestion)
                 │
  ┌─────────────────────────────────────────────────────────────────────────────┐
  │              Embibe-Inspired Dual-Agent Variant Synthesis Engine            │
  │                  (engines/synthesis/embibe_variant_engine.py)               │
  │                                                                             │
  │  [Seed Question] ──► [Agent 1: SME Author] ──► [Candidate Stem & Options]   │
  │                             │                               │               │
  │                             ▼                               ▼               │
  │                   [Candidate Key: 'B']            [Agent 2: Blind Solver]   │
  │                             │                     (No access to author key) │
  │                             ▼                               │               │
  │                   [Parity Arbiter] ◄────────────── [Derived Key: 'B']       │
  │                             │                                               │
  │                 Match? ──► YES ──► Ingest into public.completed_questions   │
  │                        ──► NO  ──► Discard & Block Hallucination            │
  └─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Embibe-Inspired Architecture (Dual-Agent Synthesis)

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

## 3. Clean Project Directory Structure

```
PrepFreeX_Ingestion_Engine/
├── apps/
│   ├── api/                              # FastAPI core backend service (Port 8000)
│   │   ├── main.py                       # Application entrypoint & CORS configuration
│   │   ├── db.py                         # Connection pool & cursor context managers
│   │   ├── routes/                       # REST endpoints (assessments, questions, auth, taxonomy)
│   │   │   ├── assessment_engine.py      # Assessment delivery, timing, cooldown & backfill
│   │   │   ├── assessment.py             # NTA scoring evaluations (+4/-1)
│   │   │   ├── questions.py              # Question catalog browsing & filtering
│   │   │   ├── auth.py                   # JWT authentication & student profile
│   │   │   ├── images.py                 # MinIO diagram presigning & proxying
│   │   │   └── taxonomy.py               # Canonical 64 chapters & 256 subtopics API
│   │   └── services/                     # Background AI explainer & variant services
│   └── admin/                            # Streamlit Reviewer & Admin Portal (Port 8501)
├── v0-prepfreex-frontend/                # Production Next.js 14 CBT Client (Port 3000)
│   ├── app/                              # App router pages & layouts
│   ├── components/                       # Interactive exam UI (palette, timer, KaTeX renderer)
│   └── lib/                              # API client, canonical taxonomy, and data contracts
├── engines/
│   ├── synthesis/                        # Embibe dual-agent variant synthesis engine
│   │   └── embibe_variant_engine.py      # SME generator, Blind Solver & Parity Arbiter
│   ├── assessment/                       # NTA scoring rules, timing models, psychometrics
│   ├── ingestion/                        # PDF extraction, OCR segmentation, Groq categorizers
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
│   ├── export_updated_catalog_and_counts.py         # Regenerates official review CSVs
│   ├── run_embibe_synthesis_batch.py                # Batch CLI for dual-agent synthesis
│   ├── quarantine_all_defective_questions.py        # Pass 1 academic OCR quarantine engine
│   ├── execute_second_deep_quarantine.py            # Pass 2 deep OCR defect quarantine engine
│   ├── clean_and_upload_all_diagrams.py             # MinIO diagram cleaner and uploader
│   ├── finish_phys02_reclassification.py            # Kinematics/PHYS_U02 reclassifier
│   ├── build_official_syllabus_json.py              # Canonical taxonomy builder
│   └── test_all_assessments_e2e.py                  # End-to-end assessment verification test
├── tests/                                # Comprehensive Pytest suite
│   ├── test_embibe_engine.py             # Embibe dual-agent verification tests
│   ├── test_admin_api.py                 # Admin API integration tests
│   ├── test_assessment_scoring.py        # NTA scoring logic tests
│   ├── test_taxonomy.py                  # Taxonomy hierarchy tests
│   └── test_deterministic.py             # Mathematical SymPy verification tests
├── data/                                 # Official reference syllabus & raw data
├── backups/                              # Database dumps and safety snapshots
├── pyproject.toml                        # Project dependencies & metadata
└── README.md                             # Primary technical documentation
```

---

## 4. Database Model & Integrity Guarantees

PrepFreeX operates under strict data separation to guarantee that student testing never corrupts canonical records:
- **`jee_mains_assesment` (Port 5432):** Master historical database (**100% Read-Only, Unaltered**).
- **`jee_mains_assesment_work` (Port 5432):** Active working database for all live assessments, reclassifications, quarantine updates, and variant ingestions.

### Key Table: `public.completed_questions`
- **Total Ingested Rows:** 3,540
- **`assessment_status = 'ELIGIBLE'`:** **3,001 clean, academically verified questions**.
- **`assessment_status = 'BROKEN'`:** **539 permanently quarantined questions** (OCR drops, watermarks, stripped equations).
- **Primary Key Sequence:** `completed_questions_id_seq` automatically assigns IDs to new variants.
- **Serving Guarantee:** All student assessment queries enforce `WHERE assessment_status = 'ELIGIBLE'`.

---

## 5. Assessment Modes & CBT Delivery

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

## 6. How to Run the Platform

### Prerequisites
- Python 3.12+ (Installed on path)
- Node.js 18+ & pnpm
- PostgreSQL 18 (Local instance on port 5432)
- MinIO Object Storage (Installed at `C:\tools\prepfreex-minio`)

### Step 1: Start Services

```powershell
# 1. Start MinIO Object Storage (Port 9000 API / 9001 Console)
powershell -File "C:\tools\prepfreex-minio\start-minio.ps1"

# 2. Start FastAPI Backend (Port 8000)
python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000

# 3. Start Next.js Frontend (Port 3000)
cd v0-prepfreex-frontend
pnpm install
pnpm dev
```

Open your browser at **`http://localhost:3000`**.  
Default test credentials: `arjun.sharma@prepfreex.com` / `Password@123`.

---

## 7. Running Embibe Parametric Synthesis

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

## 8. Test Suite & Verification

Run the test suite with Pytest:
```bash
# Run Embibe dual-agent generator & blind-solver parity test
pytest tests/test_embibe_engine.py -v

# Run full core test suite
pytest tests/test_assessment_scoring.py tests/test_taxonomy.py tests/test_deterministic.py -v
```
