import shutil
from pathlib import Path
from engines.ingestion.inventory import inventory_pdf_directory


def test_inventory_directory_on_sample(tmp_path: Path):
    syllabus_pdf = Path("data/raw/jee_dataset/syllabus/SYLLABUS.PDF")
    if not syllabus_pdf.exists():
        syllabus_pdf = Path("data/input/SYLLABUS.PDF")
    if not syllabus_pdf.exists():
        return

    # Create isolated sample directory with 1 primary and 1 duplicate
    sample_dir = tmp_path / "sample_pdfs"
    sample_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(syllabus_pdf, sample_dir / "syllabus_a.pdf")
    shutil.copy2(syllabus_pdf, sample_dir / "syllabus_b.pdf")

    out_csv = tmp_path / "inventory.csv"
    records, summary = inventory_pdf_directory(sample_dir, output_csv=out_csv)

    assert summary["total_files"] == 2
    assert summary["duplicate_groups"] == 1
    assert summary["duplicate_files"] == 1
    assert summary["unique_files"] == 1
    assert out_csv.exists()
    assert len(records) == 2

