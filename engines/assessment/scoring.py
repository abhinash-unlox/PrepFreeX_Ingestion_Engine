from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class ScoringRule(BaseModel):
    correct: float = 4.0
    incorrect: float = -1.0
    unattempted: float = 0.0


def score_response(
    question_type: str,
    user_response: dict[str, Any] | None,
    correct_answer: dict[str, Any],
    rule: ScoringRule | None = None,
) -> tuple[bool, float]:
    """Server-authoritative, deterministic scoring for all question types.
    
    Returns:
        (is_correct, score_awarded)
    """
    rule = rule or ScoringRule()

    if not user_response or not user_response.get("is_answered", True):
        return False, rule.unattempted

    ans_type = correct_answer.get("type")

    # 1. Single-choice MCQ
    if question_type in {"mcq_single", "assertion_reason", "statement_based"}:
        selected = user_response.get("positions") or user_response.get("selected_options") or []
        expected = correct_answer.get("positions") or []
        if sorted(selected) == sorted(expected):
            return True, rule.correct
        return False, rule.incorrect

    # 2. Multi-choice MCQ (JEE Advanced style partial marking or strict)
    elif question_type == "mcq_multi":
        selected = sorted(user_response.get("positions") or user_response.get("selected_options") or [])
        expected = sorted(correct_answer.get("positions") or [])
        if selected == expected:
            return True, rule.correct
        # Any incorrect selection gives negative mark
        if any(opt not in expected for opt in selected):
            return False, rule.incorrect
        # Partial positive
        return False, max(0.0, float(len(selected)))

    # 3. Numerical answer (within tolerance)
    elif question_type == "numerical":
        val = user_response.get("value")
        if val is None:
            return False, rule.unattempted
        try:
            user_val = float(val)
            expected_val = float(correct_answer.get("value", 0))
            tolerance = float(correct_answer.get("tolerance", 0.0))
            if abs(user_val - expected_val) <= tolerance:
                return True, rule.correct
            return False, rule.incorrect
        except (ValueError, TypeError):
            return False, rule.incorrect

    # 4. Match-list
    elif question_type == "match_list":
        user_pairs = user_response.get("pairs") or {}
        expected_pairs = correct_answer.get("pairs") or {}
        if user_pairs == expected_pairs:
            return True, rule.correct
        return False, rule.incorrect

    return False, rule.unattempted

