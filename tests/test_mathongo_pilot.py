from pathlib import Path

from engines.ingestion.pipeline import run_ingestion
from engines.ingestion.taxonomy import load_taxonomy
from engines.ingestion.validators import validate_import_file

ROOT = Path(__file__).resolve().parents[1]
_PILOT_PDF = ROOT / "data/raw/jee_dataset/physics/Alternating Current - JEE Main 2026 (Jan) - MathonGo.pdf"
if not _PILOT_PDF.exists():
    _PILOT_PDF = ROOT / "data/input/Alternating Current - JEE Main 2026 (Jan) - MathonGo.pdf"

_SCHEMA_PATH = ROOT / "engines/ingestion/schemas/question_import.schema.json"
if not _SCHEMA_PATH.exists():
    _SCHEMA_PATH = ROOT / "schemas/question_import.schema.json"


def test_mathongo_generic_pipeline_extracts_five_questions(tmp_path):
    pdf = _PILOT_PDF
    taxonomy_file = ROOT / "db/seeds/jee_main_2027_taxonomy_v2.json"
    if not taxonomy_file.exists():
        taxonomy_file = ROOT / "db/seeds/jee_main_2027_taxonomy.json"

    report = run_ingestion(pdf, taxonomy_file, tmp_path, dry_run=True)
    assert report["question_candidate_count"] == 5
    assert report["question_types"] == {"mcq_single": 3, "numerical": 2}
    assert report["figure_pending"] == 2

    bundle, errors = validate_import_file(
        Path(report["artifacts"]["question_import"]),
        _SCHEMA_PATH,
        load_taxonomy(taxonomy_file),
    )
    assert not errors
    assert bundle is not None
    assert {q.source_question_key for q in bundle.questions} == {"Q1", "Q2", "Q3", "Q4", "Q5"}

    by_key = {q.source_question_key: q for q in bundle.questions}

    # Verify all 5 answers: 2, 50, 314, 3, 3
    assert by_key["Q1"].answer["positions"] == [2]
    assert by_key["Q2"].answer["value"] == 50
    assert by_key["Q3"].answer["value"] == 314
    assert by_key["Q4"].answer["positions"] == [3]
    assert by_key["Q5"].answer["positions"] == [3]

    # Verify status and figure status
    for q in bundle.questions:
        assert q.status == "needs_review"
    assert by_key["Q1"].figure_status == "none"
    assert by_key["Q2"].figure_status == "pending"
    assert by_key["Q3"].figure_status == "none"
    assert by_key["Q4"].figure_status == "none"
    assert by_key["Q5"].figure_status == "pending"

    # Verify exact subtopic tags
    assert by_key["Q1"].tags[0].code == "PHY.U14.T04.S02"
    assert by_key["Q2"].tags[0].code == "PHY.U14.T05.S01"
    assert by_key["Q3"].tags[0].code == "PHY.U14.T03.S01"
    assert by_key["Q4"].tags[0].code == "PHY.U14.T02.S01"
    assert by_key["Q5"].tags[0].code == "PHY.U14.T06.S01"
    assert any(t.code == "PHY.U14.T04.S01" and not t.is_primary for t in by_key["Q5"].tags)
