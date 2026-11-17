from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4
from pydantic import BaseModel, Field

from .scoring import ScoringRule


AssessmentType = Literal[
    "diagnostic",
    "dpp",
    "chapter_test",
    "part_test",
    "full_mock",
    "revision_drill",
    "adaptive",
]

AttemptStatus = Literal[
    "in_progress",
    "submitted",
    "expired",
    "interrupted",
    "cancelled",
]


class AssessmentDefinition(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    slug: str
    title: str
    assessment_type: AssessmentType
    subject: Literal["mathematics", "physics", "chemistry", "composite"] | None = None
    is_active: bool = True


class AssessmentVersion(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    assessment_def_id: UUID
    version_number: int
    duration_minutes: int
    total_marks: int
    instructions_md: str | None = None
    scoring_rules: ScoringRule = Field(default_factory=ScoringRule)
    is_published: bool = False


class AssessmentAttempt(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    learner_id: UUID
    assessment_version_id: UUID
    status: AttemptStatus = "in_progress"
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime
    submitted_at: datetime | None = None
    submission_idempotency_key: str | None = None
    score_obtained: float | None = None
    total_possible_marks: float | None = None
    percentage: float | None = None


class AssessmentResult(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    attempt_id: UUID
    learner_id: UUID
    total_questions: int
    attempted_count: int
    correct_count: int
    incorrect_count: int
    unattempted_count: int
    score: float
    max_score: float
    accuracy_percentage: float
    percentile: float | None = None
    subject_breakdown: dict[str, Any] = Field(default_factory=dict)
    unit_breakdown: dict[str, Any] = Field(default_factory=dict)
    time_breakdown: dict[str, Any] = Field(default_factory=dict)

