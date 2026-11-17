import pytest
from pathlib import Path
from typer.testing import CliRunner

from engines.ingestion.cli import app

runner = CliRunner()
ROOT = Path(__file__).resolve().parents[1]
_PILOT_PDF = ROOT / "data/raw/jee_dataset/physics/Alternating Current - JEE Main 2026 (Jan) - MathonGo.pdf"
if not _PILOT_PDF.exists():
    _PILOT_PDF = ROOT / "data/input/Alternating Current - JEE Main 2026 (Jan) - MathonGo.pdf"


@pytest.mark.db
def test_quickstart_db_check():
    result = runner.invoke(app, ["db-check"])
    assert result.exit_code == 0
    assert "Database connection successful" in result.output


@pytest.mark.db
def test_quickstart_migrate():
    result = runner.invoke(app, ["migrate"])
    assert result.exit_code == 0


@pytest.mark.db
def test_quickstart_seed_taxonomy():
    v2_seed = ROOT / "db/seeds/jee_main_2027_taxonomy_v2.json"
    result = runner.invoke(app, ["seed-taxonomy", "--file", str(v2_seed), "--persist"])
    assert result.exit_code == 0
    assert "Seeded" in result.output


@pytest.mark.db
def test_quickstart_ingest_pdf(tmp_path):
    pdf = _PILOT_PDF
    result = runner.invoke(app, ["ingest-pdf", str(pdf), "--provider", "fake", "--dry-run"])
    assert result.exit_code == 0


@pytest.mark.db
def test_quickstart_report():
    result = runner.invoke(app, ["report"])
    assert result.exit_code == 0

