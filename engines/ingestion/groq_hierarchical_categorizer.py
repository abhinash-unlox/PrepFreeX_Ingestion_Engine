"""Groq-Powered Hierarchical Question Categorizer for PrepFreeX.

Performs curricular academic classification of JEE questions into:
Subject -> Unit -> Topic -> Subtopic
using the configured Groq model, complete subject taxonomy trees,
rigorous parent-child validation, and explicit confidence-review policies.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from engines.shared.config import settings
from engines.ingestion.llm import BaseLLMProvider, FakeLLM, GroqProvider, LLMError, get_llm_provider

logger = logging.getLogger("groq_hierarchical_categorizer")


@dataclass
class GroqClassificationResult:
    question_public_id: str
    selected_unit_code: str | None
    selected_topic_code: str | None
    selected_subtopic_code: str | None
    confidence: float
    academic_rationale: str
    evidence: list[str] = field(default_factory=list)
    alternative_classifications: list[dict[str, Any]] = field(default_factory=list)
    needs_human_review: bool = False
    review_reason: str | None = None
    is_valid: bool = False
    validation_error: str | None = None
    raw_response: dict[str, Any] = field(default_factory=dict)
    tokens_consumed: int = 0
    model_name: str = ""


class TaxonomyHierarchy:
    """In-memory index of the 767-node JEE Main 2027 taxonomy hierarchy."""

    def __init__(self, db_url: str | None = None, seed_path: Path | None = None):
        self.db_url = db_url or settings.database_url
        self.nodes_by_code: dict[str, dict[str, Any]] = {}
        self.nodes_by_id: dict[int, dict[str, Any]] = {}
        self.units_by_subject: dict[str, list[dict[str, Any]]] = {
            "physics": [],
            "chemistry": [],
            "mathematics": [],
        }
        self.topics_by_unit_id: dict[int, list[dict[str, Any]]] = {}
        self.subtopics_by_topic_id: dict[int, list[dict[str, Any]]] = {}
        self._subject_prompt_cache: dict[str, str] = {}

        self._load(seed_path)

    def _load(self, seed_path: Path | None = None):
        """Loads all nodes from PostgreSQL taxonomy table or seed JSON."""
        loaded_rows = []
        try:
            with psycopg.connect(self.db_url, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, code, parent_id, level, name, description, syllabus_text
                        FROM taxonomy
                        WHERE is_active = TRUE
                        ORDER BY code;
                        """
                    )
                    loaded_rows = [dict(r) for r in cur.fetchall()]
        except Exception as e:
            logger.warning("Could not load taxonomy from database (%s); falling back to seed file.", e)
            seed = seed_path or Path("db/seeds/jee_main_2027_taxonomy_v2.json")
            if not seed.exists():
                seed = Path("db/seeds/jee_main_2027_taxonomy.json")
            if seed.exists():
                data = json.loads(seed.read_text(encoding="utf-8"))
                nodes = data.get("nodes", data) if isinstance(data, dict) else data
                # synthesize rows
                for idx, n in enumerate(nodes, start=1):
                    loaded_rows.append({
                        "id": n.get("id", idx),
                        "code": n["code"],
                        "parent_id": n.get("parent_id"),
                        "parent_code": n.get("parent_code"),
                        "level": n["level"],
                        "name": n["name"],
                        "description": n.get("description", ""),
                        "syllabus_text": n.get("syllabus_text", ""),
                    })

        for r in loaded_rows:
            self.nodes_by_code[r["code"]] = r
            self.nodes_by_id[r["id"]] = r

        # Index by hierarchy
        for r in loaded_rows:
            lvl = r["level"]
            code = r["code"]
            subj = "physics" if code.startswith("PHY") else "mathematics" if code.startswith("MAT") else "chemistry" if code.startswith("CHE") else None

            if lvl == "unit" and subj in self.units_by_subject:
                self.units_by_subject[subj].append(r)
            elif lvl == "topic":
                pid = r.get("parent_id")
                if pid:
                    self.topics_by_unit_id.setdefault(pid, []).append(r)
            elif lvl == "subtopic":
                pid = r.get("parent_id")
                if pid:
                    self.subtopics_by_topic_id.setdefault(pid, []).append(r)

        # Sort all lists by code
        for subj in self.units_by_subject:
            self.units_by_subject[subj].sort(key=lambda x: x["code"])
        for uid in self.topics_by_unit_id:
            self.topics_by_unit_id[uid].sort(key=lambda x: x["code"])
        for tid in self.subtopics_by_topic_id:
            self.subtopics_by_topic_id[tid].sort(key=lambda x: x["code"])

        logger.info(
            "TaxonomyHierarchy indexed: %d total nodes across %d units, %d topics, %d subtopics",
            len(self.nodes_by_code),
            sum(len(u) for u in self.units_by_subject.values()),
            sum(len(t) for t in self.topics_by_unit_id.values()),
            sum(len(s) for s in self.subtopics_by_topic_id.values()),
        )

    def get_subject_taxonomy_prompt(self, subject: str) -> str:
        """Constructs a clean, compact text outline of all units, topics, and subtopics for a subject."""
        subj_clean = subject.strip().lower()
        if subj_clean in self._subject_prompt_cache:
            return self._subject_prompt_cache[subj_clean]

        units = self.units_by_subject.get(subj_clean, [])
        lines = [f"=== JEE MAIN 2027 TAXONOMY: {subj_clean.upper()} ==="]

        for u in units:
            lines.append(f"{u['code']} {u['name']}")
            topics = self.topics_by_unit_id.get(u["id"], [])
            for t in topics:
                lines.append(f"  {t['code']} {t['name']}")
                subtopics = self.subtopics_by_topic_id.get(t["id"], [])
                for s in subtopics:
                    lines.append(f"    {s['code']}: {s['name']}")

        prompt_str = "\n".join(lines)
        self._subject_prompt_cache[subj_clean] = prompt_str
        return prompt_str

    def validate_classification(
        self,
        subtopic_code: str | None,
        topic_code: str | None,
        unit_code: str | None,
        expected_subject: str,
    ) -> tuple[bool, str]:
        """Strictly validates node existence, level, parentage, and subject alignment."""
        if not subtopic_code:
            return False, "Missing subtopic code"

        sub_node = self.nodes_by_code.get(subtopic_code)
        if not sub_node:
            return False, f"Subtopic code '{subtopic_code}' does not exist in taxonomy"
        is_leaf_topic = False
        if sub_node.get("level") == "topic":
            children = self.subtopics_by_topic_id.get(sub_node["id"], [])
            if not children:
                is_leaf_topic = True
            else:
                return False, f"Node '{subtopic_code}' is of level 'topic' with available subtopics, expected 'subtopic'"
        elif sub_node.get("level") != "subtopic":
            return False, f"Node '{subtopic_code}' is of level '{sub_node.get('level')}', expected 'subtopic'"

        if is_leaf_topic:
            # For leaf topics (e.g. Experimental Skills PHY.U20, Practical Chemistry CHE.U20)
            unit_id = sub_node.get("parent_id")
            unit_node = self.nodes_by_id.get(unit_id) if unit_id else None
            if not unit_node:
                return False, f"Leaf topic '{subtopic_code}' has missing parent unit in taxonomy"
            if unit_code and unit_node["code"] != unit_code:
                return False, f"Parent-child mismatch: leaf topic '{subtopic_code}' parent is '{unit_node['code']}', but model reported '{unit_code}'"
        else:
            # Verify parent topic
            topic_id = sub_node.get("parent_id")
            topic_node = self.nodes_by_id.get(topic_id) if topic_id else None
            if not topic_node:
                return False, f"Subtopic '{subtopic_code}' has missing parent topic in taxonomy"
            if topic_node.get("level") != "topic":
                return False, f"Parent of '{subtopic_code}' has level '{topic_node.get('level')}', expected 'topic'"

            if topic_code and topic_node["code"] != topic_code:
                return False, f"Parent-child mismatch: subtopic '{subtopic_code}' parent is '{topic_node['code']}', but model reported '{topic_code}'"

            # Verify parent unit
            unit_id = topic_node.get("parent_id")
            unit_node = self.nodes_by_id.get(unit_id) if unit_id else None
            if not unit_node:
                return False, f"Topic '{topic_node['code']}' has missing parent unit in taxonomy"
            if unit_node.get("level") != "unit":
                return False, f"Parent of '{topic_node['code']}' has level '{unit_node.get('level')}', expected 'unit'"

            if unit_code and unit_node["code"] != unit_code:
                return False, f"Parent-child mismatch: topic '{topic_node['code']}' parent is '{unit_node['code']}', but model reported '{unit_code}'"

        # Verify subject match
        subj_clean = expected_subject.strip().lower()
        prefix = "PHY" if subj_clean == "physics" else "MAT" if subj_clean == "mathematics" else "CHE" if subj_clean == "chemistry" else ""
        if not subtopic_code.startswith(prefix + "."):
            return False, f"Subject mismatch: question is '{expected_subject}', but code '{subtopic_code}' belongs to different subject prefix"

        return True, "Valid"


class GroqHierarchicalCategorizer:
    """Uses Groq's LLM reasoning with full subject taxonomy context to classify questions."""

    def __init__(
        self,
        llm: BaseLLMProvider | None = None,
        taxonomy: TaxonomyHierarchy | None = None,
        db_url: str | None = None,
    ):
        self.db_url = db_url or settings.database_url
        self.taxonomy = taxonomy or TaxonomyHierarchy(db_url=self.db_url)
        self.llm = llm or get_llm_provider()

    def build_batch_prompt(self, subject: str, questions: list[dict[str, Any]]) -> str:
        """Constructs the prompt containing the complete subject taxonomy once plus the questions batch."""
        taxonomy_text = self.taxonomy.get_subject_taxonomy_prompt(subject)

        q_items = []
        for q in questions:
            opts_str = ""
            if q.get("options"):
                opts_str = "\nOptions:\n" + "\n".join([f"  ({opt.get('label_printed') or opt.get('option_key', chr(65+i))}) {opt.get('text_md', '')}" for i, opt in enumerate(q["options"])])

            ans_str = ""
            if q.get("answer"):
                ans = q["answer"]
                ans_str = f"\nAnswer: {ans.get('value', ans) if isinstance(ans, dict) else ans}"

            sol_str = ""
            if q.get("explanation_md"):
                sol_str = f"\nExplanation:\n{q['explanation_md'][:400]}"

            source_meta = ""
            if q.get("source_title") or q.get("source_file"):
                source_meta = f"\nSource Document Metadata: {q.get('source_title') or q.get('source_file')}"

            q_item = (
                f"--- QUESTION {q['public_id']} ---\n"
                f"Question Statement:\n{q['stem_md']}\n"
                f"{opts_str}"
                f"{ans_str}"
                f"{sol_str}"
                f"{source_meta}"
            )
            q_items.append(q_item)

        questions_text = "\n\n".join(q_items)

        prompt = f"""You are a senior Indian JEE Main examination academic expert and master curriculum classifier.
Your task is to classify each JEE Main question to its EXACT Unit, Topic, and Subtopic in the official syllabus hierarchy.

{taxonomy_text}

=== INSTRUCTIONS & CLASSIFICATION RULES ===
1. Read each question statement, options, answer, mathematical formulas, and solution carefully.
2. Academic Correctness Over Keyword Matching:
   - Identify the actual core concept tested by the question, NOT merely surface keywords.
   - For example, if a question tests de Broglie wavelength in matter waves, do NOT classify it as Photoelectric Effect just because both involve photons or modern physics.
   - Distinguish questions that use a concept incidentally from questions that actually test that concept.
3. Strict Hierarchy:
   - Select exactly ONE primary SUBTOPIC code from the taxonomy above (e.g. PHY.U17.T02.S02).
   - The selected topic MUST be the actual parent of the selected subtopic.
   - The selected unit MUST be the actual parent of the selected topic.
   - Never invent or fabricate a taxonomy code.
4. Confidence and Evidence:
   - Report a realistic confidence score (0.0 to 1.0).
   - If two subtopics genuinely overlap, list the alternative in 'alternative_classifications' with reasoning.
   - If evidence is ambiguous or insufficient, set 'needs_human_review': true with a clear 'review_reason'.

=== QUESTIONS TO CLASSIFY ===
{questions_text}

=== OUTPUT FORMAT ===
Return strictly valid JSON with the exact structure below. Do not wrap in markdown or include conversational text.
{{
  "classifications": [
    {{
      "question_public_id": "Q00000001",
      "selected_unit_code": "PHY.U17",
      "selected_topic_code": "PHY.U17.T02",
      "selected_subtopic_code": "PHY.U17.T02.S02",
      "confidence": 0.96,
      "academic_rationale": "The question requires calculating de Broglie wavelength ratio from kinetic energies, directly testing de Broglie relation in matter waves.",
      "evidence": [
        "de Broglie wavelength formula lambda = h / sqrt(2mE)",
        "Kinetic energy comparison for deuteron and alpha particle"
      ],
      "alternative_classifications": [
        {{
          "subtopic_code": "PHY.U17.T02.S01",
          "reason": "Theory vs problem solving distinction in matter waves"
        }}
      ],
      "needs_human_review": false,
      "review_reason": null
    }}
  ]
}}"""
        return prompt

    def classify_batch(
        self,
        subject: str,
        questions: list[dict[str, Any]],
        retry_on_failure: bool = True,
    ) -> list[GroqClassificationResult]:
        """Classifies a batch of questions for a single subject using Groq."""
        if not questions:
            return []

        # If FakeLLM, handle mock response
        if isinstance(self.llm, FakeLLM):
            mock_results = []
            for q in questions:
                # Check for canned answer
                canned = self.llm.extract_json([], f"CATEGORIZE {q['public_id']}")
                if canned and "selected_subtopic_code" in canned:
                    mock_results.append(self._parse_single_result(q["public_id"], canned, subject))
                else:
                    # Provide default mock result
                    units = self.taxonomy.units_by_subject.get(subject.lower(), [])
                    if units:
                        u = units[0]
                        topics = self.taxonomy.topics_by_unit_id.get(u["id"], [])
                        t = topics[0] if topics else None
                        subs = self.taxonomy.subtopics_by_topic_id.get(t["id"], []) if t else []
                        s = subs[0] if subs else None
                        sub_code = s["code"] if s else f"{u['code']}.T01.S01"
                        top_code = t["code"] if t else f"{u['code']}.T01"
                        res_dict = {
                            "selected_unit_code": u["code"],
                            "selected_topic_code": top_code,
                            "selected_subtopic_code": sub_code,
                            "confidence": 0.95,
                            "academic_rationale": f"Mock classification for {q['public_id']}",
                            "evidence": ["Mock testing evidence"],
                            "alternative_classifications": [],
                            "needs_human_review": False,
                            "review_reason": None,
                        }
                        mock_results.append(self._parse_single_result(q["public_id"], res_dict, subject))
                    else:
                        mock_results.append(GroqClassificationResult(
                            question_public_id=q["public_id"],
                            selected_unit_code=None,
                            selected_topic_code=None,
                            selected_subtopic_code=None,
                            confidence=0.0,
                            academic_rationale="No units found in taxonomy for subject",
                            is_valid=False,
                            validation_error="Subject not in taxonomy",
                        ))
            return mock_results

        prompt = self.build_batch_prompt(subject, questions)
        raw_res = None
        last_error = None

        attempts = 2 if retry_on_failure else 1
        for attempt in range(attempts):
            try:
                raw_res = self.llm.extract_json(images=[], prompt=prompt)
                if raw_res and ("classifications" in raw_res or "selected_subtopic_code" in raw_res):
                    break
            except Exception as e:
                last_error = e
                logger.warning("Attempt %d/%d Groq batch call failed: %s", attempt + 1, attempts, e)

        # Parse results
        results_by_pid: dict[str, GroqClassificationResult] = {}

        if raw_res:
            class_list = raw_res.get("classifications")
            if class_list is None and "selected_subtopic_code" in raw_res:
                # Single object returned
                class_list = [raw_res]
            elif not isinstance(class_list, list):
                class_list = []

            for item in class_list:
                if not isinstance(item, dict):
                    continue
                pid = item.get("question_public_id") or item.get("public_id")
                if pid:
                    results_by_pid[pid] = self._parse_single_result(pid, item, subject)

        # Ensure all questions in batch have an entry
        final_results: list[GroqClassificationResult] = []
        for q in questions:
            pid = q["public_id"]
            if pid in results_by_pid:
                final_results.append(results_by_pid[pid])
            else:
                err_msg = f"Groq response omitted question {pid} or failed: {last_error}" if last_error else f"Groq output missing classification for {pid}"
                final_results.append(GroqClassificationResult(
                    question_public_id=pid,
                    selected_unit_code=None,
                    selected_topic_code=None,
                    selected_subtopic_code=None,
                    confidence=0.0,
                    academic_rationale="Classification failed or missing from LLM response",
                    is_valid=False,
                    validation_error=err_msg,
                    raw_response=raw_res or {},
                ))

        return final_results

    def _parse_single_result(self, public_id: str, item: dict[str, Any], subject: str) -> GroqClassificationResult:
        sub_code = item.get("selected_subtopic_code") or item.get("subtopic_code")
        top_code = item.get("selected_topic_code") or item.get("topic_code")
        unit_code = item.get("selected_unit_code") or item.get("unit_code")

        # Clean codes
        if sub_code:
            sub_code = sub_code.strip()
        if top_code:
            top_code = top_code.strip()
        if unit_code:
            unit_code = unit_code.strip()

        # If model omitted unit or topic, infer from subtopic node
        if sub_code and sub_code in self.taxonomy.nodes_by_code:
            node = self.taxonomy.nodes_by_code[sub_code]
            pid = node.get("parent_id")
            if pid and pid in self.taxonomy.nodes_by_id:
                pnode = self.taxonomy.nodes_by_id[pid]
                if not top_code:
                    top_code = pnode["code"]
                gpid = pnode.get("parent_id")
                if gpid and gpid in self.taxonomy.nodes_by_id and not unit_code:
                    unit_code = self.taxonomy.nodes_by_id[gpid]["code"]

        conf = float(item.get("confidence", 0.0))
        rationale = item.get("academic_rationale") or item.get("rationale") or ""
        evidence = item.get("evidence") or []
        if isinstance(evidence, str):
            evidence = [evidence]
        alts = item.get("alternative_classifications") or []
        needs_review = bool(item.get("needs_human_review", False))
        review_reason = item.get("review_reason")

        # Validate strictly
        is_valid, val_err = self.taxonomy.validate_classification(
            subtopic_code=sub_code,
            topic_code=top_code,
            unit_code=unit_code,
            expected_subject=subject,
        )

        return GroqClassificationResult(
            question_public_id=public_id,
            selected_unit_code=unit_code if is_valid else None,
            selected_topic_code=top_code if is_valid else None,
            selected_subtopic_code=sub_code if is_valid else None,
            confidence=conf,
            academic_rationale=rationale,
            evidence=evidence,
            alternative_classifications=alts,
            needs_human_review=needs_review,
            review_reason=review_reason,
            is_valid=is_valid,
            validation_error=None if is_valid else val_err,
            raw_response=item,
        )

    def classify_single(
        self,
        stem_md: str,
        options: list[Any] | None = None,
        explanation_md: str | None = None,
        subject: str = "physics",
        public_id: str = "PROPOSAL_01",
        source_title: str | None = None,
        source_file: str | None = None,
    ) -> GroqClassificationResult:
        """Classifies a single question (convenience wrapper for pipeline stage 8 & 9)."""
        formatted_options = []
        if options:
            for i, opt in enumerate(options):
                if isinstance(opt, dict):
                    formatted_options.append(opt)
                elif hasattr(opt, "text_md"):
                    formatted_options.append({"label_printed": getattr(opt, "label_printed", chr(65+i)), "text_md": opt.text_md})
                else:
                    formatted_options.append({"label_printed": chr(65+i), "text_md": str(opt)})

        q_dict = {
            "public_id": public_id,
            "stem_md": stem_md,
            "options": formatted_options,
            "explanation_md": explanation_md,
            "source_title": source_title,
            "source_file": source_file,
        }
        res_list = self.classify_batch(subject, [q_dict], retry_on_failure=True)
        return res_list[0]

