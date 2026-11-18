"""
Staging & Verification API Router
Allows inspecting, approving, rejecting, and promoting staged questions from the new ingestion pipeline.
"""

from __future__ import annotations
import json
import uuid
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from apps.api.db import get_db_cursor
from engines.ingestion.safe_ingestor import SafeIngestionPipeline
from engines.ingestion.full_test_ingestor import FullTestIngestor

router = APIRouter(prefix="/api/v1/staging", tags=["Staging & Ingestion Review"])

class UpdateStatusRequest(BaseModel):
    notes: Optional[str] = None

class SetAnswerRequest(BaseModel):
    correct_option: str
    auto_approve: bool = True

class IngestNextRequest(BaseModel):
    subject: Optional[str] = None
    pdf_path: Optional[str] = None
    max_pages: Optional[int] = 2
    no_solver: bool = False

@router.get("/summary")
def get_staging_summary():
    """Returns top-level KPIs of the ingestion pipeline."""
    with get_db_cursor() as cur:
        # Questions KPIs
        cur.execute("""
            SELECT 
                COUNT(*) as total_staged,
                COUNT(*) FILTER (WHERE review_status = 'APPROVED') as approved,
                COUNT(*) FILTER (WHERE review_status = 'PENDING_REVIEW') as pending_review,
                COUNT(*) FILTER (WHERE review_status = 'REJECTED') as rejected,
                COUNT(*) FILTER (WHERE review_status = 'PROMOTED') as promoted,
                COALESCE(SUM(total_tokens), 0) as total_tokens_used
            FROM public.staged_questions;
        """)
        q_stats = cur.fetchone()

        # PDF Manifest KPIs
        cur.execute("""
            SELECT 
                COUNT(*) as total_pdfs,
                COUNT(*) FILTER (WHERE status = 'COMPLETED') as completed_pdfs,
                COUNT(*) FILTER (WHERE status = 'IN_PROGRESS') as in_progress_pdfs,
                COUNT(*) FILTER (WHERE status = 'PENDING') as pending_pdfs,
                COUNT(*) FILTER (WHERE status = 'FAILED') as failed_pdfs
            FROM public.pdf_ingestion_manifest;
        """)
        pdf_stats = cur.fetchone()

    return {
        "questions": q_stats,
        "manifest": pdf_stats
    }

@router.post("/ingest-next")
def ingest_next_pdf(req: Optional[IngestNextRequest] = None):
    """
    Extracts, validates, classifies, and stages questions from the next pending PDF (or specified PDF).
    """
    subject_filter = req.subject.upper() if (req and req.subject) else None
    target_path = req.pdf_path if (req and req.pdf_path) else None
    max_pages = req.max_pages if req else 2
    no_solver = req.no_solver if req else False

    with get_db_cursor() as cur:
        if target_path:
            cur.execute("""
                SELECT pdf_path, subject, chapter_guess
                FROM public.pdf_ingestion_manifest
                WHERE pdf_path = %s;
            """, (target_path,))
        elif subject_filter:
            cur.execute("""
                SELECT pdf_path, subject, chapter_guess
                FROM public.pdf_ingestion_manifest
                WHERE status = 'PENDING' AND subject = %s
                ORDER BY id ASC
                LIMIT 1;
            """, (subject_filter,))
        else:
            cur.execute("""
                SELECT pdf_path, subject, chapter_guess
                FROM public.pdf_ingestion_manifest
                WHERE status = 'PENDING' AND subject IN ('PHYSICS', 'CHEMISTRY', 'MATHEMATICS')
                ORDER BY id ASC
                LIMIT 1;
            """)
        target = cur.fetchone()

    if not target:
        raise HTTPException(status_code=404, detail="No pending PDFs found matching the criteria.")

    is_full_test = (
        "Question Paper with Answer Key.pdf" in target["pdf_path"] or
        "full_tests" in target["pdf_path"] or
        target.get("subject") == "FULL_TEST" or
        subject_filter == "FULL_TEST"
    )

    if is_full_test:
        full_ingestor = FullTestIngestor()
        metrics = full_ingestor.ingest_full_test(
            pdf_path=target["pdf_path"],
            limit_questions=15,
            auto_promote_matched=True
        )
        return {
            "status": "SUCCESS",
            "message": f"Successfully ingested full test {metrics['pdf_filename']}! ({metrics['total_extracted']} extracted, {metrics['passed_guardrails']} passed guardrails, {metrics['solver_matched']} verified by blind solver, {metrics['auto_promoted']} auto-promoted).",
            "metrics": metrics
        }

    pipeline = SafeIngestionPipeline()
    metrics = pipeline.process_pdf(
        pdf_path=target["pdf_path"],
        subject_hint=target["subject"],
        chapter_hint=target["chapter_guess"],
        max_pages=max_pages,
        run_solver=not no_solver
    )

    return {
        "status": "SUCCESS",
        "message": f"Successfully extracted from {metrics['pdf_filename']}! ({metrics['total_extracted']} questions extracted, {metrics['passed_guardrails']} passed guardrails, {metrics['solver_matched']} matched blind solver).",
        "metrics": metrics
    }

@router.get("/manifest")
def list_manifest(
    status: Optional[str] = Query(None),
    subject: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0)
):
    """Lists ingested and pending PDFs."""
    query = "SELECT * FROM public.pdf_ingestion_manifest WHERE 1=1"
    params = []

    if status:
        query += " AND status = %s"
        params.append(status)
    if subject:
        query += " AND subject = %s"
        params.append(subject.upper())

    query += " ORDER BY id ASC LIMIT %s OFFSET %s;"
    params.extend([limit, offset])

    with get_db_cursor() as cur:
        cur.execute(query, tuple(params))
        rows = cur.fetchall()

    return {"pdfs": rows}

@router.get("/questions")
def list_staged_questions(
    review_status: Optional[str] = Query(None),
    subject: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    """Lists staged questions with guardrail logs and solver arbitration results."""
    query = "SELECT * FROM public.staged_questions WHERE 1=1"
    params = []

    if review_status:
        query += " AND review_status = %s"
        params.append(review_status.upper())
    if subject:
        query += " AND subject = %s"
        params.append(subject.upper())

    query += " ORDER BY id DESC LIMIT %s OFFSET %s;"
    params.extend([limit, offset])

    with get_db_cursor() as cur:
        cur.execute(query, tuple(params))
        rows = cur.fetchall()

    return {"questions": rows}

@router.patch("/questions/{question_id}/answer")
def set_question_answer(question_id: int, req: SetAnswerRequest):
    """Sets the correct option manually from the UI and updates solver status."""
    new_opt = req.correct_option.strip().upper()
    with get_db_cursor() as cur:
        cur.execute("SELECT * FROM public.staged_questions WHERE id = %s;", (question_id,))
        q = cur.fetchone()
        if not q:
            raise HTTPException(status_code=404, detail="Staged question not found")

        solver_opt = (q["solver_option"] or "").strip().upper()
        solver_status = "MATCHED" if new_opt == solver_opt else "DISCREPANCY"
        new_review = "APPROVED" if (req.auto_approve and q["guardrail_status"] == "PASSED") else q["review_status"]

        cur.execute("""
            UPDATE public.staged_questions
            SET correct_option = %s,
                solver_status = %s,
                review_status = %s,
                reviewed_at = NOW()
            WHERE id = %s
            RETURNING *;
        """, (new_opt, solver_status, new_review, question_id))
        updated = cur.fetchone()

    return {"status": "SUCCESS", "message": f"Answer for question {question_id} set to {new_opt}.", "question": updated}

@router.post("/questions/{question_id}/approve")
def approve_question(question_id: int):
    """Marks a staged question as APPROVED for production."""
    with get_db_cursor() as cur:
        cur.execute("""
            UPDATE public.staged_questions
            SET review_status = 'APPROVED', reviewed_at = NOW()
            WHERE id = %s RETURNING id;
        """, (question_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Staged question not found")

    return {"status": "SUCCESS", "message": f"Question {question_id} approved."}

@router.post("/questions/{question_id}/reject")
def reject_question(question_id: int, req: Optional[UpdateStatusRequest] = None):
    """Marks a staged question as REJECTED."""
    with get_db_cursor() as cur:
        cur.execute("""
            UPDATE public.staged_questions
            SET review_status = 'REJECTED', reviewed_at = NOW()
            WHERE id = %s RETURNING id;
        """, (question_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Staged question not found")

    return {"status": "SUCCESS", "message": f"Question {question_id} rejected."}

@router.post("/promote")
def promote_approved_to_production():
    """
    Promotes all 'APPROVED' questions from staged_questions into completed_questions
    with assessment_status = 'ELIGIBLE' and academic_status = 'MODEL_REVIEWED'.
    """
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT * FROM public.staged_questions
            WHERE review_status = 'APPROVED';
        """)
        approved_rows = cur.fetchall()

        if not approved_rows:
            return {"promoted_count": 0, "message": "No approved questions to promote."}

        promoted_count = 0
        for r in approved_rows:
            new_uid = f"pyq_staged_{r['staging_uid']}"
            cur.execute("""
                INSERT INTO public.completed_questions (
                    question_uid, subject, unit_code, chapter_name, primary_topic_code,
                    question_type, question_text_latex, options, correct_option, numerical_target,
                    solution_text_latex, has_diagram, diagram_s3_key,
                    assessment_status, academic_status, tags
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    'ELIGIBLE', 'MODEL_REVIEWED',
                    jsonb_build_array('STAGED_PROMOTED', 'SOURCE_PDF: ' || %s)
                )
                ON CONFLICT (question_uid) DO UPDATE
                SET question_text_latex = EXCLUDED.question_text_latex,
                    options = EXCLUDED.options,
                    correct_option = EXCLUDED.correct_option,
                    solution_text_latex = EXCLUDED.solution_text_latex,
                    has_diagram = EXCLUDED.has_diagram,
                    diagram_s3_key = EXCLUDED.diagram_s3_key,
                    assessment_status = 'ELIGIBLE',
                    academic_status = 'MODEL_REVIEWED',
                    tags = EXCLUDED.tags;
            """, (
                new_uid, r["subject"], r["unit_code"], r["chapter_name"], r["primary_topic_code"],
                r["question_type"], r["question_text_latex"], json.dumps(r["options"]) if isinstance(r["options"], list) else r["options"],
                r["correct_option"], r["numerical_target"],
                r["solution_text_latex"], r["has_diagram"], r["diagram_s3_key"],
                r["source_pdf"]
            ))

            # Update staging row status
            cur.execute("""
                UPDATE public.staged_questions
                SET review_status = 'PROMOTED', promoted_at = NOW()
                WHERE id = %s;
            """, (r["id"],))
            promoted_count += 1

    return {
        "status": "SUCCESS",
        "promoted_count": promoted_count,
        "message": f"Successfully promoted {promoted_count} verified questions into active student question bank!"
    }

