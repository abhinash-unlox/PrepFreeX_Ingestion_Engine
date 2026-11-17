import json
from pathlib import Path

from engines.ingestion.llm import GeminiProvider, set_llm_provider
from engines.ingestion.pipeline import run_ingestion

ROOT = Path(__file__).resolve().parents[1]
_PILOT_PDF = ROOT / "data/raw/jee_dataset/physics/Alternating Current - JEE Main 2026 (Jan) - MathonGo.pdf"
if not _PILOT_PDF.exists():
    _PILOT_PDF = ROOT / "data/input/Alternating Current - JEE Main 2026 (Jan) - MathonGo.pdf"


def test_running_ingest_twice_gives_identical_output_and_zero_new_requests(tmp_path):
    pdf = _PILOT_PDF
    taxonomy_file = ROOT / "db/seeds/jee_main_2027_taxonomy_v2.json"
    if not taxonomy_file.exists():
        taxonomy_file = ROOT / "db/seeds/jee_main_2027_taxonomy.json"

    # Run 1
    report1 = run_ingestion(pdf, taxonomy_file, tmp_path / "run1", dry_run=True)
    bundle1 = json.loads(Path(report1["artifacts"]["question_import"]).read_text(encoding="utf-8"))

    # Run 2
    report2 = run_ingestion(pdf, taxonomy_file, tmp_path / "run2", dry_run=True)
    bundle2 = json.loads(Path(report2["artifacts"]["question_import"]).read_text(encoding="utf-8"))

    # Compare questions content
    assert len(bundle1["questions"]) == len(bundle2["questions"])
    for q1, q2 in zip(bundle1["questions"], bundle2["questions"]):
        assert q1["source_question_key"] == q2["source_question_key"]
        assert q1["stem_md"] == q2["stem_md"]
        assert q1["answer"] == q2["answer"]
        assert [t["code"] for t in q1["tags"]] == [t["code"] for t in q2["tags"]]

