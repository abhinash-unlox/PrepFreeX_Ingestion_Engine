from __future__ import annotations

import json
import re
from typing import Any

from engines.shared.groq_rotation import chat_with_rotation
from engines.shared.config import settings

VARIATION_SYSTEM_PROMPT = """You are an expert Indian JEE Main & Advanced question author, physicist, and mathematician.
Your mission is to generate high-quality, concept-preserving QUESTION VARIANTS from real canonical JEE questions.

Strict Principles of Variation:
1. PRESERVE CORE CONCEPTS: The fundamental physical/chemical law, mathematical theorem, or conceptual reasoning MUST remain identical to the original.
2. LOGICAL PARAMETER MUTATION: Mutate numerical values, constants, geometry, or algebraic coefficients into clean, realistic, solvable alternative numbers (e.g., standard angles, clean integer/fractional answers typical of JEE).
3. ACCURATE RECALCULATION: You must rigorously recalculate the new correct answer step-by-step.
4. CONSISTENT MCQ DISTRACTORS:
   - For MCQ Single Correct: Generate 4 distinct options (A, B, C, D). Exactly ONE must be mathematically correct.
   - The other 3 options must be plausible distractors representing common student sign errors, unit conversion slips, or typical JEE misconceptions.
   - For Numerical questions: The answer must be a clear single numeric value (e.g. 15, 2.5, 42).
5. STEP-BY-STEP DERIVATION & ZERO SCRATCHPAD LEAKAGE:
   - Provide a clean, direct Markdown explanation detailing the final derivation with KaTeX/LaTeX math ($...$ or $$...$$).
   - ABSOLUTE PROHIBITION: DO NOT write internal monologue, conversational debates ("Wait,", "Let's re-read", "Let's assume", "typo in the source", "to make it False"), or stream-of-consciousness inside explanation_md. Write ONLY the final textbook-clean derivation (under 150 words).
   - For multi-statement questions (A, B, C, etc.): Evaluate each statement cleanly (e.g. "(A) True: ...", "(B) False: ..."). The truth value of each statement MUST 100% match the chosen option combination in correct_answer. If you change a statement's truth value, the modified statement MUST be printed in stem_md!
6. ZERO DIAGRAM HALLUCINATION: If the original question relies on a visual diagram/circuit/figure, you MUST adapt the problem so it is fully described in prose/geometry OR strictly state why it requires no visual figure.
7. STRICT CLEAN JSON: Do NOT include unescaped raw newlines or illegal escape sequences inside JSON strings. Keep output compact (< 1500 tokens).

You MUST respond strictly in valid JSON format matching this exact schema:
{
  "scratchpad": "Internal validation/recalculation scratchpad (optional, never shown to student)",
  "stem_md": "Markdown question statement with LaTeX math",
  "question_type": "mcq_single" or "numerical",
  "options": [
    {"position": 1, "label_printed": "A", "text_md": "Option A text/math"},
    {"position": 2, "label_printed": "B", "text_md": "Option B text/math"},
    {"position": 3, "label_printed": "C", "text_md": "Option C text/math"},
    {"position": 4, "label_printed": "D", "text_md": "Option D text/math"}
  ],
  "correct_answer": {
    "type": "option", // or "numeric"
    "positions": [2], // 1-based index if option
    "value": 25.0,    // numeric value if numerical
    "tolerance": 0.0
  },
  "explanation_md": "Detailed textbook step-by-step derivation without internal monologue",
  "difficulty": 3, // 1 to 5
  "cognitive_level": "application", // conceptual, application, analytical
  "transformation_spec": {
    "parameters_changed": [
      {"parameter": "mass m", "original_value": "2 kg", "variant_value": "4 kg", "rationale": "Doubled mass to test inertia scaling"}
    ],
    "preserved_principles": ["Conservation of linear momentum", "Elastic collision coefficient e=1"],
    "difficulty_comparison": "Same difficulty as original (Level 3); tests identical formula with different clean algebra."
  }
}
"""

def generate_variant_with_groq(
    original_question: dict[str, Any],
    custom_guidance: str | None = None,
) -> dict[str, Any]:
    """Generates a mathematically sound JEE question variant from an original canonical question."""
    stem = original_question.get("stem_md", "")
    q_type = original_question.get("question_type", "mcq_single")
    subject = original_question.get("subject", "general")
    options = original_question.get("options", [])
    answer = original_question.get("answer", {})
    explanation = original_question.get("explanation_md", "")
    formulas = original_question.get("formulas_used", [])
    has_figure = original_question.get("has_figure", False)

    options_text = ""
    if options:
        for opt in options:
            options_text += f"- ({opt.get('label_printed', opt.get('position'))}) {opt.get('text_md', '')}\n"

    user_prompt = f"""### ORIGINAL JEE QUESTION SPECIFICATION
Subject: {subject.title()}
Question Type: {q_type}
Has Figure/Diagram: {has_figure}
Formulas: {', '.join(formulas) if formulas else 'Standard JEE syllabus'}

Original Stem:
{stem}

Original Options:
{options_text if options_text else 'None (Numerical/Integer question)'}

Original Answer:
{json.dumps(answer, ensure_ascii=False)}

Original Explanation / Derivation:
{explanation}
"""

    if custom_guidance:
        user_prompt += f"\nOperator Guidance:\n{custom_guidance}\n"

    user_prompt += "\nNow generate a new, concept-preserving, mathematically verified variant in the required JSON format."

    messages = [
        {"role": "system", "content": VARIATION_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    response = chat_with_rotation(
        messages=messages,
        model=settings.groq_model,
        temperature=0.2,
        response_format=None,
        max_tokens=2000,
    )

    content = response["choices"][0]["message"]["content"].strip()
    usage = response.get("usage", {})
    tokens_consumed = usage.get("total_tokens", 0)

    try:
        variant_data = json.loads(content, strict=False)
    except Exception:
        # Strip markdown code fences
        clean_c = re.sub(r"^```(?:json)?\s*", "", content.strip(), flags=re.MULTILINE)
        clean_c = re.sub(r"```\s*$", "", clean_c.strip(), flags=re.MULTILINE)
        
        match = re.search(r"\{.*\}", clean_c, re.DOTALL)
        if not match:
            raise ValueError(f"Groq did not return valid JSON: {content[:300]}")
        raw_json = match.group(0)
        
        try:
            variant_data = json.loads(raw_json, strict=False)
        except Exception:
            def fix_string_newlines(m):
                s_inner = m.group(1)
                s_inner = s_inner.replace("\r\n", "\\n").replace("\n", "\\n")
                s_inner = re.sub(r'\\([^"\\/bfnrtu])', r'\\\\\1', s_inner)
                return f'"{s_inner}"'

            fixed = re.sub(r'"((?:[^"\\]|\\.)*)"', fix_string_newlines, raw_json, flags=re.DOTALL)
            try:
                variant_data = json.loads(fixed, strict=False)
            except Exception:
                # Regex fallback extraction
                opts = []
                opt_blocks = re.findall(r'\{\s*"position"\s*:\s*(\d+)\s*,\s*"label_printed"\s*:\s*"([^"]+)"\s*,\s*"text_md"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}', raw_json, re.DOTALL)
                for pos, lbl, txt in opt_blocks:
                    opts.append({"position": int(pos), "label_printed": lbl, "text_md": txt.replace("\n", " ").strip()})

                stem_m = re.search(r'"stem_md"\s*:\s*"((?:[^"\\]|\\.)*)"', raw_json, re.DOTALL)
                stem_val = stem_m.group(1).replace("\n", " ").strip() if stem_m else original_question.get("stem_md", "")

                ans_pos_m = re.search(r'"positions"\s*:\s*\[\s*(\d+)\s*\]', raw_json)
                ans_val_m = re.search(r'"value"\s*:\s*([0-9\.\-]+)', raw_json)
                
                exp_m = re.search(r'"explanation_md"\s*:\s*"((?:[^"\\]|\\.)*)"', raw_json, re.DOTALL)
                exp_val = exp_m.group(1).replace("\n", " ").strip() if exp_m else "Generated derivation."

                variant_data = {
                    "stem_md": stem_val,
                    "question_type": "mcq_single" if opts else "numerical",
                    "options": opts,
                    "correct_answer": {
                        "type": "option" if opts else "numeric",
                        "positions": [int(ans_pos_m.group(1))] if ans_pos_m else [1],
                        "value": float(ans_val_m.group(1)) if ans_val_m else None,
                        "tolerance": 0.0
                    },
                    "explanation_md": exp_val,
                    "difficulty": 3,
                    "cognitive_level": "application",
                    "transformation_spec": {"parameters_changed": [], "preserved_principles": []}
                }

    # Clean and sanitize explanation_md
    exp = variant_data.get("explanation_md", "")
    if "<scratchpad>" in exp:
        sp_m = re.search(r"<scratchpad>(.*?)</scratchpad>", exp, flags=re.DOTALL | re.IGNORECASE)
        if sp_m:
            variant_data["scratchpad"] = sp_m.group(1).strip()
            exp = re.sub(r"<scratchpad>.*?</scratchpad>", "", exp, flags=re.DOTALL | re.IGNORECASE).strip()
            variant_data["explanation_md"] = exp

    variant_data["_tokens_consumed"] = tokens_consumed
    variant_data["_model"] = settings.groq_model
    return variant_data
