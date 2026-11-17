import pytest
from pathlib import Path
from engines.ingestion.pipeline import detect_source_subject
from engines.ingestion.registry import (
    acquire_pdf_lock,
    release_pdf_lock,
    recover_stale_locks,
    get_next_eligible_pdf,
)


def test_subject_detection_folder_vs_mathongo_filename():
    """Verify MathonGo filename does not trick the classifier into returning mathematics."""
    # Chemistry folder with MathonGo filename
    chem_win = Path("data\\raw\\jee_dataset\\chemistry\\p Block Elements - JEE Main 2026 - MathonGo.pdf")
    chem_posix = Path("data/raw/jee_dataset/chemistry/p Block Elements - JEE Main 2026 - MathonGo.pdf")
    assert detect_source_subject(chem_win) == "chemistry"
    assert detect_source_subject(chem_posix) == "chemistry"

    # Physics folder with MathonGo filename
    phys_win = Path("data\\raw\\jee_dataset\\physics\\Center of Mass - JEE Main 2026 - MathonGo.pdf")
    phys_posix = Path("data/raw/jee_dataset/physics/Center of Mass - JEE Main 2026 - MathonGo.pdf")
    assert detect_source_subject(phys_win) == "physics"
    assert detect_source_subject(phys_posix) == "physics"

    # Mathematics folder with MathonGo filename
    math_win = Path("data\\raw\\jee_dataset\\mathematics\\Limits - JEE Main 2026 - MathonGo.pdf")
    math_posix = Path("data/raw/jee_dataset/mathematics/Limits - JEE Main 2026 - MathonGo.pdf")
    assert detect_source_subject(math_win) == "mathematics"
    assert detect_source_subject(math_posix) == "mathematics"


def test_subject_detection_mixed_full_tests():
    """Verify mixed full test papers detect subject from section headers or question text."""
    full_test = Path("data/raw/jee_dataset/full_tests/JEE Main Part Test-1_.pdf")
    
    # Via section metadata
    assert detect_source_subject(full_test, section_name="Section I (Physics)") == "physics"
    assert detect_source_subject(full_test, section_name="Section II (Chemistry)") == "chemistry"
    assert detect_source_subject(full_test, section_name="Section I (Mathematics)") == "mathematics"

    # Via question text header
    assert detect_source_subject(full_test, question_text="PART A - CHEMISTRY\nQ1. What is hybridization...") == "chemistry"
    assert detect_source_subject(full_test, question_text="PART B - PHYSICS\nQ1. A body of mass 10 kg...") == "physics"
    assert detect_source_subject(full_test, question_text="PART C - MATHEMATICS\nQ1. If matrix A has det...") == "mathematics"


def test_subject_detection_unknown_returns_none():
    """Verify unknown or unclassifiable sources return None rather than defaulting to Physics."""
    unknown_pdf = Path("data/raw/jee_dataset/syllabus/SYLLABUS.PDF")
    assert detect_source_subject(unknown_pdf, question_text="General Instructions for Candidates") is None


def test_pdf_lock_ownership_and_safe_release():
    """Verify lock release requires worker ownership and resets IN_PROGRESS without losing checkpoints."""
    next_pdf = get_next_eligible_pdf()
    assert next_pdf is not None
    pdf_id = str(next_pdf["id"])

    # Worker 1 acquires lock
    assert acquire_pdf_lock(pdf_id, "worker_1") is True

    # Worker 2 cannot release Worker 1's lock
    assert release_pdf_lock(pdf_id, "worker_2") is False

    # Worker 1 releases lock safely -> reverts to DISCOVERED (since questions_extracted == 0)
    assert release_pdf_lock(pdf_id, "worker_1") is True


def test_stale_lock_recovery():
    """Verify stale-lock recovery detects orphaned locks and restores them safely."""
    next_pdf = get_next_eligible_pdf()
    assert next_pdf is not None
    pdf_id = str(next_pdf["id"])

    acquire_pdf_lock(pdf_id, "abandoned_worker")
    # Recover stale locks (simulated with 0 timeout)
    recovered = recover_stale_locks(timeout_minutes=0)
    assert recovered >= 1

