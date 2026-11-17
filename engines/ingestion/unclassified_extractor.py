from __future__ import annotations

import hashlib
import io
import os
import re
import uuid
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
from PIL import Image
from psycopg.types.json import Jsonb

from apps.api.db import get_db_cursor
from engines.shared.asset_manager import AssetManager

MONTHS = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
    "jan": "01", "feb": "02", "mar": "03", "apr": "04", "jun": "06", "jul": "07",
    "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12"
}

DATE_SHIFT_RE = re.compile(
    r"(?:JEE\s*Main\s*)?20(\d{2})\s*\((\d{1,2})\s+([A-Za-z]+)\s+Shift\s*(\d+)\)", re.I
)

WATERMARK_PATTERNS = [
    re.compile(p, re.I) for p in [
        r"#PaperPhodnaHai",
        r"www\.mathongo\.com",
        r"MathonGo",
        r"Questions\s+with\s+Answer\s+Keys",
        r"JEE\s+Main\s+20\d\d\s*\([A-Za-z\s]+\)\s*Question\s+Bank",
        r"Download\s+MARKS\s+App",
        r"Chapter-wise\s+Question\s+Bank",
        r"FIITJEE\s+Ltd\.",
        r"FIITJEE\s+Tower",
        r"www\.fiitjee\.com",
        r"FIITJEE\s+LIMITED",
        r"ALLEN\s+Career\s+Institute",
    ]
]


def detect_subject_from_path(pdf_path: Path, text: str = "") -> str:
    """Determine academic subject (physics, chemistry, mathematics) from path or content."""
    parts = [p.lower() for p in pdf_path.parts]
    if "chemistry" in parts or "chem" in parts:
        return "chemistry"
    if "physics" in parts or "phys" in parts:
        return "physics"
    if "mathematics" in parts or "maths" in parts or "math" in parts:
        return "mathematics"

    upper = text[:600].upper()
    if "CHEMISTRY" in upper:
        return "chemistry"
    if "PHYSICS" in upper:
        return "physics"
    if "MATHEMATICS" in upper:
        return "mathematics"

    return "physics"


def clean_watermarks(text: str) -> str:
    """Strip publisher headers, footers, app links, and hashtag watermarks."""
    lines = []
    for line in text.splitlines():
        if any(pat.search(line) for pat in WATERMARK_PATTERNS):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def parse_answer_and_solutions(doc: fitz.Document) -> tuple[dict[int, Any], dict[int, str]]:
    """Parse answer grid and solution blocks across the document."""
    answer_map: dict[int, Any] = {}
    solution_map: dict[int, str] = {}

    full_text = ""
    sol_start_page = -1

    for pno in range(len(doc)):
        page_text = doc[pno].get_text("text")
        upper = page_text.upper()
        if any(kw in upper for kw in ["ANSWERS AND SOLUTIONS", "ANSWER KEY", "ANSWER KEYS", "HINTS & SOLUTIONS", "SOLUTIONS"]):
            if sol_start_page == -1:
                sol_start_page = pno
        if sol_start_page != -1:
            full_text += f"\n--- PAGE {pno+1} ---\n" + page_text

    if not full_text:
        return answer_map, solution_map

    # 1. Answer Key Grid Pattern
    grid_matches = re.finditer(
        r"(?im)(?:^|\s)(?:Q\s*)?(\d{1,3})\s*(?:[.:]\s*|\s+)(?:\(([1-4A-Da-d])\)|\(([0-9.-]+)\)|(-?\d+(?:\.\d+)?))",
        full_text
    )
    for m in grid_matches:
        num = int(m.group(1))
        if num in answer_map:
            continue
        if m.group(2):
            val = m.group(2)
            pos = int(val) if val.isdigit() else ord(val.upper()) - 64
            answer_map[num] = {"type": "option", "positions": [pos], "raw": val}
        elif m.group(3) or m.group(4):
            raw_val = m.group(3) or m.group(4)
            val_num = float(raw_val) if "." in raw_val else int(raw_val)
            answer_map[num] = {"type": "numeric", "value": val_num, "tolerance": 0, "raw": raw_val}

    # 2. Solution Blocks
    sol_matches = list(re.finditer(
        r"(?im)^\s*(?:Q\s*)?(\d{1,3})\s*(?:[.:]|\s*$\n?)\s*(?:\(([0-9A-Za-z]+)\))?\s*(.*?)(?=\n\s*(?:Q\s*)?\d{1,3}\s*(?:[.:]|\s*$\n?)|\Z)",
        full_text,
        re.S
    ))
    for sm in sol_matches:
        num = int(sm.group(1))
        body = clean_watermarks(sm.group(3).strip())
        if len(body) > 10:
            solution_map[num] = body

    return answer_map, solution_map


def parse_options(block: str) -> tuple[str, list[dict[str, Any]], str]:
    """Extract stem and options from a question block.

    Supports: (1)..(4), (A)..(D), (a)..(d), a)..d), A)..D).
    Returns (stem, options_list, question_type).
    """
    options: list[dict[str, Any]] = []
    stem = block
    qtype = "numerical"

    pat = re.compile(r"(?:\(([1-4])\)|\(([A-Da-d])\))")
    matches = list(pat.finditer(block))
    first_idx = None
    if len(matches) >= 4:
        for idx, m in enumerate(matches):
            if m.group(1) == '1' or (m.group(2) and m.group(2).upper() == 'A'):
                first_idx = idx
                break

    if first_idx is not None and len(matches) - first_idx >= 4:
        use_matches = matches[first_idx:first_idx + 4]
        stem = block[:use_matches[0].start()].strip()
        for i in range(4):
            m = use_matches[i]
            lbl = f"({m.group(0)[1:-1].upper()})"
            pos = int(m.group(1)) if m.group(1) else ord(m.group(2).upper()) - 64
            s_pos = m.end()
            e_pos = use_matches[i + 1].start() if i + 1 < 4 else len(block)
            val = block[s_pos:e_pos].strip()
            options.append({"position": pos, "label_printed": lbl, "text_md": val})
        qtype = "mcq_single"
    else:
        opt_matches = list(re.finditer(r"(?im)^\s*(?:\(([1-4])\)|\(([A-Da-d])\)|([A-Da-d1-4])\s*[).])\s*(.*)$", block))
        if len(opt_matches) >= 2:
            stem = block[:opt_matches[0].start()].strip()
            for idx, om in enumerate(opt_matches[:4]):
                raw_code = om.group(1) or om.group(2) or om.group(3)
                lbl = f"({raw_code.upper()})"
                pos = int(raw_code) if raw_code.isdigit() else ord(raw_code.upper()) - 64
                val = (om.group(4) or "").strip()
                options.append({"position": pos, "label_printed": lbl, "text_md": val})
            qtype = "mcq_single" if len(options) == 4 else "mcq_multiple"

    return stem, options, qtype


def extract_questions_and_assets(
    pdf_path: Path,
    pdf_registry_id: uuid.UUID,
    job_id: uuid.UUID,
    asset_manager: AssetManager | None = None,
    staging_dir: Path | None = None,
) -> dict[str, Any]:
    """Extracts all questions and diagrams from a single PDF and stages them in PostgreSQL & MinIO."""
    mgr = asset_manager or AssetManager()
    staging_root = staging_dir or Path("data/cache/assets_staging")
    staging_root.mkdir(parents=True, exist_ok=True)

    pdf_sha256 = mgr.calculate_sha256(pdf_path)
    subject = detect_subject_from_path(pdf_path)
    filename = pdf_path.name

    doc = fitz.open(pdf_path)
    total_pages = len(doc)

    answer_map, solution_map = parse_answer_and_solutions(doc)

    q_pages = []
    for pno in range(total_pages):
        page_text = doc[pno].get_text("text").upper()
        if any(kw in page_text for kw in ["ANSWERS AND SOLUTIONS", "ANSWER KEYS", "HINTS & SOLUTIONS"]):
            break
        q_pages.append(pno)

    if not q_pages:
        q_pages = list(range(total_pages))

    candidates_created = 0
    assets_created = 0
    mcq_count = 0
    numerical_count = 0
    figures_associated = 0

    for pno in q_pages:
        page = doc[pno]
        page_num = pno + 1
        page_text = page.get_text("text")

        q_matches = list(re.finditer(
            r"(?im)^\s*(?:Q\s*)?(\d{1,3})\s*(?:[.):\-]\s*(?:20\d\d)?|[.):])\s*(.*?)(?=\n\s*(?:Q\s*)?\d{1,3}\s*(?:[.):\-]\s*(?:20\d\d)?|[.):])|\Z)",
            page_text,
            re.S
        ))

        blocks = page.get_text("blocks")
        page_images = page.get_images()

        for qm in q_matches:
            loc_num = int(qm.group(1))
            raw_block = qm.group(2).strip()

            if len(raw_block) < 15:
                continue

            exam_name = "JEE Main"
            exam_year = 2024
            date_m = DATE_SHIFT_RE.search(raw_block)
            if date_m:
                yr = 2000 + int(date_m.group(1))
                day = int(date_m.group(2))
                m_str = date_m.group(3).lower()
                month = MONTHS.get(m_str, "01")
                exam_name = f"JEE Main {yr} ({day} {m_str.capitalize()} Shift {date_m.group(4)})"
                exam_year = yr
                raw_block = raw_block[date_m.end():].strip()

            cleaned_block = clean_watermarks(raw_block)
            stem, options, qtype = parse_options(cleaned_block)

            if qtype == "mcq_single":
                mcq_count += 1
            else:
                numerical_count += 1

            ans_obj = answer_map.get(loc_num)
            sol_text = solution_map.get(loc_num)

            q_str_snippet = stem[:40].strip()
            q_y0 = 0.0
            q_y1 = float(page.rect.height)
            for b in blocks:
                if q_str_snippet in b[4] or f"Q{loc_num}" in b[4] or f"{loc_num}." in b[4]:
                    q_y0 = b[1]
                    break

            opts_str = "|".join([f"{o['position']}:{o['text_md']}" for o in options])
            hash_source = f"{subject}:{stem}:{opts_str}".strip()
            content_hash = hashlib.sha256(hash_source.encode("utf-8")).hexdigest()

            candidate_id = uuid.uuid4()
            q_key = f"{pdf_path.stem[:12]}-P{page_num:02d}-Q{loc_num:02d}"

            has_fig = False
            fig_status = "none"
            associated_assets = []

            # 1. Raster Images
            for img_info in page_images:
                xref = img_info[0]
                img_rects = page.get_image_rects(xref)
                for r in img_rects:
                    if q_y0 <= r.y0 <= q_y1 or (r.y0 >= q_y0 and r.y1 <= q_y0 + 400):
                        try:
                            base_img = doc.extract_image(xref)
                            img_bytes = base_img["image"]
                            ext = base_img["ext"]
                            if len(img_bytes) > 500:
                                asset_id = uuid.uuid4()
                                local_asset_path = staging_root / f"{asset_id}.{ext}"
                                local_asset_path.write_bytes(img_bytes)

                                # WebP thumbnail
                                try:
                                    pil_img = Image.open(io.BytesIO(img_bytes))
                                    pil_img.thumbnail((300, 300))
                                    thumb_path = staging_root / f"{asset_id}_thumb.webp"
                                    pil_img.save(thumb_path, format="WEBP")
                                    mgr.upload_and_verify_asset(
                                        local_path=thumb_path,
                                        candidate_id=str(candidate_id),
                                        role="stem",
                                        variant_type="thumbnail",
                                        source_document_id=str(pdf_registry_id),
                                        source_page_number=page_num,
                                        extraction_method="thumbnail_webp",
                                        width=pil_img.width,
                                        height=pil_img.height,
                                        alt_text=f"Thumbnail for {q_key}",
                                    )
                                except Exception:
                                    pass

                                res = mgr.upload_and_verify_asset(
                                    local_path=local_asset_path,
                                    candidate_id=str(candidate_id),
                                    role="stem",
                                    variant_type="original",
                                    source_document_id=str(pdf_registry_id),
                                    source_page_number=page_num,
                                    extraction_method="pymupdf_extracted_raster",
                                    width=base_img["width"],
                                    height=base_img["height"],
                                    alt_text=f"Extracted figure for {q_key}",
                                )
                                associated_assets.append(res)
                                assets_created += 1
                                has_fig = True
                                fig_status = "associated"
                                figures_associated += 1
                        except Exception:
                            pass

            # 2. Vector Drawings Fallback
            if not has_fig and page.get_drawings():
                try:
                    drawings = [d for d in page.get_drawings() if q_y0 <= d["rect"].y0 <= q_y0 + 350 and d["rect"].width > 30 and d["rect"].height > 30]
                    if drawings:
                        union_rect = fitz.Rect(drawings[0]["rect"])
                        for d in drawings[1:]:
                            union_rect |= d["rect"]
                        union_rect.x0 = max(0, union_rect.x0 - 5)
                        union_rect.y0 = max(0, union_rect.y0 - 5)
                        union_rect.x1 = min(page.rect.width, union_rect.x1 + 5)
                        union_rect.y1 = min(page.rect.height, union_rect.y1 + 5)

                        pix = page.get_pixmap(clip=union_rect, dpi=200)
                        asset_id = uuid.uuid4()
                        local_asset_path = staging_root / f"{asset_id}.png"
                        pix.save(local_asset_path)

                        res = mgr.upload_and_verify_asset(
                            local_path=local_asset_path,
                            candidate_id=str(candidate_id),
                            role="stem",
                            variant_type="original",
                            source_document_id=str(pdf_registry_id),
                            source_page_number=page_num,
                            extraction_method="pymupdf_vector_render",
                            width=pix.width,
                            height=pix.height,
                            alt_text=f"Rendered vector figure for {q_key}",
                        )
                        associated_assets.append(res)
                        assets_created += 1
                        has_fig = True
                        fig_status = "associated"
                        figures_associated += 1
                except Exception:
                    pass

            if not has_fig and any(term in stem.lower() for term in ["figure", "graph", "diagram", "circuit", "shown below"]):
                has_fig = True
                fig_status = "pending"

            # Stage candidate in PostgreSQL
            with get_db_cursor() as cur:
                cur.execute("""
                    INSERT INTO ingestion_question_candidates (
                        id, ingestion_job_id, pdf_registry_id, source_question_key,
                        source_q_label, source_page_start, source_page_end,
                        source_local_number, source_global_number,
                        subject_guess, question_type_guess, stem_md,
                        options_json, answer_json, classification_json,
                        extraction_json, review_status, verification_status,
                        content_hash, has_figure, figure_status,
                        source_pdf_filename, source_pdf_sha256, classification_status,
                        created_at, updated_at
                    ) VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, 'needs_review', %s,
                        %s, %s, %s,
                        %s, %s, 'PENDING',
                        NOW(), NOW()
                    )
                    ON CONFLICT (ingestion_job_id, source_question_key) DO UPDATE SET
                        stem_md = EXCLUDED.stem_md,
                        options_json = EXCLUDED.options_json,
                        answer_json = EXCLUDED.answer_json,
                        extraction_json = EXCLUDED.extraction_json,
                        content_hash = EXCLUDED.content_hash,
                        has_figure = EXCLUDED.has_figure,
                        figure_status = EXCLUDED.figure_status,
                        updated_at = NOW();
                """, (
                    candidate_id, job_id, pdf_registry_id, q_key,
                    f"Q{loc_num}", page_num, page_num,
                    loc_num, loc_num,
                    subject, qtype, stem,
                    Jsonb(options),
                    Jsonb(ans_obj) if ans_obj else None,
                    Jsonb({"status": "PENDING", "taxonomy": None, "chapter_metadata": pdf_path.stem}),
                    Jsonb({
                        "source_pdf": filename,
                        "source_sha256": pdf_sha256,
                        "exam_name": exam_name,
                        "exam_year": exam_year,
                        "solution_text": sol_text,
                        "associated_assets": associated_assets,
                    }),
                    "ANSWER_VERIFIED" if ans_obj else "ANSWER_PENDING",
                    content_hash, has_fig, fig_status,
                    filename, pdf_sha256
                ))
                candidates_created += 1

    return {
        "pdf_path": str(pdf_path),
        "filename": filename,
        "page_count": total_pages,
        "candidates_created": candidates_created,
        "assets_created": assets_created,
        "figures_associated": figures_associated,
        "mcq_count": mcq_count,
        "numerical_count": numerical_count,
        "answers_found": len(answer_map),
        "solutions_found": len(solution_map),
    }
