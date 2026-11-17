from __future__ import annotations

from typing import Any
from fastapi import APIRouter
from pydantic import BaseModel

from engines.assessment.scoring import ScoringRule, score_response

router = APIRouter(prefix="/api/v1/assessment", tags=["assessment"])


class ScoreRequest(BaseModel):
    question_type: str
    user_response: dict[str, Any] | None
    correct_answer: dict[str, Any]
    scoring_rule: ScoringRule = ScoringRule()


@router.post("/score")
def evaluate_score(req: ScoreRequest):
    is_correct, score = score_response(
        req.question_type,
        req.user_response,
        req.correct_answer,
        req.scoring_rule,
    )
    return {
        "is_correct": is_correct,
        "score_awarded": score,
    }

