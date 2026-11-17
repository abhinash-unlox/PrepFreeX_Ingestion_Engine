from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .models import ImportBundle


def _check_latex_sanity(text: str) -> list[str]:
    """Lightweight LaTeX sanity check: returns list of warnings (never drops questions)."""
    warnings = []
    # Check brace balance outside escaped braces
    cleaned = re.sub(r"\\[{}]", "", text)
    if cleaned.count("{") != cleaned.count("}"):
        warnings.append("Mismatched curly braces in LaTeX expression")
    # Check common commands that take 2 arguments like \frac
    fracs = re.findall(r"\\frac\s*({[^{}]*}|\S)", text)
    # Check for empty math blocks $$ or $$
    if re.search(r"\$\s*\$", text):
        warnings.append("Empty inline LaTeX delimiter found")
    return warnings


def _content_hash(q: Any) -> str:
    option_parts = []
    for option in sorted(getattr(q, "options", []), key=lambda x: x.position):
        normalised_option = re.sub(r"\s+", " ", option.text_md).strip().lower()
        option_label = option.label_printed or option.position
        option_parts.append(f"{option_label}:{normalised_option}")
    raw = "\n".join([
        (getattr(q, "subject", "") or "").lower(),
        (getattr(q, "question_type", "") or "").lower(),
        re.sub(r"\s+", " ", getattr(q, "stem_md", "")).strip().lower(),
        "|".join(option_parts),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_extracted_question(
    q: Any,
    taxonomy: dict[str, dict[str, Any]],
    existing_hashes: dict[str, str] | None = None,
) -> list[str]:
    """Validates a single question candidate, returning list of validation errors."""
    errors: list[str] = []
    prefix = f"Question ({getattr(q, 'source_question_key', 'UNKNOWN')})"

    qtype = getattr(q, "question_type", None)
    options = getattr(q, "options", [])
    answer = getattr(q, "answer", None)

    if qtype in {"mcq_single", "mcq_multi", "assertion_reason", "statement_based"}:
        if not options:
            errors.append(f"{prefix}: option-based question has no options")
        if not answer or answer.get("type") != "option":
            errors.append(f"{prefix}: option-based question requires answer.type=option")
        else:
            positions = answer.get("positions", [])
            valid_positions = {o.position for o in options}
            if not positions or any(p not in valid_positions for p in positions):
                errors.append(f"{prefix}: answer positions must exist in question_options")
            if len(set(positions)) != len(positions):
                errors.append(f"{prefix}: duplicate correct option positions are not allowed")
            if qtype == "mcq_single" and len(positions) != 1:
                errors.append(f"{prefix}: mcq_single requires exactly one correct position")
    elif qtype == "numerical":
        if not answer or answer.get("type") != "numeric":
            errors.append(f"{prefix}: numerical question requires answer.type=numeric")
        else:
            val = answer.get("value")
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                errors.append(f"{prefix}: numerical answer value must be numeric")
            tolerance = answer.get("tolerance", 0)
            if not isinstance(tolerance, (int, float)) or tolerance < 0:
                errors.append(f"{prefix}: numerical tolerance must be non-negative")
    elif qtype == "match_list":
        match_items = getattr(q, "match_items", [])
        if not answer or answer.get("type") != "match_list":
            errors.append(f"{prefix}: match_list question requires match_list answer")
        else:
            left_keys = {item.item_key for item in match_items if item.side == "left"}
            right_keys = {item.item_key for item in match_items if item.side == "right"}
            pairs = answer.get("pairs", [])
            if not left_keys or not right_keys or not pairs:
                errors.append(f"{prefix}: match_list requires left/right items and answer pairs")

    if getattr(q, "has_figure", False) != (getattr(q, "figure_status", "none") != "none"):
        errors.append(f"{prefix}: has_figure and figure_status disagree")

    tags = getattr(q, "tags", [])
    primary = [t for t in tags if getattr(t, "is_primary", False)]
    if len(primary) != 1:
        errors.append(f"{prefix}: exactly one primary taxonomy tag is required")

    subj = getattr(q, "subject", "") or ""
    expected_prefix = {"mathematics": "MAT.", "physics": "PHY.", "chemistry": "CHE."}.get(subj.lower())
    for tag in tags:
        t_code = getattr(tag, "code", tag.get("code") if isinstance(tag, dict) else str(tag))
        if t_code not in taxonomy:
            errors.append(f"{prefix}: unknown taxonomy code {t_code}")
        else:
            node = taxonomy[t_code]
            if not node.get("is_active", True):
                errors.append(f"{prefix}: taxonomy code {t_code} is inactive (deprecated/replaced)")
            if expected_prefix and not t_code.startswith(expected_prefix):
                errors.append(f"{prefix}: taxonomy code {t_code} does not belong to subject {subj}")

    stem_md = getattr(q, "stem_md", "") or ""
    if not stem_md.strip():
        errors.append(f"{prefix}: stem is empty")

    if stem_md.count("$") % 2 != 0:
        errors.append(f"{prefix}: unbalanced dollar delimiters in stem_md")

    expl_md = getattr(q, "explanation_md", None)
    if expl_md and expl_md.count("$") % 2 != 0:
        errors.append(f"{prefix}: unbalanced dollar delimiters in explanation_md")

    # Lightweight LaTeX warnings (flagged, never dropped)
    latex_warnings = _check_latex_sanity(stem_md)
    if expl_md:
        latex_warnings.extend(_check_latex_sanity(expl_md))
    if latex_warnings:
        flags = getattr(q, "flags", None)
        if isinstance(flags, dict):
            flags["latex_warnings"] = latex_warnings

    # Duplicate reporting
    c_hash = _content_hash(q)
    if existing_hashes and c_hash in existing_hashes:
        orig_key = existing_hashes[c_hash]
        flags = getattr(q, "flags", None)
        if isinstance(flags, dict):
            flags["possible_duplicate_of"] = orig_key

    return errors


def validate_import_file(path: Path, schema_path: Path, taxonomy: dict[str, dict[str, Any]]) -> tuple[ImportBundle | None, list[str]]:
    errors: list[str] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, [f"Invalid JSON: {exc}"]

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    errors.extend(f"JSON Schema: {e.message} at {list(e.absolute_path)}" for e in validator.iter_errors(data))
    if errors:
        return None, errors

    try:
        bundle = ImportBundle.model_validate(data)
    except Exception as exc:
        return None, [f"Model validation: {exc}"]

    seen_keys: set[str] = set()
    seen_hashes: dict[str, str] = {}
    for idx, q in enumerate(bundle.questions, 1):
        if q.source_question_key in seen_keys:
            errors.append(f"Question ({q.source_question_key}): duplicate source_question_key")
        seen_keys.add(q.source_question_key)

        q_errs = validate_extracted_question(q, taxonomy, existing_hashes=seen_hashes)
        errors.extend(q_errs)

        h = _content_hash(q)
        if h in seen_hashes:
            errors.append(f"Duplicate content hash within import: {h} ({q.source_question_key} duplicates {seen_hashes[h]})")
        else:
            seen_hashes[h] = q.source_question_key

    return bundle, errors
