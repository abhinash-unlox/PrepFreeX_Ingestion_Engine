from __future__ import annotations

from typing import Any, Literal
from datetime import date
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator

QuestionType = Literal[
    "mcq_single", "mcq_multi", "numerical", "assertion_reason",
    "statement_based", "match_list"
]


class Option(BaseModel):
    position: int = Field(gt=0)
    label_printed: str | None = None
    text_md: str


class MatchItem(BaseModel):
    side: Literal["left", "right"]
    item_key: str
    position: int = Field(gt=0)
    text_md: str


class Tag(BaseModel):
    code: str
    is_primary: bool = False
    source: Literal["human", "llm", "rule"] = "rule"
    confidence: float | None = Field(default=None, ge=0, le=1)


class ExtractedQuestion(BaseModel):
    model_config = ConfigDict(extra="allow")

    source_q_label: str
    source_question_key: str
    source_part: str | None = None
    source_section: str | None = None
    source_local_number: int | None = None
    source_global_number: int | None = None
    source_page_start: int | None = None
    source_page_end: int | None = None
    subject: Literal["mathematics", "physics", "chemistry"] | None = None
    unit_code: str | None = None
    question_type: QuestionType | None = None
    language: str = "en"
    stem_md: str
    stem_plain: str | None = None
    options: list[Option] = Field(default_factory=list)
    match_items: list[MatchItem] = Field(default_factory=list)
    answer: dict[str, Any] | None = None
    source_explanation_md: str | None = None
    status: Literal["draft", "needs_review", "verified", "rejected", "retired"] = "needs_review"
    origin: Literal["pyq", "coaching", "ai_generated", "original"] = "pyq"
    exam_name: str | None = None
    exam_year: int | None = None
    exam_date: date | None = None
    exam_shift: int | None = None
    formulas_used: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    common_mistakes: str | None = None
    source_publisher: str | None = None
    explanation_md: str | None = None
    explanation_source: Literal["source", "ai", "human"] | None = None
    answer_key_verified: bool = False
    explanation_verified: bool = False
    answer_verification_notes: str | None = None
    explanation_verification_notes: str | None = None
    difficulty: int | None = Field(default=None, ge=1, le=5)
    difficulty_source: Literal["source", "ai_estimated", "empirical"] | None = None
    cognitive_level: Literal["recall", "understand", "apply", "analyze"] | None = None
    estimated_time_sec: int | None = Field(default=None, gt=0)
    has_figure: bool = False
    figure_status: Literal["none", "pending", "attached"] = "none"
    figure_description: str | None = None
    figure_source_page: int | None = None
    tags: list[Tag] = Field(default_factory=list)
    classification_confidence: float | None = Field(default=None, ge=0, le=1)
    classification_status: Literal["classified", "needs_review", "unclassified"] = "needs_review"
    extraction_method: str = "text"
    extraction_confidence: float | None = Field(default=None, ge=0, le=1)
    flags: dict[str, Any] = Field(default_factory=dict)
    raw_extraction_text: str | None = None

    @model_validator(mode="after")
    def check_figure_state(self):
        if self.has_figure and self.figure_status == "none":
            self.figure_status = "pending"
        if not self.has_figure and self.figure_status != "none":
            raise ValueError("figure_status must be 'none' when has_figure=false")
        return self


class SourceDocument(BaseModel):
    file: str
    title: str
    publisher: str | None = None
    exam: str | None = None
    exam_year: int | None = None
    license_status: Literal["unverified", "cleared", "restricted"] = "unverified"


class ImportBundle(BaseModel):
    source_document: SourceDocument
    questions: list[ExtractedQuestion]
