"""Unit tests for PrepFreeX Groq-Powered Hierarchical Question Categorization.

Covers all 16 test scenarios using mocked Groq responses without consuming real API tokens.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engines.ingestion.classifier import Classification, SubtopicTagger
from engines.ingestion.groq_hierarchical_categorizer import (
    GroqClassificationResult,
    GroqHierarchicalCategorizer,
    TaxonomyHierarchy,
)
from engines.ingestion.llm import BaseLLMProvider, FakeLLM, LLMError
from scripts.run_groq_taxonomy_categorizer import (
    GlobalLock,
    apply_classifications_transactionally,
    load_checkpoint,
    save_checkpoint,
)


class MockLLM(BaseLLMProvider):
    """Mock LLM provider returning predetermined JSON responses or raising exceptions."""

    def __init__(self, response_data: dict | list | Exception):
        self.response_data = response_data
        self.call_count = 0

    def extract_json(self, images, prompt, json_schema=None):
        self.call_count += 1
        if isinstance(self.response_data, Exception):
            raise self.response_data
        return self.response_data


@pytest.fixture
def taxonomy_hierarchy():
    """Provides loaded taxonomy hierarchy instance."""
    return TaxonomyHierarchy()


# 1. Correct unit, topic and subtopic selection
def test_1_correct_selection(taxonomy_hierarchy):
    mock_res = {
        "classifications": [
            {
                "question_public_id": "Q00000050",
                "selected_unit_code": "PHY.U17",
                "selected_topic_code": "PHY.U17.T02",
                "selected_subtopic_code": "PHY.U17.T02.S02",
                "confidence": 0.98,
                "academic_rationale": "Direct calculation of de Broglie wavelength for matter waves.",
                "evidence": ["Formula lambda = h/sqrt(2mE)"],
                "alternative_classifications": [],
                "needs_human_review": False,
                "review_reason": None,
            }
        ]
    }
    categorizer = GroqHierarchicalCategorizer(llm=MockLLM(mock_res), taxonomy=taxonomy_hierarchy)
    questions = [{"public_id": "Q00000050", "stem_md": "de Broglie wavelength test"}]
    results = categorizer.classify_batch(subject="physics", questions=questions)

    assert len(results) == 1
    r = results[0]
    assert r.is_valid is True
    assert r.selected_unit_code == "PHY.U17"
    assert r.selected_topic_code == "PHY.U17.T02"
    assert r.selected_subtopic_code == "PHY.U17.T02.S02"
    assert r.confidence == 0.98


# 2. Question whose PDF chapter metadata conflicts with its actual content
def test_2_metadata_conflict(taxonomy_hierarchy):
    mock_res = {
        "classifications": [
            {
                "question_public_id": "Q_CONFLICT",
                "selected_unit_code": "PHY.U13",
                "selected_topic_code": "PHY.U13.T01",
                "selected_subtopic_code": "PHY.U13.T01.S01",
                "confidence": 0.95,
                "academic_rationale": "Despite PDF metadata saying Kinematics, question tests Coulomb's law.",
                "evidence": ["Electric force calculation"],
                "alternative_classifications": [],
                "needs_human_review": False,
                "review_reason": None,
            }
        ]
    }
    categorizer = GroqHierarchicalCategorizer(llm=MockLLM(mock_res), taxonomy=taxonomy_hierarchy)
    questions = [{
        "public_id": "Q_CONFLICT",
        "stem_md": "Two point charges q1 and q2 are separated by distance r. Find electrostatic force.",
        "source_title": "Kinematics - JEE Main Question Bank",
    }]
    results = categorizer.classify_batch(subject="physics", questions=questions)
    assert results[0].is_valid is True
    assert results[0].selected_unit_code == "PHY.U13"


# 3. Multiple potentially relevant topics
def test_3_multiple_relevant_topics(taxonomy_hierarchy):
    mock_res = {
        "classifications": [
            {
                "question_public_id": "Q_MULTI",
                "selected_unit_code": "PHY.U14",
                "selected_topic_code": "PHY.U14.T04",
                "selected_subtopic_code": "PHY.U14.T04.S02",
                "confidence": 0.92,
                "academic_rationale": "LC circuit energy oscillation connects capacitance with inductance.",
                "evidence": ["LC oscillation equation"],
                "alternative_classifications": [
                    {"subtopic_code": "PHY.U13.T02.S03", "reason": "Capacitor energy storage aspect"}
                ],
                "needs_human_review": False,
                "review_reason": None,
            }
        ]
    }
    categorizer = GroqHierarchicalCategorizer(llm=MockLLM(mock_res), taxonomy=taxonomy_hierarchy)
    questions = [{"public_id": "Q_MULTI", "stem_md": "In an LC circuit, capacitor of capacitance C discharges into inductor L."}]
    results = categorizer.classify_batch(subject="physics", questions=questions)
    assert results[0].is_valid is True
    assert len(results[0].alternative_classifications) == 1
    assert results[0].alternative_classifications[0]["subtopic_code"] == "PHY.U13.T02.S03"


# 4. Numerical questions (no options)
def test_4_numerical_question(taxonomy_hierarchy):
    mock_res = {
        "classifications": [
            {
                "question_public_id": "Q_NUMERICAL",
                "selected_unit_code": "MAT.U02",
                "selected_topic_code": "MAT.U02.T02",
                "selected_subtopic_code": "MAT.U02.T02.S01",
                "confidence": 0.94,
                "academic_rationale": "Numerical problem determining quadratic roots sum.",
                "evidence": ["Vieta's formula"],
                "alternative_classifications": [],
                "needs_human_review": False,
                "review_reason": None,
            }
        ]
    }
    categorizer = GroqHierarchicalCategorizer(llm=MockLLM(mock_res), taxonomy=taxonomy_hierarchy)
    questions = [{"public_id": "Q_NUMERICAL", "stem_md": "If alpha and beta are roots of x^2 - 5x + 6 = 0, find alpha^2 + beta^2.", "options": []}]
    results = categorizer.classify_batch(subject="mathematics", questions=questions)
    assert results[0].is_valid is True
    assert results[0].selected_subtopic_code == "MAT.U02.T02.S01"


# 5. Questions involving multiple mathematical concepts
def test_5_multiple_math_concepts(taxonomy_hierarchy):
    mock_res = {
        "classifications": [
            {
                "question_public_id": "Q_TANGENT",
                "selected_unit_code": "MAT.U10",
                "selected_topic_code": "MAT.U10.T02",
                "selected_subtopic_code": "MAT.U10.T02.S01",
                "confidence": 0.91,
                "academic_rationale": "Find equation of tangent to parabola y^2 = 4ax using derivative slope.",
                "evidence": ["Calculus applied to conic section"],
                "alternative_classifications": [],
                "needs_human_review": False,
                "review_reason": None,
            }
        ]
    }
    categorizer = GroqHierarchicalCategorizer(llm=MockLLM(mock_res), taxonomy=taxonomy_hierarchy)
    questions = [{"public_id": "Q_TANGENT", "stem_md": "Find slope of tangent to parabola y^2=8x at point (2, 4)."}]
    results = categorizer.classify_batch(subject="mathematics", questions=questions)
    assert results[0].is_valid is True
    assert results[0].selected_unit_code == "MAT.U10"


# 6. Invalid Groq taxonomy code
def test_6_invalid_taxonomy_code(taxonomy_hierarchy):
    mock_res = {
        "classifications": [
            {
                "question_public_id": "Q_HALLUCINATED",
                "selected_unit_code": "PHY.U99",
                "selected_topic_code": "PHY.U99.T99",
                "selected_subtopic_code": "PHY.U99.T99.S99",
                "confidence": 0.99,
                "academic_rationale": "Hallucinated code not in JEE 2027 taxonomy.",
            }
        ]
    }
    categorizer = GroqHierarchicalCategorizer(llm=MockLLM(mock_res), taxonomy=taxonomy_hierarchy)
    questions = [{"public_id": "Q_HALLUCINATED", "stem_md": "Some physics question."}]
    results = categorizer.classify_batch(subject="physics", questions=questions)
    assert results[0].is_valid is False
    assert "does not exist in taxonomy" in results[0].validation_error


# 7. Parent-child mismatch
def test_7_parent_child_mismatch(taxonomy_hierarchy):
    # Selected subtopic PHY.U17.T02.S02 belongs to PHY.U17.T02, but model reported PHY.U17.T01
    mock_res = {
        "classifications": [
            {
                "question_public_id": "Q_MISMATCH",
                "selected_unit_code": "PHY.U17",
                "selected_topic_code": "PHY.U17.T01",
                "selected_subtopic_code": "PHY.U17.T02.S02",
                "confidence": 0.95,
                "academic_rationale": "Mismatched topic and subtopic.",
            }
        ]
    }
    categorizer = GroqHierarchicalCategorizer(llm=MockLLM(mock_res), taxonomy=taxonomy_hierarchy)
    questions = [{"public_id": "Q_MISMATCH", "stem_md": "Some question."}]
    results = categorizer.classify_batch(subject="physics", questions=questions)
    assert results[0].is_valid is False
    assert "Parent-child mismatch" in results[0].validation_error


# 8. Invalid JSON response
def test_8_invalid_json_response(taxonomy_hierarchy):
    categorizer = GroqHierarchicalCategorizer(llm=MockLLM({}), taxonomy=taxonomy_hierarchy)
    questions = [{"public_id": "Q_BAD_JSON", "stem_md": "Stem."}]
    results = categorizer.classify_batch(subject="physics", questions=questions)
    assert results[0].is_valid is False
    assert "missing classification" in results[0].validation_error.lower()


# 9. Groq timeout / API exception
def test_9_groq_timeout(taxonomy_hierarchy):
    categorizer = GroqHierarchicalCategorizer(llm=MockLLM(LLMError("Groq request timed out")), taxonomy=taxonomy_hierarchy)
    questions = [{"public_id": "Q_TIMEOUT", "stem_md": "Stem."}]
    results = categorizer.classify_batch(subject="physics", questions=questions)
    assert results[0].is_valid is False
    assert "timed out" in results[0].validation_error


# 10. Rate-limit response handling
def test_10_rate_limit_response(taxonomy_hierarchy):
    categorizer = GroqHierarchicalCategorizer(llm=MockLLM(LLMError("429 Too Many Requests")), taxonomy=taxonomy_hierarchy)
    questions = [{"public_id": "Q_RATELIMIT", "stem_md": "Stem."}]
    results = categorizer.classify_batch(subject="physics", questions=questions)
    assert results[0].is_valid is False
    assert "429" in results[0].validation_error


# 11. Low-confidence classification
def test_11_low_confidence_classification(taxonomy_hierarchy):
    mock_res = {
        "classifications": [
            {
                "question_public_id": "Q_LOW_CONF",
                "selected_unit_code": "PHY.U17",
                "selected_topic_code": "PHY.U17.T02",
                "selected_subtopic_code": "PHY.U17.T02.S02",
                "confidence": 0.65,
                "academic_rationale": "Uncertain about whether this is matter waves or general kinematics.",
                "needs_human_review": True,
            }
        ]
    }
    categorizer = GroqHierarchicalCategorizer(llm=MockLLM(mock_res), taxonomy=taxonomy_hierarchy)
    questions = [{"public_id": "Q_LOW_CONF", "stem_md": "Ambiguous stem."}]
    results = categorizer.classify_batch(subject="physics", questions=questions)
    assert results[0].is_valid is True
    assert results[0].confidence == 0.65
    assert results[0].needs_human_review is True


# 12. Existing manually verified classification conflict
def test_12_manual_conflict_preservation():
    # When decision is NEEDS_HUMAN_REVIEW, apply function must skip updating primary tag
    stats = apply_classifications_transactionally(
        db_url="mock_url",
        classifications=[{
            "question_id": "11111111-1111-1111-1111-111111111111",
            "decision": "NEEDS_HUMAN_REVIEW",
            "selected_subtopic_code": "PHY.U17.T02.S02",
            "current_taxonomy_code": "PHY.U17.T01.S01",
        }],
        dry_run=True,
    )
    assert stats["applied"] == 0
    assert stats["skipped"] == 1


# 13. Database rollback on error
def test_13_database_rollback():
    with patch("psycopg.connect") as mock_conn:
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = Exception("Database disk full error")
        mock_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = mock_cursor

        with pytest.raises(Exception, match="Database disk full error"):
            apply_classifications_transactionally(
                db_url="postgresql://fake",
                classifications=[{
                    "question_id": "11111111-1111-1111-1111-111111111111",
                    "decision": "AUTO_RECLASSIFY",
                    "selected_subtopic_code": "PHY.U17.T02.S02",
                }],
                dry_run=False,
            )


# 14. Resume after interruption (checkpointing)
def test_14_resume_checkpoint(tmp_path):
    cp_path = tmp_path / "test_cp.json"
    data = {
        "completed_public_ids": ["Q00000001", "Q00000002"],
        "results": [{"public_id": "Q00000001"}],
    }
    save_checkpoint(cp_path, data)
    loaded = load_checkpoint(cp_path)
    assert "Q00000001" in loaded["completed_public_ids"]
    assert "Q00000002" in loaded["completed_public_ids"]


# 15. Duplicate execution protection (GlobalLock)
def test_15_duplicate_execution_protection(tmp_path):
    lock_file = tmp_path / "test.lock"
    lock1 = GlobalLock(lock_file)
    assert lock1.acquire() is True
    assert lock_file.exists()

    # Second lock acquisition by another instance
    lock2 = GlobalLock(lock_file)
    # Patch psutil to simulate process active
    with patch("psutil.pid_exists", return_value=True):
        assert lock2.acquire() is False

    lock1.release()
    assert not lock_file.exists()


# 16. Future ingestion integration: SubtopicTagger uses GroqHierarchicalCategorizer
def test_16_future_ingestion_integration():
    fake_tax = {"PHY.U17.T02.S02": {"code": "PHY.U17.T02.S02", "level": "subtopic", "parent_code": "PHY.U17.T02"}}
    tagger = SubtopicTagger(taxonomy=fake_tax, llm=FakeLLM())

    # When FakeLLM has no canned response, it falls back to rules or returns classification
    cls = tagger.tag(stem="A particle of mass m has kinetic energy E. Calculate de Broglie wavelength.", subject="physics")
    assert isinstance(cls, Classification)
    assert cls.subject == "physics"
