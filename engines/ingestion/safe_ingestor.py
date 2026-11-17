"""
Safe Ingestor Orchestrator
Connects Extraction -> Academic Guardrails -> 3-Tier Classification -> Blind Solver Parity -> Staging DB.
Tracks exact token usage per question and per PDF batch.
"""

from __future__ import annotations
import os
import json
import uuid
import datetime
from typing import Optional
from apps.api.db import get_db_cursor
from engines.ingestion.pdf_extractor import PDFQuestionExtractor
from engines.ingestion.guardrails import validate_question_guardrails
from engines.ingestion.hierarchical_classifier import HierarchicalClassifier
from engines.ingestion.blind_solver import BlindSolver

class SafeIngestionPipeline:
    def __init__(self):
        self.extractor = PDFQuestionExtractor()
        self.classifier = HierarchicalClassifier()
        self.solver = BlindSolver()

    def process_pdf(
        self,
        pdf_path: str,
        subject_hint: Optional[str] = None,
        chapter_hint: Optional[str] = None,
        max_pages: Optional[int] = None,
        run_solver: bool = True
    ) -> dict:
        """
        Processes a single PDF through the 4-layer safe ingestion pipeline.
        Returns summary metrics: total_extracted, passed, rejected, total_tokens.
        """
        filename = os.path.basename(pdf_path)
        print(f"\n=======================================================")
        print(f"PROCESSING PDF: {filename}")
        print(f"Subject Hint: {subject_hint} | Chapter Hint: {chapter_hint}")
        print(f"=======================================================")

        # 1. Update manifest to IN_PROGRESS
        with get_db_cursor() as cur:
            cur.execute("""
                UPDATE public.pdf_ingestion_manifest
                SET status = 'IN_PROGRESS', started_at = NOW()
                WHERE pdf_path = %s;
            """, (pdf_path,))

        metrics = {
            "pdf_filename": filename,
            "total_extracted": 0,
            "passed_guardrails": 0,
            "rejected_guardrails": 0,
            "solver_matched": 0,
            "solver_discrepancy": 0,
            "total_tokens_used": 0,
            "staged_ids": []
        }

        try:
            for q in self.extractor.extract_from_pdf(pdf_path, max_pages=max_pages):
                metrics["total_extracted"] += 1
                q_tokens = q.get("tokens_used", {})
                q_total_tokens = q_tokens.get("total", 0)

                stem = q.get("question_text_latex", "")
                opts = q.get("options", [])
                correct_opt = q.get("correct_option")
                has_diag = q.get("has_diagram", False)
                diag_key = q.get("diagram_s3_key")
                page_num = q.get("page_number", 1)

                # --- LAYER 1: ACADEMIC GUARDRAILS ---
                is_valid, flaws = validate_question_guardrails(
                    stem=stem,
                    options=opts,
                    has_diagram=has_diag,
                    diagram_s3_key=diag_key,
                    question_type=q.get("question_type", "SINGLE_CHOICE")
                )

                guardrail_status = "PASSED" if is_valid else "REJECTED"
                if is_valid:
                    metrics["passed_guardrails"] += 1
                else:
                    metrics["rejected_guardrails"] += 1

                # --- LAYER 2: 3-TIER HIERARCHICAL CLASSIFICATION ---
                class_res = self.classifier.classify_question(
                    stem=stem,
                    options=opts,
                    subject_hint=subject_hint,
                    chapter_hint=chapter_hint
                )
                c_tokens = class_res.get("tokens_used", {})
                q_total_tokens += c_tokens.get("total", 0)

                # --- LAYER 3: BLIND SOLVER PARITY ARBITER ---
                solver_status = "SKIPPED"
                solver_opt = None
                solver_reasoning = ""

                if run_solver and is_valid:
                    solve_res = self.solver.solve_blind(
                        stem=stem,
                        options=opts,
                        question_type=q.get("question_type", "SINGLE_CHOICE"),
                        extracted_answer=correct_opt
                    )
                    solver_status = solve_res.get("solver_status", "SKIPPED")
                    solver_opt = solve_res.get("solver_option")
                    solver_reasoning = solve_res.get("reasoning", "")
                    s_tokens = solve_res.get("tokens_used", {})
                    q_total_tokens += s_tokens.get("total", 0)

                    if solver_status == "MATCHED":
                        metrics["solver_matched"] += 1
                    elif solver_status == "DISCREPANCY":
                        metrics["solver_discrepancy"] += 1

                # --- OVERALL REVIEW STATUS ---
                if guardrail_status == "PASSED" and solver_status == "MATCHED":
                    review_status = "APPROVED"
                elif guardrail_status == "PASSED":
                    review_status = "PENDING_REVIEW"
                else:
                    review_status = "REJECTED"

                metrics["total_tokens_used"] += q_total_tokens

                # --- LAYER 4: WRITE TO STAGING TABLE ---
                staging_uid = f"stg_{uuid.uuid4().hex[:12]}"
                with get_db_cursor() as cur:
                    cur.execute("""
                        INSERT INTO public.staged_questions (
                            staging_uid, source_pdf, page_number,
                            subject, unit_code, chapter_name, primary_topic_code, topic_name,
                            question_type, question_text_latex, options, correct_option, numerical_target,
                            solution_text_latex, has_diagram, diagram_s3_key,
                            guardrail_status, guardrail_notes,
                            solver_status, solver_option, solver_reasoning,
                            review_status,
                            prompt_tokens, completion_tokens, total_tokens, model_name
                        ) VALUES (
                            %s, %s, %s,
                            %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s,
                            %s, %s, %s,
                            %s, %s,
                            %s, %s, %s,
                            %s,
                            %s, %s, %s, %s
                        ) RETURNING id;
                    """, (
                        staging_uid, filename, page_num,
                        class_res["subject"], class_res["unit_code"], class_res["chapter_name"],
                        class_res["primary_topic_code"], class_res["topic_name"],
                        q.get("question_type", "SINGLE_CHOICE"), stem, json.dumps(opts),
                        correct_opt, q.get("numerical_target"),
                        q.get("solution_text_latex", ""), has_diag, diag_key,
                        guardrail_status, json.dumps(flaws),
                        solver_status, solver_opt, solver_reasoning,
                        review_status,
                        q_tokens.get("prompt", 0) + c_tokens.get("prompt", 0),
                        q_tokens.get("completion", 0) + c_tokens.get("completion", 0),
                        q_total_tokens, "qwen/qwen3.8-27b"
                    ))
                    stg_id = cur.fetchone()["id"]
                    metrics["staged_ids"].append(stg_id)

                status_tag = f"[{review_status}]"
                print(f"  -> Q{metrics['total_extracted']} (p.{page_num}): {status_tag} {stem[:70]}... (Tokens: {q_total_tokens})")

            # Update manifest to COMPLETED
            with get_db_cursor() as cur:
                cur.execute("""
                    UPDATE public.pdf_ingestion_manifest
                    SET status = 'COMPLETED',
                        extracted_questions = %s,
                        passed_guardrails = %s,
                        rejected_guardrails = %s,
                        total_tokens_used = %s,
                        completed_at = NOW()
                    WHERE pdf_path = %s;
                """, (
                    metrics["total_extracted"],
                    metrics["passed_guardrails"],
                    metrics["rejected_guardrails"],
                    metrics["total_tokens_used"],
                    pdf_path
                ))

        except Exception as e:
            print(f"Error processing PDF {filename}: {e}")
            with get_db_cursor() as cur:
                cur.execute("""
                    UPDATE public.pdf_ingestion_manifest
                    SET status = 'FAILED', error_message = %s, completed_at = NOW()
                    WHERE pdf_path = %s;
                """, (str(e), pdf_path))

        print(f"\nPDF Ingestion Summary for {filename}:")
        print(f"  - Extracted: {metrics['total_extracted']}")
        print(f"  - Passed Guardrails: {metrics['passed_guardrails']}")
        print(f"  - Rejected Guardrails: {metrics['rejected_guardrails']}")
        print(f"  - Solver Matched: {metrics['solver_matched']}")
        print(f"  - Total Tokens Consumed: {metrics['total_tokens_used']}")
        return metrics
