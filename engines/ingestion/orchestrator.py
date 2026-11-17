from __future__ import annotations

import json
import logging
import os
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from engines.shared.config import settings
from .llm import GroqLedger, GroqProvider, get_llm_provider
from .pipeline import run_ingestion
from .registry import (
    acquire_pdf_lock,
    generate_reports,
    get_next_eligible_pdf,
    log_pdf_event,
    release_pdf_lock,
)

logger = logging.getLogger("orchestrator")


class OrchestrationWorker:
    """Sequential PDF Ingestion Orchestrator for PrepFreeX.
    
    Strict rules enforced:
    - Exactly ONE PDF is processed at any given time.
    - PostgreSQL is the authoritative tracker of all state and progress.
    - Token budget is checked before and tracked after every PDF.
    - Candidate staging is isolated from canonical questions.
    - Failures and interruptions are cleanly checkpointed and resumable.
    """

    def __init__(
        self,
        worker_id: str | None = None,
        database_url: str | None = None,
        dataset_root: Path = Path("data/raw/jee_dataset"),
        taxonomy_path: Path | None = None,
        max_pdf_limit: int | None = None,
        dry_run: bool = False,
    ):
        self.worker_id = worker_id or f"worker_{os.getpid()}_{int(time.time())}"
        self.database_url = database_url or settings.database_url
        self.dataset_root = dataset_root.resolve()
        self.taxonomy_path = taxonomy_path or Path("db/seeds/jee_main_2027_taxonomy_v2.json")
        if not self.taxonomy_path.exists():
            self.taxonomy_path = Path("db/seeds/jee_main_2027_taxonomy.json")
        self.max_pdf_limit = max_pdf_limit
        self.dry_run = dry_run
        self.ledger = GroqLedger()

        # Session metrics
        self.processed_pdfs_count = 0
        self.completed_pdfs: list[dict[str, Any]] = []
        self.total_tokens_consumed = 0
        self.total_questions_extracted = 0
        self.total_questions_verified = 0
        self.total_questions_promoted = 0
        self.total_questions_needing_review = 0

    def check_token_budget(self, estimated_tokens: int = 2000) -> tuple[bool, str]:
        """Verifies if authorized Groq token budget permits processing the next PDF."""
        if self.dry_run:
            return True, "Dry-run mode"

        # Check provider daily limits against ledger dynamically using all active keys
        total_keys = len(settings.groq_api_keys) if settings.groq_api_keys else 1
        max_req = settings.max_llm_requests_per_day * total_keys
        max_tok = settings.max_llm_tokens_per_day * total_keys

        can_spend, reason = self.ledger.can_spend(estimated_tokens, max_req, max_tok)
        return can_spend, reason

    def process_single_pdf(self, pdf_row: dict[str, Any]) -> dict[str, Any]:
        """Processes exactly one PDF end-to-end with database checkpointing and locking."""
        pdf_id = str(pdf_row["id"])
        rel_path = pdf_row["relative_path"]
        pdf_path = self.dataset_root / rel_path
        filename = pdf_row["filename"]
        category = pdf_row["category"]

        print(f"\n[{self.worker_id}] >>> Processing PDF: {rel_path} ({pdf_row['page_count']} pages)")

        # 1. Acquire exclusive lock in PostgreSQL
        if not acquire_pdf_lock(pdf_id, self.worker_id, self.database_url):
            print(f"[{self.worker_id}] PDF {rel_path} is currently locked by another worker. Skipping.")
            return {"status": "SKIPPED_LOCKED", "pdf_id": pdf_id}

        log_pdf_event(pdf_id, "PROCESSING_STARTED", f"Acquired lock by {self.worker_id}", database_url=self.database_url)

        # 2. Check token budget
        can_proceed, reason = self.check_token_budget(estimated_tokens=pdf_row["page_count"] * 1500)
        if not can_proceed:
            print(f"[{self.worker_id}] Token budget limit reached: {reason}. Checkpointing PDF as BLOCKED_TOKEN_BUDGET.")
            with psycopg.connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE pdf_processing_registry SET
                            processing_status = 'BLOCKED_TOKEN_BUDGET',
                            last_error = %s,
                            updated_at = now()
                        WHERE id = %s;
                        """,
                        (reason, pdf_id)
                    )
                conn.commit()
            release_pdf_lock(pdf_id, self.worker_id, database_url=self.database_url)
            log_pdf_event(pdf_id, "TOKEN_BUDGET_EXHAUSTED", reason, database_url=self.database_url)
            return {"status": "BLOCKED_TOKEN_BUDGET", "reason": reason, "pdf_id": pdf_id}

        # 3. Verify file exists on disk
        if not pdf_path.exists():
            err_msg = f"PDF file not found on disk at {pdf_path}"
            print(f"[{self.worker_id}] ERROR: {err_msg}")
            with psycopg.connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE pdf_processing_registry SET
                            processing_status = 'FAILED_RETRYABLE',
                            last_error = %s,
                            current_attempt = current_attempt + 1,
                            updated_at = now()
                        WHERE id = %s;
                        """,
                        (err_msg, pdf_id)
                    )
                conn.commit()
            release_pdf_lock(pdf_id, self.worker_id, database_url=self.database_url)
            log_pdf_event(pdf_id, "PROCESSING_FAILED", err_msg, database_url=self.database_url)
            return {"status": "FAILED_RETRYABLE", "error": err_msg, "pdf_id": pdf_id}

        # 4. Execute ingestion pipeline
        t0 = time.time()
        init_state = self.ledger.read()
        initial_requests = init_state.get("total_requests", 0)
        initial_tokens = init_state.get("total_tokens", 0)

        try:
            # Run the 13-stage pipeline
            report = run_ingestion(
                pdf_path=pdf_path,
                taxonomy_path=self.taxonomy_path,
                database_url=self.database_url,
                dry_run=self.dry_run,
            )

            job_id = report["job_id"]
            q_count = report["question_candidate_count"]
            db_stats = report.get("db_stats") or {}

            promoted_count = db_stats.get("inserted", 0)
            staged_count = db_stats.get("candidates_staged", 0)

            # Calculate token consumption
            final_state = self.ledger.read()
            req_delta = max(0, final_state.get("total_requests", 0) - initial_requests)
            token_delta = max(0, final_state.get("total_tokens", 0) - initial_tokens)

            # Link candidates in PostgreSQL to this pdf_processing_registry row
            with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    # Update candidate rows with pdf_registry_id
                    cur.execute(
                        """
                        UPDATE ingestion_question_candidates SET
                            pdf_registry_id = %s
                        WHERE ingestion_job_id = %s;
                        """,
                        (pdf_id, job_id)
                    )

                    # Link promoted canonical questions
                    cur.execute(
                        """
                        UPDATE ingestion_question_candidates iqc
                        SET canonical_question_id = q.id,
                            review_status = 'imported',
                            verification_status = CASE 
                                WHEN q.answer_key_verified THEN 'ANSWER_VERIFIED' 
                                ELSE 'ANSWER_UNVERIFIABLE' 
                            END,
                            academic_notes = 'Promoted to canonical question bank after passing all verification gates.'
                        FROM questions q
                        JOIN source_documents sd ON sd.id = q.source_doc_id
                        WHERE sd.sha256 = %s
                          AND q.source_question_key = iqc.source_question_key
                          AND iqc.pdf_registry_id = %s;
                        """,
                        (pdf_row["sha256"], pdf_id)
                    )

                    # Update unpromoted candidates with diagnostic status and academic notes
                    cur.execute(
                        """
                        UPDATE ingestion_question_candidates
                        SET review_status = 'needs_review',
                            verification_status = CASE
                                WHEN extraction_json->'flags'->>'figure_required' = 'true' OR extraction_json->>'figure_status' = 'pending' THEN 'FIGURE_PENDING'
                                WHEN extraction_json->'flags'->>'key_mismatch' = 'true' THEN 'KEY_MISMATCH'
                                WHEN extraction_json->'flags'->>'dropped_formula' = 'true' THEN 'STEM_INCOMPLETE'
                                WHEN extraction_json->'flags'->>'incomplete_options' = 'true' THEN 'OPTIONS_INCOMPLETE'
                                WHEN answer_json IS NULL THEN 'ANSWER_UNVERIFIABLE'
                                ELSE 'NEEDS_HUMAN_REVIEW'
                            END,
                            academic_notes = CASE
                                WHEN extraction_json->'flags'->>'figure_required' = 'true' OR extraction_json->>'figure_status' = 'pending' THEN 'Requires figure/diagram visual reconstruction before canonical promotion.'
                                WHEN extraction_json->'flags'->>'key_mismatch' = 'true' THEN 'Answer key mismatch detected between source key and explanation.'
                                WHEN extraction_json->'flags'->>'dropped_formula' = 'true' THEN 'Question stem missing inline equations or variables from PDF text layer.'
                                WHEN extraction_json->'flags'->>'incomplete_options' = 'true' THEN 'MCQ options missing or degenerate in PDF text layer.'
                                WHEN answer_json IS NULL THEN 'No authoritative answer key could be parsed for this question.'
                                ELSE 'Held back in staging for human review before canonical promotion.'
                            END
                        WHERE pdf_registry_id = %s AND canonical_question_id IS NULL;
                        """,
                        (pdf_id,)
                    )

                    # Fetch actual counts from candidates for this PDF
                    cur.execute(
                        """
                        SELECT 
                            COUNT(*) AS total_extracted,
                            COUNT(*) FILTER (WHERE canonical_question_id IS NOT NULL) AS promoted_cnt,
                            COUNT(*) FILTER (WHERE canonical_question_id IS NULL) AS staged_cnt,
                            COUNT(*) FILTER (WHERE verification_status = 'ANSWER_VERIFIED') AS verified_cnt
                        FROM ingestion_question_candidates
                        WHERE pdf_registry_id = %s;
                        """,
                        (pdf_id,)
                    )
                    counts = cur.fetchone() or {}
                    total_detected = counts.get("total_extracted", q_count)
                    promoted_count = counts.get("promoted_cnt", promoted_count)
                    staged_count = counts.get("staged_cnt", staged_count)
                    actual_verified = counts.get("verified_cnt", counts.get("count", 0))

                    # Determine final status
                    if total_detected == 0:
                        final_status = "NEEDS_MANUAL_REVIEW"
                    elif staged_count > 0:
                        final_status = "COMPLETED_WITH_REVIEW"
                    else:
                        final_status = "COMPLETED"

                    # Update registry row
                    cur.execute(
                        """
                        UPDATE pdf_processing_registry SET
                            processing_status = %s,
                            total_questions_detected = %s,
                            questions_extracted = %s,
                            questions_verified = %s,
                            questions_promoted = %s,
                            questions_needing_review = %s,
                            groq_requests = groq_requests + %s,
                            total_tokens = total_tokens + %s,
                            completed_at = now(),
                            last_error = NULL,
                            updated_at = now()
                        WHERE id = %s;
                        """,
                        (
                            final_status,
                            total_detected,
                            total_detected,
                            actual_verified,
                            promoted_count,
                            staged_count,
                            req_delta,
                            token_delta,
                            pdf_id,
                        )
                    )
                conn.commit()

            # Record completion audit event
            event_details = {
                "job_id": job_id,
                "questions_detected": q_count,
                "questions_promoted": promoted_count,
                "questions_needing_review": staged_count,
                "tokens_spent": token_delta,
                "elapsed_sec": round(time.time() - t0, 2),
            }
            log_pdf_event(pdf_id, f"PDF_{final_status}", f"Ingested {q_count} questions in {event_details['elapsed_sec']}s", event_details, database_url=self.database_url)

            # Update session metrics
            self.processed_pdfs_count += 1
            self.total_tokens_consumed += token_delta
            self.total_questions_extracted += q_count
            self.total_questions_verified += actual_verified
            self.total_questions_promoted += promoted_count
            self.total_questions_needing_review += staged_count

            result = {
                "status": final_status,
                "pdf_id": pdf_id,
                "filename": filename,
                "category": category,
                "questions_detected": q_count,
                "questions_promoted": promoted_count,
                "questions_needing_review": staged_count,
                "tokens_spent": token_delta,
                "elapsed_sec": event_details["elapsed_sec"],
            }
            self.completed_pdfs.append(result)
            print(f"[{self.worker_id}] Successfully finished {rel_path} -> Status: {final_status} (Promoted: {promoted_count}, Staged: {staged_count})")
            return result

        except Exception as exc:
            err_tb = traceback.format_exc()
            print(f"[{self.worker_id}] EXCEPTION processing {rel_path}: {exc}\n{err_tb}")
            with psycopg.connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE pdf_processing_registry SET
                            processing_status = 'FAILED_RETRYABLE',
                            last_error = %s,
                            current_attempt = current_attempt + 1,
                            updated_at = now()
                        WHERE id = %s;
                        """,
                        (str(exc)[:500], pdf_id)
                    )
                conn.commit()
            log_pdf_event(pdf_id, "PROCESSING_FAILED", str(exc), {"traceback": err_tb[:1000]}, database_url=self.database_url)
            return {"status": "FAILED_RETRYABLE", "error": str(exc), "pdf_id": pdf_id}

        finally:
            # 5. Release lock always
            release_pdf_lock(pdf_id, self.worker_id, database_url=self.database_url)
            # Update reports
            try:
                generate_reports(self.database_url)
            except Exception:
                pass

    def run_continuous_loop(self, category: str | None = None) -> dict[str, Any]:
        """Main loop that selects and processes PDFs sequentially until budget or stop condition."""
        print(f"\n=======================================================")
        print(f" PREPFREEX CONTINUOUS PDF INGESTION WORKER: {self.worker_id}")
        print(f" Database: {self.database_url.split('@')[-1] if '@' in self.database_url else self.database_url}")
        print(f" LLM Provider: {settings.llm_provider} ({settings.groq_model})")
        print(f" Category Filter: {category or 'All Categories'}")
        print(f" Max PDF Limit: {self.max_pdf_limit or 'Unlimited (until budget exhausted)'}")
        print(f"=======================================================\n")

        session_start = time.time()

        while True:
            # Check maximum PDF limit for this run
            if self.max_pdf_limit and self.processed_pdfs_count >= self.max_pdf_limit:
                print(f"Reached configured run limit of {self.max_pdf_limit} PDFs. Halting cleanly.")
                break

            # Fetch next eligible PDF
            next_pdf = get_next_eligible_pdf(category=category, database_url=self.database_url)
            if not next_pdf:
                print("No more eligible PDFs found in registry for processing.")
                break

            # Process the selected PDF
            res = self.process_single_pdf(next_pdf)

            # Check for budget stop
            if res.get("status") == "BLOCKED_TOKEN_BUDGET":
                print("\n[STOP CONDITION] Groq authorized token budget reached. Halting gracefully.")
                break

            # Small cooldown between PDFs to avoid burst traffic
            time.sleep(1.0)

        total_session_sec = round(time.time() - session_start, 2)
        summary = {
            "worker_id": self.worker_id,
            "session_duration_sec": total_session_sec,
            "processed_pdfs_count": self.processed_pdfs_count,
            "completed_pdfs": self.completed_pdfs,
            "total_tokens_consumed": self.total_tokens_consumed,
            "total_questions_extracted": self.total_questions_extracted,
            "total_questions_verified": self.total_questions_verified,
            "total_questions_promoted": self.total_questions_promoted,
            "total_questions_needing_review": self.total_questions_needing_review,
        }

        self.print_session_report(summary)
        return summary

    def print_session_report(self, summary: dict[str, Any]):
        """Prints the end-of-session summary required by Phase 14."""
        print("\n=======================================================")
        print(" PREPFREEX INGESTION SESSION COMPLETED")
        print("=======================================================")
        print(f"PDFs Processed in this Session: {summary['processed_pdfs_count']}")
        print(f"Session Duration: {summary['session_duration_sec']}s")
        print(f"Questions Extracted: {summary['total_questions_extracted']}")
        print(f"Questions Verified: {summary['total_questions_verified']}")
        print(f"Questions Promoted to Canonical Bank: {summary['total_questions_promoted']}")
        print(f"Questions Needing Human Review: {summary['total_questions_needing_review']}")
        print(f"Groq Tokens Consumed: {summary['total_tokens_consumed']:,}")

        # Fetch remaining and completed counts from database
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM pdf_processing_registry WHERE processing_status IN ('COMPLETED', 'COMPLETED_WITH_REVIEW')")
                total_completed = cur.fetchone()["count"]
                cur.execute("SELECT COUNT(*) FROM pdf_processing_registry WHERE processing_status NOT IN ('COMPLETED', 'COMPLETED_WITH_REVIEW')")
                total_remaining = cur.fetchone()["count"]

        print(f"Total Completed PDFs in Database: {total_completed}")
        print(f"Total Remaining PDFs in Database: {total_remaining}")
        print("=======================================================\n")
