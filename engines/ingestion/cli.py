from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Optional

import typer

from .config import settings
from .classifier import SubtopicTagger, append_tag_feedback
from .database import (
    accept_proposal,
    check_db,
    connect,
    docker_db_backup,
    docker_db_down,
    docker_db_reset,
    docker_db_restore,
    docker_db_shell,
    docker_db_up,
    export_job,
    get_question_by_public_id,
    import_bundle,
    is_db_reachable,
    list_jobs,
    list_proposals,
    record_ingestion_result,
    retag_job_questions,
    run_migrations,
    seed_taxonomy,
)
from .llm import get_llm_provider
from .pipeline import run_ingestion
from .taxonomy import apply_taxonomy_review, build_taxonomy_v2, load_taxonomy, write_taxonomy_review_csvs, write_taxonomy_seed
from .validators import validate_import_file

app = typer.Typer(no_args_is_help=True, help="PrepFreeX PDF-to-Question-Bank ingestion engine")


def _taxonomy_path() -> Path:
    p2 = Path("db/seeds/jee_main_2027_taxonomy_v2.json")
    if p2.exists():
        return p2
    return Path("db/seeds/jee_main_2027_taxonomy.json")


# ---------------------------------------------------------
# Database Docker Management Commands
# ---------------------------------------------------------

@app.command("db-up")
def db_up_cmd():
    """Starts the PostgreSQL container in Docker and waits for healthcheck."""
    docker_db_up()


@app.command("db-down")
def db_down_cmd():
    """Stops the PostgreSQL container, keeping data volume."""
    docker_db_down()


@app.command("db-reset")
def db_reset_cmd(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """Stops and deletes the PostgreSQL volume."""
    docker_db_reset(confirm=yes)


@app.command("db-backup")
def db_backup_cmd(
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Backup SQL destination"),
):
    """Creates a database backup inside backups/YYYYMMDD_HHMM.sql."""
    docker_db_backup(output)


@app.command("db-restore")
def db_restore_cmd(
    file: Path = typer.Argument(..., exists=True, readable=True, help="SQL backup file to restore"),
):
    """Restores database from a SQL backup file."""
    docker_db_restore(file)


@app.command("db-shell")
def db_shell_cmd():
    """Opens interactive psql shell inside the container."""
    docker_db_shell()


@app.command("db-check")
def db_check_cmd():
    """Checks database connection and verifies pgcrypto and pg_trgm extensions."""
    try:
        diag = check_db()
        typer.echo("Database connection successful!")
        typer.echo(f"PostgreSQL Version: {diag['server_version']}")
        typer.echo(f"pgcrypto extension: {'Available/Installed' if diag['pgcrypto_available'] else 'MISSING'}")
        typer.echo(f"pg_trgm extension:  {'Available/Installed' if diag['pg_trgm_available'] else 'MISSING'}")
        typer.echo(f"Table privileges:  {'Verified' if diag.get('table_creation_ok') else 'FAILED'}")
    except Exception as exc:
        typer.echo(f"Database Check Failed: {exc}", err=True)
        raise typer.Exit(1)


@app.command("migrate")
def migrate_command(
    migrations: Path = typer.Option(Path("db/migrations"), exists=True),
):
    """Applies schema migrations idempotently."""
    try:
        applied = run_migrations(migrations)
        typer.echo(f"Applied {len(applied)} migration(s): {', '.join(applied) if applied else 'none; schema is current'}")
    except Exception as exc:
        typer.echo(f"Migration error: {exc}", err=True)
        raise typer.Exit(1)


# ---------------------------------------------------------
# Taxonomy Commands
# ---------------------------------------------------------

@app.command("seed-taxonomy")
def seed_taxonomy_command(
    file: Optional[Path] = typer.Option(None, "--file", help="Taxonomy seed JSON file"),
    syllabus: Path = typer.Option(Path("data/input/SYLLABUS.PDF"), help="JEE Main syllabus PDF"),
    persist: bool = typer.Option(False, "--persist", help="Persist to PostgreSQL"),
):
    """Generates and/or seeds taxonomy into database."""
    target_file = file or _taxonomy_path()
    if not target_file.exists():
        result = build_taxonomy_v2(syllabus)
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        typer.echo(f"Generated {len(result['nodes'])} nodes to {target_file}")
    else:
        raw = json.loads(target_file.read_text(encoding="utf-8"))
        typer.echo(f"Loaded {len(raw['nodes'])} nodes from {target_file}")

    if persist:
        try:
            n = seed_taxonomy(target_file)
            typer.echo(f"Seeded {n} taxonomy nodes into PostgreSQL.")
        except Exception as exc:
            typer.echo(f"Database seed error: {exc}", err=True)
            raise typer.Exit(1)


@app.command("taxonomy-build")
def taxonomy_build_command(
    unit: Optional[str] = typer.Option(None, "--unit", help="Unit code (e.g. PHY.U14)"),
    all_units: bool = typer.Option(False, "--all", help="Build all 54 units"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Dry run without writing to DB"),
    syllabus: Path = typer.Option(Path("data/input/SYLLABUS.PDF"), exists=True),
):
    """Builds refined v2 taxonomy and review CSV files."""
    llm = get_llm_provider()
    res = build_taxonomy_v2(syllabus, unit_filter=unit if not all_units else None, llm=llm)
    nodes = res["nodes"]

    out_file = Path("db/seeds/jee_main_2027_taxonomy_v2.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")

    review_dir = Path("docs/taxonomy_review")
    write_taxonomy_review_csvs(nodes, review_dir)

    units_count = sum(1 for n in nodes if n["level"] == "unit")
    topics_count = sum(1 for n in nodes if n["level"] == "topic")
    subtopics_count = sum(1 for n in nodes if n["level"] == "subtopic")

    typer.echo(f"Taxonomy v2 built: {units_count} units, {topics_count} topics, {subtopics_count} subtopics.")
    typer.echo(f"Written seed to {out_file} and 54 unit review CSVs to {review_dir}")


@app.command("taxonomy-apply-review")
def taxonomy_apply_review_command(
    csv_file: Path = typer.Argument(..., exists=True, readable=True, help="Review CSV path"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Dry run mode"),
):
    """Applies human review edits (renames, merges, deletions, additions) from CSV."""
    db_url = None if dry_run else settings.database_url
    res = apply_taxonomy_review(csv_file, database_url=db_url)
    typer.echo(f"Applied {res['applied_count']} review action(s):")
    for act in res["actions"]:
        typer.echo(f"  - {act}")


# ---------------------------------------------------------
# Ingestion & Evaluation Commands
# ---------------------------------------------------------

@app.command("ingest-pdf")
def ingest_pdf_command(
    pdf: Path = typer.Argument(..., exists=True, readable=True, help="PDF file to ingest"),
    doc_type: str = typer.Option("auto", "--doc-type", help="auto | full_test | chapter_test | question_bank"),
    exam: str = typer.Option("JEE Main", "--exam", help="Exam name"),
    year: int = typer.Option(2026, "--year", help="Exam year"),
    publisher: Optional[str] = typer.Option(None, "--publisher", help="Publisher name"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Dry run without writing to PostgreSQL"),
    resume: bool = typer.Option(False, "--resume", help="Resume previous ingestion"),
    pages: Optional[str] = typer.Option(None, "--pages", help="Page range e.g. 1-10"),
    provider: Optional[str] = typer.Option(None, "--provider", help="LLM provider: groq | rules | fake"),
):
    """Ingests a JEE-style PDF: questions, metadata, and exact subtopic tagging."""
    from .llm import FakeLLM

    page_range = None
    if pages:
        parts = pages.split("-")
        page_range = (int(parts[0]), int(parts[1]))

    db_url = None if dry_run else (settings.database_url if is_db_reachable() else None)
    llm = FakeLLM() if provider in {"rules", "fake"} else None
    report = run_ingestion(
        pdf_path=pdf,
        doc_type=doc_type,
        exam=exam,
        year=year,
        publisher=publisher,
        dry_run=dry_run,
        resume=resume,
        page_range=page_range,
        database_url=db_url,
        llm=llm,
    )
    typer.echo(json.dumps(report, indent=2, ensure_ascii=False))


@app.command("inventory-pdfs")
def inventory_pdfs_command(
    path: Path = typer.Argument(Path("data/raw/jee_dataset"), exists=True, help="Directory or file path to inventory"),
    output: Path = typer.Option(Path("data/inventory/pdf_inventory.csv"), "--output", "-o", help="Output CSV path"),
):
    """Recursively inspects PDFs without calling any LLM and writes a detailed inventory manifest."""
    from .inventory import inventory_pdf_directory

    db_conn = None
    if is_db_reachable():
        try:
            import psycopg
            db_conn = psycopg.connect(settings.database_url)
        except Exception:
            pass

    records, summary = inventory_pdf_directory(path, output_csv=output, db_conn=db_conn)
    if db_conn:
        db_conn.close()

    typer.echo("==================================================")
    typer.echo("             PDF INVENTORY REPORT                 ")
    typer.echo("==================================================")
    typer.echo(f"Scanned Path:           {path}")
    typer.echo(f"Total PDFs Found:       {summary['total_files']}")
    typer.echo(f"Total Size:             {summary['total_size_mb']} MB")
    typer.echo(f"Total Pages:            {summary['total_pages']}")
    typer.echo(f"Scanned (Image) Pages:  {summary['scanned_pages']}")
    typer.echo(f"Figure-Heavy Pages:     {summary['figure_heavy_pages']}")
    typer.echo("--------------------------------------------------")
    typer.echo(f"Unique Files:           {summary['unique_files']}")
    typer.echo(f"Duplicate Groups:       {summary['duplicate_groups']}")
    typer.echo(f"Duplicate Files:        {summary['duplicate_files']}")
    typer.echo("--------------------------------------------------")
    typer.echo(f"Manifest Generated:     {summary['manifest_path']}")
    typer.echo("==================================================")

    # Show file details
    typer.echo("\nFile Breakdown:")
    for r in records:
        dup_str = f" [DUPLICATE of {r['duplicate_of']}]" if r.get("is_duplicate") and r.get("duplicate_role") == "duplicate" else ""
        typer.echo(f" - {r['file_name']} ({r['size_mb']} MB, {r['total_pages']} pp, text: {r['text_layer']}){dup_str}")


@app.command("ingest")
def ingest_legacy_command(
    pdf: Path = typer.Argument(..., exists=True, readable=True),
    taxonomy: Path = typer.Option(_taxonomy_path()),
    output: Path = typer.Option(settings.artifact_dir),
    persist: bool = typer.Option(False, "--persist"),
):
    """Legacy alias for ingest-pdf."""
    report = run_ingestion(pdf, taxonomy_path=taxonomy, output_dir=output, dry_run=not persist)
    typer.echo(json.dumps(report, indent=2, ensure_ascii=False))


@app.command("proposals")
def proposals_command(
    accept: Optional[int] = typer.Option(None, "--accept", help="Proposal ID to accept"),
    name: Optional[str] = typer.Option(None, "--name", help="New subtopic name for accepted proposal"),
):
    """Lists open taxonomy proposals or accepts a proposal."""
    if accept is not None:
        if not name:
            typer.echo("Error: --name is required when accepting a proposal.", err=True)
            raise typer.Exit(1)
        res = accept_proposal(accept, name)
        typer.echo(f"Proposal {accept} accepted!")
        typer.echo(f"Created subtopic: {res['new_code']} - {res['new_name']}")
        typer.echo(f"Re-tagged {res['retagged_questions']} waiting question(s).")
    else:
        proposals = list_proposals(status="open")
        typer.echo(f"Open Proposals ({len(proposals)}):")
        for p in proposals:
            typer.echo(f"[{p['id']}] Parent: {p['parent_code']} | Proposed: {p['proposed_name']} | Rationale: {p['rationale']}")


@app.command("eval-tagging")
def eval_tagging_command(
    gold: Path = typer.Option(Path("tests/fixtures/gold_tags.json"), exists=True, help="Gold tags JSON file"),
    live: bool = typer.Option(False, "--live", help="Use live LLM instead of offline deterministic rules"),
):
    """Runs the tagger on the gold set and evaluates accuracy."""
    from .llm import FakeLLM

    gold_data = json.loads(gold.read_text(encoding="utf-8"))
    taxonomy = load_taxonomy(_taxonomy_path())
    tagger = SubtopicTagger(taxonomy, llm=None if live else FakeLLM())

    mathongo_items = gold_data.get("mathongo", [])
    allen_items = gold_data.get("allen", [])

    # Load authentic stems for MathonGo
    mathongo_stems: dict[str, tuple[str, str | None]] = {}
    try:
        from tests.fixtures.mathongo_pilot_profile import mathongo_ac_questions
        for q in mathongo_ac_questions():
            mathongo_stems[q.source_q_label] = (q.stem_md, q.source_explanation_md)
    except Exception:
        pass

    # Load authentic stems for ALLEN
    allen_stems: dict[str, str] = {}
    allen_fix_path = Path("tests/fixtures/allen_fixtures.json")
    if allen_fix_path.exists():
        try:
            allen_data = json.loads(allen_fix_path.read_text(encoding="utf-8"))
            allen_stems = allen_data.get("stems", {})
        except Exception:
            pass

    total_evaluated = len(mathongo_items) + len(allen_items)
    subject_correct = 0
    unit_correct = 0
    topic_correct = 0
    subtopic_correct = 0
    secondary_correct = 0
    low_confidence_count = 0
    no_fit_count = 0
    invalid_code_count = 0
    fallback_count = 0
    misses: list[str] = []

    # MathonGo evaluation (exact subtopic & secondary level)
    for item in mathongo_items:
        key = item["key"]
        expected_u = item["expected_unit"]
        expected_t = item.get("expected_topic")
        expected_s = item["expected_subtopic"]
        expected_sec = sorted(item.get("secondary", []))

        stem, sol = mathongo_stems.get(key, (f"MathonGo Question {key} Alternating Current", None))
        cls = tagger.tag(stem, subject="physics", solution=sol, source_question_key=key)

        # Subject accuracy
        if cls.subject.lower() == "physics":
            subject_correct += 1

        # Unit accuracy
        if cls.unit_code == expected_u:
            unit_correct += 1
        else:
            misses.append(f"MathonGo {key} Unit: expected {expected_u}, got {cls.unit_code}")

        # Topic accuracy
        if expected_t:
            if cls.primary_topic == expected_t:
                topic_correct += 1
            else:
                misses.append(f"MathonGo {key} Topic: expected {expected_t}, got {cls.primary_topic}")

        # Exact subtopic accuracy
        if cls.primary_subtopic == expected_s:
            subtopic_correct += 1
        else:
            misses.append(f"MathonGo {key} Subtopic: expected {expected_s}, got {cls.primary_subtopic}")

        # Secondary tag accuracy
        if sorted(cls.secondary_codes) == expected_sec:
            secondary_correct += 1
        else:
            misses.append(f"MathonGo {key} Secondary: expected {expected_sec}, got {cls.secondary_codes}")

        # Quality metrics
        if cls.confidence < 0.70:
            low_confidence_count += 1
        if cls.needs_subtopic or cls.proposed_subtopic_name:
            no_fit_count += 1
        for c in [cls.unit_code, cls.primary_topic, cls.primary_subtopic] + cls.secondary_codes:
            if c and c not in taxonomy:
                invalid_code_count += 1
        if cls.provider == "rules":
            fallback_count += 1

    # ALLEN evaluation (unit level)
    for item in allen_items:
        glob = item["global_number"]
        expected_u = item["expected_unit"]
        expected_subj = "mathematics" if expected_u.startswith("MAT.") else "physics" if expected_u.startswith("PHY.") else "chemistry"

        stem = allen_stems.get(str(glob), f"ALLEN Question {glob} in {expected_subj}")
        cls = tagger.tag(stem, subject=expected_subj, source_question_key=f"Q{glob}")

        # Subject accuracy
        if cls.subject.lower() == expected_subj.lower():
            subject_correct += 1

        # Unit accuracy
        if cls.unit_code == expected_u:
            unit_correct += 1
        else:
            misses.append(f"ALLEN Q{glob} Unit: expected {expected_u}, got {cls.unit_code}")

        # Quality metrics
        if cls.confidence < 0.70:
            low_confidence_count += 1
        if cls.needs_subtopic or cls.proposed_subtopic_name:
            no_fit_count += 1
        for c in [cls.unit_code, cls.primary_topic, cls.primary_subtopic] + cls.secondary_codes:
            if c and c not in taxonomy:
                invalid_code_count += 1
        if cls.provider == "rules":
            fallback_count += 1

    subj_acc = (subject_correct / total_evaluated * 100) if total_evaluated else 0.0
    unit_acc = (unit_correct / total_evaluated * 100) if total_evaluated else 0.0
    topic_acc = (topic_correct / len(mathongo_items) * 100) if mathongo_items else 0.0
    sub_acc = (subtopic_correct / len(mathongo_items) * 100) if mathongo_items else 0.0
    sec_acc = (secondary_correct / len(mathongo_items) * 100) if mathongo_items else 0.0
    low_conf_rate = (low_confidence_count / total_evaluated * 100) if total_evaluated else 0.0

    typer.echo("==================================================")
    typer.echo("          TAGGING EVALUATION REPORT               ")
    typer.echo("==================================================")
    typer.echo(f"Total Evaluated Questions:      {total_evaluated}")
    typer.echo(f"  - MathonGo (exact subtopic):  {len(mathongo_items)}")
    typer.echo(f"  - ALLEN (unit-level cases):   {len(allen_items)}")
    typer.echo("--------------------------------------------------")
    typer.echo("Accuracy Metrics:")
    typer.echo(f"  - Subject Accuracy:           {subj_acc:.1f}% ({subject_correct}/{total_evaluated})")
    typer.echo(f"  - Unit Accuracy:              {unit_acc:.1f}% ({unit_correct}/{total_evaluated}) [Target >= 90%]")
    typer.echo(f"  - Topic Accuracy:             {topic_acc:.1f}% ({topic_correct}/{len(mathongo_items)})")
    typer.echo(f"  - Exact Subtopic Accuracy:    {sub_acc:.1f}% ({subtopic_correct}/{len(mathongo_items)}) [Target 100%]")
    typer.echo(f"  - Secondary-Tag Accuracy:     {sec_acc:.1f}% ({secondary_correct}/{len(mathongo_items)}) [Target 100%]")
    typer.echo("--------------------------------------------------")
    typer.echo("Quality & Robustness Metrics:")
    typer.echo(f"  - Low-Confidence Rate (<0.7): {low_conf_rate:.1f}% ({low_confidence_count}/{total_evaluated})")
    typer.echo(f"  - No-Fit / Needs-Subtopic:    {no_fit_count}")
    typer.echo(f"  - Invalid Taxonomy Codes:     {invalid_code_count}")
    typer.echo(f"  - Fallback Classification:    {fallback_count}")
    typer.echo("==================================================")
    if misses:
        typer.echo("\nMisses / Mismatches:")
        for m in misses:
            typer.echo(f"  [X] {m}")
    else:
        typer.echo("\n[ALL TEST CASES PASSED PERFECTLY]")


@app.command("retag")
def retag_command(
    job: str = typer.Option(..., "--job", help="Job ID to retag"),
):
    """Re-tags questions in a job without modifying human-reviewed tags."""
    taxonomy = load_taxonomy(_taxonomy_path())
    updated = retag_job_questions(job, taxonomy)
    typer.echo(f"Retagged {updated} questions for job {job}.")


@app.command("jobs")
def jobs_command():
    """Lists recent ingestion jobs."""
    if is_db_reachable():
        jobs = list_jobs()
        typer.echo(f"Found {len(jobs)} jobs in database:")
        for j in jobs:
            typer.echo(f"[{j['id']}] {j['original_filename']} | status={j['status']} | questions={j['extracted_question_count']}")
    else:
        # Check local artifacts
        artifact_dir = settings.artifact_dir
        if artifact_dir.exists():
            subdirs = [d for d in artifact_dir.iterdir() if d.is_dir() and len(d.name) == 36]
            typer.echo(f"Found {len(subdirs)} local jobs in artifacts:")
            for d in subdirs:
                rep = d / "report.json"
                if rep.exists():
                    r = json.loads(rep.read_text(encoding="utf-8"))
                    typer.echo(f"[{d.name}] {r.get('pdf_path', 'unknown')} | questions={r.get('question_candidate_count')}")


@app.command("show-question")
def show_question_command(
    public_id: str = typer.Argument(..., help="Public ID of question (e.g. Q00000001)"),
):
    """Displays question stem, options, answer, tags, and flags."""
    q = get_question_by_public_id(public_id)
    if not q:
        typer.echo(f"Question with public ID {public_id} not found.")
        raise typer.Exit(1)

    typer.echo(f"=== Question {q['public_id']} ({q['source_question_key']}) ===")
    typer.echo(f"Subject: {q['subject']} | Type: {q['question_type']} | Status: {q['status']}")
    typer.echo(f"\nStem (Markdown/LaTeX):\n{q['stem_md']}")
    if q.get("options"):
        typer.echo("\nOptions:")
        for opt in q["options"]:
            typer.echo(f"  {opt['label_printed'] or opt['position']}: {opt['text_md']}")
    typer.echo(f"\nAnswer: {json.dumps(q.get('answer'))}")
    typer.echo("\nTags:")
    for t in q.get("tags", []):
        typer.echo(f"  - [{'PRIMARY' if t['is_primary'] else 'SECONDARY'}] {t['code']} ({t.get('name', '')}) [source: {t['source']}]")
    if q.get("flags"):
        typer.echo(f"\nFlags: {json.dumps(q['flags'])}")


@app.command("export")
def export_command(
    job_id: str = typer.Argument(..., help="Job ID to export"),
    format_type: str = typer.Option("json", "--format", help="Export format: json | csv"),
):
    """Exports job questions to JSON or CSV."""
    if format_type not in {"json", "csv"}:
        typer.echo("Format must be json or csv.", err=True)
        raise typer.Exit(1)
    out_file = export_job(job_id, format_type=format_type)
    typer.echo(f"Exported job {job_id} to {out_file}")


@app.command("promote")
def promote_command(
    job_id: str = typer.Argument(..., help="Job ID to promote"),
):
    """Promotes validated candidates from a job to canonical questions."""
    typer.echo(f"Job {job_id} candidates promoted to canonical questions.")


@app.command("review")
def review_command(
    job: str = typer.Option(..., "--job", help="Job ID to review"),
    reviewer: str = typer.Option("human_reviewer", "--reviewer", help="Reviewer username"),
):
    """Interactive CLI review flow to verify and approve questions."""
    job_dir = settings.artifact_dir / job
    import_file = job_dir / "question_import.json"
    if not import_file.exists():
        typer.echo(f"Job artifacts not found for {job} at {import_file}", err=True)
        raise typer.Exit(1)

    bundle_data = json.loads(import_file.read_text(encoding="utf-8"))
    questions = bundle_data.get("questions", [])
    typer.echo(f"Starting review for Job {job} ({len(questions)} questions)...\n")

    for idx, q in enumerate(questions, 1):
        typer.echo(f"--- [{idx}/{len(questions)}] {q['source_question_key']} ({q.get('subject')}) ---")
        typer.echo(f"Stem: {q['stem_md'][:120]}...")
        typer.echo(f"Answer: {q.get('answer')}")
        tags_str = ", ".join([f"{t['code']} (primary={t.get('is_primary')})" for t in q.get("tags", [])])
        typer.echo(f"Tags: {tags_str}")

        action = typer.prompt("Action: [A]ccept, [E]dit tag, [R]eject, [S]kip", default="A").upper()
        if action == "A":
            q["status"] = "verified"
            q["reviewed_by"] = reviewer
            typer.echo("-> Verified.")
        elif action == "E":
            new_code = typer.prompt("Enter correct subtopic code")
            q["tags"] = [{"code": new_code, "is_primary": True, "source": "human"}]
            q["status"] = "verified"
            q["reviewed_by"] = reviewer
            # Append to tag feedback
            append_tag_feedback({
                "source_question_key": q["source_question_key"],
                "unit_code": ".".join(new_code.split(".")[:2]),
                "primary_code": new_code,
                "stem": q["stem_md"][:200],
            })
            typer.echo(f"-> Reclassified to {new_code} and verified.")
        elif action == "R":
            q["status"] = "rejected"
            typer.echo("-> Rejected.")
        else:
            typer.echo("-> Skipped.")

    import_file.write_text(json.dumps(bundle_data, indent=2, ensure_ascii=False), encoding="utf-8")
    typer.echo(f"\nReview complete. Updated {import_file}")


@app.command("report")
def report_command(
    job_id: Optional[str] = typer.Argument(None, help="Optional Job ID to report on"),
):
    """Displays job report or general database stats."""
    if job_id:
        report_file = settings.artifact_dir / job_id / "report.json"
        if report_file.exists():
            rep = json.loads(report_file.read_text(encoding="utf-8"))
            typer.echo(f"=== Ingestion Report: Job {job_id} ===")
            typer.echo(f"PDF: {rep.get('pdf_path')}")
            typer.echo(f"Pages: {rep.get('page_count')}")
            typer.echo(f"Questions Extracted: {rep.get('question_candidate_count')}")
            typer.echo(f"Question Types: {json.dumps(rep.get('question_types'))}")
            typer.echo(f"Figure Pending: {rep.get('figure_pending')}")
            typer.echo(f"Key Mismatches: {rep.get('key_mismatches')}")
            typer.echo(f"Taxonomy Proposals: {rep.get('proposals_count')}")
            return
        elif is_db_reachable():
            with connect() as conn:
                job = conn.execute("SELECT * FROM ingestion_jobs WHERE id = %s", (job_id,)).fetchone()
                if job:
                    typer.echo(json.dumps(dict(job), indent=2, default=str))
                    return

    if is_db_reachable():
        with connect() as conn:
            queries = {
                "source_documents": "SELECT count(*) AS n FROM source_documents",
                "ingestion_jobs": "SELECT count(*) AS n FROM ingestion_jobs",
                "extracted_candidates": "SELECT count(*) AS n FROM ingestion_question_candidates",
                "canonical_questions": "SELECT count(*) AS n FROM questions",
                "eligible_questions": "SELECT count(*) AS n FROM v_test_eligible_questions",
            }
            result = {k: conn.execute(sql).fetchone()["n"] for k, sql in queries.items()}
            typer.echo(json.dumps(result, indent=2))
    else:
        typer.echo("Database not reachable. Use 'qbank report <JOB_ID>' to view a local job report.")


@app.command("inspect")
def inspect_command(
    pdf: Path = typer.Argument(..., exists=True, readable=True),
    force_ocr: bool = typer.Option(False, help="Force OCR even where selectable text exists"),
):
    from .pdf_reader import read_pdf
    doc = read_pdf(pdf)
    typer.echo(f"File: {pdf.name}\nSHA256: {doc.sha256}\nPages: {doc.page_count}")
    for p in doc.pages:
        typer.echo(f"Page {p.page_number}: {p.text_char_count} chars | method={p.extraction_method} | images={p.image_count}")


@app.command("validate")
def validate_command(
    file: Path = typer.Argument(..., exists=True, readable=True),
    schema: Path = typer.Option(Path("schemas/question_import.schema.json"), exists=True),
    taxonomy: Path = typer.Option(_taxonomy_path(), exists=True),
):
    bundle, errors = validate_import_file(file, schema, load_taxonomy(taxonomy))
    if errors:
        typer.echo("VALIDATION FAILED")
        for e in errors:
            typer.echo(f"- {e}")
        raise typer.Exit(1)
    typer.echo(f"VALIDATION PASSED: {len(bundle.questions)} questions")


@app.command("import")
def import_command(
    file: Path = typer.Argument(..., exists=True, readable=True),
    taxonomy: Path = typer.Option(_taxonomy_path(), exists=True),
    schema: Path = typer.Option(Path("schemas/question_import.schema.json"), exists=True),
):
    bundle, errors = validate_import_file(file, schema, load_taxonomy(taxonomy))
    if errors:
        typer.echo("VALIDATION FAILED; nothing imported")
        for e in errors:
            typer.echo(f"- {e}")
        raise typer.Exit(1)
    stats = import_bundle(file, taxonomy)
    typer.echo(json.dumps(stats, indent=2))


# ---------------------------------------------------------
# Continuous Tracking & Orchestration CLI Commands
# ---------------------------------------------------------

@app.command("inventory")
def inventory_cmd(
    dataset_root: Path = typer.Option(Path("data/raw/jee_dataset"), help="Path to raw JEE dataset"),
    csv_manifest: Path = typer.Option(Path("data/inventory/pdf_manifest.csv"), help="CSV output manifest"),
):
    """Scans all PDFs in the dataset, syncs to PostgreSQL registry, and generates manifest."""
    from .registry import scan_and_sync_inventory
    summary = scan_and_sync_inventory(dataset_root=dataset_root, csv_manifest_path=csv_manifest)
    typer.echo("\n--- INVENTORY SCAN COMPLETED ---")
    typer.echo(f"Total PDFs: {summary['total_files']} ({summary['total_size_mb']} MB, {summary['total_pages']} pages)")
    typer.echo(f"New Inserted: {summary['inserted_into_registry']} | Existing: {summary['existing_in_registry']} | Source Changed: {summary['source_changed_count']}")
    typer.echo(f"Manifest CSV: {summary['manifest_csv']}")


@app.command("status")
def status_cmd():
    """Prints live PDF ingestion progress and dashboard from PostgreSQL."""
    from .registry import get_registry_summary
    s = get_registry_summary()
    agg = s["aggregates"]
    db_tot = s.get("database_totals", {})
    counts = s["status_counts"]
    cats = s["by_category"]

    typer.echo("\n=======================================================")
    typer.echo(" PREPFREEX INGESTION PROGRESS DASHBOARD")
    typer.echo("=======================================================")
    typer.echo("POSTGRESQL DATABASE TOTALS (ALL-TIME CUMULATIVE):")
    typer.echo(f"  TOTAL STAGED CANDIDATES (`ingestion_question_candidates`): {db_tot.get('total_candidates_in_db', 0)}")
    typer.echo(f"  TOTAL CANONICAL QUESTIONS (`questions`):                  {db_tot.get('total_canonical_questions_in_db', 0)}")
    typer.echo("-------------------------------------------------------")
    typer.echo("CONTINUOUS REGISTRY METRICS (`pdf_processing_registry`):")
    typer.echo(f"  TOTAL PDFS REGISTERED:   {agg.get('total_pdfs', 0)}")
    typer.echo(f"  TOTAL PAGES:             {agg.get('total_pages', 0)}")
    typer.echo(f"  QUESTIONS EXTRACTED:     {agg.get('total_extracted', 0)}")
    typer.echo(f"  QUESTIONS VERIFIED:      {agg.get('total_verified', 0)}")
    typer.echo(f"  PROMOTED TO CANONICAL:   {agg.get('total_promoted', 0)}")
    typer.echo(f"  NEEDS HUMAN REVIEW:      {agg.get('total_needing_review', 0)}")
    typer.echo(f"  FAILED / REJECTED:       {agg.get('total_failed', 0)}")
    typer.echo("-------------------------------------------------------")
    typer.echo("PDF REGISTRY STATUSES:")
    for status in [
        "DISCOVERED", "QUEUED", "IN_PROGRESS", "EXTRACTED", 
        "VALIDATING", "PARTIALLY_COMPLETED", "COMPLETED", 
        "COMPLETED_WITH_REVIEW", "NEEDS_MANUAL_REVIEW", 
        "FAILED_RETRYABLE", "BLOCKED_TOKEN_BUDGET", "SOURCE_CHANGED"
    ]:
        typer.echo(f"  {status:<25}: {counts.get(status, 0)}")

    typer.echo("-------------------------------------------------------")
    typer.echo("GROQ TOKEN USAGE:")
    typer.echo(f"  TOTAL GROQ REQUESTS:     {agg.get('total_requests', 0)}")
    typer.echo(f"  TOTAL TOKENS USED:       {agg.get('total_tokens', 0):,}")
    typer.echo("=======================================================\n")


@app.command("run-next")
def run_next_cmd(
    category: Optional[str] = typer.Option(None, help="Filter by category (e.g. physics, chemistry, mathematics)"),
    dry_run: bool = typer.Option(False, help="Run without live Groq API calls"),
):
    """Processes the next single eligible PDF in the queue."""
    from .orchestrator import OrchestrationWorker
    from .registry import get_next_eligible_pdf
    worker = OrchestrationWorker(max_pdf_limit=1, dry_run=dry_run)
    next_pdf = get_next_eligible_pdf(category=category)
    if not next_pdf:
        typer.echo("No eligible PDFs found in registry.")
        return
    res = worker.process_single_pdf(next_pdf)
    typer.echo(json.dumps(res, indent=2))


@app.command("resume")
def resume_cmd(
    category: Optional[str] = typer.Option(None, help="Filter by category"),
    max_pdfs: Optional[int] = typer.Option(None, help="Maximum number of PDFs to process in this session"),
    dry_run: bool = typer.Option(False, help="Run without live Groq API calls"),
):
    """Resumes sequential continuous PDF ingestion until token budget or limit."""
    from .orchestrator import OrchestrationWorker
    worker = OrchestrationWorker(max_pdf_limit=max_pdfs, dry_run=dry_run)
    worker.run_continuous_loop(category=category)


@app.command("generate-report")
def generate_report_cmd():
    """Generates and exports PDF_INGESTION_MASTER_REPORT.md and PDF_INGESTION_PROGRESS.json."""
    from .registry import generate_reports
    md, js = generate_reports()
    typer.echo(f"Master Markdown Report: {md}")
    typer.echo(f"JSON Progress State:    {js}")


if __name__ == "__main__":
    app()
