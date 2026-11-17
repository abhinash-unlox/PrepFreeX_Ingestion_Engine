from __future__ import annotations

import math
from typing import Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from apps.api.db import get_db_cursor, check_db_health


router = APIRouter(prefix="/api/v1", tags=["admin"])


# ============================================================================
# PYDANTIC RESPONSE MODELS
# ============================================================================

class HealthResponse(BaseModel):
    status: str
    database_connected: bool
    database_name: str
    database_version: str


class SourceSummaryItem(BaseModel):
    id: str
    title: str
    publisher: str | None = None
    exam: str | None = None
    license_status: str
    question_count: int


class AdminSummaryResponse(BaseModel):
    total_questions: int
    total_staged_candidates: int = 0
    by_subject: dict[str, int]
    by_question_type: dict[str, int]
    by_review_status: dict[str, int]
    by_source: list[SourceSummaryItem]
    total_taxonomy_nodes: int
    eligible_question_count: int
    pending_figures_count: int


class QuestionOptionModel(BaseModel):
    position: int
    label_printed: str | None = None
    text_md: str


class QuestionTagModel(BaseModel):
    code: str
    name: str
    level: str
    is_primary: bool
    confidence: float | None = None
    source: str = "llm"


class QuestionSourceModel(BaseModel):
    id: str
    title: str
    publisher: str | None = None
    exam: str | None = None
    exam_year: int | None = None
    file_path: str | None = None
    license_status: str


class QuestionSummaryItem(BaseModel):
    public_id: str
    version: int
    subject: str
    question_type: str
    difficulty: int | None = None
    cognitive_level: str | None = None
    stem_preview: str
    status: str
    has_figure: bool
    figure_status: str
    unit_code: str | None = None
    unit_name: str | None = None
    topic_code: str | None = None
    topic_name: str | None = None
    subtopic_code: str | None = None
    subtopic_name: str | None = None
    source_title: str | None = None
    source_local_number: int | None = None
    source_global_number: int | None = None
    source_page_start: int | None = None


class QuestionListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    total_pages: int
    items: list[QuestionSummaryItem]


class QuestionDetailResponse(BaseModel):
    public_id: str
    version: int
    subject: str
    question_type: str
    stem_md: str
    stem_plain: str | None = None
    options: list[QuestionOptionModel]
    answer: dict[str, Any]
    explanation_md: str | None = None
    source_explanation_md: str | None = None
    unit_code: str | None = None
    unit_name: str | None = None
    topic_code: str | None = None
    topic_name: str | None = None
    subtopic_code: str | None = None
    subtopic_name: str | None = None
    primary_tag: QuestionTagModel | None = None
    secondary_tags: list[QuestionTagModel] = Field(default_factory=list)
    difficulty: int | None = None
    difficulty_source: str | None = None
    cognitive_level: str | None = None
    estimated_time_sec: int | None = None
    formulas_used: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    common_mistakes: str | None = None
    concept_tags: list[str] = Field(default_factory=list)
    skill_tags: list[str] = Field(default_factory=list)
    source: QuestionSourceModel
    source_q_label: str | None = None
    source_local_number: int | None = None
    source_global_number: int | None = None
    source_page_start: int | None = None
    source_page_end: int | None = None
    answer_key_verified: bool
    explanation_verified: bool
    answer_verification_notes: str | None = None
    explanation_verification_notes: str | None = None
    extraction_confidence: float | None = None
    classification_confidence: float | None = None
    has_figure: bool
    figure_status: str
    figure_description: str | None = None
    status: str
    flags: dict[str, Any] = Field(default_factory=dict)
    revisions: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str
    updated_at: str


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.get("/health", response_model=HealthResponse)
def get_health():
    """Health check endpoint returning system and native PostgreSQL connectivity status."""
    db_info = check_db_health()
    status = "ok" if db_info["database_connected"] else "database_unavailable"
    return HealthResponse(
        status=status,
        database_connected=bool(db_info["database_connected"]),
        database_name=str(db_info["database_name"]),
        database_version=str(db_info["database_version"]),
    )


@router.get("/admin/summary", response_model=AdminSummaryResponse)
def get_admin_summary():
    """Aggregated statistics across canonical questions, taxonomy, sources, and review status."""
    try:
        with get_db_cursor() as cur:
            # Total questions (canonical)
            cur.execute("SELECT COUNT(*) AS total FROM questions")
            total_questions = cur.fetchone()["total"]

            # Total candidate questions (raw / staged)
            cur.execute("SELECT COUNT(*) AS total FROM ingestion_question_candidates")
            total_staged_candidates = cur.fetchone()["total"]

            # By subject
            cur.execute("SELECT subject, COUNT(*) AS count FROM questions GROUP BY subject ORDER BY subject")
            by_subject = {r["subject"]: r["count"] for r in cur.fetchall()}

            # By question type
            cur.execute("SELECT question_type, COUNT(*) AS count FROM questions GROUP BY question_type ORDER BY question_type")
            by_type = {r["question_type"]: r["count"] for r in cur.fetchall()}

            # By review status
            cur.execute("SELECT status, COUNT(*) AS count FROM questions GROUP BY status ORDER BY status")
            by_status = {r["status"]: r["count"] for r in cur.fetchall()}

            # By source
            cur.execute("""
                SELECT 
                    d.id::text,
                    d.title,
                    d.publisher,
                    d.exam,
                    d.license_status,
                    COUNT(q.id) AS question_count
                FROM source_documents d
                LEFT JOIN questions q ON q.source_doc_id = d.id
                GROUP BY d.id, d.title, d.publisher, d.exam, d.license_status
                ORDER BY question_count DESC, d.title ASC
            """)
            by_source = [
                SourceSummaryItem(
                    id=r["id"],
                    title=r["title"],
                    publisher=r["publisher"],
                    exam=r["exam"],
                    license_status=r["license_status"],
                    question_count=r["question_count"],
                )
                for r in cur.fetchall()
            ]

            # Total taxonomy nodes
            cur.execute("SELECT COUNT(*) AS total FROM taxonomy")
            total_tax = cur.fetchone()["total"]

            # Eligible questions view
            cur.execute("SELECT COUNT(*) AS total FROM v_test_eligible_questions")
            eligible_count = cur.fetchone()["total"]

            # Pending figures count
            cur.execute("SELECT COUNT(*) AS total FROM questions WHERE figure_status = 'pending'")
            pending_figs = cur.fetchone()["total"]

            return AdminSummaryResponse(
                total_questions=total_questions,
                total_staged_candidates=total_staged_candidates,
                by_subject=by_subject,
                by_question_type=by_type,
                by_review_status=by_status,
                by_source=by_source,
                total_taxonomy_nodes=total_tax,
                eligible_question_count=eligible_count,
                pending_figures_count=pending_figs,
            )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database error during summary generation: {e}")


@router.get("/admin/questions", response_model=QuestionListResponse)
def list_questions(
    search: str | None = Query(None, description="Search question text or public ID"),
    subject: str | None = Query(None, description="Filter by subject"),
    unit_code: str | None = Query(None, description="Filter by taxonomy unit code"),
    topic_code: str | None = Query(None, description="Filter by taxonomy topic code"),
    subtopic_code: str | None = Query(None, description="Filter by taxonomy subtopic code"),
    question_type: str | None = Query(None, description="Filter by question type"),
    difficulty: int | None = Query(None, ge=1, le=5, description="Filter by difficulty 1-5"),
    status: str | None = Query(None, description="Filter by review status"),
    source: str | None = Query(None, description="Filter by source document title or ID"),
    has_figure: bool | None = Query(None, description="Filter by figure presence"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
):
    """Paginated list of questions with combined multi-parameter filtering."""
    try:
        with get_db_cursor() as cur:
            where_clauses: list[str] = []
            params: list[Any] = []

            if search:
                where_clauses.append("(q.public_id ILIKE %s OR q.stem_md ILIKE %s OR q.stem_plain ILIKE %s)")
                patt = f"%{search.strip()}%"
                params.extend([patt, patt, patt])

            if subject:
                where_clauses.append("q.subject = %s")
                params.append(subject.lower())

            if question_type:
                where_clauses.append("q.question_type = %s")
                params.append(question_type)

            if difficulty:
                where_clauses.append("q.difficulty = %s")
                params.append(difficulty)

            if status:
                where_clauses.append("q.status = %s")
                params.append(status)

            if has_figure is not None:
                where_clauses.append("q.has_figure = %s")
                params.append(has_figure)

            if source:
                where_clauses.append("(d.title ILIKE %s OR d.id::text = %s)")
                patt = f"%{source.strip()}%"
                params.extend([patt, source.strip()])

            if subtopic_code:
                where_clauses.append("t_sub.code = %s")
                params.append(subtopic_code)
            elif topic_code:
                where_clauses.append("t_top.code = %s")
                params.append(topic_code)
            elif unit_code:
                where_clauses.append("t_unit.code = %s")
                params.append(unit_code)

            where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

            # Count total matching
            count_query = f"""
                SELECT COUNT(DISTINCT q.id) AS total
                FROM questions q
                JOIN source_documents d ON d.id = q.source_doc_id
                LEFT JOIN question_tags qt ON qt.question_id = q.id AND qt.is_primary = true
                LEFT JOIN taxonomy t_sub ON t_sub.id = qt.taxonomy_id
                LEFT JOIN taxonomy t_top ON t_top.id = t_sub.parent_id
                LEFT JOIN taxonomy t_unit ON t_unit.id = t_top.parent_id
                {where_sql}
            """
            cur.execute(count_query, params)
            total = cur.fetchone()["total"]

            total_pages = math.ceil(total / page_size) if total > 0 else 1
            offset = (page - 1) * page_size

            # Fetch page items
            data_query = f"""
                SELECT 
                    q.public_id,
                    q.version,
                    q.subject,
                    q.question_type,
                    q.difficulty,
                    q.cognitive_level,
                    q.stem_md,
                    q.status,
                    q.has_figure,
                    q.figure_status,
                    q.source_local_number,
                    q.source_global_number,
                    q.source_page_start,
                    d.title as source_title,
                    t_sub.code as subtopic_code,
                    t_sub.name as subtopic_name,
                    t_top.code as topic_code,
                    t_top.name as topic_name,
                    t_unit.code as unit_code,
                    t_unit.name as unit_name
                FROM questions q
                JOIN source_documents d ON d.id = q.source_doc_id
                LEFT JOIN question_tags qt ON qt.question_id = q.id AND qt.is_primary = true
                LEFT JOIN taxonomy t_sub ON t_sub.id = qt.taxonomy_id
                LEFT JOIN taxonomy t_top ON t_top.id = t_sub.parent_id
                LEFT JOIN taxonomy t_unit ON t_unit.id = t_top.parent_id
                {where_sql}
                ORDER BY q.public_id ASC
                LIMIT %s OFFSET %s
            """
            cur.execute(data_query, params + [page_size, offset])
            rows = cur.fetchall()

            items = []
            for r in rows:
                stem_raw = r["stem_md"] or ""
                # Strip excessive whitespace or markdown for clean preview
                preview = stem_raw.replace("\n", " ").strip()
                if len(preview) > 120:
                    preview = preview[:117] + "..."

                items.append(
                    QuestionSummaryItem(
                        public_id=r["public_id"],
                        version=r["version"],
                        subject=r["subject"],
                        question_type=r["question_type"],
                        difficulty=r["difficulty"],
                        cognitive_level=r["cognitive_level"],
                        stem_preview=preview,
                        status=r["status"],
                        has_figure=r["has_figure"],
                        figure_status=r["figure_status"],
                        unit_code=r["unit_code"],
                        unit_name=r["unit_name"],
                        topic_code=r["topic_code"],
                        topic_name=r["topic_name"],
                        subtopic_code=r["subtopic_code"],
                        subtopic_name=r["subtopic_name"],
                        source_title=r["source_title"],
                        source_local_number=r["source_local_number"],
                        source_global_number=r["source_global_number"],
                        source_page_start=r["source_page_start"],
                    )
                )

            return QuestionListResponse(
                total=total,
                page=page,
                page_size=page_size,
                total_pages=total_pages,
                items=items,
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database query error: {e}")


@router.get("/admin/questions/{public_id}", response_model=QuestionDetailResponse)
def get_question_detail(public_id: str):
    """Complete administrative question record with full options, tags, solutions, and provenance."""
    clean_id = public_id.strip().upper()
    try:
        with get_db_cursor() as cur:
            cur.execute("""
                SELECT 
                    q.id,
                    q.public_id,
                    q.version,
                    q.subject,
                    q.question_type,
                    q.stem_md,
                    q.stem_plain,
                    q.answer,
                    q.explanation_md,
                    q.source_explanation_md,
                    q.difficulty,
                    q.difficulty_source,
                    q.cognitive_level,
                    q.estimated_time_sec,
                    q.formulas_used,
                    q.keywords,
                    q.common_mistakes,
                    q.has_figure,
                    q.figure_status,
                    q.figure_description,
                    q.status,
                    q.extraction_confidence,
                    q.flags,
                    q.source_q_label,
                    q.source_local_number,
                    q.source_global_number,
                    q.source_page_start,
                    q.source_page_end,
                    q.answer_key_verified,
                    q.explanation_verified,
                    q.answer_verification_notes,
                    q.explanation_verification_notes,
                    q.created_at::text as created_at,
                    q.updated_at::text as updated_at,
                    d.id::text as source_id,
                    d.title as source_title,
                    d.publisher as source_publisher,
                    d.exam as source_exam,
                    d.exam_year as source_exam_year,
                    d.file_path as source_file_path,
                    d.license_status as source_license_status,
                    t_sub.code as subtopic_code,
                    t_sub.name as subtopic_name,
                    t_top.code as topic_code,
                    t_top.name as topic_name,
                    t_unit.code as unit_code,
                    t_unit.name as unit_name,
                    qt_prim.confidence as classification_confidence
                FROM questions q
                JOIN source_documents d ON d.id = q.source_doc_id
                LEFT JOIN question_tags qt_prim ON qt_prim.question_id = q.id AND qt_prim.is_primary = true
                LEFT JOIN taxonomy t_sub ON t_sub.id = qt_prim.taxonomy_id
                LEFT JOIN taxonomy t_top ON t_top.id = t_sub.parent_id
                LEFT JOIN taxonomy t_unit ON t_unit.id = t_top.parent_id
                WHERE q.public_id = %s
            """, (clean_id,))
            q = cur.fetchone()
            if not q:
                raise HTTPException(status_code=404, detail=f"Question with public ID '{clean_id}' not found.")

            q_id = q["id"]

            # Options
            cur.execute("""
                SELECT position, label_printed, text_md
                FROM question_options
                WHERE question_id = %s
                ORDER BY position ASC
            """, (q_id,))
            options = [
                QuestionOptionModel(
                    position=r["position"],
                    label_printed=r["label_printed"],
                    text_md=r["text_md"],
                )
                for r in cur.fetchall()
            ]

            # All tags
            cur.execute("""
                SELECT 
                    t.code,
                    t.name,
                    t.level,
                    qt.is_primary,
                    qt.confidence,
                    qt.source
                FROM question_tags qt
                JOIN taxonomy t ON t.id = qt.taxonomy_id
                WHERE qt.question_id = %s
                ORDER BY qt.is_primary DESC, t.code ASC
            """, (q_id,))
            tag_rows = cur.fetchall()
            primary_tag = None
            secondary_tags = []
            for tr in tag_rows:
                tag_model = QuestionTagModel(
                    code=tr["code"],
                    name=tr["name"],
                    level=tr["level"],
                    is_primary=tr["is_primary"],
                    confidence=tr["confidence"],
                    source=tr["source"] or "llm",
                )
                if tr["is_primary"] and primary_tag is None:
                    primary_tag = tag_model
                else:
                    secondary_tags.append(tag_model)

            # Revisions
            cur.execute("""
                SELECT version, snapshot, changed_by, reason, changed_at::text as changed_at
                FROM question_revisions
                WHERE question_id = %s
                ORDER BY version ASC
            """, (q_id,))
            revisions = [dict(r) for r in cur.fetchall()]

            # Concept / skill tags from flags if present
            flags_dict = q["flags"] or {}
            concept_tags = flags_dict.get("concept_tags") or []
            skill_tags = flags_dict.get("skill_tags") or []

            source_model = QuestionSourceModel(
                id=q["source_id"],
                title=q["source_title"],
                publisher=q["source_publisher"],
                exam=q["source_exam"],
                exam_year=q["source_exam_year"],
                file_path=q["source_file_path"],
                license_status=q["source_license_status"],
            )

            return QuestionDetailResponse(
                public_id=q["public_id"],
                version=q["version"],
                subject=q["subject"],
                question_type=q["question_type"],
                stem_md=q["stem_md"],
                stem_plain=q["stem_plain"],
                options=options,
                answer=q["answer"],
                explanation_md=q["explanation_md"],
                source_explanation_md=q["source_explanation_md"],
                unit_code=q["unit_code"],
                unit_name=q["unit_name"],
                topic_code=q["topic_code"],
                topic_name=q["topic_name"],
                subtopic_code=q["subtopic_code"],
                subtopic_name=q["subtopic_name"],
                primary_tag=primary_tag,
                secondary_tags=secondary_tags,
                difficulty=q["difficulty"],
                difficulty_source=q["difficulty_source"],
                cognitive_level=q["cognitive_level"],
                estimated_time_sec=q["estimated_time_sec"],
                formulas_used=q["formulas_used"] or [],
                keywords=q["keywords"] or [],
                common_mistakes=q["common_mistakes"],
                concept_tags=concept_tags,
                skill_tags=skill_tags,
                source=source_model,
                source_q_label=q["source_q_label"],
                source_local_number=q["source_local_number"],
                source_global_number=q["source_global_number"],
                source_page_start=q["source_page_start"],
                source_page_end=q["source_page_end"],
                answer_key_verified=q["answer_key_verified"],
                explanation_verified=q["explanation_verified"],
                answer_verification_notes=q["answer_verification_notes"],
                explanation_verification_notes=q["explanation_verification_notes"],
                extraction_confidence=q["extraction_confidence"],
                classification_confidence=q["classification_confidence"],
                has_figure=q["has_figure"],
                figure_status=q["figure_status"],
                figure_description=q["figure_description"],
                status=q["status"],
                flags=flags_dict,
                revisions=revisions,
                created_at=q["created_at"],
                updated_at=q["updated_at"],
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error loading question '{clean_id}': {e}")


@router.get("/admin/taxonomy")
def get_admin_taxonomy():
    """Hierarchical taxonomy tree (Subject -> Unit -> Topic -> Subtopic) for UI filter cascading."""
    try:
        with get_db_cursor() as cur:
            cur.execute("""
                SELECT id, code, level, name, parent_id
                FROM taxonomy
                WHERE is_active = true
                ORDER BY code ASC
            """)
            nodes = cur.fetchall()

            # Group into subjects -> units -> topics -> subtopics
            id_to_node = {n["id"]: n for n in nodes}
            by_code = {n["code"]: n for n in nodes}

            # Group by level
            units = [n for n in nodes if n["level"] == "unit"]
            topics = [n for n in nodes if n["level"] == "topic"]
            subtopics = [n for n in nodes if n["level"] == "subtopic"]

            # Structure response
            return {
                "total_nodes": len(nodes),
                "units": [
                    {
                        "code": u["code"],
                        "name": u["name"],
                        "subject": "mathematics" if u["code"].startswith("MAT") else "physics" if u["code"].startswith("PHY") else "chemistry",
                    }
                    for u in units
                ],
                "topics": [
                    {
                        "code": t["code"],
                        "name": t["name"],
                        "parent_unit": id_to_node[t["parent_id"]]["code"] if t["parent_id"] in id_to_node else None,
                    }
                    for t in topics
                ],
                "subtopics": [
                    {
                        "code": s["code"],
                        "name": s["name"],
                        "parent_topic": id_to_node[s["parent_id"]]["code"] if s["parent_id"] in id_to_node else None,
                    }
                    for s in subtopics
                ],
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error loading taxonomy: {e}")

