from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz

from .config import settings


@dataclass
class PageRecord:
    page_number: int
    text: str
    extraction_method: str
    text_char_count: int
    image_count: int
    has_drawings: bool
    image_path: str | None = None


@dataclass
class DocumentRecord:
    path: str
    sha256: str
    page_count: int
    title: str
    metadata: dict[str, Any]
    pages: list[PageRecord]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalise_text(text: str) -> str:
    text = text.replace("\u00a0", " ").replace("\ufeff", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def render_page(path: Path, page_number: int, out_path: Path, dpi: int | None = None) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open(path) as pdf:
        if page_number < 1 or page_number > len(pdf):
            raise ValueError(f"Page number {page_number} outside 1..{len(pdf)}")
        pix = pdf[page_number - 1].get_pixmap(dpi=dpi or settings.pdf_render_dpi, alpha=False)
        pix.save(out_path)
    return out_path


def read_pdf(
    path: Path,
    render_dir: Path | None = None,
    dpi: int | None = None,
    page_range: tuple[int, int] | None = None,
) -> DocumentRecord:
    if not path.exists() or path.suffix.lower() != ".pdf":
        raise FileNotFoundError(f"PDF not found or unsupported: {path}")

    render_dir = render_dir or (settings.artifact_dir / "pages" / path.stem.replace(" ", "_"))
    render_dir.mkdir(parents=True, exist_ok=True)
    target_dpi = dpi or settings.pdf_render_dpi
    pages: list[PageRecord] = []

    with fitz.open(path) as pdf:
        meta = {k: v for k, v in (pdf.metadata or {}).items() if v}
        total_pages = len(pdf)
        start_p = 1
        end_p = total_pages
        if page_range:
            start_p = max(1, page_range[0])
            end_p = min(total_pages, page_range[1])

        for i in range(start_p - 1, end_p):
            page = pdf[i]
            p_no = i + 1
            text = _normalise_text(page.get_text("text", sort=True))

            image_path_obj = render_dir / f"page-{p_no:03d}.png"
            if not image_path_obj.exists():
                pix = page.get_pixmap(dpi=target_dpi, alpha=False)
                pix.save(image_path_obj)
            image_path = str(image_path_obj)

            pages.append(PageRecord(
                page_number=p_no,
                text=text,
                extraction_method="rendered_image" if len(text) < settings.ocr_min_text_chars else "text_with_image",
                text_char_count=len(text),
                image_count=len(page.get_images(full=True)),
                has_drawings=bool(page.get_drawings()),
                image_path=image_path,
            ))

        title = str(meta.get("title") or path.stem)
        return DocumentRecord(
            path=str(path.resolve()),
            sha256=sha256_file(path),
            page_count=total_pages,
            title=title,
            metadata=meta,
            pages=pages,
        )
