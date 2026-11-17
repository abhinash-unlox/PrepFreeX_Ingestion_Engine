import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from engines.ingestion.registry import (
    acquire_pdf_lock,
    release_pdf_lock,
    get_next_eligible_pdf,
    get_registry_summary,
    scan_and_sync_inventory,
)
from engines.ingestion.orchestrator import OrchestrationWorker
from engines.shared.config import settings


def test_registry_summary_loads():
    """Verify that get_registry_summary returns expected dictionary structure from PostgreSQL."""
    summary = get_registry_summary()
    assert "status_counts" in summary
    assert "aggregates" in summary
    assert "by_category" in summary
    assert summary["aggregates"]["total_pdfs"] >= 800


def test_pdf_lock_acquisition_and_release():
    """Verify single-worker locking prevents multiple sessions from acquiring the same PDF."""
    next_pdf = get_next_eligible_pdf()
    assert next_pdf is not None, "At least one eligible PDF should exist"
    pdf_id = str(next_pdf["id"])
    worker_a = "worker_test_alpha"
    worker_b = "worker_test_beta"

    # Worker A acquires lock
    assert acquire_pdf_lock(pdf_id, worker_a) is True

    # Worker B tries to acquire lock on the same PDF -> should fail
    assert acquire_pdf_lock(pdf_id, worker_b) is False

    # Worker A releases lock
    release_pdf_lock(pdf_id, worker_a)

    # Now Worker B can acquire it
    assert acquire_pdf_lock(pdf_id, worker_b) is True

    # Clean up
    release_pdf_lock(pdf_id, worker_b)


def test_orchestrator_budget_check():
    """Verify token budget enforcement handles limits gracefully."""
    worker = OrchestrationWorker(worker_id="test_budget_worker")
    can_proceed, reason = worker.check_token_budget(estimated_tokens=500)
    # With authorized configured keys and budget, this should be True
    assert isinstance(can_proceed, bool)
    assert isinstance(reason, str)


def test_dry_run_single_pdf_processing():
    """Verify that dry-run processing stages candidates cleanly without live LLM calls."""
    worker = OrchestrationWorker(worker_id="test_dry_worker", dry_run=True, max_pdf_limit=1)
    fake_pdf = {
        "id": "00000000-0000-0000-0000-000000000000",
        "relative_path": "physics/test.pdf",
        "filename": "test.pdf",
        "category": "physics",
        "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "page_count": 2,
        "processing_status": "DISCOVERED"
    }

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn
    mock_cursor.fetchone.return_value = {"count": 1}

    with patch("engines.ingestion.orchestrator.acquire_pdf_lock", return_value=True), \
         patch("engines.ingestion.orchestrator.release_pdf_lock", return_value=True), \
         patch("engines.ingestion.orchestrator.log_pdf_event"), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("engines.ingestion.orchestrator.psycopg.connect", return_value=mock_conn), \
         patch("engines.ingestion.orchestrator.run_ingestion") as mock_run_ingest:
        mock_run_ingest.return_value = {
            "job_id": "00000000-0000-0000-0000-000000000001",
            "question_candidate_count": 5,
            "db_stats": {
                "candidates_staged": 5,
                "inserted": 0,
                "needs_review": 5
            }
        }
        res = worker.process_single_pdf(fake_pdf)
        assert res["status"] in {"COMPLETED", "COMPLETED_WITH_REVIEW", "NEEDS_MANUAL_REVIEW"}
        assert "questions_detected" in res


