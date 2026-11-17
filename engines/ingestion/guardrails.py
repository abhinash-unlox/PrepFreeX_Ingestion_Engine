"""
Academic Guardrail Validator
Strict zero-token deterministic sanity checks protecting against common VLM/OCR extraction flaws.
"""

from __future__ import annotations
import re
from typing import Any

# 1. Unrendered scientific exponents (e.g. 1.73 1010 or 48.8 1011)
STRIPPED_EXPONENT_RE = re.compile(r'\b\d+\.?\d*\s+10(?:1[0-9]|2[0-5]|[3-9])\b')

# 2. Dangling prepositions before period or comma indicating stripped equations
DANGLING_PREP_RE = re.compile(r'\b(?:is|of|in|to|at|with|by|from|equal to)\s+[\.\,]', re.IGNORECASE)

# 3. Empty unit brackets e.g. (in )
EMPTY_UNIT_RE = re.compile(r'\(in\s+\)|\[in\s+\]|\(in\s*\)', re.IGNORECASE)

# 4. Coaching institute branding / scraped web watermarks
WATERMARK_RE = re.compile(
    r'(?:mathongo|#MathBoleTohMathonGo|www\.mathongo|Question Bank|'
    r'JEE Main 202\d\s+April|JEE Main 202\d\s+January|Allen|Resonance|Fiitjee|Aakash|Vedantu)',
    re.IGNORECASE
)

# 5. Broken Assertion-Reason format (missing A/R labels)
BROKEN_AR_OPTS_RE = [
    re.compile(r'^\s*is true but\s+is false', re.IGNORECASE),
    re.compile(r'^\s*is false but\s+is true', re.IGNORECASE),
    re.compile(r'^\s*Both\s+and\s+are true', re.IGNORECASE),
    re.compile(r'^\s*Both\s+and\s+are false', re.IGNORECASE),
]

# 6. Diagram references
FIGURE_REF_RE = re.compile(
    r'\b(?:see figure|given figure|shown in figure|as shown in the figure|shown below|in the circuit shown)\b',
    re.IGNORECASE
)

def validate_question_guardrails(
    stem: str,
    options: list[Any],
    has_diagram: bool = False,
    diagram_s3_key: str | None = None,
    question_type: str = "SINGLE_CHOICE"
) -> tuple[bool, list[str]]:
    """
    Evaluates extracted question content against strict academic integrity rules.
    Returns (is_valid, list_of_flaws).
    """
    flaws: list[str] = []
    clean_stem = " ".join((stem or "").split()).strip()

    # --- STEM CHECKS ---
    if not clean_stem:
        flaws.append("EMPTY_STEM: Question text is completely empty.")
        return False, flaws

    if len(clean_stem) < 20:
        flaws.append(f"STEM_TOO_SHORT: Question text has only {len(clean_stem)} characters.")

    if DANGLING_PREP_RE.search(clean_stem):
        flaws.append("DANGLING_PREPOSITION: Dropped equation or variable before period/comma.")

    if EMPTY_UNIT_RE.search(clean_stem):
        flaws.append("EMPTY_UNIT_PARENTHESIS: Found empty unit specification like '(in )'.")

    if WATERMARK_RE.search(clean_stem):
        flaws.append("WATERMARK_IN_STEM: Found coaching watermark or scrap header in question stem.")

    # LaTeX delimiter parity ($ count should be even)
    dollar_count = clean_stem.count('$')
    if dollar_count % 2 != 0:
        flaws.append(f"UNBALANCED_LATEX_DELIMITERS: Question has an odd number ({dollar_count}) of '$' delimiters.")

    # Ghost diagram check
    if FIGURE_REF_RE.search(clean_stem):
        if not has_diagram or not diagram_s3_key:
            flaws.append("MISSING_DIAGRAM: Stem refers to a figure/circuit, but no diagram S3 asset is attached.")

    # --- OPTIONS CHECKS ---
    if question_type == "SINGLE_CHOICE":
        clean_opts = [
            (o.get("text", "") if isinstance(o, dict) else str(o)).strip()
            for o in (options or [])
        ]

        if len(clean_opts) != 4:
            flaws.append(f"INVALID_OPTION_COUNT: Expected 4 options, found {len(clean_opts)}.")
        else:
            # Check empty options
            for idx, opt in enumerate(clean_opts):
                if not opt:
                    flaws.append(f"EMPTY_OPTION: Option {chr(65 + idx)} is empty.")
                if WATERMARK_RE.search(opt):
                    flaws.append(f"WATERMARK_IN_OPTION: Option {chr(65 + idx)} contains watermark text.")
                if STRIPPED_EXPONENT_RE.search(opt):
                    flaws.append(f"STRIPPED_EXPONENT: Option {chr(65 + idx)} contains flattened scientific exponent (e.g. 1010/1011).")
                for ar_pat in BROKEN_AR_OPTS_RE:
                    if ar_pat.search(opt):
                        flaws.append(f"BROKEN_AR_OPTION: Option {chr(65 + idx)} missing Assertion/Reason subject label.")
                        break

            # Check duplicate options
            lowered = [o.lower() for o in clean_opts if o]
            if len(lowered) == 4 and len(set(lowered)) < 4:
                flaws.append("DUPLICATE_OPTIONS: Two or more option choices are identical.")

    is_valid = len(flaws) == 0
    return is_valid, flaws
