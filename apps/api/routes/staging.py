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

router = APIRouter(prefix="/api/v1/staging", tags=["Staging & Ingestion Review"])

class UpdateStatusRequest(BaseModel):
    notes: Optional[str] = None

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
                );
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
