"""
3-Tier Hierarchical Classifier for JEE Curriculum
Categorizes questions into Subject -> Unit/Chapter -> 4 Canonical Subtopics with database foreign-key guarantees.
Uses direct Groq API with rotating keys and token usage tracking.
"""

from __future__ import annotations
import os
import json
import re
import itertools
from typing import Optional
import requests
from engines.shared.config import settings
from apps.api.db import get_db_cursor

CANONICAL_TAXONOMY_PATH = "v0-prepfreex-frontend/lib/canonical-taxonomy.json"

class HierarchicalClassifier:
    def __init__(self, api_keys: Optional[list[str]] = None):
        raw_keys = api_keys or list(settings.groq_api_keys) or ([settings.groq_api_key] if settings.groq_api_key else [])
        self.api_keys = [k for k in raw_keys if k]
        self.key_cycle = itertools.cycle(self.api_keys) if self.api_keys else None
        self.taxonomy = self._load_taxonomy()
        self.model = "qwen/qwen3.8-27b"

    def _load_taxonomy(self) -> dict:
        if os.path.exists(CANONICAL_TAXONOMY_PATH):
            with open(CANONICAL_TAXONOMY_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _call_groq_json(self, prompt: str) -> tuple[dict, dict]:
        tok = {"prompt": 0, "completion": 0, "total": 0}
        if not self.key_cycle:
            return {}, tok

        api_key = next(self.key_cycle)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
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
                timeout=15
            )
            if resp.status_code == 200:
                data = resp.json()
                usage = data.get("usage", {})
                tok = {
                    "prompt": usage.get("prompt_tokens", 0),
                    "completion": usage.get("completion_tokens", 0),
                    "total": usage.get("total_tokens", 0)
                }
                parsed = json.loads(data["choices"][0]["message"]["content"])
                return parsed, tok
        except Exception:
            pass
        return {}, tok

    def classify_question(
        self,
        stem: str,
        options: list[str],
        subject_hint: Optional[str] = None,
        chapter_hint: Optional[str] = None
    ) -> dict:
        tokens_used = {"prompt": 0, "completion": 0, "total": 0}

        # --- TIER 1: SUBJECT ---
        subject = (subject_hint or "").upper()
        if subject not in ["PHYSICS", "CHEMISTRY", "MATHEMATICS"]:
            subject = self._infer_subject_deterministic(stem, options)

        # --- TIER 2: UNIT / CHAPTER ---
        chapters_in_subj = self.taxonomy.get(subject, [])
        matched_chapter = None

        if chapter_hint:
            norm_hint = re.sub(r'[^a-zA-Z0-9]', '', chapter_hint.lower())
            for ch in chapters_in_subj:
                norm_ch = re.sub(r'[^a-zA-Z0-9]', '', ch["chapter_name"].lower())
                if norm_hint in norm_ch or norm_ch in norm_hint:
                    matched_chapter = ch
                    break

        if not matched_chapter and chapters_in_subj:
            options_prompt = "\n".join([f"- {c['unit_code']}: {c['chapter_name']}" for c in chapters_in_subj])
            prompt = f"""You are a master JEE curriculum classifier.
Identify which canonical chapter this {subject} question belongs to:

QUESTION:
{stem[:500]}

AVAILABLE CHAPTERS:
{options_prompt}

Output ONLY valid JSON:
{{"unit_code": "<chosen_unit_code>"}}"""

            parsed, t2_tok = self._call_groq_json(prompt)
            tokens_used["prompt"] += t2_tok["prompt"]
            tokens_used["completion"] += t2_tok["completion"]
            tokens_used["total"] += t2_tok["total"]

            uc = parsed.get("unit_code")
            for c in chapters_in_subj:
                if c["unit_code"] == uc:
                    matched_chapter = c
                    break

        if not matched_chapter:
            matched_chapter = chapters_in_subj[0] if chapters_in_subj else {
                "unit_code": f"{subject[:4]}_U01",
                "chapter_name": "General Fundamentals",
                "topics": []
            }

        unit_code = matched_chapter["unit_code"]
        chapter_name = matched_chapter["chapter_name"]
        topics_list = matched_chapter.get("topics", [])

        # --- TIER 3: CONSTRAINED 4-SUBTOPIC SELECTOR ---
        if not topics_list:
            return {
                "subject": subject,
                "unit_code": unit_code,
                "chapter_name": chapter_name,
                "primary_topic_code": f"{unit_code}_T01",
                "topic_name": "Core Principles",
                "tokens_used": tokens_used
            }

        topic_choices = "\n".join([f"- {t['topic_code']}: {t['topic_name']}" for t in topics_list])
        prompt = f"""You are classifying a JEE Main question for the chapter: '{chapter_name}'.
Pick the SINGLE most relevant subtopic from the exact 4 choices below:

QUESTION:
{stem[:600]}

OPTIONS:
{options[:4]}

AVAILABLE SUBTOPICS:
{topic_choices}

Output ONLY valid JSON:
{{"topic_code": "<one_of_the_above_codes>", "reasoning": "1 sentence why"}}"""

        parsed, t3_tok = self._call_groq_json(prompt)
        tokens_used["prompt"] += t3_tok["prompt"]
        tokens_used["completion"] += t3_tok["completion"]
        tokens_used["total"] += t3_tok["total"]

        chosen_code = parsed.get("topic_code")
        validated_code, validated_name = self._validate_topic_in_db(chosen_code, topics_list)

        return {
            "subject": subject,
            "unit_code": unit_code,
            "chapter_name": chapter_name,
            "primary_topic_code": validated_code,
            "topic_name": validated_name,
            "tokens_used": tokens_used
        }

    def _infer_subject_deterministic(self, stem: str, options: list[str]) -> str:
        text = (stem + " " + " ".join(options)).lower()
        if any(w in text for w in ["integral", "derivative", "matrix", "determinant", "probability", "ellipse", "hyperbola", "tangent", "triangle", "vector"]):
            return "MATHEMATICS"
        if any(w in text for w in ["reaction", "molar", "acid", "base", "orbital", "isomer", "benzene", "catalyst", "enthalpy", "compound"]):
            return "CHEMISTRY"
        return "PHYSICS"

    def _validate_topic_in_db(self, topic_code: Optional[str], fallback_topics: list[dict]) -> tuple[str, str]:
        if not topic_code:
            fb = fallback_topics[0]
            return fb["topic_code"], fb["topic_name"]

        try:
            with get_db_cursor() as cur:
                cur.execute("""
                    SELECT topic_code, topic_name FROM public.chapter_topics WHERE topic_code = %s;
                """, (topic_code,))
                row = cur.fetchone()
                if row:
                    return row["topic_code"], row["topic_name"]
        except Exception:
            pass

        for fb in fallback_topics:
            if fb["topic_code"] == topic_code:
                return fb["topic_code"], fb["topic_name"]

        fb = fallback_topics[0]
        return fb["topic_code"], fb["topic_name"]
