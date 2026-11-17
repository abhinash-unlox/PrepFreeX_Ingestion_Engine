from __future__ import annotations

import csv
import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF


def compute_sha256_streaming(file_path: Path, chunk_size: int = 65536) -> str:
    """Computes SHA-256 without loading the full file into memory."""
    hasher = hashlib.sha256()
    with file_path.open("rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()


def inspect_single_pdf(file_path: Path, base_dir: Path | None = None) -> dict[str, Any]:
    """Inspects a single PDF file for page count, text layer, and figures without calling an LLM."""
    base = base_dir or file_path.parent
    try:
        rel_path = str(file_path.relative_to(base)).replace("\\", "/")
    except ValueError:
        rel_path = str(file_path).replace("\\", "/")

    stat = file_path.stat()
    size_bytes = stat.st_size
    size_mb = round(size_bytes / (1024 * 1024), 2)
    sha256_hex = compute_sha256_streaming(file_path)

    total_pages = 0
    scanned_pages = 0
    figure_heavy_pages = 0
    text_layer = "unknown"
    error = None

    try:
        with fitz.open(file_path) as doc:
            total_pages = doc.page_count
            for p in doc:
                txt = p.get_text("text").strip()
                char_count = len(txt)
                images = p.get_images()
                img_count = len(images) if images else 0
                drawings = p.get_drawings()
                draw_count = len(drawings) if drawings else 0

                # Scanned page detection: virtually no selectable text
                if char_count < 40:
                    scanned_pages += 1

                # Figure heavy detection: contains raster images or multiple vector drawings
                if img_count >= 2 or (img_count >= 1 and draw_count >= 2) or draw_count >= 6:
                    figure_heavy_pages += 1

            if total_pages == 0:
                text_layer = "empty"
            elif scanned_pages == 0:
                text_layer = "full"
            elif scanned_pages == total_pages:
                text_layer = "none (scanned)"
            else:
                text_layer = f"partial ({total_pages - scanned_pages}/{total_pages} pages)"

    except Exception as exc:
        error = str(exc)
        text_layer = f"corrupt/error: {error}"

    return {
        "file_name": file_path.name,
        "relative_path": rel_path,
        "absolute_path": str(file_path.resolve()),
        "sha256": sha256_hex,
        "size_bytes": size_bytes,
        "size_mb": size_mb,
        "total_pages": total_pages,
        "text_layer": text_layer,
        "scanned_pages": scanned_pages,
        "figure_heavy_pages": figure_heavy_pages,
        "error": error,
    }


def inventory_pdf_directory(
    root_path: Path,
    output_csv: Path | None = None,
    db_conn: Any | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Recursively scans a directory for PDFs and compiles an inventory report."""
    root_path = root_path.resolve()
    if root_path.is_file():
        pdf_files = [root_path]
        base_dir = root_path.parent
    else:
        pdf_files = sorted(root_path.rglob("*.pdf"))
        base_dir = root_path

    # Check known database source documents if connection is available
    known_db_docs: dict[str, str] = {}
    if db_conn is not None:
        try:
            with db_conn.cursor() as cur:
                cur.execute("SELECT sha256, license_status FROM source_documents;")
                for r in cur.fetchall():
                    known_db_docs[r[0]] = f"db_indexed (license: {r[1]})"
        except Exception:
            pass

    records: list[dict[str, Any]] = []
    sha_groups: dict[str, list[int]] = defaultdict(list)

    for idx, pdf in enumerate(pdf_files):
        rec = inspect_single_pdf(pdf, base_dir=base_dir)
        rec["processing_status"] = known_db_docs.get(rec["sha256"], "unindexed")
        records.append(rec)
        sha_groups[rec["sha256"]].append(idx)

    # Flag exact duplicates
    duplicate_groups_count = 0
    duplicate_files_count = 0
    for sha, indices in sha_groups.items():
        if len(indices) > 1:
            duplicate_groups_count += 1
            primary_rel = records[indices[0]]["relative_path"]
            for idx in indices:
                is_primary = (idx == indices[0])
                records[idx]["is_duplicate"] = True
                records[idx]["duplicate_role"] = "primary" if is_primary else "duplicate"
                records[idx]["duplicate_of"] = "" if is_primary else primary_rel
                if not is_primary:
                    duplicate_files_count += 1
        else:
            records[indices[0]]["is_duplicate"] = False
            records[indices[0]]["duplicate_role"] = "unique"
            records[indices[0]]["duplicate_of"] = ""

    # Generate CSV output if path provided
    if output_csv:
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "file_name",
            "relative_path",
            "sha256",
            "size_mb",
            "total_pages",
            "text_layer",
            "scanned_pages",
            "figure_heavy_pages",
            "is_duplicate",
            "duplicate_role",
            "duplicate_of",
            "processing_status",
        ]
        with output_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for r in records:
                writer.writerow(r)

    total_mb = sum(r["size_mb"] for r in records)
    total_pages = sum(r["total_pages"] for r in records)
    total_scanned = sum(r["scanned_pages"] for r in records)
    total_figures = sum(r["figure_heavy_pages"] for r in records)

    summary = {
        "total_files": len(records),
        "total_size_mb": round(total_mb, 2),
        "total_pages": total_pages,
        "scanned_pages": total_scanned,
        "figure_heavy_pages": total_figures,
        "duplicate_groups": duplicate_groups_count,
        "duplicate_files": duplicate_files_count,
        "unique_files": len(records) - duplicate_files_count,
        "manifest_path": str(output_csv) if output_csv else None,
    }
    return records, summary

