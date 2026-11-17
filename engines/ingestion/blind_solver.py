"""
AIR-1 Blind Solver & Parity Arbiter
Solves questions without seeing the extracted answer key to detect Qwen extraction errors or wrong answer keys.
"""

from __future__ import annotations
import json
import itertools
from typing import Optional
import requests
from engines.shared.config import settings

class BlindSolver:
    def __init__(self, api_keys: Optional[list[str]] = None):
        raw_keys = api_keys or list(settings.groq_api_keys) or ([settings.groq_api_key] if settings.groq_api_key else [])
        self.api_keys = [k for k in raw_keys if k]
        self.key_cycle = itertools.cycle(self.api_keys) if self.api_keys else None
        self.model = "openai/gpt-oss-120b"

    def solve_blind(
        self,
        stem: str,
        options: list[str],
        question_type: str = "SINGLE_CHOICE",
        extracted_answer: Optional[str] = None
    ) -> dict:
        """
        Solves the question independently.
        Returns:
            solver_option: 'A', 'B', 'C', 'D' or numerical string
            reasoning: step-by-step LaTeX proof
            solver_status: 'MATCHED' or 'DISCREPANCY'
            tokens_used: dict
        """
        tokens_used = {"prompt": 0, "completion": 0, "total": 0}
        if not self.key_cycle:
            return {
                "solver_option": None,
                "reasoning": "Solver skipped (No API key)",
                "solver_status": "SKIPPED",
                "tokens_used": tokens_used
            }

        api_key = next(self.key_cycle)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        formatted_opts = ""
        for idx, o in enumerate(options[:4]):
            formatted_opts += f"Option {chr(65 + idx)}: {o}\n"

        prompt = f"""You are an AIR-1 JEE Advanced solver.
Solve the following question with rigorous mathematical and physical reasoning.
DO NOT assume any pre-existing answer key. Compute the result from first principles.

QUESTION:
{stem}

OPTIONS:
{formatted_opts}

Return your solution strictly as valid JSON:
{{
  "step_by_step_solution": "Concise step-by-step derivation with formulas in LaTeX $...$",
  "correct_option": "A, B, C, or D",
  "final_answer_value": "The computed value if numerical"
}}"""

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "response_format": {"type": "json_object"}
        }

        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json=payload,
                headers=headers,
                timeout=25
            )
            if resp.status_code == 200:
                data = resp.json()
                usage = data.get("usage", {})
                tokens_used = {
                    "prompt": usage.get("prompt_tokens", 0),
                    "completion": usage.get("completion_tokens", 0),
                    "total": usage.get("total_tokens", 0)
                }
                parsed = json.loads(data["choices"][0]["message"]["content"])
                sol_opt = (parsed.get("correct_option") or "").strip().upper()
                if len(sol_opt) > 1:
                    # e.g. "OPTION A" -> "A"
                    for char in ["A", "B", "C", "D"]:
                        if char in sol_opt:
                            sol_opt = char
                            break

                reasoning = parsed.get("step_by_step_solution") or ""

                # Parity Check
                clean_extracted = (extracted_answer or "").strip().upper()
                if clean_extracted and sol_opt:
                    status = "MATCHED" if sol_opt == clean_extracted else "DISCREPANCY"
                else:
                    status = "UNVERIFIED"

                return {
                    "solver_option": sol_opt,
                    "reasoning": reasoning,
                    "solver_status": status,
                    "tokens_used": tokens_used
                }
        except Exception as e:
            return {
                "solver_option": None,
                "reasoning": f"Solver error: {e}",
                "solver_status": "ERROR",
                "tokens_used": tokens_used
            }

        return {
            "solver_option": None,
            "reasoning": "Solver failed to return 200 OK",
            "solver_status": "FAILED",
            "tokens_used": tokens_used
        }
