from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import Any, Optional

from apps.api.db import get_db_cursor
from engines.shared.groq_rotation import chat_with_rotation

logger = logging.getLogger(__name__)

GENERATOR_SYSTEM_PROMPT = """You are a senior Indian IIT JEE Main Chief Question Author and Subject Matter Expert.
Your task is to take a verified canonical JEE Main question and synthesize a high-calibre, mathematically robust VARIANT.

Strict Rules for Variant Generation:
1. PRESERVE THE DEEP CONCEPT: The fundamental theory, governing physics/chemistry/math equations, and cognitive level must remain identical.
2. SYSTEMATIC PARAMETRIC MUTATION:
   - Mutate numerical coefficients, physical constants, masses, angles, lengths, or chemical reagents into clean, realistic values.
   - Ensure calculations result in clean integer or simple fraction/decimal answers (no messy unapproximable numbers).
3. ABSOLUTE ARITHMETIC RIGOR:
   - Compute your exact numerical result step-by-step FIRST.
   - Explicitly verify your calculation (e.g. 2% + 2(3%) = 2% + 6% = 8%).
   - Ensure the correct option letter ('A', 'B', 'C', or 'D') EXACTLY points to the option containing your calculated result.
   - Double-check significant figure and decimal rounding rules according to standard JEE Main conventions.
4. FOUR DISTINCT PLAUSIBLE OPTIONS:
   - Generate exactly 4 distinct options ('A', 'B', 'C', 'D').
   - Include realistic distractors corresponding to common student pitfalls (e.g. forgotten factors of 2, sign errors, inverse square errors).
5. CONCISE SOLUTION:
   - Keep solution_latex clean, elegant, and directly to the point (< 120 words).
   - Do NOT include conversational filler, scratchpad monologue, or trial-and-error deliberations.
6. Output strictly JSON matching this schema:
{
  "stem": "Detailed question statement with LaTeX math wrapped in $...$",
  "options": [
    "Option A with $...$",
    "Option B with $...$",
    "Option C with $...$",
    "Option D with $...$"
  ],
  "correct_option": "A", // Exactly one of "A", "B", "C", "D"
  "solution_latex": "Step-by-step textbook derivation with LaTeX math wrapped in $...$"
}"""

BLIND_SOLVER_SYSTEM_PROMPT = """You are a JEE Advanced All India Rank 1 top competitive solver.
You are given a freshly authored question and multiple-choice options. You DO NOT know what the author claims the answer is.
Your task is to solve the problem from FIRST PRINCIPLES with 100% mathematical precision and select the single correct option.

Strict Rules:
1. Read the problem statement carefully and identify all given parameters.
2. Write out the exact physical/mathematical equations.
3. Perform the arithmetic step-by-step with absolute rigor.
4. Match your calculated result against the provided options ('A', 'B', 'C', 'D').
5. Output strictly JSON matching this schema:
{
  "derivation": "Step-by-step first-principles solution with equations in $...$",
  "calculated_value": "Final numerical or symbolic value obtained",
  "selected_option": "A" // Exactly one of "A", "B", "C", "D"
}"""


def _robust_json_loads(text: str) -> dict[str, Any] | None:
    """Robustly parse JSON object from LLM response text, handling unescaped LaTeX backslashes."""
    text = text.strip()
    if "```" in text:
        parts = text.split("```")
        for p in parts:
            p_clean = p.strip()
            if p_clean.startswith("json"):
                p_clean = p_clean[4:].strip()
            if p_clean.startswith("{") and p_clean.endswith("}"):
                text = p_clean
                break

    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        text = m.group(0)

    try:
        return json.loads(text, strict=False)
    except Exception:
        pass

    try:
        fixed = re.sub(r'\\([^\'"\\/bfnrtu]|u[0-9a-fA-F]{0,3}[^0-9a-fA-F]?)', r'\\\\\1', text)
        return json.loads(fixed, strict=False)
    except Exception:
        pass

    # Forgiving regex-based field extractor
    result = {}
    stem_m = re.search(r'"stem"\s*:\s*"(.*?)(?<!\\)"', text, re.DOTALL)
    if stem_m:
        result["stem"] = stem_m.group(1).encode().decode('unicode_escape', errors='ignore')

    opt_m = re.search(r'"selected_option"\s*:\s*"([A-D])"', text, re.IGNORECASE)
    if opt_m:
        result["selected_option"] = opt_m.group(1).upper()

    corr_m = re.search(r'"correct_option"\s*:\s*"([A-D])"', text, re.IGNORECASE)
    if corr_m:
        result["correct_option"] = corr_m.group(1).upper()

    options_m = re.search(r'"options"\s*:\s*\[(.*?)\]', text, re.DOTALL)
    if options_m:
        raw_opts = options_m.group(1)
        opts = re.findall(r'"(.*?)(?<!\\)"', raw_opts, re.DOTALL)
        result["options"] = [o.encode().decode('unicode_escape', errors='ignore') for o in opts]

    sol_m = re.search(r'"(solution_latex|derivation)"\s*:\s*"(.*?)(?<!\\)"', text, re.DOTALL)
    if sol_m:
        result[sol_m.group(1)] = sol_m.group(2).encode().decode('unicode_escape', errors='ignore')

    if ("selected_option" in result or "correct_option" in result) and ("stem" in result or "derivation" in result or "options" in result):
        return result

    return None


def generate_variant_candidate(seed_question: dict[str, Any]) -> dict[str, Any] | None:
    """Step 1: Generator Agent creates a mutated candidate question."""
    stem = seed_question.get("question_text_latex", "")
    opts = seed_question.get("options") or []
    if isinstance(opts, str):
        try: opts = json.loads(opts)
        except Exception: opts = []
    
    clean_opts = []
    for o in opts:
        if isinstance(o, dict): clean_opts.append(o.get("text", ""))
        else: clean_opts.append(str(o))

    user_prompt = f"""Subject: {seed_question.get('subject', 'Physics')}
Chapter: {seed_question.get('chapter_name', '')}
Topic: {seed_question.get('primary_topic_code', '')}

Original Question:
{stem}

Original Options:
A: {clean_opts[0] if len(clean_opts) > 0 else ''}
B: {clean_opts[1] if len(clean_opts) > 1 else ''}
C: {clean_opts[2] if len(clean_opts) > 2 else ''}
D: {clean_opts[3] if len(clean_opts) > 3 else ''}

Original Correct Option: {seed_question.get('correct_option', 'A')}
Original Solution:
{seed_question.get('solution_text_latex', '')[:400]}

Generate a fresh, mathematically sound variant JSON:"""

    try:
        resp = chat_with_rotation(
            messages=[
                {"role": "system", "content": GENERATOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3,
            max_tokens=1800
        )
        content = resp["choices"][0]["message"]["content"]
        data = _robust_json_loads(content)
        if not data or not data.get("stem") or not data.get("options") or not data.get("correct_option"):
            return None
        if len(data.get("options", [])) != 4:
            return None
        data["correct_option"] = str(data["correct_option"]).strip().upper()
        return data
    except Exception as e:
        logger.error(f"Generator Agent failed: {e}")
        return None


def blind_solve_candidate(candidate_stem: str, candidate_options: list[str]) -> dict[str, Any] | None:
    """Step 2: Blind Solver Agent solves candidate without seeing generator's answer key."""
    opts_str = "\n".join([f"Option {chr(65+i)}: {opt}" for i, opt in enumerate(candidate_options)])
    user_prompt = f"""Solve this question completely from first principles and select the correct option.

Question:
{candidate_stem}

Options:
{opts_str}

Output your step-by-step derivation and selected option in JSON:"""

    try:
        resp = chat_with_rotation(
            messages=[
                {"role": "system", "content": BLIND_SOLVER_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.0,
            max_tokens=1500
        )
        content = resp["choices"][0]["message"]["content"]
        data = _robust_json_loads(content)
        if not data or not data.get("selected_option"):
            print(f"[DEBUG BLIND SOLVER LEN]: {len(content)}")
            print(f"[DEBUG BLIND SOLVER TAIL]: {repr(content[-300:])}")
            return None
        data["selected_option"] = str(data["selected_option"]).strip().upper()
        return data
    except Exception as e:
        logger.error(f"Blind Solver Agent failed: {e}")
        return None


def verify_and_ingest_variant(seed_question: dict[str, Any], max_attempts: int = 3, dry_run: bool = False) -> dict[str, Any]:
    """Orchestrates: Generator -> Blind Solver -> Parity Arbiter -> DB Ingestion (with automatic retry on parity failure)."""
    t0 = time.perf_counter()
    result = {
        "seed_id": seed_question.get("id"),
        "seed_uid": seed_question.get("question_uid"),
        "topic_code": seed_question.get("primary_topic_code"),
        "parity_passed": False,
        "attempts_made": 0,
        "generator_candidate": None,
        "blind_solver_result": None,
        "ingested_id": None,
        "duration_sec": 0.0,
        "reason": ""
    }

    for attempt in range(1, max_attempts + 1):
        result["attempts_made"] = attempt
        candidate = generate_variant_candidate(seed_question)
        if not candidate:
            result["reason"] = f"Attempt {attempt}: Generator output invalid"
            continue
        result["generator_candidate"] = candidate

        solver_data = blind_solve_candidate(candidate["stem"], candidate["options"])
        if not solver_data:
            result["reason"] = f"Attempt {attempt}: Blind solver failed"
            continue
        result["blind_solver_result"] = solver_data

        gen_opt = candidate["correct_option"]
        solv_opt = solver_data["selected_option"]

        if gen_opt != solv_opt:
            result["reason"] = f"Attempt {attempt} PARITY FAILED: Generator claimed '{gen_opt}' but Blind Solver derived '{solv_opt}'"
            logger.warning(f"Seed {seed_question.get('id')} attempt {attempt} parity mismatch: {gen_opt} != {solv_opt}. Retrying...")
            continue

        # Parity Passed!
        result["parity_passed"] = True
        result["reason"] = f"PARITY VERIFIED on attempt {attempt}: Both agreed on Option {gen_opt}"
        break

    if not result["parity_passed"]:
        result["duration_sec"] = round(time.perf_counter() - t0, 2)
        return result

    # 4. Ingest into completed_questions
    if not dry_run:
        new_uid = f"var_{seed_question.get('primary_topic_code', 'GEN').lower()}_{uuid.uuid4().hex[:10]}"
        options_json = json.dumps([{"identifier": chr(65+idx), "text": opt} for idx, opt in enumerate(candidate["options"])])
        tags_json = json.dumps([
            "AI_VERIFIED_VARIANT",
            f"PARENT_SEED_ID: {seed_question.get('id')}",
            f"PARENT_SEED_UID: {seed_question.get('question_uid')}",
            f"BLIND_SOLVER_AGREEMENT: {gen_opt}"
        ])

        with get_db_cursor() as cur:
            cur.execute("""
                INSERT INTO public.completed_questions (
                    question_uid,
                    unit_code,
                    chapter_name,
                    subject,
                    subtopic_id,
                    primary_topic_code,
                    question_type,
                    question_text_latex,
                    options,
                    correct_option,
                    numerical_target,
                    solution_text_latex,
                    has_diagram,
                    difficulty_tier,
                    tags,
                    academic_status,
                    assessment_status,
                    is_synthetic,
                    concise_explanation
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s
                ) RETURNING id;
            """, (
                new_uid,
                seed_question.get("unit_code"),
                seed_question.get("chapter_name"),
                seed_question.get("subject"),
                seed_question.get("subtopic_id"),
                seed_question.get("primary_topic_code"),
                seed_question.get("question_type") or "SINGLE_CHOICE",
                candidate["stem"],
                options_json,
                gen_opt,
                None,
                candidate.get("solution_latex", "") + "\n\n**Blind Verification Proof:**\n" + solver_data.get("derivation", ""),
                False,
                seed_question.get("difficulty_tier") or "Tier 2",
                tags_json,
                "AI_VERIFIED_VARIANT",
                "ELIGIBLE",
                True,
                candidate.get("solution_latex", "")[:250]
            ))
            inserted = cur.fetchone()
            if inserted:
                result["ingested_id"] = inserted["id"]

    result["duration_sec"] = round(time.perf_counter() - t0, 2)
    return result
