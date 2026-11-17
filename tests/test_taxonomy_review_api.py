import pytest
from fastapi.testclient import TestClient
from apps.api.main import app

client = TestClient(app)

def test_taxonomy_review_summary():
    resp = client.get("/api/v1/admin/taxonomy-review/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_canonical"] >= 399
    assert "reviewed_count" in data
    assert "confirmed_count" in data
    assert "reclassified_count" in data
    assert "proposals_count" in data
    assert "uncertain_count" in data
    assert "source_problem_count" in data
    assert "completion_pct" in data
    assert "accuracy_pct" in data
    assert "original_accuracy_pct" in data
    assert "corrected_coverage_pct" in data

def test_taxonomy_tree_structure():
    resp = client.get("/api/v1/admin/taxonomy-review/taxonomy-tree")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_nodes"] == 767
    assert len(data["units"]) == 54
    assert len(data["topics"]) == 185
    assert len(data["subtopics"]) == 522

def test_review_question_list_and_filters():
    resp = client.get("/api/v1/admin/taxonomy-review/questions?page=1&page_size=5")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 399
    assert len(data["items"]) == 5

    resp_phy = client.get("/api/v1/admin/taxonomy-review/questions?subject=physics&page=1&page_size=5")
    assert resp_phy.status_code == 200
    data_phy = resp_phy.json()
    for item in data_phy["items"]:
        assert item["subject"] == "physics"

    resp_unit = client.get("/api/v1/admin/taxonomy-review/questions?unit_code=PHY.U14&page=1&page_size=5")
    assert resp_unit.status_code == 200
    data_u = resp_unit.json()
    assert data_u["total"] >= 1

def test_review_question_detail_hierarchy():
    resp = client.get("/api/v1/admin/taxonomy-review/question/Q00000001")
    assert resp.status_code == 200
    data = resp.json()
    assert data["public_id"] == "Q00000001"
    assert data["subject"] == "physics"
    assert "stem_md" in data
    assert "options" in data
    assert "answer" in data
    
    tax = data["current_taxonomy"]
    assert "subject" in tax
    assert "unit" in tax
    assert "topic" in tax
    assert "subtopic" in tax
    assert tax["subject"]["code"] == "PHY"
    assert tax["unit"]["code"] == "PHY.U14"
    assert tax["subtopic"]["code"] == "PHY.U14.T04.S02"

def test_source_page_preview():
    resp = client.get("/api/v1/admin/taxonomy-review/source-page/Q00000001")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert len(resp.content) > 1000

def test_decision_and_immediate_apply_workflow():
    # 1. Submit CONFIRM_CORRECT on Q00000003
    resp = client.post("/api/v1/admin/taxonomy-review/decision", json={
        "public_id": "Q00000003",
        "reviewer_decision": "CONFIRM_CORRECT",
        "reviewer_notes": "Test verification of LC oscillation question",
        "reviewer_id": "pytest_runner"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert "audit_id" in data

    # 2. Test Draft RECLASSIFY (apply_immediately=False)
    resp_rec = client.post("/api/v1/admin/taxonomy-review/decision", json={
        "public_id": "Q00000004",
        "reviewer_decision": "RECLASSIFY",
        "proposed_subtopic_id": 378,
        "reviewer_notes": "Reclassifying to PHY.U14.T04.S01 via draft test",
        "reviewer_id": "pytest_runner",
        "apply_immediately": False
    })
    assert resp_rec.status_code == 200
    audit_id = resp_rec.json()["audit_id"]

    det_pre = client.get("/api/v1/admin/taxonomy-review/question/Q00000004").json()
    assert det_pre["latest_audit"]["is_applied"] is False

    # 3. Apply correction explicitly
    resp_app = client.post("/api/v1/admin/taxonomy-review/apply-correction", json={
        "audit_id": audit_id,
        "reviewer_id": "pytest_runner"
    })
    assert resp_app.status_code == 200

    # 4. Test Immediate Reclassification & Apply (apply_immediately=True)
    resp_imm = client.post("/api/v1/admin/taxonomy-review/decision", json={
        "public_id": "Q00000004",
        "reviewer_decision": "RECLASSIFY",
        "proposed_subtopic_id": 373,
        "reviewer_notes": "Immediate reclassify to PHY.U14.T02.S01 (RMS non-sinusoidal)",
        "reviewer_id": "pytest_runner",
        "apply_immediately": True
    })
    assert resp_imm.status_code == 200
    assert resp_imm.json()["is_applied"] is True

    det_imm = client.get("/api/v1/admin/taxonomy-review/question/Q00000004").json()
    assert det_imm["current_taxonomy"]["subtopic"]["id"] == 373
    assert det_imm["latest_audit"]["is_applied"] is True

    # 5. Test duplicate review suppression
    resp_dup = client.post("/api/v1/admin/taxonomy-review/decision", json={
        "public_id": "Q00000004",
        "reviewer_decision": "RECLASSIFY",
        "proposed_subtopic_id": 373,
        "reviewer_notes": "Immediate reclassify to PHY.U14.T02.S01 (RMS non-sinusoidal)",
        "reviewer_id": "pytest_runner",
        "apply_immediately": True
    })
    assert resp_dup.status_code == 200
    assert resp_dup.json().get("duplicate_suppressed") is True

def test_prevent_invalid_decision():
    resp = client.post("/api/v1/admin/taxonomy-review/decision", json={
        "public_id": "Q00000001",
        "reviewer_decision": "INVALID_DECISION_NAME"
    })
    assert resp.status_code == 400

def test_offline_suggestion():
    resp = client.get("/api/v1/admin/taxonomy-review/suggest/Q00000001")
    assert resp.status_code == 200
    data = resp.json()
    assert "suggestions" in data

def test_next_unreviewed_endpoint():
    resp = client.get("/api/v1/admin/taxonomy-review/next-unreviewed")
    assert resp.status_code == 200
    data = resp.json()
    assert "public_id" in data
