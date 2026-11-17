import json
from pathlib import Path

from engines.ingestion.llm import FakeLLM
from engines.ingestion.pipeline import run_ingestion

ROOT = Path(__file__).resolve().parents[1]
_ALLEN_PDF = ROOT / "data/raw/jee_dataset/full_tests/JEE Main Part Test-1_.pdf"
if not _ALLEN_PDF.exists():
    _ALLEN_PDF = ROOT / "data/raw/jee_dataset/full_tests/10. PART TEST - 01 (04-12-2025).pdf"
if not _ALLEN_PDF.exists():
    _ALLEN_PDF = ROOT / "data/input/JEE Main Part Test-1_.pdf"


def test_allen_part_test_numeric_answers_and_q73_mismatch(tmp_path):
    pdf = _ALLEN_PDF
    taxonomy_file = ROOT / "db/seeds/jee_main_2027_taxonomy_v2.json"
    if not taxonomy_file.exists():
        taxonomy_file = ROOT / "db/seeds/jee_main_2027_taxonomy.json"

    report = run_ingestion(pdf, taxonomy_file, tmp_path, dry_run=True, llm=FakeLLM())
    assert report["question_candidate_count"] == 75

    bundle_path = Path(report["artifacts"]["question_import"])
    bundle_data = json.loads(bundle_path.read_text(encoding="utf-8"))
    questions = bundle_data["questions"]

    # Global number to answer value mapping
    by_global = {q["source_global_number"]: q for q in questions if q.get("source_global_number")}

    expected_sec2_answers = {
        21: 12,
        22: 281,
        23: 2,
        24: 6,
        25: 2,
        46: 1172,
        47: 7,
        48: 5,
        49: 5,
        50: 2,
        71: 4,
        72: 5,
        73: 125,
        74: 4,
        75: 4,
    }

    for g_num, expected_val in expected_sec2_answers.items():
        assert g_num in by_global, f"Global question {g_num} missing"
        q = by_global[g_num]
        assert q["question_type"] == "numerical"
        assert q["answer"]["value"] == expected_val, f"Q{g_num} expected {expected_val}, got {q['answer']['value']}"

    # Verify Question 73 mismatch handling
    q73 = by_global[73]
    # Key remains 125 (NEVER overwritten)
    assert q73["answer"]["value"] == 125
    # Flagged with key_mismatch
    assert q73["flags"].get("key_mismatch") is True
    # answer_key_verified is False
    assert q73["answer_key_verified"] is False
    # Verification notes contains details
    assert q73.get("answer_verification_notes") is not None
    assert "-125" in q73["answer_verification_notes"]

