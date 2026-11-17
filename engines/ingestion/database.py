from __future__ import annotations

import csv
import io
import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import settings


def connect(database_url: str | None = None):
    url = database_url or settings.database_url
    if not url:
        raise RuntimeError("DATABASE_URL is empty. Copy .env.example to .env and configure it.")
    import psycopg
    from psycopg.rows import dict_row
    return psycopg.connect(url, row_factory=dict_row)


def is_db_reachable(database_url: str | None = None) -> bool:
    try:
        url = database_url or settings.database_url
        if not url:
            return False
        import psycopg
        with psycopg.connect(url, connect_timeout=2) as conn:
            conn.execute("SELECT 1")
            return True
    except Exception:
        return False


def check_db(database_url: str | None = None) -> dict[str, Any]:
    """Connects to database, prints server version, checks pgcrypto/pg_trgm, verifies privileges."""
    url = database_url or settings.database_url
    if not url:
        raise RuntimeError("DATABASE_URL is not set. Check .env configuration.")

    try:
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(url, connect_timeout=3, row_factory=dict_row) as conn:
            row = conn.execute("SHOW server_version;").fetchone()
            server_version = row["server_version"] if row else "unknown"

            # Check available extensions
            exts = conn.execute(
                "SELECT name FROM pg_available_extensions WHERE name IN ('pgcrypto', 'pg_trgm')"
            ).fetchall()
            available = {r["name"] for r in exts}

            # Check installed extensions
            installed_exts = conn.execute(
                "SELECT extname FROM pg_extension WHERE extname IN ('pgcrypto', 'pg_trgm')"
            ).fetchall()
            installed = {r["extname"] for r in installed_exts}

            # Check table creation privilege
            table_creation_ok = False
            try:
                conn.execute("CREATE TEMP TABLE _prepfreex_priv_check (id int);")
                conn.execute("DROP TABLE _prepfreex_priv_check;")
                table_creation_ok = True
            except Exception:
                table_creation_ok = False

            return {
                "status": "connected",
                "server_version": server_version,
                "pgcrypto_available": "pgcrypto" in available or "pgcrypto" in installed,
                "pg_trgm_available": "pg_trgm" in available or "pg_trgm" in installed,
                "pgcrypto_installed": "pgcrypto" in installed,
                "pg_trgm_installed": "pg_trgm" in installed,
                "table_creation_ok": table_creation_ok,
            }
    except Exception as exc:
        err = str(exc).lower()
        if "password authentication failed" in err:
            raise RuntimeError(f"Wrong password: Authentication failed for user. Check POSTGRES_PASSWORD in .env.") from exc
        if "does not exist" in err and "database" in err:
            raise RuntimeError(f"Database missing: The target database does not exist. Check POSTGRES_DB in .env.") from exc
        if "refused" in err or "10061" in err or "could not connect" in err:
            raise RuntimeError(
                f"Connection refused: Could not connect to PostgreSQL at {settings.postgres_host}:{settings.postgres_port}. "
                "Ensure native PostgreSQL service is running and listening on port 5432."
            ) from exc

        raise RuntimeError(f"Database connection error: {exc}") from exc


def docker_db_up() -> bool:
    """Runs docker compose up -d and waits for healthcheck."""
    subprocess.run(["docker", "compose", "up", "-d"], check=True)
    print("Waiting for database healthcheck...")
    for _ in range(30):
        try:
            res = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Health.Status}}", "prepfreex-postgres"],
                capture_output=True, text=True
            )
            if res.stdout.strip() == "healthy":
                print("Database container is healthy.")
                return True
        except Exception:
            pass
        time.sleep(1)
    print("Database container started (healthcheck wait timed out).")
    return True


def docker_db_down() -> bool:
    """Stops the container, keeping volume data."""
    subprocess.run(["docker", "compose", "stop"], check=True)
    print("Database container stopped (data volume preserved).")
    return True


def docker_db_reset(confirm: bool = False) -> bool:
    """Stops and deletes the volume."""
    if not confirm:
        ans = input("Are you sure you want to delete all database data? [y/N]: ").strip().lower()
        if ans not in {"y", "yes"}:
            print("Reset aborted.")
            return False
    subprocess.run(["docker", "compose", "down", "-v"], check=True)
    print("Database reset: container stopped and data volume deleted.")
    return True


def docker_db_backup(output_file: Path | None = None) -> Path:
    """Runs pg_dump inside container to backups/YYYYMMDD_HHMM.sql."""
    backup_dir = Path("backups")
    backup_dir.mkdir(parents=True, exist_ok=True)
    out = output_file or (backup_dir / f"{datetime.now().strftime('%Y%m%d_%H%M')}.sql")

    user = settings.postgres_user or "prepfreex"
    db = settings.postgres_db or "prepfreex_qbank"

    with out.open("w", encoding="utf-8") as f:
        subprocess.run(
            ["docker", "exec", "-t", "prepfreex-postgres", "pg_dump", "-U", user, "-d", db],
            stdout=f, check=True
        )
    print(f"Backup created at {out}")
    return out


def docker_db_restore(input_file: Path) -> bool:
    """Restores database from backup file."""
    if not input_file.exists():
        raise FileNotFoundError(f"Backup file not found: {input_file}")

    user = settings.postgres_user or "prepfreex"
    db = settings.postgres_db or "prepfreex_qbank"

    with input_file.open("r", encoding="utf-8") as f:
        subprocess.run(
            ["docker", "exec", "-i", "prepfreex-postgres", "psql", "-U", user, "-d", db],
            stdin=f, check=True
        )
    print(f"Restored database from {input_file}")
    return True


def docker_db_shell():
    """Opens interactive psql inside container."""
    user = settings.postgres_user or "prepfreex"
    db = settings.postgres_db or "prepfreex_qbank"
    subprocess.run(["docker", "exec", "-it", "prepfreex-postgres", "psql", "-U", user, "-d", db])


def run_migrations(migrations_dir: Path, database_url: str | None = None) -> list[str]:
    applied: list[str] = []
    with connect(database_url) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version text PRIMARY KEY,
                filename text NOT NULL,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
        """)
        conn.commit()
        for path in sorted(migrations_dir.glob("*.sql")):
            with conn.transaction():
                exists = conn.execute(
                    "SELECT 1 FROM schema_migrations WHERE version = %s",
                    (path.stem.split("_")[0],)
                ).fetchone()
                if exists:
                    continue
                sql = path.read_text(encoding="utf-8")
                conn.execute(sql)
                conn.execute(
                    "INSERT INTO schema_migrations(version, filename) VALUES (%s, %s)",
                    (path.stem.split("_")[0], path.name)
                )
                applied.append(path.name)
    return applied


def seed_taxonomy(seed_path: Path, database_url: str | None = None) -> int:
    raw = json.loads(seed_path.read_text(encoding="utf-8"))
    version = raw["taxonomy_version"]
    nodes = raw["nodes"]
    with connect(database_url) as conn:
        code_to_id: dict[str, int] = {}
        pending = list(nodes)
        while pending:
            progress = False
            for node in pending[:]:
                parent_code = node.get("parent_code")
                if parent_code and parent_code not in code_to_id:
                    row = conn.execute(
                        "SELECT id FROM taxonomy WHERE taxonomy_version=%s AND code=%s",
                        (version, parent_code)
                    ).fetchone()
                    if not row:
                        continue
                    code_to_id[parent_code] = row["id"]
                parent_id = code_to_id.get(parent_code) if parent_code else None

                # Support v2 columns: description, example_stems, replaced_by
                desc = node.get("description")
                stems = node.get("example_stems") or []
                is_act = node.get("is_active", True)

                row = conn.execute(
                    """INSERT INTO taxonomy
                       (taxonomy_version, code, parent_id, level, name, syllabus_text, sort_order, is_reviewed, is_active, description, example_stems)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (taxonomy_version, code) DO UPDATE SET
                         parent_id=EXCLUDED.parent_id,
                         level=EXCLUDED.level,
                         name=EXCLUDED.name,
                         syllabus_text=EXCLUDED.syllabus_text,
                         sort_order=EXCLUDED.sort_order,
                         is_reviewed=taxonomy.is_reviewed,
                         is_active=EXCLUDED.is_active,
                         description=EXCLUDED.description,
                         example_stems=EXCLUDED.example_stems
                       RETURNING id""",
                    (version, node["code"], parent_id, node["level"], node["name"],
                     node.get("syllabus_text"), node.get("sort_order"), node.get("is_reviewed", False),
                     is_act, desc, stems)
                ).fetchone()
                code_to_id[node["code"]] = row["id"]
                pending.remove(node)
                progress = True
            if not progress:
                missing = [n["code"] for n in pending]
                raise RuntimeError(f"Taxonomy parent dependency unresolved: {missing}")
        conn.commit()
    return len(nodes)


def list_proposals(status: str = "open", database_url: str | None = None) -> list[dict[str, Any]]:
    with connect(database_url) as conn:
        rows = conn.execute(
            "SELECT * FROM taxonomy_proposals WHERE status = %s ORDER BY created_at DESC",
            (status,)
        ).fetchall()
        return [dict(r) for r in rows]


def accept_proposal(proposal_id: int, new_name: str, database_url: str | None = None) -> dict[str, Any]:
    with connect(database_url) as conn:
        with conn.transaction():
            prop = conn.execute("SELECT * FROM taxonomy_proposals WHERE id = %s", (proposal_id,)).fetchone()
            if not prop:
                raise ValueError(f"Proposal {proposal_id} not found.")

            parent_code = prop["parent_code"]
            parent_row = conn.execute("SELECT * FROM taxonomy WHERE code = %s", (parent_code,)).fetchone()
            if not parent_row:
                raise ValueError(f"Parent code {parent_code} not found in taxonomy.")

            # Assign fresh code
            existing = conn.execute(
                "SELECT code FROM taxonomy WHERE parent_id = %s", (parent_row["id"],)
            ).fetchall()
            nums = [int(r["code"].split(".")[-1][1:]) for r in existing if "." in r["code"]]
            next_num = (max(nums) + 1) if nums else 1
            new_code = f"{parent_code}.S{next_num:02d}"

            # Insert new subtopic
            new_tax = conn.execute(
                """INSERT INTO taxonomy
                   (taxonomy_version, code, parent_id, level, name, syllabus_text, sort_order, is_reviewed, is_active)
                   VALUES (%s, %s, %s, 'subtopic', %s, %s, %s, true, true)
                   RETURNING id""",
                (prop["taxonomy_version"], new_code, parent_row["id"], new_name, new_name, next_num)
            ).fetchone()

            # Update proposal status
            conn.execute(
                "UPDATE taxonomy_proposals SET status = 'accepted' WHERE id = %s", (proposal_id,)
            )

            # Re-tag waiting questions
            example_keys = prop.get("example_question_keys") or []
            retagged_count = 0
            if example_keys:
                for q_key in example_keys:
                    q_row = conn.execute(
                        "SELECT id FROM questions WHERE source_question_key = %s", (q_key,)
                    ).fetchone()
                    if q_row:
                        # Replace primary tag with new subtopic
                        conn.execute(
                            "UPDATE question_tags SET taxonomy_id = %s WHERE question_id = %s AND is_primary = true",
                            (new_tax["id"], q_row["id"])
                        )
                        # Clear needs_subtopic flag
                        conn.execute(
                            "UPDATE questions SET flags = flags - 'needs_subtopic' WHERE id = %s",
                            (q_row["id"],)
                        )
                        retagged_count += 1

            return {
                "new_code": new_code,
                "new_name": new_name,
                "retagged_questions": retagged_count,
            }


def import_bundle(bundle_path: Path, taxonomy_path: Path, database_url: str | None = None) -> dict[str, int]:
    from .models import ImportBundle
    from .validators import _content_hash
    from .taxonomy import load_taxonomy
    from .pdf_reader import sha256_file
    from psycopg.types.json import Jsonb

    bundle = ImportBundle.model_validate_json(bundle_path.read_text(encoding="utf-8"))
    taxonomy = load_taxonomy(taxonomy_path)
    taxonomy_version = json.loads(taxonomy_path.read_text(encoding="utf-8"))["taxonomy_version"]
    source = bundle.source_document
    source_path = Path(source.file)
    if not source_path.exists():
        raise FileNotFoundError(source.file)
    digest = sha256_file(source_path)
    stats = {"inserted": 0, "updated": 0, "unchanged": 0, "failed": 0, "candidates_staged": 0}

    content_columns = [
        "source_q_label", "source_question_key", "source_part", "source_section",
        "source_local_number", "source_global_number", "source_page_start", "source_page_end",
        "figure_source_page", "origin", "exam_name", "exam_year", "exam_date", "exam_shift",
        "subject", "question_type", "language", "stem_md", "stem_plain", "answer",
        "explanation_md", "explanation_source", "source_explanation_md", "answer_key_verified",
        "explanation_verified", "answer_verification_notes", "explanation_verification_notes",
        "difficulty", "difficulty_source", "cognitive_level", "estimated_time_sec",
        "formulas_used", "keywords", "common_mistakes", "has_figure", "figure_status",
        "figure_description", "status", "extraction_method", "extraction_confidence", "flags",
    ]

    with connect(database_url) as conn:
        with conn.transaction():
            src = conn.execute(
                """INSERT INTO source_documents
                   (sha256,title,publisher,exam,exam_year,file_path,license_status)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (sha256) DO UPDATE SET
                     title=EXCLUDED.title,
                     publisher=COALESCE(source_documents.publisher,EXCLUDED.publisher),
                     exam=COALESCE(source_documents.exam,EXCLUDED.exam),
                     exam_year=COALESCE(source_documents.exam_year,EXCLUDED.exam_year),
                     file_path=EXCLUDED.file_path
                   RETURNING id""",
                (digest, source.title, source.publisher, source.exam, source.exam_year,
                 str(source_path.resolve()), source.license_status)
            ).fetchone()
            source_id = src["id"]

            tag_ids: dict[str, int] = {}
            for code in {t.code for q in bundle.questions for t in q.tags}:
                if code not in taxonomy:
                    continue
                row = conn.execute(
                    "SELECT id FROM taxonomy WHERE taxonomy_version=%s AND code=%s",
                    (taxonomy_version, code)
                ).fetchone()
                if row:
                    tag_ids[code] = row["id"]

            for q in bundle.questions:
                content_hash = _content_hash(q)
                current = conn.execute(
                    "SELECT * FROM questions WHERE source_doc_id=%s AND source_question_key=%s",
                    (source_id, q.source_question_key)
                ).fetchone()
                new_question = q.model_dump(mode="python")
                new_question["answer"] = q.answer
                new_options = [o.model_dump(mode="python") for o in q.options]
                new_tags = [t.model_dump(mode="python") for t in q.tags]

                # Strict canonical promotion eligibility checks
                promotable = True
                if not q.stem_md or len(q.stem_md.strip()) < 25 or q.flags.get("dropped_formula"):
                    promotable = False

                if not q.subject or q.subject not in {"mathematics", "physics", "chemistry"} or q.flags.get("ambiguous_subject"):
                    promotable = False

                if q.has_figure or q.figure_status != "none" or q.flags.get("figure_required"):
                    promotable = False

                if not q.answer or not q.answer_key_verified or q.flags.get("key_mismatch") or q.flags.get("answer_type_mismatch"):
                    promotable = False

                if q.question_type == "mcq_single":
                    if len(q.options) != 4 or any(len(o.text_md.strip()) == 0 for o in q.options) or q.flags.get("incomplete_options"):
                        promotable = False
                    elif not q.answer.get("positions") or any(p not in {1, 2, 3, 4} for p in q.answer.get("positions", [])):
                        promotable = False
                elif q.question_type == "numerical":
                    if q.options:
                        promotable = False
                    if not isinstance(q.answer.get("value"), (int, float)) or isinstance(q.answer.get("value"), bool):
                        promotable = False
                else:
                    promotable = False

                subj_prefix = {"mathematics": "MAT.", "physics": "PHY.", "chemistry": "CHE."}.get(str(q.subject).lower(), "")
                primary_tags = [t for t in q.tags if t.is_primary and t.code in tag_ids and t.code.startswith(subj_prefix)]
                if len(primary_tags) != 1:
                    promotable = False

                if q.flags.get("validation_errors"):
                    promotable = False

                if not promotable:
                    stats["candidates_staged"] += 1
                    continue

                # Global content hash deduplication
                if not current:
                    existing_hash = conn.execute(
                        "SELECT id FROM questions WHERE content_hash = %s",
                        (content_hash,)
                    ).fetchone()
                    if existing_hash:
                        stats["unchanged"] += 1
                        continue

                if current:
                    old_options = conn.execute(
                        "SELECT position,label_printed,text_md FROM question_options WHERE question_id=%s ORDER BY position",
                        (current["id"],)
                    ).fetchall()
                    old_tags = conn.execute(
                        """SELECT t.code,qt.is_primary,qt.source,qt.confidence
                           FROM question_tags qt JOIN taxonomy t ON t.id=qt.taxonomy_id
                           WHERE qt.question_id=%s ORDER BY t.code""",
                        (current["id"],)
                    ).fetchall()
                    old_match_items = conn.execute(
                        "SELECT side,item_key,position,text_md FROM question_match_items WHERE question_id=%s ORDER BY side,position",
                        (current["id"],)
                    ).fetchall()
                    old_question = {k: current.get(k) for k in content_columns}
                    old_comparable = {
                        "question": old_question,
                        "options": [dict(x) for x in old_options],
                        "tags": sorted([dict(x) for x in old_tags], key=lambda x: x["code"]),
                        "match_items": [dict(x) for x in old_match_items],
                    }
                    new_comparable = {
                        "question": {k: new_question.get(k) for k in content_columns},
                        "options": new_options,
                        "tags": sorted(new_tags, key=lambda x: x["code"]),
                        "match_items": [m.model_dump(mode="python") for m in q.match_items],
                    }
                    old_json = json.dumps(old_comparable, ensure_ascii=False, sort_keys=True, default=str)
                    new_json = json.dumps(new_comparable, ensure_ascii=False, sort_keys=True, default=str)
                    if old_json == new_json and current["content_hash"] == content_hash:
                        stats["unchanged"] += 1
                        continue

                    previous_version = current["version"]
                    full_snapshot = {
                        "question": dict(current),
                        "options": [dict(x) for x in old_options],
                        "tags": [dict(x) for x in old_tags],
                        "match_items": [dict(x) for x in old_match_items],
                    }
                    conn.execute(
                        "INSERT INTO question_revisions(question_id,version,snapshot,changed_by,reason) VALUES(%s,%s,%s,%s,%s)",
                        (current["id"], previous_version, Jsonb(json.loads(json.dumps(full_snapshot, ensure_ascii=False, default=str))), "importer", "Changed by re-import")
                    )
                    question_id = current["id"]
                    conn.execute("DELETE FROM question_options WHERE question_id=%s", (question_id,))
                    conn.execute("DELETE FROM question_tags WHERE question_id=%s", (question_id,))
                    conn.execute("DELETE FROM question_match_items WHERE question_id=%s", (question_id,))
                    assignments = ",".join(f"{col}=%s" for col in content_columns)
                    values = []
                    for col in content_columns:
                        val = new_question.get(col)
                        if col in {"answer", "flags"}:
                            val = Jsonb(val) if val is not None else None
                        values.append(val)
                    values.extend([content_hash, question_id])
                    conn.execute(
                        f"UPDATE questions SET version=version+1,{assignments},content_hash=%s,updated_at=now() WHERE id=%s",
                        values
                    )
                    stats["updated"] += 1
                else:
                    columns = ["source_doc_id"] + content_columns + ["content_hash"]
                    vals = [source_id]
                    for col in content_columns:
                        val = new_question.get(col)
                        if col in {"answer", "flags"}:
                            val = Jsonb(val) if val is not None else None
                        vals.append(val)
                    vals.append(content_hash)
                    placeholders = ",".join(["%s"] * len(columns))
                    inserted = conn.execute(
                        f"INSERT INTO questions({','.join(columns)}) VALUES({placeholders}) RETURNING id",
                        vals
                    ).fetchone()
                    question_id = inserted["id"]
                    stats["inserted"] += 1

                for option in q.options:
                    conn.execute(
                        "INSERT INTO question_options(question_id,position,label_printed,text_md) VALUES(%s,%s,%s,%s)",
                        (question_id, option.position, option.label_printed, option.text_md)
                    )
                for tag in q.tags:
                    if tag.code in tag_ids:
                        conn.execute(
                            "INSERT INTO question_tags(question_id,taxonomy_id,is_primary,confidence,source) VALUES(%s,%s,%s,%s,%s)",
                            (question_id, tag_ids[tag.code], tag.is_primary, tag.confidence, tag.source)
                        )
                for item in q.match_items:
                    conn.execute(
                        "INSERT INTO question_match_items(question_id,side,item_key,position,text_md) VALUES(%s,%s,%s,%s,%s)",
                        (question_id, item.side, item.item_key, item.position, item.text_md)
                    )
                conn.execute(
                    """INSERT INTO question_sources
                       (question_id,source_doc_id,source_q_label,source_page_start,source_page_end,relationship)
                       VALUES (%s,%s,%s,%s,%s,'origin')
                       ON CONFLICT DO NOTHING""",
                    (question_id, source_id, q.source_q_label, q.source_page_start, q.source_page_end)
                )
    return stats


def get_question_by_public_id(public_id: str, database_url: str | None = None) -> dict[str, Any] | None:
    with connect(database_url) as conn:
        q = conn.execute("SELECT * FROM questions WHERE public_id = %s", (public_id,)).fetchone()
        if not q:
            return None
        res = dict(q)
        options = conn.execute(
            "SELECT position, label_printed, text_md FROM question_options WHERE question_id = %s ORDER BY position",
            (res["id"],)
        ).fetchall()
        tags = conn.execute(
            """SELECT t.code, t.name, qt.is_primary, qt.confidence, qt.source
               FROM question_tags qt JOIN taxonomy t ON t.id = qt.taxonomy_id
               WHERE qt.question_id = %s ORDER BY qt.is_primary DESC""",
            (res["id"],)
        ).fetchall()
        res["options"] = [dict(o) for o in options]
        res["tags"] = [dict(t) for t in tags]
        return res


def list_jobs(database_url: str | None = None) -> list[dict[str, Any]]:
    with connect(database_url) as conn:
        rows = conn.execute("SELECT * FROM ingestion_jobs ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


def export_job(job_id: str, format_type: str = "json", output_dir: Path | None = None, database_url: str | None = None) -> Path:
    out_dir = output_dir or Path("data/jobs") / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"export.{format_type}"

    questions: list[dict[str, Any]] = []
    # If file exists locally under artifacts/<job_id>/question_import.json, load it
    local_import = out_dir / "question_import.json"
    if local_import.exists():
        data = json.loads(local_import.read_text(encoding="utf-8"))
        questions = data.get("questions", [])

    if format_type == "csv":
        with out_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["source_question_key", "subject", "question_type", "stem_md", "answer", "status"])
            for q in questions:
                writer.writerow([
                    q.get("source_question_key"),
                    q.get("subject"),
                    q.get("question_type"),
                    q.get("stem_md"),
                    json.dumps(q.get("answer")),
                    q.get("status"),
                ])
    else:
        out_path.write_text(json.dumps(questions, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path


def record_ingestion_result(
    report: dict[str, Any],
    pdf_path: Path,
    database_url: str | None = None,
    doc: Any | None = None,
    classifications: list[dict[str, Any]] | None = None,
) -> str:
    """Persist extracted candidates, document pages, classification runs, and job details into PostgreSQL."""
    from psycopg.types.json import Jsonb
    from .models import ImportBundle
    from .pdf_reader import sha256_file

    job_id = report["job_id"]
    job_dir = Path(report["artifacts"]["job_dir"])
    bundle = ImportBundle.model_validate_json(Path(report["artifacts"]["question_import"]).read_text(encoding="utf-8"))
    source = bundle.source_document
    digest = sha256_file(pdf_path)

    with connect(database_url) as conn:
        with conn.transaction():
            src = conn.execute(
                """INSERT INTO source_documents
                   (sha256,title,publisher,exam,exam_year,file_path,license_status)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (sha256) DO UPDATE SET
                     title=EXCLUDED.title, publisher=COALESCE(source_documents.publisher,EXCLUDED.publisher),
                     exam=COALESCE(source_documents.exam,EXCLUDED.exam),
                     exam_year=COALESCE(source_documents.exam_year,EXCLUDED.exam_year),
                     file_path=EXCLUDED.file_path
                   RETURNING id""",
                (digest, source.title, source.publisher, source.exam, source.exam_year,
                 str(pdf_path.resolve()), source.license_status)
            ).fetchone()
            src_id = src["id"]

            conn.execute(
                """INSERT INTO ingestion_jobs
                   (id,source_doc_id,original_filename,sha256,status,document_type,page_count,
                    extracted_question_count,taxonomy_version,classifier_provider,started_at,completed_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),now())
                   ON CONFLICT (id) DO UPDATE SET
                     status=EXCLUDED.status,
                     extracted_question_count=EXCLUDED.extracted_question_count,
                     completed_at=now()""",
                (job_id, src_id, pdf_path.name, digest, "needs_review",
                 report.get("layout_profile", {}).get("doc_type", "auto"), report["page_count"],
                 report["question_candidate_count"], settings.taxonomy_version,
                 settings.llm_provider)
            )

            # Persist document pages
            if doc and hasattr(doc, "pages"):
                for p in doc.pages:
                    conn.execute(
                        """INSERT INTO document_pages
                           (ingestion_job_id, page_number, extracted_text, extraction_method,
                            text_char_count, image_count, has_drawings, rendered_image_path, processing_status)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT (ingestion_job_id, page_number) DO UPDATE SET
                             extracted_text=EXCLUDED.extracted_text,
                             text_char_count=EXCLUDED.text_char_count,
                             image_count=EXCLUDED.image_count,
                             has_drawings=EXCLUDED.has_drawings,
                             rendered_image_path=EXCLUDED.rendered_image_path,
                             processing_status=EXCLUDED.processing_status""",
                        (job_id, p.page_number, p.text, p.extraction_method or "pymupdf",
                         p.text_char_count, p.image_count, p.has_drawings,
                         str(getattr(p, "image_path", None) or getattr(p, "rendered_image_path", None) or ""), "extracted")
                    )

            # Persist question candidates
            for q in bundle.questions:
                conn.execute(
                    """INSERT INTO ingestion_question_candidates
                       (ingestion_job_id,source_question_key,source_q_label,source_part,source_section,
                        source_local_number,source_global_number,source_page_start,source_page_end,
                        subject_guess,question_type_guess,stem_md,options_json,answer_json,
                        classification_json,extraction_json,review_status)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'needs_review')
                       ON CONFLICT (ingestion_job_id,source_question_key) DO UPDATE SET
                         subject_guess=EXCLUDED.subject_guess,
                         question_type_guess=EXCLUDED.question_type_guess,
                         stem_md=EXCLUDED.stem_md,
                         options_json=EXCLUDED.options_json,
                         answer_json=EXCLUDED.answer_json,
                         updated_at=now()""",
                    (job_id, q.source_question_key, q.source_q_label, q.source_part, q.source_section,
                     q.source_local_number, q.source_global_number, q.source_page_start, q.source_page_end,
                     q.subject, q.question_type, q.stem_md,
                     Jsonb([o.model_dump(mode="json") for o in q.options]),
                     Jsonb(q.answer) if q.answer is not None else None,
                     Jsonb({"tags": [t.model_dump(mode="json") for t in q.tags]}),
                     Jsonb(q.model_dump(mode="json")))
                )

            # Persist classification runs
            if classifications:
                for c in classifications:
                    conn.execute(
                        """INSERT INTO classification_runs
                           (ingestion_job_id, source_question_key, taxonomy_version, provider, model, prompt_version, result_json)
                           VALUES (%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT (ingestion_job_id, source_question_key, taxonomy_version, prompt_version)
                           DO UPDATE SET result_json=EXCLUDED.result_json""",
                        (job_id, c["source_question_key"], settings.taxonomy_version,
                         c.get("provider", "rules"), c.get("model", "rules"),
                         c.get("prompt_version", "v1"), Jsonb(c.get("result", {})))
                    )
    return job_id
    return job_id


def retag_job_questions(job_id: str, taxonomy: dict[str, dict[str, Any]], database_url: str | None = None) -> int:
    """Re-tags existing questions in a job, keeping source='human' tags untouched."""
    from .classifier import SubtopicTagger
    tagger = SubtopicTagger(taxonomy)
    updated_count = 0

    with connect(database_url) as conn:
        with conn.transaction():
            rows = conn.execute(
                """SELECT q.id, q.stem_md, q.subject, q.source_question_key
                   FROM questions q
                   JOIN ingestion_jobs j ON j.source_doc_id = q.source_doc_id
                   WHERE j.id = %s""",
                (job_id,)
            ).fetchall()

            for r in rows:
                # Check if human tag exists
                human_tag = conn.execute(
                    "SELECT 1 FROM question_tags WHERE question_id = %s AND source = 'human'",
                    (r["id"],)
                ).fetchone()
                if human_tag:
                    continue

                cls = tagger.tag(r["stem_md"], subject=r["subject"], source_question_key=r["source_question_key"])
                if cls.primary_subtopic and cls.primary_subtopic in taxonomy:
                    tax_id = conn.execute("SELECT id FROM taxonomy WHERE code = %s", (cls.primary_subtopic,)).fetchone()
                    if tax_id:
                        conn.execute("DELETE FROM question_tags WHERE question_id = %s", (r["id"],))
                        conn.execute(
                            "INSERT INTO question_tags (question_id, taxonomy_id, is_primary, source, confidence) VALUES (%s, %s, true, 'llm', %s)",
                            (r["id"], tax_id["id"], cls.confidence)
                        )
                        updated_count += 1
    return updated_count
