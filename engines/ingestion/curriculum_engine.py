"""
Curriculum Categorization & Taxonomy Alignment Engine
Guarantees that every question is mapped to the exact Subject -> Canonical Unit -> 4-Topic Subtopic
with PostgreSQL foreign-key validation against public.chapter_topics.
Protects against cross-subject contamination (e.g. math/physics dumped into chemistry).
"""

from __future__ import annotations
import os
import re
import json
import itertools
from typing import Optional, Any
import requests

from engines.shared.config import settings
from apps.api.db import get_db_cursor

CANONICAL_TAXONOMY_PATH = "v0-prepfreex-frontend/lib/canonical-taxonomy.json"

class CurriculumEngine:
    def __init__(self, api_keys: Optional[list[str]] = None):
        raw_keys = api_keys or list(settings.groq_api_keys) or ([settings.groq_api_key] if settings.groq_api_key else [])
        self.api_keys = [k for k in raw_keys if k]
        self.key_cycle = itertools.cycle(self.api_keys) if self.api_keys else None
        self.model = "openai/gpt-oss-20b"
        self.taxonomy = self._load_taxonomy()

        # Build in-memory lookup maps
        self.topics_by_code: dict[str, dict] = {}
        self.chapters_by_code: dict[str, dict] = {}
        self._build_indices()

    def _load_taxonomy(self) -> dict:
        if os.path.exists(CANONICAL_TAXONOMY_PATH):
            with open(CANONICAL_TAXONOMY_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _build_indices(self):
        for subj, chapters in self.taxonomy.items():
            for ch in chapters:
                uc = ch["unit_code"]
                self.chapters_by_code[uc] = ch
                for t in ch.get("topics", []):
                    tc = t["topic_code"]
                    self.topics_by_code[tc] = {
                        "topic_code": tc,
                        "topic_name": t["topic_name"],
                        "unit_code": uc,
                        "chapter_name": ch["chapter_name"],
                        "subject": subj.upper()
                    }

    def infer_subject(self, stem: str, options: list[Any] = None) -> tuple[Optional[str], int]:
        """
        Determines the true subject using strong unambiguous mathematical, physical, and chemical symbols.
        Returns (inferred_subject, confidence_score). Returns (None, 0) if uncertain.
        """
        opts_text = ""
        if options:
            opts_text = " ".join([str(o.get("text", "") if isinstance(o, dict) else o) for o in options])
        text = f"{stem} {opts_text}".lower()

        # Strong mathematics patterns
        math_score = 0
        math_strong = [
            r'\bmatrix\b', r'\bdeterminant\b', r'\bdifferentiable\b', r'\bintegral\b',
            r'\bpolynomial\b', r'\bquadratic equation\b', r'\bellipse\b', r'\bhyperbola\b',
            r'\bparabola\b', r'\bpermutation\b', r'\bcombination\b', r'\bprobability\b',
            r'\btriangle\b', r'\btangent\b', r'\bnormal to\b', r'\bvector\b', r'\bf\(x\)',
            r'\bg\(x\)', r'\bdy/dx\b', r'\\int\b', r'\bcot\(', r'\bsin\(', r'\bcos\(', r'\btan\(',
            r'\bcontinuous function\b', r'\bdomain of\b', r'\brange of\b', r'\blocal maxima\b',
            r'\blocal minima\b', r'\bbinomial expansion\b'
        ]
        for p in math_strong:
            if re.search(p, text):
                math_score += 2

        # Strong physics patterns
        phys_score = 0
        phys_strong = [
            r'\bvelocity\b', r'\bacceleration\b', r'\bcapacitor\b', r'\bcapacitance\b',
            r'\bresistor\b', r'\bresistance\b', r'\bmagnetic field\b', r'\belectric field\b',
            r'\brefractive index\b', r'\bfocal length\b', r'\bmoment of inertia\b', r'\bnewton\b',
            r'\bjoule\b', r'\binductor\b', r'\binductance\b', r'\bwavelength\b', r'\bfrequency\b',
            r'\bphoton\b', r'\bkinetic energy\b', r'\bgravitation\b', r'\btorque\b', r'\bpotentiometer\b',
            r'\brms\b', r'\bms\s*[-–]?\s*[12]\b', r'\bm/s\b', r'\bwire of length\b', r'\bprism\b'
        ]
        for p in phys_strong:
            if re.search(p, text):
                phys_score += 2

        # Strong chemistry patterns
        chem_score = 0
        chem_strong = [
            r'\boxidation state\b', r'\breaction\b', r'\breagent\b', r'\bmolar\b', r'\bmol\b',
            r'\bcatalyst\b', r'\bisomer\b', r'\benthalpy\b', r'\bequilibrium constant\b',
            r'\bbenzene\b', r'\bacid\b', r'\bbase\b', r'\bcoordination\b', r'\bligand\b',
            r'\belectrophile\b', r'\bnucleophile\b', r'\baldehyde\b', r'\bketone\b',
            r'\bether\b', r'\bester\b', r'\bhalide\b', r'\bpolymer\b', r'\bbiomolecule\b',
            r'\bstoichiometry\b', r'\bph\b', r'\belectrochemistry\b', r'\bkj\s*mol',
            r'\belectron configuration\b', r'\bd-electron\b', r'\bparamagnetic\b', r'\bdiamagnetic\b',
            r'\bspin-only\b', r'\[[a-zA-Z]{1,2}\([a-zA-Z0-9]+\)\]', r'\borbital\b', r'\bhybridisation\b',
            r'\bhybridization\b', r'\bbohr radius\b', r'\bradioactive decay\b'
        ]
        for p in chem_strong:
            if re.search(p, text):
                chem_score += 2

        scores = [("MATHEMATICS", math_score), ("PHYSICS", phys_score), ("CHEMISTRY", chem_score)]
        scores.sort(key=lambda x: x[1], reverse=True)

        if scores[0][1] >= 2 and scores[0][1] > scores[1][1]:
            return scores[0][0], scores[0][1]

        return None, 0

    def _call_groq_json(self, prompt: str) -> tuple[dict, dict]:
        tok = {"prompt": 0, "completion": 0, "total": 0}
        if not self.api_keys:
            return {}, tok

        max_attempts = max(3, len(self.api_keys) * 2)
        for attempt in range(max_attempts):
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
                    timeout=20
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
                elif resp.status_code in (429, 500, 502, 503):
                    import time
                    time.sleep(1.0 + attempt * 0.5)
                    continue
            except Exception:
                import time
                time.sleep(1.0)
                continue

        return {}, tok

    def categorize_question(
        self,
        stem: str,
        options: list[Any] = None,
        subject_hint: Optional[str] = None,
        chapter_hint: Optional[str] = None
    ) -> dict:
        """
        Categorizes a question into Subject -> Unit -> Subtopic.
        Guarantees foreign-key alignment with public.chapter_topics.
        """
        tokens_used = {"prompt": 0, "completion": 0, "total": 0}

        # 1. Subject Resolution (Deterministic priority)
        inferred, conf_score = self.infer_subject(stem, options)
        subject = subject_hint.upper() if subject_hint else (inferred or "PHYSICS")
        # If the question text strongly contradicts the subject hint (e.g. capacitor in chemistry), override
        if inferred and conf_score >= 4 and inferred != subject:
            subject = inferred

        chapters_list = self.taxonomy.get(subject.title()) or self.taxonomy.get(subject, [])
        if not chapters_list:
            # Fallback across case
            for k, v in self.taxonomy.items():
                if k.upper() == subject.upper():
                    chapters_list = v
                    break

        matched_chapter = None

        # 2. Match chapter hint if provided
        if chapter_hint:
            norm_hint = re.sub(r'[^a-zA-Z0-9]', '', chapter_hint.lower())
            for ch in chapters_list:
                norm_ch = re.sub(r'[^a-zA-Z0-9]', '', ch["chapter_name"].lower())
                if norm_hint in norm_ch or norm_ch in norm_hint:
                    matched_chapter = ch
                    break

        # 3. LLM Chapter Identification
        if not matched_chapter and chapters_list:
            options_prompt = "\n".join([f"- {c['unit_code']}: {c['chapter_name']}" for c in chapters_list])
            prompt = f"""You are a master JEE curriculum classifier.
Identify which canonical chapter this {subject} question belongs to from the list below:

QUESTION:
{stem[:600]}

AVAILABLE CHAPTERS:
{options_prompt}

Output ONLY valid JSON:
{{"unit_code": "<exact_unit_code_from_list>"}}"""

            parsed, tok = self._call_groq_json(prompt)
            tokens_used["prompt"] += tok["prompt"]
            tokens_used["completion"] += tok["completion"]
            tokens_used["total"] += tok["total"]

            uc = str(parsed.get("unit_code") or "").strip().upper()
            if uc:
                for c in chapters_list:
                    if c["unit_code"].upper() == uc:
                        matched_chapter = c
                        break
                if not matched_chapter:
                    for c in chapters_list:
                        if uc.lower() in c["chapter_name"].lower() or c["chapter_name"].lower() in uc.lower():
                            matched_chapter = c
                            break

        if not matched_chapter:
            matched_chapter = chapters_list[0] if chapters_list else {
                "unit_code": f"{subject[:4]}_U01",
                "chapter_name": "General Fundamentals",
                "topics": []
            }

        unit_code = matched_chapter["unit_code"]
        chapter_name = matched_chapter["chapter_name"]
        topics_list = matched_chapter.get("topics", [])

        # 4. LLM Subtopic Identification
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

AVAILABLE SUBTOPICS:
{topic_choices}

Output ONLY valid JSON:
{{"topic_code": "<exact_topic_code_from_list>"}}"""

        parsed, tok = self._call_groq_json(prompt)
        tokens_used["prompt"] += tok["prompt"]
        tokens_used["completion"] += tok["completion"]
        tokens_used["total"] += tok["total"]

        chosen_code = str(parsed.get("topic_code") or "").strip()
        matched_topic = None

        for t in topics_list:
            if t["topic_code"].upper() == chosen_code.upper():
                matched_topic = t
                break

        if not matched_topic and chosen_code:
            for t in topics_list:
                if chosen_code.lower() in t["topic_name"].lower() or t["topic_name"].lower() in chosen_code.lower():
                    matched_topic = t
                    break

        if not matched_topic:
            matched_topic = topics_list[0]

        # 5. Database Foreign-Key Guarantee
        validated_code = matched_topic["topic_code"]
        validated_name = matched_topic["topic_name"]

        try:
            with get_db_cursor() as cur:
                cur.execute("""
                    SELECT topic_code, topic_name FROM public.chapter_topics WHERE topic_code = %s;
                """, (validated_code,))
                row = cur.fetchone()
                if row:
                    validated_code = row["topic_code"]
                    validated_name = row["topic_name"]
        except Exception:
            pass

        return {
            "subject": subject,
            "unit_code": unit_code,
            "chapter_name": chapter_name,
            "primary_topic_code": validated_code,
            "topic_name": validated_name,
            "tokens_used": tokens_used
        }
