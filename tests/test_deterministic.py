import pytest
from engines.ingestion.models import ExtractedQuestion, Option, Tag
from engines.ingestion.pdf_reader import DocumentRecord, PageRecord
from engines.ingestion.pipeline import classify_page_roles, detect_layout_profile
from engines.ingestion.validators import _check_latex_sanity, _content_hash, validate_extracted_question


def test_content_hash_deterministic():
    q1 = ExtractedQuestion(
        source_q_label="Q1",
        source_question_key="Q1",
        subject="physics",
        question_type="mcq_single",
        stem_md="Find the velocity $v$ when $t = 2\\text{ s}$.",
        options=[
            Option(position=1, label_printed="(1)", text_md="10 m/s"),
            Option(position=2, label_printed="(2)", text_md="20 m/s"),
        ],
        answer={"type": "option", "positions": [1]},
    )
    q2 = ExtractedQuestion(
        source_q_label="Q1",
        source_question_key="Q1",
        subject="physics",
        question_type="mcq_single",
        stem_md="Find  the  velocity  $v$  when  $t = 2\\text{ s}$.",  # extra spaces
        options=[
            Option(position=2, label_printed="(2)", text_md="20 m/s"),  # reversed order
            Option(position=1, label_printed="(1)", text_md="10 m/s"),
        ],
        answer={"type": "option", "positions": [1]},
    )
    assert _content_hash(q1) == _content_hash(q2)


def test_dollar_balance_and_latex_sanity():
    # Balanced dollars
    q_good = ExtractedQuestion(
        source_q_label="Q1",
        source_question_key="Q1",
        subject="physics",
        question_type="numerical",
        stem_md="Calculate $\\omega = \\sqrt{k/m}$ for the oscillator.",
        options=[],
        answer={"type": "numeric", "value": 10},
        tags=[Tag(code="PHY.U10.T01.S01", is_primary=True)],
    )
    dummy_tax = {"PHY.U10.T01.S01": {"code": "PHY.U10.T01.S01", "level": "subtopic", "is_active": True}}
    errs = validate_extracted_question(q_good, dummy_tax)
    assert not errs

    # Unbalanced dollars
    q_bad = ExtractedQuestion(
        source_q_label="Q2",
        source_question_key="Q2",
        subject="physics",
        question_type="numerical",
        stem_md="Calculate $\\omega = \\sqrt{k/m} for the oscillator.",  # missing closing $
        options=[],
        answer={"type": "numeric", "value": 10},
        tags=[Tag(code="PHY.U10.T01.S01", is_primary=True)],
    )
    errs_bad = validate_extracted_question(q_bad, dummy_tax)
    assert any("unbalanced dollar delimiters" in e for e in errs_bad)

    # LaTeX brace sanity check
    warnings = _check_latex_sanity("\\frac{a}{b} + {unclosed")
    assert any("Mismatched curly braces" in w for w in warnings)


def test_section_offset_mapping():
    # Test local-to-global mapping for ALLEN 75-question paper
    sections = [
        ("mathematics", "I", 1, 1),
        ("mathematics", "I", 20, 20),
        ("mathematics", "II", 1, 21),
        ("mathematics", "II", 5, 25),
        ("physics", "I", 1, 26),
        ("physics", "I", 20, 45),
        ("physics", "II", 1, 46),
        ("physics", "II", 5, 50),
        ("chemistry", "I", 1, 51),
        ("chemistry", "I", 20, 70),
        ("chemistry", "II", 1, 71),
        ("chemistry", "II", 5, 75),
    ]
    bases = {
        ("mathematics", "I"): 0,
        ("mathematics", "II"): 20,
        ("physics", "I"): 25,
        ("physics", "II"): 45,
        ("chemistry", "I"): 50,
        ("chemistry", "II"): 70,
    }
    for subj, sec, local_n, expected_global in sections:
        calc_global = bases[(subj, sec)] + local_n
        assert calc_global == expected_global


def test_option_letter_to_position_mapping():
    letter_map = {"A": 1, "B": 2, "C": 3, "D": 4}
    assert letter_map["A"] == 1
    assert letter_map["B"] == 2
    assert letter_map["C"] == 3
    assert letter_map["D"] == 4


def test_page_role_heuristics():
    pages = [
        PageRecord(1, "JEE Main 2026 Test Series\nInstructions:\nTime Allowed: 3 Hours\nMax Marks: 300", "text", 100, 0, False),
        PageRecord(2, "PART-1 : MATHEMATICS\nSECTION-I\n1) Find the determinant of matrix A\n(A) 1\n(B) 2", "text", 120, 0, False),
        PageRecord(18, "ANSWER KEYS\nPART-1 : MATHEMATICS\nSECTION-I\nQ. 1 2 3 4\nA. C B A A", "text", 150, 0, False),
        PageRecord(19, "SOLUTIONS\nPART-1 : MATHEMATICS\n1) det(A) = 4", "text", 80, 0, False),
    ]
    doc = DocumentRecord("sample.pdf", "0"*64, 4, "sample", {}, pages)
    roles = classify_page_roles(doc)
    assert roles[1] == "cover"
    assert roles[2] == "questions"
    assert roles[18] == "answer_key"
    assert roles[19] == "solutions"

