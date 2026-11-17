from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from apps.api.db import get_db_cursor

router = APIRouter(prefix="/api/v1/taxonomy", tags=["Official JEE Main Taxonomy"])


class SubjectItem(BaseModel):
    code: str
    name: str
    total_chapters: int
    total_topics: int


class ChapterItem(BaseModel):
    id: int
    unit_code: str
    chapter_name: str
    chapter_slug: str
    subject: str
    chapter_number: int | None
    total_topics: int
    eligible_question_count: int = 0
    variant_count: int = 0


class TopicItem(BaseModel):
    id: int
    topic_code: str
    topic_name: str
    topic_number: int
    unit_code: str
    chapter_id: int | None
    subject: str
    eligible_question_count: int = 0
    variant_count: int = 0


@router.get("/subjects", response_model=list[SubjectItem])
def get_subjects():
    """Returns official JEE Main subjects with chapter and topic counts."""
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT 
                c.subject,
                count(DISTINCT c.id) as chapter_count,
                count(DISTINCT t.id) as topic_count
            FROM public.chapters c
            JOIN public.chapter_topics t ON t.chapter_id = c.id AND t.active = TRUE
            WHERE c.is_canonical = TRUE
            GROUP BY c.subject
            ORDER BY 
                CASE c.subject 
                    WHEN 'PHYSICS' THEN 1 
                    WHEN 'CHEMISTRY' THEN 2 
                    WHEN 'MATHEMATICS' THEN 3 
                    ELSE 4 
                END;
        """)
        rows = cur.fetchall()
        
    return [
        SubjectItem(
            code=r["subject"],
            name=r["subject"].title(),
            total_chapters=r["chapter_count"],
            total_topics=r["topic_count"]
        )
        for r in rows
    ]


@router.get("/chapters", response_model=list[ChapterItem])
def get_chapters(subject: Optional[str] = Query(None, description="PHYSICS, CHEMISTRY, or MATHEMATICS")):
    """Returns the 64 canonical Unit/Chapters under the given subject or all subjects."""
    with get_db_cursor() as cur:
        query = """
            SELECT 
                c.id, c.unit_code, c.chapter_name, c.chapter_slug, c.subject, c.chapter_number,
                count(DISTINCT t.id) as total_topics,
                count(DISTINCT q.id) as question_count
            FROM public.chapters c
            LEFT JOIN public.chapter_topics t ON t.chapter_id = c.id AND t.active = TRUE
            LEFT JOIN public.completed_questions q ON q.unit_code = c.unit_code
            WHERE c.is_canonical = TRUE
        """
        params = []
        if subject:
            query += " AND c.subject = %s"
            params.append(subject.upper())
            
        query += " GROUP BY c.id, c.unit_code, c.chapter_name, c.chapter_slug, c.subject, c.chapter_number ORDER BY c.chapter_number ASC, c.chapter_name ASC;"
        cur.execute(query, params)
        rows = cur.fetchall()
        
    return [
        ChapterItem(
            id=r["id"],
            unit_code=r["unit_code"],
            chapter_name=r["chapter_name"],
            chapter_slug=r["chapter_slug"],
            subject=r["subject"],
            chapter_number=r["chapter_number"],
            total_topics=r["total_topics"],
            eligible_question_count=r["question_count"]
        )
        for r in rows
    ]


@router.get("/topics", response_model=list[TopicItem])
def get_topics(
    chapter_code: Optional[str] = Query(None, description="e.g. PHYS_U12 or chapter_id or chapter_name"),
    subject: Optional[str] = Query(None)
):
    """Returns official topics (strictly 4 per chapter) under the selected chapter."""
    with get_db_cursor() as cur:
        query = """
            SELECT 
                t.id, t.topic_code, t.topic_name, t.topic_number, t.unit_code, t.chapter_id, t.subject,
                count(DISTINCT q.id) as question_count
            FROM public.chapter_topics t
            JOIN public.chapters c ON c.id = t.chapter_id AND c.is_canonical = TRUE
            LEFT JOIN public.completed_questions q ON q.primary_topic_code = t.topic_code
            WHERE t.active = TRUE
        """
        params = []
        if chapter_code:
            # Match by unit_code or chapter_name or id
            if chapter_code.isdigit():
                query += " AND (c.id = %s OR t.chapter_id = %s)"
                params.extend([int(chapter_code), int(chapter_code)])
            else:
                query += " AND (c.unit_code = %s OR c.chapter_name = %s OR t.unit_code = %s)"
                params.extend([chapter_code, chapter_code, chapter_code])
        if subject:
            query += " AND t.subject = %s"
            params.append(subject.upper())

        query += " GROUP BY t.id, t.topic_code, t.topic_name, t.topic_number, t.unit_code, t.chapter_id, t.subject ORDER BY t.topic_number ASC;"
        cur.execute(query, params)
        rows = cur.fetchall()

    return [
        TopicItem(
            id=r["id"],
            topic_code=r["topic_code"],
            topic_name=r["topic_name"],
            topic_number=r["topic_number"],
            unit_code=r["unit_code"],
            chapter_id=r["chapter_id"],
            subject=r["subject"],
            eligible_question_count=r["question_count"]
        )
        for r in rows
    ]


@router.get("/tree")
def get_taxonomy_tree():
    """Returns the complete authoritative 3-tier hierarchy: Subject -> Chapter -> Topics."""
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT 
                c.subject,
                c.id as chapter_id,
                c.unit_code,
                c.chapter_name,
                c.chapter_slug,
                c.chapter_number,
                t.id as topic_id,
                t.topic_code,
                t.topic_name,
                t.topic_number
            FROM public.chapters c
            JOIN public.chapter_topics t ON t.chapter_id = c.id AND t.active = TRUE
            WHERE c.is_canonical = TRUE
            ORDER BY 
                CASE c.subject WHEN 'PHYSICS' THEN 1 WHEN 'CHEMISTRY' THEN 2 WHEN 'MATHEMATICS' THEN 3 ELSE 4 END,
                c.chapter_number ASC,
                t.topic_number ASC;
        """)
        rows = cur.fetchall()

    tree: dict[str, dict] = {}
    for r in rows:
        sub = r["subject"]
        if sub not in tree:
            tree[sub] = {"subject": sub, "name": sub.title(), "chapters": {}}
        
        chap_id = r["chapter_id"]
        if chap_id not in tree[sub]["chapters"]:
            tree[sub]["chapters"][chap_id] = {
                "id": chap_id,
                "unit_code": r["unit_code"],
                "name": r["chapter_name"],
                "slug": r["chapter_slug"],
                "number": r["chapter_number"],
                "topics": []
            }
        
        tree[sub]["chapters"][chap_id]["topics"].append({
            "id": r["topic_id"],
            "code": r["topic_code"],
            "name": r["topic_name"],
            "number": r["topic_number"]
        })

    # Convert to clean nested arrays
    result = []
    for sub_data in tree.values():
        sub_obj = {
            "subject": sub_data["subject"],
            "name": sub_data["name"],
            "chapters": [chap for chap in sub_data["chapters"].values()]
        }
        result.append(sub_obj)

    return result


@router.get("/topics/{topic_code}/availability")
def get_topic_availability(topic_code: str):
    """Reports exact real counts of verified questions and variants for a topic."""
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT t.id, t.topic_code, t.topic_name, t.unit_code, t.subject, c.chapter_name
            FROM public.chapter_topics t
            JOIN public.chapters c ON c.id = t.chapter_id
            WHERE t.topic_code = %s AND t.active = TRUE;
        """, (topic_code,))
        topic = cur.fetchone()
        if not topic:
            raise HTTPException(status_code=404, detail=f"Topic '{topic_code}' not found in official taxonomy.")

        # Question count
        cur.execute("""
            SELECT 
                count(*) as total_eligible,
                count(*) filter (where question_type = 'SINGLE_CHOICE') as mcq_count,
                count(*) filter (where question_type = 'NUMERICAL_VALUE') as numerical_count,
                count(*) filter (where has_diagram = TRUE) as diagram_count
            FROM public.completed_questions
            WHERE primary_topic_code = %s;
        """, (topic_code,))
        q_stats = cur.fetchone()

        # Variant count in generated_question_mappings
        cur.execute("""
            SELECT count(*) as variant_count
            FROM public.generated_question_mappings
            WHERE unit_code = %s;
        """, (topic["unit_code"],))
        var_count = cur.fetchone()["variant_count"]

    return {
        "topic_code": topic["topic_code"],
        "topic_name": topic["topic_name"],
        "chapter_name": topic["chapter_name"],
        "unit_code": topic["unit_code"],
        "subject": topic["subject"],
        "eligible_questions": q_stats["total_eligible"],
        "mcq_questions": q_stats["mcq_count"],
        "numerical_questions": q_stats["numerical_count"],
        "diagram_questions": q_stats["diagram_count"],
        "verified_variants": var_count,
        "is_sufficient_for_practice": q_stats["total_eligible"] >= 5
    }
