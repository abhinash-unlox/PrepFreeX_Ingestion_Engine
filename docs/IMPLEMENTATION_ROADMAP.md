# PrepFreeX — Implementation Roadmap (Phases 0 to 4)

## Phase 0: Baseline Infrastructure (Completed)
- Native PostgreSQL 18.6 setup on Windows without Docker dependencies.
- Database migrations (`0001_init.sql`, `0002_taxonomy_v2.sql`) with `pgcrypto` and `pg_trgm`.
- Seeding canonical JEE Main 2027 taxonomy (767 nodes across 3 subjects, 54 units).
- Pilot ingestion of MathonGo Alternating Current (5 questions with exact subtopic tags).

---

## Phase 1: Architecture, Storage & Inventory (Completed)
- **Root Cause Fix**: Resolved classification default bug, achieving 100% unit accuracy on ALLEN gold set and 100% exact subtopic accuracy on MathonGo.
- **Repository Restructuring**: Decoupled repository into `services/ingestion_engine`, `services/assessment_engine`, `apps/api`, `apps/web`, `packages/shared`.
- **Local Object Storage**: Implemented `LocalObjectStorage` with S3-style bucket/key semantics, atomic writes, streaming transfers, and path traversal protection.
- **Stage-Specific Token Caching**: Designed `StageCache` ensuring taxonomy updates do not trigger PDF re-extraction.
- **PDF Inventory Utility**: Built `qbank inventory-pdfs` scanning PDF collections without LLM calls, generating `data/manifests/pdf_inventory.csv` and identifying duplicates.
- **Database Schema Designs**: Formulated migrations `0003_assessment_engine.sql` and `0004_question_bank_enhancements.sql`.

---

## Phase 2: Assessment Engine Execution (Upcoming)
1. **Apply Migrations**: Execute `0003_assessment_engine.sql` and `0004_question_bank_enhancements.sql` on `prepfreex`.
2. **Implement Test Assembly Service**:
   - Section configuration (Mandatory MCQs + Optional Numerical choices e.g. 5 out of 10).
   - Immutable question snapshots upon test session creation.
3. **Attempt Session Manager**:
   - Server-side countdown timers and expiration checks.
   - Idempotent submission endpoint preventing double-grading.
   - States: `in_progress`, `submitted`, `expired`, `interrupted`, `cancelled`.
4. **Adaptive Engine (CAT)**:
   - Initial difficulty assignment from topic mastery.
   - Real-time difficulty adjustment using Item Response Theory (IRT) empirical p-values.

---

## 3. Phase 3: Large-Scale Ingestion & Dataset Unpacking (Upcoming)
1. **Unpack Dataset**: Extract selected coaching question banks from `JEE DATASET.zip` into `data/input/pdfs/question_banks/` and `data/input/pdfs/full_tests/`.
2. **Batch Ingestion Workers**:
   - Run asynchronous ingestion workers processing unindexed PDFs.
   - Persist question diagram crops to `data/object_store/local/question-diagrams/`.
3. **Human Review Dashboard (`apps/web`)**:
   - Reviewer UI for approving `ingestion_question_candidates` into canonical `questions`.
   - Managing and approving `taxonomy_proposals`.

---

## Phase 4: Production Hardening & Cloud Scale (Future)
1. **Cloud Object Store**: Switch `STORAGE_BACKEND=s3` to target Cloudflare R2 or AWS S3.
2. **High-Concurrency CBT**: Load test assessment attempt submissions up to 10,000 concurrent students.
3. **CDN Integration**: Serve static math fonts and diagram assets via Cloudflare CDN.

