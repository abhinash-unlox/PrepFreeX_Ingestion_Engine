import os
import re
import time
import json
import httpx
from typing import Optional, Dict, Any
from dotenv import load_dotenv

load_dotenv()

raw_keys = os.getenv("GROQ_API_KEYS", "") or os.getenv("GROQ_API_KEY", "")
GROQ_KEYS = [k.strip() for k in raw_keys.replace("\n", ",").split(",") if k.strip()]
if not GROQ_KEYS:
    GROQ_KEYS = [os.getenv("GROQ_API_KEY", "")]

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")

_key_idx = 0

def get_next_key() -> str:
    global _key_idx
    k = GROQ_KEYS[_key_idx % len(GROQ_KEYS)]
    _key_idx += 1
    return k

def ensure_math_wrapped(val: str) -> str:
    """Wraps bare LaTeX notation in $...$ so KaTeX renders it flawlessly, preventing nested $$."""
    if not val or not isinstance(val, str):
        return ""
    s = val.strip()
    if not s:
        return ""
    # If already contains $, math delimiters are present
    if "$" in s:
        return s
    # If contains raw LaTeX math commands without $, wrap the mathematical expression
    has_latex = bool(re.search(r'\\(?:text|cdot|times|frac|mu|alpha|beta|sigma|theta|Delta|pm|mp)\b', s))
    if has_latex:
        return f"${s}$"
    return s

def generate_groq_review_item(
    stem: str,
    options: list[str],
    user_label: str,
    correct_label: str,
    subject: str = "Physics"
) -> Dict[str, str]:
    """Generates clean LaTeX formatted user_answer, correct_answer, and 2-3 line concise explanation via Groq."""
    opts_str = ""
    if isinstance(options, list):
        opts_str = "\n".join([f"{chr(65+i)}: {str(o)}" for i, o in enumerate(options[:4])])
    elif options:
        opts_str = str(options)

    prompt = (
        f"Question: {stem}\n"
        f"Options:\n{opts_str}\n\n"
        f"User Selected Option Label: {user_label or 'Not answered'}\n"
        f"Verified Correct Option Label: {correct_label}\n\n"
        "Return a valid JSON object with exactly three string keys:\n"
        "1. 'user_answer': The student's chosen option letter and its mathematical content with complete, valid LaTeX math wrapped in $...$ (e.g. 'B — $5.4 \\times 10^5$' or 'Not answered').\n"
        "2. 'correct_answer': The verified option letter and its mathematical content with complete, valid LaTeX math wrapped in $...$ (e.g. 'C — $6.67 \\times 10^{-8}\\text{ dyne}\\cdot\\text{cm}^2/\\text{g}^2$').\n"
        "3. 'concise_explanation': Strictly 2 to 3 lines explaining the physical reasoning and calculation leading to the correct answer. Use clean LaTeX math ($...$). No conversational filler."
    )

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": f"You are a master JEE {subject} coach. Output strictly valid JSON with zero latex errors."},
            {"role": "user", "content": prompt}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
        "max_tokens": 300
    }

    max_attempts = max(3, len(GROQ_KEYS))
    for attempt in range(max_attempts):
        key = get_next_key()
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"
        }
        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.post(GROQ_URL, headers=headers, json=payload)
                if res.status_code == 429:
                    time.sleep(0.5)
                    continue
                if res.status_code == 200:
                    data = res.json()
                    content = data["choices"][0]["message"]["content"].strip()
                    parsed = json.loads(content)
                    return {
                        "user_answer": parsed.get("user_answer", ""),
                        "correct_answer": parsed.get("correct_answer", ""),
                        "concise_explanation": parsed.get("concise_explanation", "")
                    }
        except Exception:
            continue

    return {}
