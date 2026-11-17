# Architecture and Extraction Decisions

1. Phase 1 is a local-first ingestion foundation, not a student assessment application.
2. PostgreSQL is the structured source of truth. PDFs and images are external assets; local artifacts are used for this MVP and Cloudflare R2 is the intended future provider.
3. Every source document is SHA-256 hashed and begins with `license_status=unverified`.
4. Repeated question labels are not unique. `source_question_key` is the source-scoped idempotency key; source part, section, local number and global number are stored separately.
5. Extracted candidates are staged in `ingestion_question_candidates`. They are not canonical/publishable questions until validated and reviewed.
6. Canonical question versioning is separate from assessment-specific marks. Marking rules belong to future assessment configuration.
7. Answer-key correctness and explanation correctness are independent verification dimensions.
8. Chemistry unit numbering is continuous: Physical Chemistry 1–8, Inorganic Chemistry 9–12, Organic Chemistry 13–20.
9. The supplied syllabus contains 54 units: Mathematics 14, Physics 20, Chemistry 20.
10. Candidate topic phrases are derived conservatively from syllabus text and remain `is_reviewed=false`; they are not represented as official NTA topic/subtopic labels.
11. Physics Unit 14 uses the manually specified working topics and subtopics from the project prompt. All authored nodes remain unreviewed.
12. MathonGo Q2's printed solution includes a peak/RMS substitution inconsistency. The supplied answer 50 μF independently follows from the resonance condition; the source explanation remains flagged unverified.
13. The generic pipeline handles the MathonGo pilot without hardcoded filename conditionals. The hardcoded pilot profile was moved to `tests/fixtures/mathongo_pilot_profile.py`.
14. The supplied ALLEN test PDF is image-based. In Phase 2, the vision LLM extraction and deterministic answer-key mapping are integrated into the generic pipeline.
15. The ALLEN paper's section/global numbering follows: Mathematics I 1–20, Mathematics II 21–25, Physics I 26–45, Physics II 46–50, Chemistry I 51–70, Chemistry II 71–75.
16. Default LLM provider is `gemini` using the official `google-genai` Python SDK (version 2.x), reading `GEMINI_API_KEY` and `GEMINI_MODEL` (defaulting to `gemini-2.5-flash` for multimodal vision extraction on the free tier). An `openai_compatible` provider remains available as a secondary alternative.
17. No question is published automatically. All newly ingested questions land with `status='needs_review'` and `license_status='unverified'`. Human review is mandatory for publication.
18. Free-tier LLM rate limiting is strictly enforced: `LLM_REQUESTS_PER_MINUTE=15`, exponential backoff on HTTP 429/5xx, per-run request budget `MAX_LLM_REQUESTS=100`, and a SHA-256 disk cache in `artifacts/llm_cache/` keyed by `sha256(prompt + image bytes + model)` to guarantee zero duplicate API calls on re-runs and `--resume`.
19. Structured JSON output: Always requests structured JSON validated against JSON Schema / Pydantic models. On invalid output, retries once with the validation error appended; on second failure, logs an `ingestion_errors` entry and continues without terminating the job.
20. Taxonomy v2 Migration (`0002_taxonomy_v2.sql`): Adds `description text`, `example_stems text[]`, and `replaced_by bigint REFERENCES taxonomy(id)` to `taxonomy`. Introduces `taxonomy_proposals` table for subtopic candidates proposed by the tagger. Updates `v_test_eligible_questions` view to require `needs_subtopic=false`.
21. Subtopic Tagging Constraints: Primary tag must be at the exact SUBTOPIC level (unit > topic > subtopic), with up to two secondary tags. Subtopics must be mutually exclusive and together cover the coaching chapter problem types. If no subtopic fits, the tagger logs a `taxonomy_proposals` row, tags at topic level, and marks `flags.needs_subtopic=true`.
22. Code Stability: Codes follow format `SUB.Uxx.Tyy.Szz`. Codes are assigned strictly by code, never by the LLM, and existing codes are never reused or renumbered.
23. Practical Units: Physics Unit 20 (Experimental Skills) and Chemistry Unit 20 (Practical) generate topics only, with no subtopics.
24. Independent Answer Verification: The engine derives the answer from the worked solution and compares it against the printed answer key. In case of mismatch (e.g. ALLEN Q73 where key is 125 but solution yields -125 kJ/mol), the printed key is NOT modified; instead `flags.key_mismatch=true`, `answer_key_verified=false`, and details are saved in `answer_verification_notes`.
25. Deduplication: Questions are hashed by SHA-256 over normalized stem + options. Duplicates within or across jobs are reported in `flags.possible_duplicate_of` rather than silently dropped.
26. Docker Database Path: `docker-compose.yml` runs PostgreSQL 16 with `pgvector/pgvector:pg16`, bound to `127.0.0.1:${POSTGRES_PORT:-5432}` only, using named volume `prepfreex_pgdata` and credentials from `.env`. Helper commands (`qbank db-up`, `db-down`, `db-reset`, `db-backup`, `db-restore`, `db-shell`, `db-check`) manage the lifecycle.
27. Sandbox Isolation & `--dry-run`: Because sandbox environments lack Docker daemon and network access, all commands writing to PostgreSQL support `--dry-run`, writing full pipeline output to `artifacts/<job_id>/*.json`. Tests requiring live database are marked `@pytest.mark.db` and skip automatically when `DATABASE_URL` is unset or unreachable.
