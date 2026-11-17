from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any
import fitz
from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field

from apps.api.db import get_db_cursor

router = APIRouter(prefix="/api/v1/admin/taxonomy-review", tags=["taxonomy-review"])


# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class ReviewSummaryResponse(BaseModel):
    total_canonical: int
    reviewed_count: int
    confirmed_count: int
    reclassified_count: int
    proposals_count: int
    uncertain_count: int
    source_problem_count: int
    not_reviewed_count: int
    corrections_applied_count: int
    completion_pct: float
    accuracy_pct: float
    original_accuracy_pct: float = 0.0
    corrected_coverage_pct: float = 0.0


class TaxonomyNodeInfo(BaseModel):
    id: int
    code: str
    name: str
    level: str
    parent_id: int | None = None
    subject: str | None = None


class TaxonomyTreeResponse(BaseModel):
    total_nodes: int
    subjects: list[TaxonomyNodeInfo]
    units: list[TaxonomyNodeInfo]
    topics: list[TaxonomyNodeInfo]
    subtopics: list[TaxonomyNodeInfo]


class ReviewQuestionItem(BaseModel):
    public_id: str
    subject: str
    question_type: str
    stem_preview: str
    unit_code: str | None = None
    unit_name: str | None = None
    topic_code: str | None = None
    topic_name: str | None = None
    subtopic_code: str | None = None
    subtopic_name: str | None = None
    source_title: str | None = None
    source_local_number: int | None = None
    source_page_start: int | None = None
    latest_decision: str | None = None
    is_applied: bool | None = None
    reviewed_at: str | None = None


class ReviewQuestionListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    total_pages: int
    items: list[ReviewQuestionItem]


class TaxonomyHierarchySnapshot(BaseModel):
    subject: dict[str, Any] = Field(default_factory=dict)
    unit: dict[str, Any] = Field(default_factory=dict)
    topic: dict[str, Any] = Field(default_factory=dict)
    subtopic: dict[str, Any] = Field(default_factory=dict)
    tag_level: str = "subtopic"
    is_primary: bool = True
    confidence: float | None = None


class ReviewHistoryItem(BaseModel):
    audit_id: int
    decision: str
    reviewer_id: str
    reviewer_notes: str | None = None
    proposed_taxonomy: dict[str, Any] | None = None
    is_applied: bool
    reviewed_at: str
    applied_at: str | None = None
    applied_by: str | None = None


class ReviewQuestionDetailResponse(BaseModel):
    public_id: str
    id: str
    subject: str
    question_type: str
    language: str
    stem_md: str
    stem_plain: str | None = None
    options: list[dict[str, Any]] = Field(default_factory=list)
    answer: dict[str, Any] = Field(default_factory=dict)
    explanation_md: str | None = None
    source_explanation_md: str | None = None
    difficulty: int | None = None
    cognitive_level: str | None = None
    estimated_time_sec: int | None = None
    formulas_used: list[str] = Field(default_factory=list)
    concept_tags: list[str] = Field(default_factory=list)
    skill_tags: list[str] = Field(default_factory=list)
    source_title: str | None = None
    source_publisher: str | None = None
    source_exam_name: str | None = None
    source_exam_year: int | None = None
    source_file_path: str | None = None
    source_q_label: str | None = None
    source_local_number: int | None = None
    source_page_start: int | None = None
    source_page_end: int | None = None
    has_figure: bool = False
    figure_status: str = "none"
    figure_description: str | None = None
    current_taxonomy: TaxonomyHierarchySnapshot
    secondary_tags: list[dict[str, Any]] = Field(default_factory=list)
    review_history: list[ReviewHistoryItem] = Field(default_factory=list)
    latest_audit: ReviewHistoryItem | None = None


class SubmitDecisionRequest(BaseModel):
    public_id: str
    reviewer_decision: str  # CONFIRM_CORRECT, RECLASSIFY, NEEDS_TAXONOMY_PROPOSAL, UNCERTAIN, SOURCE_PROBLEM
    proposed_subtopic_id: int | None = None
    proposal_details: str | None = None
    reviewer_notes: str | None = None
    reviewer_id: str = "internal_reviewer"
    apply_immediately: bool = True


class ApplyCorrectionRequest(BaseModel):
    audit_id: int
    reviewer_id: str = "internal_reviewer"


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def trace_taxonomy_hierarchy(cur, taxonomy_id: int) -> dict[str, Any]:
    """Given a taxonomy node id, recursively traces parent up to subject and returns a structured dictionary."""
    cur.execute("""
        WITH RECURSIVE tax_tree AS (
            SELECT id, code, name, level, parent_id, 1 as depth
            FROM taxonomy
            WHERE id = %s
            UNION ALL
            SELECT t.id, t.code, t.name, t.level, t.parent_id, tt.depth + 1
            FROM taxonomy t
            JOIN tax_tree tt ON t.id = tt.parent_id
        )
        SELECT id, code, name, level, parent_id FROM tax_tree ORDER BY depth DESC;
    """, (taxonomy_id,))
    chain = cur.fetchall()
    
    hierarchy = {
        "subject": {},
        "unit": {},
        "topic": {},
        "subtopic": {},
        "tag_level": "subtopic"
    }
    
    for node in chain:
        lvl = node["level"]
        item = {"id": node["id"], "code": node["code"], "name": node["name"]}
        if lvl in ("subject", "area"):
            hierarchy["subject"] = item
        elif lvl == "unit":
            hierarchy["unit"] = item
        elif lvl == "topic":
            hierarchy["topic"] = item
        elif lvl == "subtopic":
            hierarchy["subtopic"] = item
            hierarchy["tag_level"] = "subtopic"

    if chain:
        hierarchy["tag_level"] = chain[-1]["level"]
        
    return hierarchy


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.get("/summary", response_model=ReviewSummaryResponse)
def get_review_summary():
    """Returns live summary metrics of the taxonomy audit progress."""
    try:
        with get_db_cursor() as cur:
            cur.execute("SELECT count(*) as cnt FROM questions")
            total_canonical = cur.fetchone()["cnt"]

            # Distinct questions with an audit decision
            cur.execute("""
                SELECT count(DISTINCT question_id) as cnt 
                FROM taxonomy_review_audits
            """)
            reviewed_count = cur.fetchone()["cnt"]

            # Latest decision per question
            cur.execute("""
                SELECT DISTINCT ON (question_id)
                    question_id, reviewer_decision, is_applied
                FROM taxonomy_review_audits
                ORDER BY question_id, reviewed_at DESC, id DESC
            """)
            latest_rows = cur.fetchall()

            decision_counts = {
                "CONFIRM_CORRECT": 0,
                "RECLASSIFY": 0,
                "NEEDS_TAXONOMY_PROPOSAL": 0,
                "UNCERTAIN": 0,
                "SOURCE_PROBLEM": 0
            }
            for r in latest_rows:
                d = r["reviewer_decision"]
                if d in decision_counts:
                    decision_counts[d] += 1

            cur.execute("SELECT count(*) as cnt FROM taxonomy_review_audits WHERE is_applied = true")
            applied_count = cur.fetchone()["cnt"]

            not_reviewed = total_canonical - reviewed_count
            completion_pct = round((reviewed_count * 100.0 / total_canonical), 1) if total_canonical > 0 else 0.0

            # Accuracy: Confirmed / (Confirmed + Reclassified) - uncertain cases excluded from denominator
            decided = decision_counts["CONFIRM_CORRECT"] + decision_counts["RECLASSIFY"]
            original_accuracy_pct = round((decision_counts["CONFIRM_CORRECT"] * 100.0 / decided), 1) if decided > 0 else 100.0

            # Corrected taxonomy coverage: (Confirmed + Corrections Applied) / Total Canonical
            corrected_coverage_pct = round(((decision_counts["CONFIRM_CORRECT"] + applied_count) * 100.0 / total_canonical), 1) if total_canonical > 0 else 0.0

            return ReviewSummaryResponse(
                total_canonical=total_canonical,
                reviewed_count=reviewed_count,
                confirmed_count=decision_counts["CONFIRM_CORRECT"],
                reclassified_count=decision_counts["RECLASSIFY"],
                proposals_count=decision_counts["NEEDS_TAXONOMY_PROPOSAL"],
                uncertain_count=decision_counts["UNCERTAIN"],
                source_problem_count=decision_counts["SOURCE_PROBLEM"],
                not_reviewed_count=not_reviewed,
                corrections_applied_count=applied_count,
                completion_pct=completion_pct,
                accuracy_pct=original_accuracy_pct,
                original_accuracy_pct=original_accuracy_pct,
                corrected_coverage_pct=corrected_coverage_pct
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error loading review summary: {e}")


@router.get("/taxonomy-tree", response_model=TaxonomyTreeResponse)
def get_taxonomy_tree():
    """Returns the full 767-node taxonomy organized by level for UI cascading selectboxes."""
    try:
        with get_db_cursor() as cur:
            cur.execute("""
                SELECT id, code, level, name, parent_id
                FROM taxonomy
                WHERE is_active = true
                ORDER BY code ASC
            """)
            nodes = cur.fetchall()

            subjects = []
            units = []
            topics = []
            subtopics = []

            for n in nodes:
                lvl = n["level"]
                code = n["code"]
                subj = "mathematics" if code.startswith("MAT") else "physics" if code.startswith("PHY") else "chemistry"
                info = TaxonomyNodeInfo(
                    id=n["id"],
                    code=n["code"],
                    name=n["name"],
                    level=lvl,
                    parent_id=n["parent_id"],
                    subject=subj
                )
                if lvl in ("subject", "area"):
                    subjects.append(info)
                elif lvl == "unit":
                    units.append(info)
                elif lvl == "topic":
                    topics.append(info)
                elif lvl == "subtopic":
                    subtopics.append(info)

            return TaxonomyTreeResponse(
                total_nodes=len(nodes),
                subjects=subjects,
                units=units,
                topics=topics,
                subtopics=subtopics
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error loading taxonomy tree: {e}")


@router.get("/questions", response_model=ReviewQuestionListResponse)
def list_review_questions(
    subject: str | None = Query(None),
    unit_code: str | None = Query(None),
    topic_code: str | None = Query(None),
    subtopic_code: str | None = Query(None),
    review_status: str = Query("ALL"),
    suspicious_only: bool = Query(False),
    missing_subtopic_only: bool = Query(False),
    missing_source_only: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(1, ge=1, le=100)
):
    """Filters canonical questions for taxonomy review."""
    try:
        with get_db_cursor() as cur:
            where_clauses = ["1=1"]
            params: list[Any] = []

            if subject and subject.lower() != "all":
                where_clauses.append("LOWER(q.subject) = LOWER(%s)")
                params.append(subject.strip())

            if unit_code and unit_code.lower() != "all":
                where_clauses.append("(u.code = %s OR t.code LIKE %s)")
                params.extend([unit_code.strip(), f"{unit_code.strip()}%"])

            if topic_code and topic_code.lower() != "all":
                where_clauses.append("(top.code = %s OR t.code LIKE %s)")
                params.extend([topic_code.strip(), f"{topic_code.strip()}%"])

            if subtopic_code and subtopic_code.lower() != "all":
                where_clauses.append("t.code = %s")
                params.append(subtopic_code.strip())

            if missing_subtopic_only:
                where_clauses.append("(t.level != 'subtopic' OR t.id IS NULL)")

            if missing_source_only:
                where_clauses.append("(q.source_doc_id IS NULL OR q.source_q_label IS NULL)")

            if suspicious_only:
                where_clauses.append("""
                    (t.level != 'subtopic' OR 
                     (q.subject = 'physics' AND t.code NOT LIKE 'PHY%%') OR
                     (q.subject = 'chemistry' AND t.code NOT LIKE 'CHE%%') OR
                     (q.subject = 'mathematics' AND t.code NOT LIKE 'MAT%%'))
                """)

            # Review status filtering
            if review_status == "NOT_REVIEWED":
                where_clauses.append("latest_audit.reviewer_decision IS NULL")
            elif review_status == "CORRECTIONS_APPLIED":
                where_clauses.append("latest_audit.is_applied = true")
            elif review_status in ("CONFIRM_CORRECT", "RECLASSIFY", "NEEDS_TAXONOMY_PROPOSAL", "UNCERTAIN", "SOURCE_PROBLEM"):
                where_clauses.append("latest_audit.reviewer_decision = %s")
                params.append(review_status)

            where_sql = " AND ".join(where_clauses)

            # CTE for latest audit record per question
            base_sql = f"""
                WITH latest_audits AS (
                    SELECT DISTINCT ON (question_id)
                        question_id, reviewer_decision, is_applied, reviewed_at
                    FROM taxonomy_review_audits
                    ORDER BY question_id, reviewed_at DESC, id DESC
                )
                SELECT 
                    q.public_id,
                    q.subject,
                    q.question_type,
                    LEFT(q.stem_plain, 140) as stem_preview,
                    u.code as unit_code,
                    u.name as unit_name,
                    top.code as topic_code,
                    top.name as topic_name,
                    t.code as subtopic_code,
                    t.name as subtopic_name,
                    d.title as source_title,
                    q.source_local_number,
                    q.source_page_start,
                    latest_audit.reviewer_decision as latest_decision,
                    latest_audit.is_applied,
                    latest_audit.reviewed_at
                FROM questions q
                LEFT JOIN question_tags qt ON q.id = qt.question_id AND qt.is_primary = true
                LEFT JOIN taxonomy t ON qt.taxonomy_id = t.id
                LEFT JOIN taxonomy top ON t.parent_id = top.id
                LEFT JOIN taxonomy u ON top.parent_id = u.id
                LEFT JOIN source_documents d ON q.source_doc_id = d.id
                LEFT JOIN latest_audits latest_audit ON q.id = latest_audit.question_id
                WHERE {where_sql}
            """

            # Count total
            count_sql = f"SELECT count(*) as cnt FROM ({base_sql}) subquery"
            cur.execute(count_sql, params)
            total = cur.fetchone()["cnt"]

            total_pages = max(1, (total + page_size - 1) // page_size)
            offset = (page - 1) * page_size

            # Fetch page items
            paged_sql = f"{base_sql} ORDER BY q.public_id ASC LIMIT %s OFFSET %s"
            cur.execute(paged_sql, params + [page_size, offset])
            rows = cur.fetchall()

            items = [
                ReviewQuestionItem(
                    public_id=r["public_id"],
                    subject=r["subject"],
                    question_type=r["question_type"],
                    stem_preview=r["stem_preview"] or "",
                    unit_code=r["unit_code"],
                    unit_name=r["unit_name"],
                    topic_code=r["topic_code"],
                    topic_name=r["topic_name"],
                    subtopic_code=r["subtopic_code"],
                    subtopic_name=r["subtopic_name"],
                    source_title=r["source_title"],
                    source_local_number=r["source_local_number"],
                    source_page_start=r["source_page_start"],
                    latest_decision=r["latest_decision"],
                    is_applied=r["is_applied"],
                    reviewed_at=str(r["reviewed_at"]) if r["reviewed_at"] else None
                )
                for r in rows
            ]

            return ReviewQuestionListResponse(
                total=total,
                page=page,
                page_size=page_size,
                total_pages=total_pages,
                items=items
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error listing review questions: {e}")


@router.get("/question/{public_id}", response_model=ReviewQuestionDetailResponse)
def get_review_question_detail(public_id: str):
    """Returns complete details of a single question for taxonomy audit."""
    clean_id = public_id.strip().upper()
    try:
        with get_db_cursor() as cur:
            cur.execute("""
                SELECT 
                    q.*,
                    d.title as source_title,
                    d.publisher as source_publisher,
                    d.exam as source_exam_name,
                    d.exam_year as source_exam_year,
                    d.file_path as source_file_path,
                    d.license_status as source_license_status
                FROM questions q
                LEFT JOIN source_documents d ON q.source_doc_id = d.id
                WHERE q.public_id = %s
            """, (clean_id,))
            q = cur.fetchone()
            if not q:
                raise HTTPException(status_code=404, detail=f"Question {clean_id} not found")

            # Fetch options
            cur.execute("""
                SELECT position, label_printed, text_md
                FROM question_options
                WHERE question_id = %s
                ORDER BY position ASC
            """, (q["id"],))
            options = cur.fetchall()

            # Primary tag & full taxonomy chain
            cur.execute("""
                SELECT qt.taxonomy_id, qt.confidence, qt.is_primary, t.level
                FROM question_tags qt
                JOIN taxonomy t ON qt.taxonomy_id = t.id
                WHERE qt.question_id = %s AND qt.is_primary = true
            """, (q["id"],))
            ptag = cur.fetchone()

            if ptag:
                tax_hierarchy = trace_taxonomy_hierarchy(cur, ptag["taxonomy_id"])
                tax_hierarchy["is_primary"] = True
                tax_hierarchy["confidence"] = ptag["confidence"]
            else:
                tax_hierarchy = {
                    "subject": {"name": q["subject"]},
                    "unit": {},
                    "topic": {},
                    "subtopic": {},
                    "tag_level": "none",
                    "is_primary": False,
                    "confidence": None
                }

            # Secondary tags
            cur.execute("""
                SELECT t.id, t.code, t.name, t.level, qt.confidence
                FROM question_tags qt
                JOIN taxonomy t ON qt.taxonomy_id = t.id
                WHERE qt.question_id = %s AND qt.is_primary = false
                ORDER BY t.code ASC
            """, (q["id"],))
            sec_tags = cur.fetchall()

            # Review history
            cur.execute("""
                SELECT 
                    id as audit_id,
                    reviewer_decision as decision,
                    reviewer_id,
                    reviewer_notes,
                    proposed_taxonomy_snapshot as proposed_taxonomy,
                    is_applied,
                    reviewed_at,
                    applied_at,
                    applied_by
                FROM taxonomy_review_audits
                WHERE question_id = %s
                ORDER BY reviewed_at DESC, id DESC
            """, (q["id"],))
            history_rows = cur.fetchall()

            history_items = [
                ReviewHistoryItem(
                    audit_id=r["audit_id"],
                    decision=r["decision"],
                    reviewer_id=r["reviewer_id"],
                    reviewer_notes=r["reviewer_notes"],
                    proposed_taxonomy=r["proposed_taxonomy"],
                    is_applied=r["is_applied"],
                    reviewed_at=str(r["reviewed_at"]),
                    applied_at=str(r["applied_at"]) if r["applied_at"] else None,
                    applied_by=r["applied_by"]
                )
                for r in history_rows
            ]

            latest_audit = history_items[0] if history_items else None

            return ReviewQuestionDetailResponse(
                public_id=q["public_id"],
                id=str(q["id"]),
                subject=q["subject"],
                question_type=q["question_type"],
                language=q["language"] or "en",
                stem_md=q["stem_md"] or "",
                stem_plain=q["stem_plain"] or "",
                options=options,
                answer=q["answer"] or {},
                explanation_md=q["explanation_md"],
                source_explanation_md=q["source_explanation_md"],
                difficulty=q["difficulty"],
                cognitive_level=q["cognitive_level"],
                estimated_time_sec=q["estimated_time_sec"],
                formulas_used=q["formulas_used"] or [],
                concept_tags=q["concept_tags"] or [],
                skill_tags=q["skill_tags"] or [],
                source_title=q["source_title"],
                source_publisher=q["source_publisher"],
                source_exam_name=q["source_exam_name"],
                source_exam_year=q["source_exam_year"],
                source_file_path=q["source_file_path"],
                source_q_label=q["source_q_label"],
                source_local_number=q["source_local_number"],
                source_page_start=q["source_page_start"],
                source_page_end=q["source_page_end"],
                has_figure=q["has_figure"] or False,
                figure_status=q["figure_status"] or "none",
                figure_description=q["figure_description"],
                current_taxonomy=TaxonomyHierarchySnapshot(**tax_hierarchy),
                secondary_tags=sec_tags,
                review_history=history_items,
                latest_audit=latest_audit
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error loading question detail {clean_id}: {e}")


@router.get("/source-page/{public_id}")
def get_source_page_preview(public_id: str):
    """Renders the original source PDF page as a high-clarity PNG image."""
    clean_id = public_id.strip().upper()
    try:
        with get_db_cursor() as cur:
            cur.execute("""
                SELECT q.source_page_start, d.file_path, d.title
                FROM questions q
                JOIN source_documents d ON q.source_doc_id = d.id
                WHERE q.public_id = %s
            """, (clean_id,))
            row = cur.fetchone()
            if not row or not row["file_path"]:
                raise HTTPException(status_code=404, detail="Source document file path not found")

            file_path = Path(row["file_path"])
            if not file_path.exists():
                raise HTTPException(status_code=404, detail=f"PDF file does not exist on disk: {file_path}")

            page_num = row["source_page_start"] or 1
            doc = fitz.open(str(file_path))
            page_idx = max(0, min(page_num - 1, len(doc) - 1))
            page = doc.load_page(page_idx)
            pix = page.get_pixmap(dpi=130)
            png_bytes = pix.tobytes("png")

            return Response(content=png_bytes, media_type="image/png")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render source page for {clean_id}: {e}")


@router.get("/next-unreviewed")
def get_next_unreviewed_question(
    subject: str | None = Query(None),
    unit_code: str | None = Query(None)
):
    """Returns the public_id of the next unreviewed canonical question matching filters."""
    try:
        with get_db_cursor() as cur:
            where_clauses = ["a.id IS NULL"]
            params: list[Any] = []

            if subject and subject.lower() != "all":
                where_clauses.append("LOWER(q.subject) = LOWER(%s)")
                params.append(subject.strip())

            if unit_code and unit_code.lower() != "all":
                where_clauses.append("(u.code = %s OR t.code LIKE %s)")
                params.extend([unit_code.strip(), f"{unit_code.strip()}%"])

            where_sql = " AND ".join(where_clauses)

            cur.execute(f"""
                SELECT q.public_id
                FROM questions q
                LEFT JOIN question_tags qt ON q.id = qt.question_id AND qt.is_primary = true
                LEFT JOIN taxonomy t ON qt.taxonomy_id = t.id
                LEFT JOIN taxonomy top ON t.parent_id = top.id
                LEFT JOIN taxonomy u ON top.parent_id = u.id
                LEFT JOIN (
                    SELECT DISTINCT question_id, id FROM taxonomy_review_audits
                ) a ON q.id = a.question_id
                WHERE {where_sql}
                ORDER BY q.public_id ASC
                LIMIT 1
            """, params)
            row = cur.fetchone()
            if not row:
                return {"public_id": None, "message": "All matching questions have been reviewed!"}

            return {"public_id": row["public_id"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error finding next unreviewed question: {e}")


@router.post("/decision")
def submit_review_decision(req: SubmitDecisionRequest):
    """Records a manual reviewer taxonomy decision and applies corrections immediately when requested in one atomic transaction."""
    clean_id = req.public_id.strip().upper()
    allowed_decisions = ("CONFIRM_CORRECT", "RECLASSIFY", "NEEDS_TAXONOMY_PROPOSAL", "UNCERTAIN", "SOURCE_PROBLEM")
    if req.reviewer_decision not in allowed_decisions:
        raise HTTPException(status_code=400, detail=f"Invalid decision. Must be one of: {allowed_decisions}")

    try:
        with get_db_cursor() as cur:
            cur.execute("SELECT id, subject FROM questions WHERE public_id = %s", (clean_id,))
            q = cur.fetchone()
            if not q:
                raise HTTPException(status_code=404, detail=f"Question {clean_id} not found")

            # Check for duplicate review submission
            cur.execute("""
                SELECT id, reviewer_decision, proposed_taxonomy_snapshot, reviewer_notes, is_applied
                FROM taxonomy_review_audits
                WHERE question_id = %s
                ORDER BY reviewed_at DESC, id DESC
                LIMIT 1
            """, (q["id"],))
            latest_audit = cur.fetchone()

            if latest_audit and latest_audit["reviewer_decision"] == req.reviewer_decision:
                lat_prop = latest_audit["proposed_taxonomy_snapshot"]
                lat_prop_id = (lat_prop.get("proposed_node_id") or lat_prop.get("subtopic", {}).get("id")) if lat_prop else None
                if lat_prop_id == req.proposed_subtopic_id and (latest_audit["reviewer_notes"] or "") == (req.reviewer_notes or ""):
                    if not req.apply_immediately or latest_audit["is_applied"]:
                        return {
                            "status": "success",
                            "message": f"Review decision '{req.reviewer_decision}' is already recorded for {clean_id}.",
                            "audit_id": latest_audit["id"],
                            "is_applied": latest_audit["is_applied"],
                            "duplicate_suppressed": True
                        }

            # Get current taxonomy snapshot
            cur.execute("""
                SELECT qt.taxonomy_id
                FROM question_tags qt
                WHERE qt.question_id = %s AND qt.is_primary = true
            """, (q["id"],))
            ptag = cur.fetchone()
            existing_snapshot = trace_taxonomy_hierarchy(cur, ptag["taxonomy_id"]) if ptag else {"subject": q["subject"]}

            proposed_snapshot = None
            proposed_node = None

            if req.reviewer_decision == "RECLASSIFY":
                if not req.proposed_subtopic_id:
                    raise HTTPException(status_code=400, detail="proposed_subtopic_id is required when decision is RECLASSIFY")
                cur.execute("SELECT id, code, name, level FROM taxonomy WHERE id = %s", (req.proposed_subtopic_id,))
                proposed_node = cur.fetchone()
                if not proposed_node:
                    raise HTTPException(status_code=400, detail=f"Taxonomy node id {req.proposed_subtopic_id} does not exist")
                
                proposed_snapshot = trace_taxonomy_hierarchy(cur, req.proposed_subtopic_id)
                proposed_snapshot["proposed_node_id"] = req.proposed_subtopic_id

            elif req.reviewer_decision == "NEEDS_TAXONOMY_PROPOSAL":
                proposed_snapshot = {
                    "proposal_type": "MISSING_SUBTOPIC",
                    "details": req.proposal_details or req.reviewer_notes or "Proposal recorded"
                }

            is_applied_flag = False
            applied_at_val = None
            applied_by_val = None

            # Immediate Application for RECLASSIFY
            if req.reviewer_decision == "RECLASSIFY" and req.apply_immediately and proposed_node:
                target_subject = "mathematics" if proposed_node["code"].startswith("MAT") else "physics" if proposed_node["code"].startswith("PHY") else "chemistry"

                # 1. Update questions.subject if target subject differs
                if target_subject.lower() != q["subject"].lower():
                    cur.execute("UPDATE questions SET subject = %s, updated_at = NOW() WHERE id = %s", (target_subject, q["id"]))

                # 2. Update primary tag in question_tags
                cur.execute("""
                    UPDATE question_tags 
                    SET taxonomy_id = %s,
                        confidence = 1.0,
                        source = 'human',
                        reviewed_by = %s,
                        reviewed_at = NOW()
                    WHERE question_id = %s AND is_primary = true
                """, (proposed_node["id"], req.reviewer_id, q["id"]))

                if cur.rowcount == 0:
                    cur.execute("""
                        INSERT INTO question_tags (question_id, taxonomy_id, is_primary, confidence, source, reviewed_by, reviewed_at)
                        VALUES (%s, %s, true, 1.0, 'human', %s, NOW())
                    """, (q["id"], proposed_node["id"], req.reviewer_id))

                is_applied_flag = True
                applied_by_val = req.reviewer_id

                # 3. Log into general review_records as well
                cur.execute("""
                    INSERT INTO review_records (
                        question_id, reviewer, action, previous_state, new_state, notes, created_at
                    ) VALUES (%s, %s, 'reclassified', %s, %s, %s, NOW())
                """, (
                    q["id"],
                    req.reviewer_id,
                    json.dumps(existing_snapshot),
                    json.dumps(proposed_snapshot),
                    req.reviewer_notes or "Taxonomy reclassification applied via immediate review"
                ))

            elif req.reviewer_decision == "CONFIRM_CORRECT":
                # Mark confirmation on primary tag
                cur.execute("""
                    UPDATE question_tags 
                    SET reviewed_by = %s,
                        reviewed_at = NOW()
                    WHERE question_id = %s AND is_primary = true
                """, (req.reviewer_id, q["id"]))

                cur.execute("""
                    INSERT INTO review_records (
                        question_id, reviewer, action, previous_state, new_state, notes, created_at
                    ) VALUES (%s, %s, 'approved', %s, %s, %s, NOW())
                """, (
                    q["id"],
                    req.reviewer_id,
                    json.dumps(existing_snapshot),
                    json.dumps(existing_snapshot),
                    req.reviewer_notes or "Taxonomy confirmed correct via review"
                ))

            # Insert append-only audit record
            cur.execute("""
                INSERT INTO taxonomy_review_audits (
                    question_id,
                    existing_taxonomy_snapshot,
                    proposed_taxonomy_snapshot,
                    reviewer_decision,
                    reviewer_notes,
                    reviewer_id,
                    is_applied,
                    reviewed_at,
                    applied_at,
                    applied_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), CASE WHEN %s THEN NOW() ELSE NULL END, %s)
                RETURNING id, reviewed_at, is_applied
            """, (
                q["id"],
                json.dumps(existing_snapshot),
                json.dumps(proposed_snapshot) if proposed_snapshot else None,
                req.reviewer_decision,
                req.reviewer_notes,
                req.reviewer_id,
                is_applied_flag,
                is_applied_flag,
                applied_by_val
            ))
            res = cur.fetchone()

            msg = f"Recorded review decision '{req.reviewer_decision}' for {clean_id}"
            if is_applied_flag and proposed_node:
                msg = f"Successfully reclassified and applied correction for {clean_id}: now mapped to {proposed_node['code']} - {proposed_node['name']}"

            return {
                "status": "success",
                "message": msg,
                "audit_id": res["id"],
                "is_applied": res["is_applied"],
                "reviewed_at": str(res["reviewed_at"]),
                "new_taxonomy_code": proposed_node["code"] if proposed_node else None,
                "new_taxonomy_name": proposed_node["name"] if proposed_node else None
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error saving review decision: {e}")


@router.post("/apply-correction")
def apply_taxonomy_correction(req: ApplyCorrectionRequest):
    """Explicitly applies a RECLASSIFY review decision to the canonical question_tags transactionally."""
    try:
        with get_db_cursor() as cur:
            cur.execute("""
                SELECT 
                    a.id, a.question_id, a.reviewer_decision, a.proposed_taxonomy_snapshot,
                    a.existing_taxonomy_snapshot, a.reviewer_notes, a.is_applied,
                    q.public_id, q.subject
                FROM taxonomy_review_audits a
                JOIN questions q ON a.question_id = q.id
                WHERE a.id = %s
            """, (req.audit_id,))
            audit = cur.fetchone()
            if not audit:
                raise HTTPException(status_code=404, detail=f"Audit record {req.audit_id} not found")

            if audit["is_applied"]:
                return {
                    "status": "already_applied",
                    "message": f"Audit {req.audit_id} has already been applied."
                }

            if audit["reviewer_decision"] != "RECLASSIFY":
                raise HTTPException(status_code=400, detail=f"Only RECLASSIFY decisions can be applied (found: {audit['reviewer_decision']})")

            proposed_snapshot = audit["proposed_taxonomy_snapshot"]
            if not proposed_snapshot:
                raise HTTPException(status_code=400, detail="Missing proposed taxonomy snapshot in audit record")

            # Extract new taxonomy id
            new_subtopic_id = proposed_snapshot.get("proposed_node_id") or proposed_snapshot.get("subtopic", {}).get("id") or proposed_snapshot.get("topic", {}).get("id")
            if not new_subtopic_id:
                raise HTTPException(status_code=400, detail="Could not determine target taxonomy node ID from proposed snapshot")

            # Verify target node
            cur.execute("SELECT id, code, name, level FROM taxonomy WHERE id = %s", (new_subtopic_id,))
            target_node = cur.fetchone()
            if not target_node:
                raise HTTPException(status_code=400, detail=f"Target taxonomy node {new_subtopic_id} not found")

            # Determine subject of target node
            target_subject = "mathematics" if target_node["code"].startswith("MAT") else "physics" if target_node["code"].startswith("PHY") else "chemistry"
            
            # 1. Update questions.subject if it differs
            if target_subject.lower() != audit["subject"].lower():
                cur.execute("UPDATE questions SET subject = %s, updated_at = NOW() WHERE id = %s", (target_subject, audit["question_id"]))

            # 2. Update primary tag in question_tags
            cur.execute("""
                UPDATE question_tags 
                SET taxonomy_id = %s,
                    confidence = 1.0,
                    source = 'human',
                    reviewed_by = %s,
                    reviewed_at = NOW()
                WHERE question_id = %s AND is_primary = true
            """, (new_subtopic_id, req.reviewer_id, audit["question_id"]))

            # If no primary tag existed, insert it
            if cur.rowcount == 0:
                cur.execute("""
                    INSERT INTO question_tags (question_id, taxonomy_id, is_primary, confidence, source, reviewed_by, reviewed_at)
                    VALUES (%s, %s, true, 1.0, 'human', %s, NOW())
                """, (audit["question_id"], new_subtopic_id, req.reviewer_id))

            # 3. Mark audit record as applied
            cur.execute("""
                UPDATE taxonomy_review_audits
                SET is_applied = true,
                    applied_at = NOW(),
                    applied_by = %s
                WHERE id = %s
            """, (req.reviewer_id, req.audit_id))

            # 4. Record in general review_records table as well
            cur.execute("""
                INSERT INTO review_records (
                    question_id, reviewer, action, previous_state, new_state, notes, created_at
                ) VALUES (%s, %s, 'reclassified', %s, %s, %s, NOW())
            """, (
                audit["question_id"],
                req.reviewer_id,
                json.dumps(audit["existing_taxonomy_snapshot"]),
                json.dumps(proposed_snapshot),
                audit["reviewer_notes"] or "Taxonomy reclassification applied via manual review"
            ))

            return {
                "status": "success",
                "message": f"Successfully applied taxonomy correction to {audit['public_id']}: mapped to {target_node['code']} - {target_node['name']}",
                "public_id": audit["public_id"],
                "new_taxonomy_code": target_node["code"],
                "new_taxonomy_name": target_node["name"]
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error applying correction: {e}")


@router.get("/suggest/{public_id}")
def suggest_taxonomy_classification(public_id: str):
    """Offline heuristic taxonomy suggestion that matches question text keywords against taxonomy nodes without consuming Groq tokens."""
    clean_id = public_id.strip().upper()
    try:
        with get_db_cursor() as cur:
            cur.execute("SELECT stem_plain, subject FROM questions WHERE public_id = %s", (clean_id,))
            q = cur.fetchone()
            if not q:
                raise HTTPException(status_code=404, detail="Question not found")

            stem = q["stem_plain"] or ""
            subj_prefix = "MAT" if q["subject"] == "mathematics" else "PHY" if q["subject"] == "physics" else "CHE"

            # Search taxonomy subtopics matching keywords in stem
            # Using basic word trigrams or tsvector if available, or ILIKE ranking
            cur.execute("""
                SELECT 
                    t.id, t.code, t.name, t.level,
                    u.code as unit_code, u.name as unit_name,
                    top.code as topic_code, top.name as topic_name
                FROM taxonomy t
                JOIN taxonomy top ON t.parent_id = top.id
                JOIN taxonomy u ON top.parent_id = u.id
                WHERE t.level = 'subtopic' AND t.code LIKE %s
                ORDER BY length(t.name) ASC
            """, (f"{subj_prefix}%",))
            candidates = cur.fetchall()

            # Rank by keyword overlap with stem
            stem_lower = stem.lower()
            scored = []
            for c in candidates:
                words = set(w.lower() for w in c["name"].split() if len(w) > 3)
                if not words:
                    continue
                matches = sum(1 for w in words if w in stem_lower)
                score = matches / len(words) if words else 0
                if matches > 0:
                    scored.append((score, c))

            scored.sort(key=lambda x: x[0], reverse=True)
            top_suggestions = [
                {
                    "subtopic_id": s[1]["id"],
                    "subtopic_code": s[1]["code"],
                    "subtopic_name": s[1]["name"],
                    "topic_name": s[1]["topic_name"],
                    "unit_name": s[1]["unit_name"],
                    "confidence_score": round(s[0], 2),
                    "note": "Offline Keyword-Overlap Suggestion (0 Groq tokens)"
                }
                for s in scored[:3]
            ]

            return {
                "public_id": clean_id,
                "suggestions": top_suggestions
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Suggestion error: {e}")
