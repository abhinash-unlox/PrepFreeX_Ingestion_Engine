# Ingestion Pipeline Architecture & Stages

The PrepFreeX Ingestion Engine takes JEE-style PDFs (question papers, chapter tests, question banks) and transforms them into structured questions staged and published in PostgreSQL with exact subtopic classifications.

---

## High-Level Execution Modes

1. **Live Mode (`qbank ingest-pdf PATH`)**:
   - Executes the complete 13-stage pipeline.
   - Uses `google-genai` (model `gemini-2.5-flash`) for vision-capable LaTeX transcription and answer verification.
   - Persists staged question candidates to `ingestion_question_candidates` and promotes verified candidates into `questions`, `question_options`, `question_tags`, etc.
2. **Dry-Run Mode (`qbank ingest-pdf PATH --dry-run`)**:
   - Executes all 13 stages without requiring Docker, live PostgreSQL, or active API credentials.
   - Employs recorded fixtures, disk caching (`artifacts/llm_cache/`), and offline heuristics.
   - Writes all structured artifacts, reports, and bundles to `artifacts/<job_id>/*.json`.

---

## 13 Pipeline Stages

### Stage 1: Register Document
- **Function**: Computes SHA-256 hash of the input PDF.
- **Idempotency**: If document with the same SHA-256 already exists in `source_documents`, skips registration unless `--force` is specified.
- **Writes**:
  - DB: `source_documents` row with `license_status='unverified'`.
  - DB: `ingestion_jobs` row in status `'processing'`.
  - Disk: `artifacts/<job_id>/` working directory.

### Stage 2: Render Pages
- **Function**: Renders every page of the document at 200 DPI into PNG images (`artifacts/<job_id>/pages/page-XXX.png`). Selectable text is extracted with PyMuPDF as a lightweight hint.
- **Writes**:
  - DB: `document_pages` rows (page number, extraction method, text character count, image count).
  - Disk: `artifacts/<job_id>/pages/*.png`.

### Stage 3: Classify Page Roles
- **Function**: Classifies every page into one of: `questions`, `answer_key`, `solutions`, `cover`, or `other`.
- **Heuristics**:
  - Cover pages: Header instructions, max marks, no numbered questions.
  - Answer keys: Headings like `ANSWER KEYS`, `KEY SHEET`, or tabular grid layouts.
  - Solutions: Headings like `SOLUTIONS`, `HINTS & SOLUTIONS`, `ANSWERS AND SOLUTIONS`.
  - Questions: Numbered question stems (`Q1.`, `1)`), part headers (`PART-1 : MATHEMATICS`).
- **Writes**:
  - Disk: `artifacts/<job_id>/pages.json`.

### Stage 4: Layout Profile Detection
- **Function**: Automatically detects document layout characteristics:
  - Numbering format (`Q1.` vs `1)` vs `1.`).
  - Section restarts (e.g. 1–20 in Section I, restarting at 1–5 in Section II).
  - Subject/Part headers (`PART-1 : MATHEMATICS`, `SECTION-I`).
  - Option labeling style (`(A)` vs `(1)`).
  - Answer key location (`grid_at_end`, `merged_with_solutions`, `inline`).
- **Writes**:
  - Disk: `artifacts/<job_id>/layout_profile.json`.
  - DB: Stored in `ingestion_jobs.document_type` and layout flags.

### Stage 5: Question Extraction
- **Function**: Processes question pages in 1–2 page sliding windows with overlap to capture questions crossing page boundaries.
- **Fields Extracted**:
  - `source_q_label`, `source_local_number`, `source_global_number`.
  - `source_part`, `source_section`, `source_page_start`, `source_page_end`.
  - `question_type`: `mcq_single`, `mcq_multi`, `numerical`, `assertion_reason`, `statement_based`, `match_list`.
  - `stem_md`: Markdown + LaTeX (`$...$`, `\begin{bmatrix}`, `\ce{...}`).
  - `options[]` (for MCQs) or `match_items[]` (kept strictly out of options).
  - Figure cues: `has_figure`, `figure_description`, `figure_status='pending'`.
- **Writes**:
  - Internal candidate representation in pipeline memory.

### Stage 6: Answer Key Parsing
- **Function**: Parses answers from tabular answer grids or inline keys.
  - Text-based PDFs: Deterministic regular expression parsing over table cells.
  - Scanned PDFs: Vision LLM extraction with validation (cell count, valid letters/numbers).
  - Offset mapping: Maps local numbers to global numbers using section offsets:
    - Math Section I: 1–20, Section II: 21–25.
    - Physics Section I: 26–45, Section II: 46–50.
    - Chemistry Section I: 51–70, Section II: 71–75.
  - Letter conversion: Converts printed letters `A, B, C, D` to question option positions `1, 2, 3, 4`.
  - Numerical answers: Formatted as `{"type": "numeric", "value": val, "tolerance": 0, "unit": unit}`.

### Stage 7: Solution Matching
- **Function**: Associates solutions with questions by global number or local label.
- **Writes**:
  - `explanation_md` with `explanation_source='source'`.
  - `source_explanation_md` (untouched raw text).
  - Flags `solution_has_figure` if figures are found in the solution.

### Stage 8: Independent Answer Verification
- **Function**: Vision LLM independently evaluates the solution steps to derive the final answer and compares it with the printed answer key.
- **Behavior**:
  - If match: `answer_key_verified=true`.
  - If mismatch: `answer_key_verified=false`, `flags.key_mismatch=true`, and diagnostic stored in `answer_verification_notes`.
  - **Invariant**: The printed key is NEVER overwritten.
  - `explanation_verified` remains `false` until human SME approval.

### Stage 9: Subtopic Tagging (`SubtopicTagger`)
- **Function**: Constrained LLM selection:
  1. Unit selection (constrained to that subject).
  2. Topic selection (constrained to that unit).
  3. Subtopic selection (constrained to that topic, complete with description and examples).
- **Secondary Tags**: Up to 2 secondary codes in the same subject.
- **Few-Shot Prompting**: Loads up to 3 recent human corrections from `db/tag_feedback.jsonl`.
- **No-Fit Handling**: If no subtopic fits, inserts into `taxonomy_proposals`, tags question at TOPIC level, and sets `flags.needs_subtopic=true`.
- **Confidence**: If below `TAG_CONFIDENCE_THRESHOLD` (0.8), sets `flags.low_tag_confidence=true`.

### Stage 10: Metadata Enrichment
- **Function**:
  - AI-estimated metadata: `difficulty` (1–5), `cognitive_level` (`recall`/`understand`/`apply`/`analyze`), `estimated_time_sec`, `formulas_used[]`, `keywords[]`, `common_mistakes`.
  - Deterministic metadata: Exam name, year, date, shift parsed from phrases like `JEE Main 2026 (21 January Shift 2)` (`origin='pyq'`).

### Stage 11: Validation (`validators.py`)
- **Rules Verified**:
  - Option positions exist in options list.
  - Numerical values are valid numbers.
  - Balanced dollar signs (`$`) in stem and explanation.
  - Lightweight LaTeX brace check (flags warning, never drops question).
  - Exactly ONE primary tag; all tag codes exist and are active.
  - SHA-256 `content_hash` generated for deduplication.
  - Duplicates reported via `flags.possible_duplicate_of`.

### Stage 12: Persistence / Candidate Staging
- **DB Writes**:
  - Always writes to `ingestion_question_candidates` first.
  - Candidates that pass validation (non-null answer, options consistent with type, primary tag) are promoted to canonical tables: `questions`, `question_options`, `question_match_items`, `question_tags`, `question_sources`.
  - Upsert on `(source_doc_id, source_question_key)`.
  - Revisions tracked in `question_revisions` upon content modification.
- **Disk Writes**:
  - `artifacts/<job_id>/question_import.json`
  - `artifacts/<job_id>/classifications.json`
  - `artifacts/<job_id>/layout_profile.json`

### Stage 13: Report Generation
- **Function**: Aggregates statistics:
  - Page counts and classified roles.
  - Questions extracted vs expected.
  - Question type breakdown (`mcq_single`, `numerical`).
  - Figure-pending count and key mismatch count.
  - LLM cache and request metrics.
- **Writes**:
  - Disk: `artifacts/<job_id>/report.json`.
  - Terminal: Formatted summary via `qbank report <JOB_ID>`.

