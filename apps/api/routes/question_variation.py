from __future__ import annotations

import json
import uuid
from typing import Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from apps.api.db import get_db_cursor
from engines.shared.config import settings
from engines.variation.generator import generate_variant_with_groq
from engines.variation.validator import (
    validate_structural,
    review_variant_with_groq,
    run_comprehensive_validation,
)

router = APIRouter(prefix="/api/v1/admin/question-variation", tags=["Admin Question Variation"])


class VariantGenerationRequest(BaseModel):
    public_id: str
    custom_guidance: str | None = None
    run_llm_review: bool = True


class ExperimentReviewRequest(BaseModel):
    human_verdict: str  # GOOD, INCORRECT, NEEDS_EDIT
    reviewer_feedback: str | None = None


@router.get("/filters")
def get_variation_filters():
    """Retrieve distinct Subjects, Units, and Topics available in canonical questions."""
    with get_db_cursor() as cur:
        # Subjects
        cur.execute("SELECT DISTINCT subject FROM questions WHERE status != 'rejected' ORDER BY subject;")
        subjects = [r["subject"] for r in cur.fetchall()]

        # Units & Topics from taxonomy connected to canonical questions
        cur.execute("""
            SELECT DISTINCT
                t_unit.code AS unit_code,
                t_unit.name AS unit_name,
                t_top.code AS topic_code,
                t_top.name AS topic_name,
                q.subject
            FROM questions q
            JOIN question_tags qt ON q.id = qt.question_id AND qt.is_primary = TRUE
            JOIN taxonomy t_sub ON qt.taxonomy_id = t_sub.id
            JOIN taxonomy t_top ON t_sub.parent_id = t_top.id
            JOIN taxonomy t_unit ON t_top.parent_id = t_unit.id
            ORDER BY q.subject, t_unit.code, t_top.code;
        """)
        hierarchy = cur.fetchall()

    return {
        "subjects": subjects,
        "hierarchy": hierarchy,
    }


@router.get("/questions")
def list_canonical_questions(
    subject: str | None = Query(None),
    unit_code: str | None = Query(None),
    topic_code: str | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """Browse canonical questions with optional subject/unit/topic/search filters."""
    conditions = ["q.status != 'rejected'"]
    params = []

    if subject:
        conditions.append("q.subject = %s")
        params.append(subject.lower())

    if search:
        conditions.append("(q.public_id ILIKE %s OR q.stem_plain ILIKE %s)")
        search_param = f"%{search.strip()}%"
        params.extend([search_param, search_param])

    if unit_code or topic_code:
        conditions.append("""
            EXISTS (
                SELECT 1 FROM question_tags qt
                JOIN taxonomy t_sub ON qt.taxonomy_id = t_sub.id
                JOIN taxonomy t_top ON t_sub.parent_id = t_top.id
                JOIN taxonomy t_unit ON t_top.parent_id = t_unit.id
                WHERE qt.question_id = q.id AND qt.is_primary = TRUE
                """ + (" AND t_unit.code = %s" if unit_code else "") +
                (" AND t_top.code = %s" if topic_code else "") + """
            )
        """)
        if unit_code:
            params.append(unit_code)
        if topic_code:
            params.append(topic_code)

    where_clause = " WHERE " + " AND ".join(conditions)

    query = f"""
        SELECT 
            q.id,
            q.public_id,
            q.subject,
            q.question_type,
            q.difficulty,
            q.stem_plain,
            q.has_figure,
            q.origin,
            q.created_at,
            t_unit.code AS unit_code,
            t_unit.name AS unit_name,
            t_top.code AS topic_code,
            t_top.name AS topic_name,
            t_sub.code AS subtopic_code,
            t_sub.name AS subtopic_name
        FROM questions q
        LEFT JOIN question_tags qt ON q.id = qt.question_id AND qt.is_primary = TRUE
        LEFT JOIN taxonomy t_sub ON qt.taxonomy_id = t_sub.id
        LEFT JOIN taxonomy t_top ON t_sub.parent_id = t_top.id
        LEFT JOIN taxonomy t_unit ON t_top.parent_id = t_unit.id
        {where_clause}
        ORDER BY q.public_id ASC
        LIMIT %s OFFSET %s;
    """
    params.extend([limit, offset])

    with get_db_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM questions q {where_clause};", params[:-2])
        total = cur.fetchone()["count"]

        cur.execute(query, params)
        rows = cur.fetchall()

    return {
        "total": total,
        "questions": rows,
    }


@router.get("/questions/{public_id}")
def get_canonical_question_detail(public_id: str):
    """Retrieve complete question detail including options, answer, explanation, and tags."""
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT 
                q.*,
                t_unit.code AS unit_code,
                t_unit.name AS unit_name,
                t_top.code AS topic_code,
                t_top.name AS topic_name,
                t_sub.code AS subtopic_code,
                t_sub.name AS subtopic_name
            FROM questions q
            LEFT JOIN question_tags qt ON q.id = qt.question_id AND qt.is_primary = TRUE
            LEFT JOIN taxonomy t_sub ON qt.taxonomy_id = t_sub.id
            LEFT JOIN taxonomy t_top ON t_sub.parent_id = t_top.id
            LEFT JOIN taxonomy t_unit ON t_top.parent_id = t_unit.id
            WHERE q.public_id = %s;
        """, (public_id,))
        question = cur.fetchone()

        if not question:
            raise HTTPException(status_code=404, detail=f"Question {public_id} not found")

        cur.execute("""
            SELECT position, label_printed, text_md
            FROM question_options
            WHERE question_id = %s
            ORDER BY position ASC;
        """, (question["id"],))
        options = cur.fetchall()
        question["options"] = options

    return question


@router.post("/generate")
def generate_variant(req: VariantGenerationRequest):
    """Invokes Groq to generate a variant, validates it, and saves it in experimental storage."""
    # 1. Fetch canonical question
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT q.*, 
                   t_unit.code AS unit_code, t_unit.name AS unit_name,
                   t_top.code AS topic_code, t_top.name AS topic_name,
                   t_sub.code AS subtopic_code, t_sub.name AS subtopic_name
            FROM questions q
            LEFT JOIN question_tags qt ON q.id = qt.question_id AND qt.is_primary = TRUE
            LEFT JOIN taxonomy t_sub ON qt.taxonomy_id = t_sub.id
            LEFT JOIN taxonomy t_top ON t_sub.parent_id = t_top.id
            LEFT JOIN taxonomy t_unit ON t_top.parent_id = t_unit.id
            WHERE q.public_id = %s;
        """, (req.public_id,))
        q = cur.fetchone()

        if not q:
            raise HTTPException(status_code=404, detail=f"Question {req.public_id} not found")

        cur.execute("""
            SELECT position, label_printed, text_md
            FROM question_options
            WHERE question_id = %s
            ORDER BY position ASC;
        """, (q["id"],))
        options = cur.fetchall()
        q["options"] = options

    # 2. Invoke Groq Generator
    variant_data = generate_variant_with_groq(q, custom_guidance=req.custom_guidance)

    # 3. Optional Groq Self-Review (Independent Auditor)
    groq_review = None
    if req.run_llm_review:
        groq_review = review_variant_with_groq(q, variant_data)

    # 4. Comprehensive Multi-Tier Validation & Status Assignment
    val_summary = run_comprehensive_validation(variant_data, q, groq_review=groq_review)
    status = val_summary["status"]
    structural_results = val_summary["structural"]
    deterministic_results = val_summary["deterministic"]
    difficulty_analysis = val_summary["difficulty"]

    # 5. Persist into Experimental Tables (Never canonical questions)
    gen_id = uuid.uuid4()
    var_public_id = f"VAR_{req.public_id}_{uuid.uuid4().hex[:6].upper()}"

    stem_plain = variant_data.get("stem_md", "")
    answer_json = json.dumps(variant_data.get("correct_answer", {}))
    explanation = variant_data.get("explanation_md", "")
    diff = int(variant_data.get("difficulty", q.get("difficulty", 3)))
    cog_level = variant_data.get("cognitive_level", "application")

    with get_db_cursor() as cur:
        cur.execute("""
            INSERT INTO generated_questions (
                id, public_id, source_question_id, subject, question_type,
                stem_md, stem_plain, answer, explanation_md, status,
                difficulty, cognitive_level
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s);
        """, (
            str(gen_id), var_public_id, q["id"], q["subject"], variant_data.get("question_type", q["question_type"]),
            variant_data.get("stem_md", ""), stem_plain, answer_json, explanation, status,
            diff, cog_level
        ))

        # Insert options if mcq
        for opt in variant_data.get("options", []):
            cur.execute("""
                INSERT INTO generated_question_options (
                    generated_question_id, position, label_printed, text_md
                ) VALUES (%s, %s, %s, %s);
            """, (
                str(gen_id), opt.get("position", 1), opt.get("label_printed", "A"), opt.get("text_md", "")
            ))

        # Insert experiment run
        source_snapshot = {
            "public_id": q["public_id"],
            "stem_md": q["stem_md"],
            "options": q["options"],
            "answer": q["answer"],
            "explanation_md": q["explanation_md"],
            "subject": q["subject"],
            "unit": q.get("unit_code"),
            "topic": q.get("topic_code"),
            "subtopic": q.get("subtopic_code"),
        }
        tokens_used = variant_data.get("_tokens_consumed", 0) + (groq_review.get("_review_tokens", 0) if groq_review else 0)

        cur.execute("""
            INSERT INTO generated_question_experiments (
                generated_question_id, source_question_id, source_snapshot,
                transformation_spec, validation_results, groq_review,
                model_name, tokens_consumed, deterministic_validation,
                difficulty_analysis, validation_status
            ) VALUES (%s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s::jsonb, %s::jsonb, %s)
            RETURNING id;
        """, (
            str(gen_id), q["id"],
            json.dumps(source_snapshot),
            json.dumps(variant_data.get("transformation_spec", {})),
            json.dumps(structural_results),
            json.dumps(groq_review) if groq_review else None,
            variant_data.get("_model", settings.groq_model),
            tokens_used,
            json.dumps(deterministic_results),
            json.dumps(difficulty_analysis),
            status
        ))
        exp_id = cur.fetchone()["id"]

    return {
        "experiment_id": exp_id,
        "variant_id": str(gen_id),
        "variant_public_id": var_public_id,
        "status": status,
        "source_question": source_snapshot,
        "variant": variant_data,
        "structural_validation": structural_results,
        "deterministic_validation": deterministic_results,
        "difficulty_analysis": difficulty_analysis,
        "groq_review": groq_review,
        "tokens_consumed": tokens_used,
    }


@router.get("/experiments")
def list_experiments(limit: int = 20, offset: int = 0):
    """List historical variation generation experiments."""
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT 
                e.id AS experiment_id,
                e.model_name,
                e.tokens_consumed,
                e.human_verdict,
                e.reviewer_feedback,
                e.validation_status,
                e.created_at,
                gq.public_id AS variant_public_id,
                gq.subject,
                gq.question_type,
                gq.status AS variant_status,
                q.public_id AS source_public_id
            FROM generated_question_experiments e
            JOIN generated_questions gq ON e.generated_question_id = gq.id
            JOIN questions q ON e.source_question_id = q.id
            ORDER BY e.created_at DESC
            LIMIT %s OFFSET %s;
        """, (limit, offset))
        experiments = cur.fetchall()

        cur.execute("SELECT COUNT(*) FROM generated_question_experiments;")
        total = cur.fetchone()["count"]

    return {
        "total": total,
        "experiments": experiments,
    }


@router.get("/experiments/{experiment_id}")
def get_experiment_detail(experiment_id: int):
    """Retrieve full details of an experiment including snapshots and validations."""
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT 
                e.*,
                gq.public_id AS variant_public_id,
                gq.stem_md AS variant_stem_md,
                gq.answer AS variant_answer,
                gq.explanation_md AS variant_explanation_md,
                gq.question_type AS variant_type,
                gq.status AS variant_status
            FROM generated_question_experiments e
            JOIN generated_questions gq ON e.generated_question_id = gq.id
            WHERE e.id = %s;
        """, (experiment_id,))
        exp = cur.fetchone()
        if not exp:
            raise HTTPException(status_code=404, detail="Experiment not found")

        cur.execute("""
            SELECT position, label_printed, text_md
            FROM generated_question_options
            WHERE generated_question_id = %s
            ORDER BY position ASC;
        """, (exp["generated_question_id"],))
        exp["variant_options"] = cur.fetchall()

    return exp


@router.post("/experiments/{experiment_id}/review")
def review_experiment(experiment_id: int, req: ExperimentReviewRequest):
    """Submit human evaluation verdict (GOOD, INCORRECT, NEEDS_EDIT) on a variant."""
    with get_db_cursor() as cur:
        cur.execute("""
            UPDATE generated_question_experiments
            SET human_verdict = %s,
                reviewer_feedback = %s,
                reviewed_at = NOW()
            WHERE id = %s
            RETURNING generated_question_id;
        """, (req.human_verdict, req.reviewer_feedback, experiment_id))
        res = cur.fetchone()
        if not res:
            raise HTTPException(status_code=404, detail="Experiment not found")

        gen_q_id = res["generated_question_id"]

        # Update generated_questions status accordingly
        new_status = "APPROVED" if req.human_verdict == "GOOD" else ("REJECTED" if req.human_verdict == "INCORRECT" else "NEEDS_REVIEW")
        cur.execute("""
            UPDATE generated_questions
            SET status = %s,
                updated_at = NOW()
            WHERE id = %s;
        """, (new_status, gen_q_id))

    return {"status": "success", "experiment_id": experiment_id, "human_verdict": req.human_verdict, "new_status": new_status}
