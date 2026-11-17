import json
from pathlib import Path

from engines.ingestion.taxonomy import (
    apply_taxonomy_review,
    build_taxonomy_v2,
    write_taxonomy_review_csvs,
)

ROOT = Path(__file__).resolve().parents[1]
_SYLLABUS_PDF = ROOT / "data/raw/jee_dataset/syllabus/SYLLABUS.PDF"
if not _SYLLABUS_PDF.exists():
    _SYLLABUS_PDF = ROOT / "data/input/SYLLABUS.PDF"


def test_syllabus_taxonomy_has_correct_unit_counts():
    data = build_taxonomy_v2(_SYLLABUS_PDF)
    nodes = data["nodes"]
    units = [n for n in nodes if n["level"] == "unit"]
    assert len(units) == 54
    assert sum(n["code"].startswith("MAT.") for n in units) == 14
    assert sum(n["code"].startswith("PHY.") for n in units) == 20
    assert sum(n["code"].startswith("CHE.") for n in units) == 20
    by_code = {n["code"]: n for n in nodes}
    assert by_code["CHE.U08"]["parent_code"] == "CHE.PHYSICAL"
    assert by_code["CHE.U09"]["parent_code"] == "CHE.INORGANIC"
    assert by_code["CHE.U13"]["parent_code"] == "CHE.ORGANIC"
    assert by_code["PHY.U14.T04.S02"]["parent_code"] == "PHY.U14.T04"


def test_taxonomy_build_produces_valid_v2_json(tmp_path):
    data = build_taxonomy_v2(_SYLLABUS_PDF)
    nodes = data["nodes"]

    # Unique codes
    codes = [n["code"] for n in nodes]
    assert len(codes) == len(set(codes)), "All taxonomy codes must be unique"

    by_code = {n["code"]: n for n in nodes}

    # Every subtopic has a parent topic
    subtopics = [n for n in nodes if n["level"] == "subtopic"]
    for sub in subtopics:
        parent = sub["parent_code"]
        assert parent in by_code, f"Subtopic {sub['code']} parent {parent} missing"
        assert by_code[parent]["level"] == "topic"

    # Every unit has at least one topic
    units = [n for n in nodes if n["level"] == "unit"]
    for u in units:
        topics_for_unit = [n for n in nodes if n["level"] == "topic" and n["parent_code"] == u["code"]]
        assert len(topics_for_unit) >= 1, f"Unit {u['code']} has no topics"

    # Physics U14 nodes identical to v1 (same 15 topic/subtopic nodes and codes)
    u14_nodes = [n for n in nodes if n["code"].startswith("PHY.U14.T")]
    assert len(u14_nodes) == 15
    expected_u14_codes = {
        "PHY.U14.T01", "PHY.U14.T02", "PHY.U14.T02.S01", "PHY.U14.T03",
        "PHY.U14.T03.S01", "PHY.U14.T03.S02", "PHY.U14.T04", "PHY.U14.T04.S01",
        "PHY.U14.T04.S02", "PHY.U14.T05", "PHY.U14.T05.S01", "PHY.U14.T06",
        "PHY.U14.T06.S01", "PHY.U14.T06.S02", "PHY.U14.T07"
    }
    assert {n["code"] for n in u14_nodes} == expected_u14_codes

    # Physics U20 and Chemistry U20 have topics only, no subtopics
    assert not any(n["code"].startswith("PHY.U20.T") and n["level"] == "subtopic" for n in nodes)
    assert not any(n["code"].startswith("CHE.U20.T") and n["level"] == "subtopic" for n in nodes)


def test_taxonomy_apply_review_rename_and_merge(tmp_path):
    # Setup test seed
    test_seed = tmp_path / "test_seed.json"
    data = {
        "taxonomy_version": "test_v1",
        "nodes": [
            {"code": "PHY.U01", "level": "unit", "name": "Units and Measurements", "parent_code": "PHY", "is_reviewed": True, "is_active": True},
            {"code": "PHY.U01.T01", "level": "topic", "name": "Units of measurement", "parent_code": "PHY.U01", "is_reviewed": False, "is_active": True},
            {"code": "PHY.U01.T01.S01", "level": "subtopic", "name": "SI units and fundamental quantities", "parent_code": "PHY.U01.T01", "is_reviewed": False, "is_active": True},
            {"code": "PHY.U01.T01.S02", "level": "subtopic", "name": "Redundant subtopic to merge", "parent_code": "PHY.U01.T01", "is_reviewed": False, "is_active": True},
        ]
    }
    test_seed.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # Create review CSV
    csv_file = tmp_path / "PHY.U01.csv"
    csv_file.write_text(
        "code,level,name,description,example_stems,action\n"
        "PHY.U01,unit,Units and Measurements,,,keep\n"
        "PHY.U01.T01,topic,Units of measurement,,,keep\n"
        "PHY.U01.T01.S01,subtopic,Renamed SI Units,New description,Stem 1 | Stem 2,rename\n"
        "PHY.U01.T01.S02,subtopic,Redundant subtopic,,,merge_into:PHY.U01.T01.S01\n"
        ",subtopic,Newly Added Subtopic,Description of new,Stem A | Stem B,add\n",
        encoding="utf-8"
    )

    res = apply_taxonomy_review(csv_file, seed_path=test_seed)
    assert res["applied_count"] >= 3

    updated = json.loads(test_seed.read_text(encoding="utf-8"))["nodes"]
    by_code = {n["code"]: n for n in updated}

    # Renamed node
    assert by_code["PHY.U01.T01.S01"]["name"] == "Renamed SI Units"
    assert by_code["PHY.U01.T01.S01"]["is_reviewed"] is True

    # Merged node
    assert by_code["PHY.U01.T01.S02"]["is_active"] is False
    assert by_code["PHY.U01.T01.S02"]["replaced_by"] == "PHY.U01.T01.S01"

    # Newly added node got fresh code
    assert "PHY.U01.T01.S03" in by_code
    assert by_code["PHY.U01.T01.S03"]["name"] == "Newly Added Subtopic"
