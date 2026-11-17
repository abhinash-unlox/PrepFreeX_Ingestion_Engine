from __future__ import annotations

import json
import re
from typing import Any

from engines.shared.groq_rotation import chat_with_rotation
from engines.shared.config import settings
from engines.variation.deterministic_validator import (
    validate_math_deterministically,
    validate_physics_deterministically,
    validate_chemistry_deterministically,
    validate_mcq_options,
    analyze_difficulty_drift,
)

FORBIDDEN_SCRATCHPAD_PATTERNS = [
    r"\bwait\b",
    r"\blet's re-read\b",
    r"\blet's assume\b",
    r"\blet's adjust\b",
    r"\btypo in the source\b",
    r"\bto make it false\b",
    r"\bto make it true\b",
    r"\bconsistent with the original's intent\b",
    r"\bah,\b",
    r"\bi will change\b",
    r"\bmy variant\b",
]

def validate_scratchpad_absence(variant: dict[str, Any]) -> dict[str, Any]:
    """Validates that explanation_md does not contain LLM deliberation, internal debates, or scratchpad leakage."""
    explanation = variant.get("explanation_md", "")
    
    # Check for <scratchpad> tags
    if "<scratchpad>" in explanation:
        sp_match = re.search(r"<scratchpad>(.*?)</scratchpad>", explanation, flags=re.DOTALL | re.IGNORECASE)
        if sp_match:
            variant["scratchpad"] = sp_match.group(1).strip()
            explanation = re.sub(r"<scratchpad>.*?</scratchpad>", "", explanation, flags=re.DOTALL | re.IGNORECASE).strip()
            variant["explanation_md"] = explanation

    errors = []
    for pat in FORBIDDEN_SCRATCHPAD_PATTERNS:
        if re.search(pat, explanation, flags=re.IGNORECASE):
            errors.append(f"Forbidden conversational deliberation pattern detected: '{pat}'")

    return {
        "passed": len(errors) == 0,
        "errors": errors,
        "sanitized_explanation": explanation
    }

def validate_multi_statement_consistency(variant: dict[str, Any]) -> dict[str, Any]:
    """For questions evaluating multiple statements (A, B, C, etc.), verifies that the
    individual statement truth values deduced in the explanation match the claimed correct option.
    """
    stem = variant.get("stem_md", "")
    explanation = variant.get("explanation_md", "")
    options = variant.get("options", [])
    correct_ans = variant.get("correct_answer", {})
    
    stmt_matches = re.findall(r"\b([A-E])\.\s+[A-Z]", stem)
    if len(stmt_matches) < 2:
        return {"passed": True, "details": "Not a multi-statement question"}
    
    true_stmts = set()
    false_stmts = set()
    
    for stmt in ["A", "B", "C", "D", "E"]:
        true_pat = rf"(?:\({stmt}\)|Statement\s+{stmt}|Statement\s+\({stmt}\))[:\s\*\-]+(?:is\s+)?(?:\*\*)?True\b"
        false_pat = rf"(?:\({stmt}\)|Statement\s+{stmt}|Statement\s+\({stmt}\))[:\s\*\-]+(?:is\s+)?(?:\*\*)?False\b"
        
        has_true = bool(re.search(true_pat, explanation, flags=re.IGNORECASE))
        has_false = bool(re.search(false_pat, explanation, flags=re.IGNORECASE))
        
        if has_true and has_false:
            t_idx = max([m.start() for m in re.finditer(true_pat, explanation, flags=re.IGNORECASE)])
            f_idx = max([m.start() for m in re.finditer(false_pat, explanation, flags=re.IGNORECASE)])
            if t_idx > f_idx:
                true_stmts.add(stmt)
            else:
                false_stmts.add(stmt)
        elif has_true:
            true_stmts.add(stmt)
        elif has_false:
            false_stmts.add(stmt)
            
    summary_match = re.search(r"Correct\s+statements?:?\s*([A-E,\s\band]+)", explanation, flags=re.IGNORECASE)
    if summary_match:
        summary_raw = summary_match.group(1).upper()
        summary_stmts = set(re.findall(r"\b([A-E])\b", summary_raw))
        if summary_stmts:
            true_stmts = summary_stmts
            
    if not true_stmts:
        return {"passed": True, "details": "No explicit statement truth breakdown found in explanation"}
        
    pos = correct_ans.get("positions", [])
    if not pos or pos[0] < 1 or pos[0] > len(options):
        return {"passed": False, "errors": ["Invalid option position"]}
        
    chosen_opt = options[pos[0] - 1]
    chosen_text = chosen_opt.get("text_md", "") if isinstance(chosen_opt, dict) else str(chosen_opt)
    
    chosen_claimed = set(re.findall(r"\b([A-E])\b", chosen_text.upper()))
    
    if chosen_claimed:
        if chosen_claimed != true_stmts:
            return {
                "passed": False,
                "errors": [
                    f"Logical contradiction: Explanation evaluates correct statements as {sorted(list(true_stmts))}, "
                    f"but chosen Option ({pos[0]}: '{chosen_text}') specifies {sorted(list(chosen_claimed))}."
                ]
            }
            
    return {"passed": True, "true_statements": sorted(list(true_stmts))}

def run_comprehensive_validation(
    variant: dict[str, Any],
    orig_q: dict[str, Any],
    groq_review: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Runs all validation tiers: structural, domain deterministic, options, difficulty drift, and assigns segregated status."""
    structural = validate_structural(variant)
    mcq = validate_mcq_options(variant)
    scratchpad = validate_scratchpad_absence(variant)
    multi_stmt = validate_multi_statement_consistency(variant)
    
    subject = orig_q.get("subject", "").lower()
    if subject == "mathematics":
        deterministic = validate_math_deterministically(variant)
    elif subject == "physics":
        deterministic = validate_physics_deterministically(variant, orig_q)
    elif subject == "chemistry":
        deterministic = validate_chemistry_deterministically(variant)
    else:
        deterministic = {"domain": subject, "verified": False, "discrepancy": "No domain validator"}

    difficulty = analyze_difficulty_drift(orig_q, variant)
    
    # Determine Segregated Status:
    has_structural_error = not structural["passed"] or not mcq["distinct_options"] or not mcq["single_correct_key"]
    has_scratchpad_error = not scratchpad["passed"]
    has_multi_stmt_error = not multi_stmt["passed"]
    has_deterministic_flaw = bool(deterministic.get("discrepancy"))
    llm_verdict = groq_review.get("overall_verdict") if groq_review else None
    
    all_errors = list(structural.get("errors", [])) + list(scratchpad.get("errors", [])) + list(multi_stmt.get("errors", []))
    if has_deterministic_flaw:
        all_errors.append(deterministic.get("discrepancy"))
    
    if has_structural_error or has_scratchpad_error or has_multi_stmt_error or has_deterministic_flaw or llm_verdict == "REJECTED":
        status = "REJECTED"
    elif deterministic.get("verified"):
        status = "MACHINE_VERIFIED"
    elif llm_verdict == "APPROVED" and structural["passed"]:
        status = "LLM_REVIEWED"
    elif structural["passed"]:
        status = "STRUCTURALLY_VALID"
    else:
        status = "NEEDS_REVIEW"

    return {
        "status": status,
        "errors": all_errors,
        "structural": structural,
        "mcq_options": mcq,
        "scratchpad": scratchpad,
        "multi_statement": multi_stmt,
        "deterministic": deterministic,
        "difficulty": difficulty,
    }

def validate_structural(variant: dict[str, Any]) -> dict[str, Any]:
    """Validates basic structure, options uniqueness, non-empty stem, answer formatting."""
    checks = {
        "has_stem": bool(variant.get("stem_md", "").strip()),
        "has_explanation": bool(variant.get("explanation_md", "").strip()),
        "valid_question_type": variant.get("question_type") in ("mcq_single", "mcq_multiple", "numerical"),
        "options_distinct": True,
        "correct_answer_valid": True,
        "latex_balanced": True,
        "warnings": [],
        "errors": [],
    }

    stem = variant.get("stem_md", "")
    q_type = variant.get("question_type")
    options = variant.get("options", [])
    answer = variant.get("correct_answer", {})

    # Check LaTeX math dollar sign parity
    dollar_count = stem.count("$")
    if dollar_count % 2 != 0:
        checks["latex_balanced"] = False
        checks["warnings"].append("Question stem has unbalanced LaTeX math dollar signs ($).")

    if q_type == "mcq_single":
        if len(options) != 4:
            checks["errors"].append(f"Expected 4 options for mcq_single, found {len(options)}.")
        texts = [opt.get("text_md", "").strip().lower() for opt in options]
        if len(set(texts)) != len(texts):
            checks["options_distinct"] = False
            checks["errors"].append("Multiple options contain duplicate text/answers.")

        ans_pos = answer.get("positions", [])
        if not ans_pos or len(ans_pos) != 1 or ans_pos[0] not in [1, 2, 3, 4]:
            checks["correct_answer_valid"] = False
            checks["errors"].append(f"Invalid answer positions {ans_pos} for mcq_single.")
    elif q_type == "numerical":
        if "value" not in answer:
            checks["correct_answer_valid"] = False
            checks["errors"].append("Numerical question must specify a 'value' in correct_answer.")

    checks["passed"] = len(checks["errors"]) == 0
    return checks


def review_variant_with_groq(
    original_question: dict[str, Any],
    variant_data: dict[str, Any],
) -> dict[str, Any]:
    """Uses Groq in an independent verification persona to independently check math and validity."""
    system_prompt = """You are a rigorous Senior JEE Math & Science Content Auditor.
Your job is to independently verify whether a newly generated question variant:
1. Is mathematically and scientifically 100% correct.
2. Has exact step-by-step math that matches its stated correct answer.
3. Has 3 plausible distractors (for MCQ) with zero duplicate options.
4. Preserves the exact concepts of the original question while introducing logical new values.
5. Has no ambiguous phrasing or missing parameters.

Return strictly JSON:
{
  "mathematically_sound": true or false,
  "concept_preserved": true or false,
  "solvable_with_given_info": true or false,
  "calculated_answer_matches": true or false,
  "independent_solution_summary": "Short 2-line independent derivation of the new answer",
  "identified_flaws_or_discrepancies": "None" or detailed description of errors,
  "overall_verdict": "APPROVED" or "NEEDS_REVISION" or "REJECTED"
}
"""

    user_prompt = f"""### ORIGINAL QUESTION
Stem: {original_question.get('stem_md')}
Answer: {json.dumps(original_question.get('answer'))}

### GENERATED VARIANT TO AUDIT
Stem: {variant_data.get('stem_md')}
Question Type: {variant_data.get('question_type')}
Options: {json.dumps(variant_data.get('options'))}
Claimed Correct Answer: {json.dumps(variant_data.get('correct_answer'))}
Claimed Explanation: {variant_data.get('explanation_md')}
Transformation Spec: {json.dumps(variant_data.get('transformation_spec'))}

Please audit the variant thoroughly and output JSON.
"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        response = chat_with_rotation(
            messages=messages,
            model=settings.groq_model,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        content = response["choices"][0]["message"]["content"].strip()
        audit = json.loads(content)
        audit["_review_tokens"] = response.get("usage", {}).get("total_tokens", 0)
        return audit
    except Exception as e:
        return {
            "mathematically_sound": False,
            "concept_preserved": True,
            "solvable_with_given_info": True,
            "calculated_answer_matches": False,
            "identified_flaws_or_discrepancies": f"LLM Reviewer Exception: {str(e)}",
            "overall_verdict": "NEEDS_REVISION",
        }

