from __future__ import annotations

import os
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.admin.api_client import AdminAPIClient


@pytest.fixture
def client():
    return TestClient(app)


def test_api_health(client):
    """GET /api/v1/health returns healthy DB connection without credentials."""
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["database_connected"] is True
    assert data["database_name"] == "prepfreex"
    assert "PostgreSQL" in data["database_version"]
    # Ensure no credentials leaked
    assert "password" not in str(data).lower()
    assert "user" not in data


def test_summary_counts(client):
    """GET /api/v1/admin/summary returns exact DB aggregates."""
    resp = client.get("/api/v1/admin/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_questions"] >= 11
    assert "physics" in data["by_subject"]
    assert "mathematics" in data["by_subject"]
    assert "chemistry" in data["by_subject"]
    assert data["total_taxonomy_nodes"] == 767
    assert data["eligible_question_count"] == 0
    assert len(data["by_source"]) >= 3


def test_question_list_retrieval(client):
    """GET /api/v1/admin/questions returns question summaries with taxonomy info."""
    resp = client.get("/api/v1/admin/questions?page_size=10")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 11
    assert len(data["items"]) <= 10
    first = data["items"][0]
    assert "public_id" in first
    assert "subject" in first
    assert "question_type" in first
    assert "stem_preview" in first
    assert "status" in first


def test_pagination(client):
    """Verify page and page_size controls."""
    resp1 = client.get("/api/v1/admin/questions?page=1&page_size=2")
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert len(data1["items"]) == 2
    assert data1["page"] == 1
    assert data1["page_size"] == 2

    resp2 = client.get("/api/v1/admin/questions?page=2&page_size=2")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert len(data2["items"]) == 2
    assert data2["page"] == 2

    # Verify stable sorting (different items on page 1 vs page 2)
    ids_p1 = {item["public_id"] for item in data1["items"]}
    ids_p2 = {item["public_id"] for item in data2["items"]}
    assert ids_p1.isdisjoint(ids_p2)


def test_subject_filters(client):
    """Verify subject filtering."""
    for subj in ["mathematics", "physics", "chemistry"]:
        resp = client.get(f"/api/v1/admin/questions?subject={subj}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] > 0
        for item in data["items"]:
            assert item["subject"] == subj


def test_unit_topic_subtopic_filters(client):
    """Verify taxonomy filtering by unit, topic, and subtopic."""
    # Filter by unit MAT.U03
    resp_unit = client.get("/api/v1/admin/questions?unit_code=MAT.U03")
    assert resp_unit.status_code == 200
    data_unit = resp_unit.json()
    assert data_unit["total"] >= 1
    assert all(it["unit_code"] == "MAT.U03" for it in data_unit["items"])

    # Filter by subtopic
    sub_code = "PHY.U07.T04.S03"
    resp_sub = client.get(f"/api/v1/admin/questions?subtopic_code={sub_code}")
    assert resp_sub.status_code == 200
    data_sub = resp_sub.json()
    assert data_sub["total"] >= 1
    assert all(it["subtopic_code"] == sub_code for it in data_sub["items"])


def test_question_detail_and_options(client):
    """Verify question detail endpoint returns complete options, answer, and explanation."""
    resp = client.get("/api/v1/admin/questions/Q00000001")
    assert resp.status_code == 200
    data = resp.json()
    assert data["public_id"] == "Q00000001"
    assert data["subject"] == "physics"
    assert len(data["options"]) == 4
    # Check options are sorted by position
    positions = [o["position"] for o in data["options"]]
    assert positions == [1, 2, 3, 4]
    assert data["answer"] is not None
    assert data["status"] == "needs_review"
    assert data["source"]["license_status"] == "unverified"


def test_correct_taxonomy_mapping(client):
    """Verify taxonomy hierarchy in detail view."""
    resp = client.get("/api/v1/admin/questions/Q00000006")
    assert resp.status_code == 200
    data = resp.json()
    assert data["unit_code"] == "MAT.U03"
    assert data["topic_code"] == "MAT.U03.T02"
    assert data["subtopic_code"] == "MAT.U03.T02.S02"
    assert data["primary_tag"]["code"] == "MAT.U03.T02.S02"
    assert data["primary_tag"]["is_primary"] is True


def test_empty_search_results(client):
    """Verify searching for non-existent text returns total=0 and items=[]."""
    resp = client.get("/api/v1/admin/questions?search=nonexistent_query_term_12345")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []


def test_db_unavailable_response():
    """Verify graceful handling when database is unavailable."""
    with patch("apps.api.routes.questions.get_db_cursor") as mock_cursor:
        mock_cursor.side_effect = Exception("PostgreSQL down")
        test_client = TestClient(app)
        resp = test_client.get("/api/v1/admin/summary")
        assert resp.status_code == 503
        assert "Database error" in resp.json()["detail"]


def test_streamlit_api_client(client):
    """Verify AdminAPIClient communication and telemetry."""
    # Test client using custom session or local testclient
    admin_client = AdminAPIClient(base_url="http://testserver")
    with patch("requests.request", side_effect=client.request):
        health, lat, status, err = admin_client.get_health()
        assert status == 200
        assert health["database_connected"] is True
        assert err is None
        assert admin_client.last_diagnostic["endpoint"] == "/api/v1/health"

        summary, lat, status, err = admin_client.get_summary()
        assert status == 200
        assert summary["total_questions"] >= 11


def test_no_direct_postgres_in_streamlit():
    """STRICT RULE VERIFICATION: Ensure apps/admin contains ZERO database imports or SQL queries."""
    admin_dir = "apps/admin"
    forbidden_terms = [
        "import psycopg",
        "from psycopg",
        "import sqlite3",
        "import asyncpg",
        "from engines.ingestion.database",
        "import database",
        "DATABASE_URL",
        "get_db_cursor",
    ]

    for root, _, files in os.walk(admin_dir):
        for f in files:
            if f.endswith(".py"):
                file_path = os.path.join(root, f)
                with open(file_path, "r", encoding="utf-8") as fp:
                    content = fp.read()
                    for term in forbidden_terms:
                        assert term not in content, f"Forbidden term '{term}' found in {file_path}! Streamlit must communicate ONLY via REST."

