from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .pdf_reader import DocumentRecord, render_page

QUESTION_HEADING = re.compile(r"(?im)^\s*(?:Q\s*)?(\d{1,3})\s*[.)]\s*(?=\S)")
OPTION_LINE = re.compile(r"(?m)^\s*(?:\(([1-9])\)|([A-D])\s*[).])\s*(.*)$", re.I)
DATE_SHIFT = re.compile(r"JEE\s*Main\s*20(\d{2})\s*\((\d{1,2})\s+([A-Za-z]+)\s+Shift\s*(\d+)\)", re.I)


@dataclass
class Candidate:
    key: str
    label: str
    page_start: int
    page_end: int
    text: str
    subject: str | None = None
    source_part: str | None = None
    source_section: str | None = None
    local_number: int | None = None
    global_number: int | None = None
    figure_pages: list[int] = field(default_factory=list)
    flags: dict[str, Any] = field(default_factory=dict)


def _subject_for_page(text: str, current: str | None) -> str | None:
    upper = text.upper()
    if "PART-1" in upper or "PART 1" in upper or "MATHEMATICS" in upper:
        return "mathematics"
    if "PART-2" in upper or "PART 2" in upper or re.search(r"\bPHYSICS\b", upper):
        return "physics"
    if "PART-3" in upper or "PART 3" in upper or re.search(r"\bCHEMISTRY\b", upper):
        return "chemistry"
    return current


def _split_mathongo(doc: DocumentRecord, pdf_path: Path) -> list[Candidate]:
    # The supplied MathonGo layout has five Qn. headings on its first page.
    page = next((p for p in doc.pages if re.search(r"(?im)^\s*Q1\.", p.text)), None)
    if page is None:
        return []
    text = page.text
    matches = list(re.finditer(r"(?im)^\s*Q(\d+)\.", text))
    candidates: list[Candidate] = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[match.start():end].strip()
        n = int(match.group(1))
        candidates.append(Candidate(
            key=f"Q{n}", label=f"Q{n}", page_start=page.page_number,
            page_end=page.page_number, text=block, subject="physics",
            local_number=n, global_number=n,
            figure_pages=[page.page_number] if "figure" in block.lower() or n in {2, 5} else [],
            flags={"layout_profile": "mathongo_question_bank", "visual_math_review_required": True},
        ))
    return candidates


def _split_generic(doc: DocumentRecord) -> list[Candidate]:
    candidates: list[Candidate] = []
    current_subject: str | None = None
    current_part: str | None = None
    current_section: str | None = None
    current: dict[str, Any] | None = None
    in_answer_or_solution_section = False
    local_global_bases = {
        ("mathematics", "I"): 0,
        ("mathematics", "II"): 20,
        ("physics", "I"): 25,
        ("physics", "II"): 45,
        ("chemistry", "I"): 50,
        ("chemistry", "II"): 70,
    }

    def finish_current():
        nonlocal current
        if current and len("\n".join(current["lines"]).strip()) >= 25:
            key = f"{(current['subject'] or 'UNK')[:3].upper()}-S{current['section'] or 'X'}-Q{current['number']:02d}"
            candidates.append(Candidate(
                key=key,
                label=f"Q{current['number']}",
                page_start=current["page_start"],
                page_end=current["page_end"],
                text="\n".join(current["lines"]).strip(),
                subject=current["subject"],
                source_part=current["part"],
                source_section=current["section"],
                local_number=current["number"],
                global_number=(local_global_bases.get((current["subject"], current["section"]), 0) + current["number"])
                    if current["subject"] and current["section"] else None,
                figure_pages=[current["page_start"]],
                flags={
                    "layout_profile": "line_state_machine",
                    "ocr_based": current["ocr_based"],
                    "visual_inspection_required": True,
                },
            ))
        current = None

    qstart = re.compile(r"^\s*(?:Q\s*)?(\d{1,2})\s*[).]\s+(.*)$", re.I)
    for page in doc.pages:
        lines = page.text.splitlines()
        for line in lines:
            stripped = line.strip()
            upper = stripped.upper()
            if not stripped:
                if current:
                    current["lines"].append("")
                continue
            if re.search(r"(?im)^\s*(?:ANSWER\s+KEYS?|ANSWERS\s+AND\s+SOLUTIONS|SOLUTIONS)\b", upper):
                finish_current()
                in_answer_or_solution_section = True
                break
            if in_answer_or_solution_section:
                break

            part_match = re.match(r"^\s*PART\s*[-:]?\s*(\d+)\b", upper)
            if part_match:
                finish_current()
                current_part = part_match.group(1)
                if current_part == "1":
                    current_subject = "mathematics"
                elif current_part == "2":
                    current_subject = "physics"
                elif current_part == "3":
                    current_subject = "chemistry"
                continue
            if current_subject is None:
                if re.match(r"^\s*MATHEMATICS\s*$", upper):
                    current_subject = "mathematics"
                elif re.match(r"^\s*PHYSICS\s*$", upper):
                    current_subject = "physics"
                elif re.match(r"^\s*CHEMISTRY\s*$", upper):
                    current_subject = "chemistry"

            section_match = re.match(r"^\s*SECTION\s*[-:]?\s*(I{1,2}|1|2)\b", upper)
            if section_match:
                finish_current()
                token = section_match.group(1).upper()
                current_section = "II" if token in {"II", "2"} else "I"
                continue

            match = qstart.match(line)
            if match:
                number = int(match.group(1))
                # Reject obvious non-question list numbers unless the number is sequential,
                # or a new section has just started with Q1.
                if current is None or number == 1 or number == current["number"] + 1 or number <= 20:
                    finish_current()
                    current = {
                        "number": number,
                        "subject": current_subject,
                        "part": current_part,
                        "section": current_section,
                        "page_start": page.page_number,
                        "page_end": page.page_number,
                        "lines": [line.strip()],
                        "ocr_based": page.extraction_method == "ocr",
                    }
                    continue
            if current:
                current["lines"].append(line)
                current["page_end"] = page.page_number
    finish_current()
    # Ensure staging keys remain unique even if OCR misreads/repeats a local question number.
    seen: set[str] = set()
    for candidate in candidates:
        if candidate.key in seen:
            candidate.key = f"{candidate.key}-P{candidate.page_start:03d}"
            candidate.flags["duplicate_ocr_label"] = True
        seen.add(candidate.key)
    return candidates


def split_questions(doc: DocumentRecord, pdf_path: Path) -> tuple[list[Candidate], str]:
    mathongo = _split_mathongo(doc, pdf_path)
    if len(mathongo) == 5:
        return mathongo, "mathongo_question_bank"
    generic = _split_generic(doc)
    if "part test" in pdf_path.stem.lower() and doc.page_count >= 30:
        return generic, "allen_part_test_75"
    return generic, "generic"
