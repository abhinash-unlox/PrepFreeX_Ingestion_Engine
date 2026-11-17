from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from engines.shared.groq_rotation import chat_with_rotation

logger = logging.getLogger(__name__)

FAST_MUTATE_SYSTEM_PROMPT = """You are an expert Indian JEE Main question author and physicist/mathematician.
Your task is to mutate the numerical values or variables of the given question to create a fresh, high-quality variant.

Strict Rules:
1. PRESERVE THE CORE CONCEPT: The physics/chemistry/math theory, formula, and conceptual reasoning must remain identical to the original question.
2. CLEAN NUMBERS: Change given numbers, masses, angles, lengths, or coefficients into clean, realistic numbers that lead to clean solutions.
3. RECALCULATE ACCURATELY: Solve the problem with the new numbers and determine the new correct option.
4. FOUR DISTINCT OPTIONS: Generate 4 distinct options (Option A, Option B, Option C, Option D) with LaTeX math ($...$).
5. DO NOT output any scratchpad, markdown code fences, or internal deliberations.
6. Output ONLY a valid JSON object matching this exact schema:
{
  "stem": "Mutated question statement with $...$ for math expressions",
  "options": ["Option A text/math", "Option B text/math", "Option C text/math", "Option D text/math"],
  "correct_option": "A", // Exactly one of "A", "B", "C", "D"
  "explanation": "2-3 lines concise textbook derivation with math wrapped in $...$."
}"""


def fast_mutate_question(canonical_question: dict[str, Any]) -> dict[str, Any] | None:
    """Mutates a canonical question using Groq to produce new values, recalculated options, and solution."""
    stem = canonical_question.get("question_text_latex", "")
    if not stem or len(stem.strip()) < 10:
        return None

    opts = canonical_question.get("options") or []
    if isinstance(opts, str):
        try:
            opts = json.loads(opts)
        except Exception:
            opts = []
    
    clean_opts = []
    for o in opts:
        if isinstance(o, dict):
            clean_opts.append(o.get("text") or str(o))
        else:
            clean_opts.append(str(o))

    prompt = (
        f"Original Subject: {canonical_question.get('subject', 'Physics')}\n"
        f"Original Chapter: {canonical_question.get('chapter_name', '')}\n"
        f"Original Question:\n{stem}\n"
        f"Original Options:\n{clean_opts}\n"
        f"Original Answer: Option {canonical_question.get('correct_option', 'A')}\n\n"
        "Generate fresh variant JSON:"
    )

    try:
        t0 = time.perf_counter()
        resp = chat_with_rotation(
            messages=[
                {"role": "system", "content": FAST_MUTATE_SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            max_tokens=700
        )
        elapsed = time.perf_counter() - t0

        raw = resp["choices"][0]["message"]["content"].strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        # Parse JSON
        data = json.loads(raw)
        
        # Validation checks
        if not data.get("stem") or not data.get("options") or len(data["options"]) < 4:
            logger.warning(f"Groq variant incomplete for question {canonical_question.get('id')}")
            return None

        corr = str(data.get("correct_option", "A")).strip().upper()
        if corr not in ("A", "B", "C", "D"):
            corr = "A"

        data["correct_option"] = corr
        data["elapsed_seconds"] = round(elapsed, 2)
        return data

    except Exception as e:
        logger.warning(f"Groq variant generation failed for question {canonical_question.get('id')}: {e}")
        return None

