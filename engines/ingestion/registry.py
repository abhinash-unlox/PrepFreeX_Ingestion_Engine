from __future__ import annotations

import csv
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
import psycopg
from psycopg.rows import dict_row

from engines.shared.config import settings

VALID_REGISTRY_STATUSES = {
    "DISCOVERED",
    "QUEUED",
    "IN_PROGRESS",
    "EXTRACTED",
    "VALIDATING",
    "PARTIALLY_COMPLETED",
    "COMPLETED",
    "COMPLETED_WITH_REVIEW",
    "NEEDS_MANUAL_REVIEW",
    "FAILED_RETRYABLE",
    "BLOCKED_TOKEN_BUDGET",
    "SOURCE_CHANGED",
}


def compute_sha256(file_path: Path, chunk_size: int = 65536) -> str:
    """Computes streaming SHA-256 for a file without loading all into memory."""
    hasher = hashlib.sha256()
    with file_path.open("rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()


def get_pdf_page_count(file_path: Path) -> int:
    """Reads PDF page count quickly using PyMuPDF."""
    try:
        with fitz.open(file_path) as doc:
            return doc.page_count
    except Exception:
        return 0


def scan_and_sync_inventory(
    dataset_root: Path = Path("data/raw/jee_dataset"),
    database_url: str | None = None,
    csv_manifest_path: Path = Path("data/inventory/pdf_manifest.csv"),
) -> dict[str, Any]:
    """Scans all PDFs in dataset_root, registers them into PostgreSQL, and exports the CSV manifest.
    
    Zero Groq calls are made during this inventory scan.
    """
    db_url = database_url or settings.database_url
    dataset_root = dataset_root.resolve()
    pdf_files = sorted(dataset_root.rglob("*.pdf"))

    print(f"Scanning {len(pdf_files)} PDF files in {dataset_root}...")

    scanned_items = []
    sha_map: dict[str, list[str]] = {}
    folder_counts: dict[str, int] = {}
    folder_bytes: dict[str, int] = {}
    total_bytes = 0
    total_pages = 0

    t0 = time.time()
    for pdf_path in pdf_files:
        rel = pdf_path.relative_to(dataset_root).as_posix()
        parts = rel.split("/")
        category = parts[0] if len(parts) > 1 else "root"
        folder_counts[category] = folder_counts.get(category, 0) + 1

        stat = pdf_path.stat()
        size_bytes = stat.st_size
        total_bytes += size_bytes
        folder_bytes[category] = folder_bytes.get(category, 0) + size_bytes

        sha = compute_sha256(pdf_path)
        sha_map.setdefault(sha, []).append(rel)

        p_count = get_pdf_page_count(pdf_path)
        total_pages += p_count

        scanned_items.append({
            "relative_path": rel,
            "filename": pdf_path.name,
            "category": category,
            "sha256": sha,
            "file_size_bytes": size_bytes,
            "page_count": p_count,
            "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
        })

    elapsed = time.time() - t0
    print(f"Scanned {len(scanned_items)} files ({total_bytes / (1024*1024):.2f} MB, {total_pages} pages) in {elapsed:.2f}s")

    # Duplicate detection (identical SHA-256)
    duplicate_groups = {sha: paths for sha, paths in sha_map.items() if len(paths) > 1}
    duplicate_files_count = sum(len(paths) - 1 for paths in duplicate_groups.values())

    # Sync into PostgreSQL pdf_processing_registry
    inserted_count = 0
    updated_count = 0
    source_changed_count = 0

    with psycopg.connect(db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            for item in scanned_items:
                cur.execute(
                    "SELECT id, sha256, processing_status FROM pdf_processing_registry WHERE relative_path = %s",
                    (item["relative_path"],)
                )
                existing = cur.fetchone()

                if existing is None:
                    # New PDF discovered
                    cur.execute(
                        """
                        INSERT INTO pdf_processing_registry (
                            relative_path, filename, category, sha256, 
                            file_size_bytes, page_count, processing_status
                        ) VALUES (%s, %s, %s, %s, %s, %s, 'DISCOVERED')
                        RETURNING id;
                        """,
                        (
                            item["relative_path"],
                            item["filename"],
                            item["category"],
                            item["sha256"],
                            item["file_size_bytes"],
                            item["page_count"],
                        )
                    )
                    new_id = cur.fetchone()["id"]
                    cur.execute(
                        """
                        INSERT INTO pdf_processing_events (pdf_id, event_type, message, details)
                        VALUES (%s, 'PDF_DISCOVERED', 'PDF initially discovered during dataset scan', %s);
                        """,
                        (new_id, json.dumps({"category": item["category"], "pages": item["page_count"]}))
                    )
                    inserted_count += 1
                else:
                    # Existing PDF: check if SHA-256 changed
                    if existing["sha256"] != item["sha256"]:
                        cur.execute(
                            """
                            UPDATE pdf_processing_registry SET
                                sha256 = %s,
                                file_size_bytes = %s,
                                page_count = %s,
                                processing_status = 'SOURCE_CHANGED',
                                updated_at = now()
                            WHERE id = %s;
                            """,
                            (item["sha256"], item["file_size_bytes"], item["page_count"], existing["id"])
                        )
                        cur.execute(
                            """
                            INSERT INTO pdf_processing_events (pdf_id, event_type, message, details)
                            VALUES (%s, 'SOURCE_CHANGED', 'PDF content SHA-256 hash changed on disk', %s);
                            """,
                            (existing["id"], json.dumps({"old_sha": existing["sha256"], "new_sha": item["sha256"]}))
                        )
                        source_changed_count += 1
                    else:
                        # Update metadata if needed
                        cur.execute(
                            """
                            UPDATE pdf_processing_registry SET
                                file_size_bytes = %s,
                                page_count = %s,
                                updated_at = now()
                            WHERE id = %s;
                            """,
                            (item["file_size_bytes"], item["page_count"], existing["id"])
                        )
                        updated_count += 1
        conn.commit()

    # Generate CSV manifest
    csv_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    id, relative_path, filename, category, sha256, 
                    file_size_bytes, page_count, processing_status,
                    total_questions_detected, questions_extracted,
                    questions_verified, questions_promoted, questions_needing_review,
                    total_tokens, groq_requests, last_error, updated_at
                FROM pdf_processing_registry
                ORDER BY category, relative_path;
            """)
            rows = cur.fetchall()

    fieldnames = [
        "id", "relative_path", "filename", "category", "sha256", 
        "file_size_bytes", "page_count", "processing_status",
        "total_questions_detected", "questions_extracted",
        "questions_verified", "questions_promoted", "questions_needing_review",
        "total_tokens", "groq_requests", "last_error", "updated_at"
    ]
    with csv_manifest_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(dict(r))

    summary = {
        "total_files": len(scanned_items),
        "total_pages": total_pages,
        "total_size_mb": round(total_bytes / (1024 * 1024), 2),
        "by_category": {
            cat: {
                "count": folder_counts[cat],
                "size_mb": round(folder_bytes[cat] / (1024 * 1024), 2),
            }
            for cat in sorted(folder_counts)
        },
        "duplicate_groups": len(duplicate_groups),
        "duplicate_files_count": duplicate_files_count,
        "inserted_into_registry": inserted_count,
        "existing_in_registry": updated_count,
        "source_changed_count": source_changed_count,
        "manifest_csv": str(csv_manifest_path.resolve()),
    }
    return summary


def get_registry_summary(database_url: str | None = None) -> dict[str, Any]:
    """Queries PostgreSQL pdf_processing_registry to compute aggregate progress."""
    db_url = database_url or settings.database_url
    with psycopg.connect(db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            # Counts by status
            cur.execute("""
                SELECT processing_status, COUNT(*) AS count 
                FROM pdf_processing_registry 
                GROUP BY processing_status;
            """)
            by_status = {r["processing_status"]: r["count"] for r in cur.fetchall()}

            # Aggregate sums
            cur.execute("""
                SELECT 
                    COUNT(*) AS total_pdfs,
                    COALESCE(SUM(page_count), 0) AS total_pages,
                    COALESCE(SUM(total_questions_detected), 0) AS total_detected,
                    COALESCE(SUM(questions_extracted), 0) AS total_extracted,
                    COALESCE(SUM(questions_verified), 0) AS total_verified,
                    COALESCE(SUM(questions_rejected), 0) AS total_rejected,
                    COALESCE(SUM(questions_needing_review), 0) AS total_needing_review,
                    COALESCE(SUM(questions_promoted), 0) AS total_promoted,
                    COALESCE(SUM(failed_questions), 0) AS total_failed,
                    COALESCE(SUM(groq_requests), 0) AS total_requests,
                    COALESCE(SUM(prompt_tokens), 0) AS total_prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) AS total_completion_tokens,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens
                FROM pdf_processing_registry;
            """)
            agg = dict(cur.fetchone())

            # All-time PostgreSQL database table counts
            cur.execute("SELECT COUNT(*) AS count FROM ingestion_question_candidates;")
            total_db_candidates = cur.fetchone()["count"]

            cur.execute("SELECT COUNT(*) AS count FROM questions;")
            total_db_canonical = cur.fetchone()["count"]

            # Category breakdown
            cur.execute("""
                SELECT category, COUNT(*) as count,
                       SUM(CASE WHEN processing_status IN ('COMPLETED', 'COMPLETED_WITH_REVIEW') THEN 1 ELSE 0 END) as completed,
                       SUM(questions_promoted) as promoted
                FROM pdf_processing_registry
                GROUP BY category
                ORDER BY category;
            """)
            by_category = {r["category"]: dict(r) for r in cur.fetchall()}

    return {
        "status_counts": by_status,
        "aggregates": agg,
        "database_totals": {
            "total_candidates_in_db": total_db_candidates,
            "total_canonical_questions_in_db": total_db_canonical,
        },
        "by_category": by_category,
    }


def acquire_pdf_lock(pdf_id: str, worker_id: str, database_url: str | None = None) -> bool:
    """Attempts to acquire an exclusive lock on a PDF row in PostgreSQL.
    
    Ensures single-worker execution: returns True if lock acquired, False otherwise.
    """
    db_url = database_url or settings.database_url
    with psycopg.connect(db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE pdf_processing_registry
                SET locked_by = %s,
                    locked_at = now(),
                    processing_status = 'IN_PROGRESS',
                    started_at = COALESCE(started_at, now()),
                    updated_at = now()
                WHERE id = %s AND (locked_by IS NULL OR locked_at < now() - INTERVAL '30 minutes')
                RETURNING id;
                """,
                (worker_id, pdf_id)
            )
            acquired = cur.fetchone() is not None
        conn.commit()

    if acquired:
        log_pdf_event(pdf_id, "LOCK_ACQUIRED", f"Lock acquired by {worker_id}", database_url=db_url)
    return acquired


def release_pdf_lock(
    pdf_id: str, 
    worker_id: str, 
    new_status: str | None = None,
    database_url: str | None = None
) -> bool:
    """Releases the lock on a PDF row safely, ensuring no orphaned IN_PROGRESS states.
    
    Requirements:
    - Only the owning worker can release the lock.
    - If status was still IN_PROGRESS:
        - If questions were partially extracted (> 0), transitions to PARTIALLY_COMPLETED.
        - If 0 questions extracted, transitions back to DISCOVERED.
    - If caller specifies new_status (e.g. COMPLETED, FAILED_RETRYABLE), respects it.
    - Clears locked_by and locked_at.
    - Logs LOCK_RELEASED event.
    """
    db_url = database_url or settings.database_url
    released = False

    with psycopg.connect(db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            # Check current state and ownership
            cur.execute(
                "SELECT processing_status, questions_extracted, locked_by FROM pdf_processing_registry WHERE id = %s",
                (pdf_id,)
            )
            row = cur.fetchone()
            if not row or row["locked_by"] != worker_id:
                return False  # Ownership mismatch or row not found

            current_status = row["processing_status"]
            questions_count = row["questions_extracted"]

            # Determine appropriate final status
            if new_status:
                target_status = new_status
            elif current_status == "IN_PROGRESS":
                target_status = "PARTIALLY_COMPLETED" if questions_count > 0 else "DISCOVERED"
            else:
                target_status = current_status

            cur.execute(
                """
                UPDATE pdf_processing_registry
                SET locked_by = NULL,
                    locked_at = NULL,
                    processing_status = %s,
                    updated_at = now()
                WHERE id = %s AND locked_by = %s
                RETURNING id;
                """,
                (target_status, pdf_id, worker_id)
            )
            released = cur.fetchone() is not None
        conn.commit()

    if released:
        log_pdf_event(pdf_id, "LOCK_RELEASED", f"Lock released by {worker_id}. Status: {target_status}", database_url=db_url)
    return released


def recover_stale_locks(timeout_minutes: int = 30, database_url: str | None = None) -> int:
    """Recovers any orphaned or expired locks across the registry safely.
    
    Recovers:
    1. Rows where locked_at is older than timeout_minutes.
    2. Rows where processing_status is 'IN_PROGRESS' but locked_by is NULL.
    Preserves checkpoints: sets PARTIALLY_COMPLETED if questions_extracted > 0, else DISCOVERED.
    """
    db_url = database_url or settings.database_url
    recovered_count = 0

    with psycopg.connect(db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, filename, questions_extracted, locked_by, locked_at
                FROM pdf_processing_registry
                WHERE (locked_by IS NOT NULL AND locked_at < now() - (%s * INTERVAL '1 minute'))
                   OR (processing_status = 'IN_PROGRESS' AND locked_by IS NULL);
                """,
                (timeout_minutes,)
            )
            stale_rows = cur.fetchall()

            for r in stale_rows:
                target_status = "PARTIALLY_COMPLETED" if r["questions_extracted"] > 0 else "DISCOVERED"
                cur.execute(
                    """
                    UPDATE pdf_processing_registry
                    SET locked_by = NULL,
                        locked_at = NULL,
                        processing_status = %s,
                        updated_at = now()
                    WHERE id = %s;
                    """,
                    (target_status, r["id"])
                )
                recovered_count += 1
                cur.execute(
                    """
                    INSERT INTO pdf_processing_events (pdf_id, event_type, message, details)
                    VALUES (%s, 'STALE_LOCK_RECOVERED', 'Stale lock safely recovered', %s);
                    """,
                    (r["id"], json.dumps({"previous_locked_by": r["locked_by"], "target_status": target_status}))
                )
        conn.commit()
    return recovered_count


def log_pdf_event(
    pdf_id: str, 
    event_type: str, 
    message: str, 
    details: dict[str, Any] | None = None, 
    database_url: str | None = None
) -> None:
    """Logs an append-only event in pdf_processing_events."""
    db_url = database_url or settings.database_url
    details_json = json.dumps(details or {})
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO pdf_processing_events (pdf_id, event_type, message, details)
                VALUES (%s, %s, %s, %s);
                """,
                (pdf_id, event_type, message, details_json)
            )
        conn.commit()


def get_next_eligible_pdf(
    category: str | None = None, 
    prefer_mathongo: bool = True,
    balance_subjects: bool = True,
    database_url: str | None = None
) -> dict[str, Any] | None:
    """Selects the next eligible PDF to process in deterministic, coverage-driven order.
    
    Eligible statuses: 'DISCOVERED', 'QUEUED', 'PARTIALLY_COMPLETED', 'FAILED_RETRYABLE'
    Deterministic preference:
      1. MathonGo chapter-wise question banks (clean digital text + high yield)
      2. Dynamic syllabus coverage balancing (prioritizing subjects with fewest canonical questions)
      3. In ascending page count order (shorter, high-precision chapter PDFs first)
      4. In alphabetical category and filename order
    """
    db_url = database_url or settings.database_url
    with psycopg.connect(db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            # Check current canonical distribution to prioritize underrepresented subjects
            subj_order = {"chemistry": 1, "mathematics": 2, "physics": 3}
            if balance_subjects:
                try:
                    cur.execute("SELECT subject, COUNT(*) AS cnt FROM questions GROUP BY subject;")
                    live_counts = {"chemistry": 0, "mathematics": 0, "physics": 0}
                    for r in cur.fetchall():
                        if r["subject"] in live_counts:
                            live_counts[r["subject"]] = r["cnt"]
                    # Rank subjects: fewest canonical questions first
                    sorted_subjs = sorted(live_counts.keys(), key=lambda s: live_counts[s])
                    subj_order = {subj: rank for rank, subj in enumerate(sorted_subjs, start=1)}
                except Exception:
                    pass

            query = """
                SELECT * FROM pdf_processing_registry
                WHERE processing_status IN ('DISCOVERED', 'QUEUED', 'PARTIALLY_COMPLETED', 'FAILED_RETRYABLE', 'BLOCKED_TOKEN_BUDGET')
                  AND (locked_by IS NULL OR locked_at < now() - INTERVAL '30 minutes')
            """
            params: list[Any] = []
            if category:
                query += " AND category = %s"
                params.append(category)

            # Deterministic coverage-driven ordering
            query += f"""
                ORDER BY 
                    CASE 
                        WHEN filename ILIKE '%%MathonGo%%' THEN 1 
                        ELSE 2 
                    END,
                    CASE 
                        WHEN category = 'chemistry' THEN {subj_order.get('chemistry', 1)}
                        WHEN category = 'mathematics' THEN {subj_order.get('mathematics', 2)}
                        WHEN category = 'physics' THEN {subj_order.get('physics', 3)}
                        WHEN category = 'full_tests' THEN 4
                        ELSE 5 
                    END,
                    page_count ASC,
                    relative_path ASC
                LIMIT 1;
            """
            cur.execute(query, params)
            row = cur.fetchone()
            return dict(row) if row else None


def generate_reports(database_url: str | None = None, reports_dir: Path = Path("reports")) -> tuple[Path, Path]:
    """Generates PDF_INGESTION_MASTER_REPORT.md and PDF_INGESTION_PROGRESS.json from PostgreSQL state."""
    db_url = database_url or settings.database_url
    reports_dir.mkdir(parents=True, exist_ok=True)
    summary = get_registry_summary(db_url)

    agg = summary["aggregates"]
    counts = summary["status_counts"]
    cats = summary["by_category"]

    json_path = reports_dir / "PDF_INGESTION_PROGRESS.json"
    md_path = reports_dir / "PDF_INGESTION_MASTER_REPORT.md"

    # Write JSON progress snapshot
    json_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    # Fetch recent PDF table
    with psycopg.connect(db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT filename, category, page_count, processing_status, 
                       questions_extracted, questions_verified, questions_promoted,
                       total_tokens, updated_at
                FROM pdf_processing_registry
                ORDER BY updated_at DESC
                LIMIT 25;
            """)
            recent_rows = cur.fetchall()

    # Generate Markdown master report
    db_tot = summary.get("database_totals", {})
    md_lines = [
        "# PrepFreeX — Continuous PDF Ingestion Master Report",
        "",
        f"*Generated on: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}*",
        "",
        "## 1. PostgreSQL Database Totals (All-Time Cumulative)",
        "",
        f"- **Total Staged Candidates in DB (`ingestion_question_candidates`):** {db_tot.get('total_candidates_in_db', 0):,}",
        f"- **Total Canonical Questions in DB (`questions`):** {db_tot.get('total_canonical_questions_in_db', 0):,}",
        "",
        "## 2. Continuous Registry Pipeline Summary (`pdf_processing_registry`)",
        "",
        f"- **Total PDFs in Registry:** {agg.get('total_pdfs', 0):,}",
        f"- **Total Pages:** {agg.get('total_pages', 0):,}",
        f"- **Questions Extracted via Pipeline:** {agg.get('total_extracted', 0):,}",
        f"- **Questions Verified via Pipeline:** {agg.get('total_verified', 0):,}",
        f"- **Questions Promoted via Pipeline:** {agg.get('total_promoted', 0):,}",
        f"- **Questions Needing Review via Pipeline:** {agg.get('total_needing_review', 0):,}",
        f"- **Total Groq API Requests:** {agg.get('total_requests', 0):,}",
        f"- **Total Groq Tokens Used:** {agg.get('total_tokens', 0):,}",
        "",
        "## 3. PDF Processing Status Breakdown",
        "",
        "| Processing Status | Count |",
        "| :--- | ---: |",
    ]

    for st in [
        "DISCOVERED", "QUEUED", "IN_PROGRESS", "EXTRACTED", 
        "VALIDATING", "PARTIALLY_COMPLETED", "COMPLETED", 
        "COMPLETED_WITH_REVIEW", "NEEDS_MANUAL_REVIEW", 
        "FAILED_RETRYABLE", "BLOCKED_TOKEN_BUDGET", "SOURCE_CHANGED"
    ]:
        md_lines.append(f"| `{st}` | {counts.get(st, 0):,} |")

    md_lines.extend([
        "",
        "## 3. Category Breakdown",
        "",
        "| Category | Total PDFs | Completed | Questions Promoted |",
        "| :--- | ---: | ---: | ---: |",
    ])
    for cat_name, c_data in sorted(cats.items()):
        md_lines.append(f"| **{cat_name}** | {c_data.get('count', 0):,} | {c_data.get('completed', 0):,} | {c_data.get('promoted', 0):,} |")

    md_lines.extend([
        "",
        "## 4. Recently Active PDFs",
        "",
        "| Filename | Category | Pages | Status | Extracted | Verified | Promoted | Tokens |",
        "| :--- | :--- | ---: | :--- | ---: | ---: | ---: | ---: |",
    ])
    for r in recent_rows:
        fn = r["filename"][:35] + "..." if len(r["filename"]) > 38 else r["filename"]
        md_lines.append(
            f"| `{fn}` | {r['category']} | {r['page_count']} | `{r['processing_status']}` | "
            f"{r['questions_extracted']} | {r['questions_verified']} | {r['questions_promoted']} | {r['total_tokens']:,} |"
        )

    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    return md_path, json_path
