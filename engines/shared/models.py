from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class TaxonomyNode(BaseModel):
    code: str
    name: str
    level: Literal["subject", "area", "unit", "topic", "subtopic"]
    parent_code: str | None = None
    description: str | None = None
    syllabus_text: str | None = None
    sort_order: int | None = None
    is_active: bool = True


class Option(BaseModel):
    position: int
    label_printed: str | None = None
    text_md: str


class Tag(BaseModel):
    code: str
    is_primary: bool = False
    confidence: float | None = None
    source: Literal["human", "llm", "rule"] = "rule"


class CanonicalQuestion(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    public_id: str
    version: int = 1
    subject: Literal["mathematics", "physics", "chemistry"]
    question_type: Literal[
        "mcq_single", "mcq_multi", "numerical", "assertion_reason", "statement_based", "match_list"
    ]
    stem_md: str
    stem_plain: str | None = None
    options: list[Option] = Field(default_factory=list)
    answer: dict[str, Any]
    explanation_md: str | None = None
    difficulty: int = 3
    cognitive_level: Literal["recall", "understand", "apply", "analyze"] = "apply"
    tags: list[Tag] = Field(default_factory=list)
    concept_tags: list[str] = Field(default_factory=list)
    skill_tags: list[str] = Field(default_factory=list)
    formulas_used: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    has_figure: bool = False
    figure_status: Literal["none", "pending", "attached"] = "none"
    status: Literal["draft", "needs_review", "verified", "rejected", "retired"] = "needs_review"
    content_hash: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

