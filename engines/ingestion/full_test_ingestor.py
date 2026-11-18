"""
Automated Full-Length Test Ingestor for JEE Main
Extracts, classifies, and verifies questions from full-length ExamGoal / NTA question papers.
Only agrees and promotes questions where the AIR-1 Blind Solver independently verifies the official answer key.
"""

from __future__ import annotations
import os
import re
import json
import uuid
from typing import Optional, Generator
import fitz  # PyMuPDF

from apps.api.db import get_db_cursor
from engines.ingestion.guardrails import validate_question_guardrails
from engines.ingestion.curriculum_engine import CurriculumEngine
from engines.ingestion.blind_solver import BlindSolver

class FullTestIngestor:
    def __init__(self):
        self.classifier = CurriculumEngine()
        self.solver = BlindSolver()

    def clean_boilerplate(self, text: str) -> str:
        """Removes ExamGoal and website boilerplate from stems and options and normalizes OCR scientific units."""
        patterns = [
            r'Open solution',
            r'Keep practising on the ExamGOAL app[\s\S]*?(?=\Z|Q\d+\.)',
            r'Chapter-wise PYQs with solutions[^\n]*',
            r'Google Play[^\n]*',
            r'GET IT ON[^\n]*',
            r'JEE Main \d{4}.*?Page \d+ / \d+',
            r'Solutions:\s*questions\.examside\.com[^\n]*',
            r'Scan the QR code[^\n]*',
            r'ExamGOAL\s+P\s+Y\s+Q\s+P\s+D\s+F',
            r'pdf\.questions\.examgoal\.com',
        ]
        cleaned = text
        for p in patterns:
            cleaned = re.sub(p, '', cleaned, flags=re.IGNORECASE)

        # Normalize OCR superscript units into clean LaTeX
        cleaned = re.sub(r'\bms\s*[-–]?\s*1\b', r'\\text{m s}^{-1}', cleaned)
        cleaned = re.sub(r'\bms\s*[-–]?\s*2\b', r'\\text{m s}^{-2}', cleaned)
        cleaned = re.sub(r'\bms\s*[-–]?\s*3\b', r'\\text{m s}^{-3}', cleaned)
        cleaned = re.sub(r'\bkg\s*m\s*[-–]?\s*3\b', r'\\text{kg m}^{-3}', cleaned)
        cleaned = re.sub(r'\bkg\s*m\s*[-–]?\s*2\b', r'\\text{kg m}^{-2}', cleaned)
        cleaned = re.sub(r'\bkg\s*m\s*[-–]?\s*1\b', r'\\text{kg m}^{-1}', cleaned)
        cleaned = re.sub(r'\brad\s*s\s*[-–]?\s*1\b', r'\\text{rad s}^{-1}', cleaned)
        cleaned = re.sub(r'\brad\s*s\s*[-–]?\s*2\b', r'\\text{rad s}^{-2}', cleaned)
        cleaned = re.sub(r'\bN\s*m\s*[-–]?\s*2\b', r'\\text{N m}^{-2}', cleaned)
        cleaned = re.sub(r'\bN\s*m\s*[-–]?\s*1\b', r'\\text{N m}^{-1}', cleaned)
        cleaned = re.sub(r'\bkJ\s*mol\s*[-–]?\s*1\b', r'\\text{kJ mol}^{-1}', cleaned)
        cleaned = re.sub(r'\bJ\s*mol\s*[-–]?\s*1\b', r'\\text{J mol}^{-1}', cleaned)
        cleaned = re.sub(r'\bmol\s*L\s*[-–]?\s*1\b', r'\\text{mol L}^{-1}', cleaned)

        return cleaned.strip()

    def extract_answer_key(self, doc: fitz.Document) -> dict[int, str]:
        """Extracts the official answer key table from the last pages."""
        ans_key: dict[int, str] = {}
        for page in doc[-3:]:
            text = page.get_text("text")
            if "Answer Key" in text:
                matches = re.findall(r'(\d+)\.\s+([A-D]|\d+)', text)
                for q_num, ans in matches:
                    ans_key[int(q_num)] = ans.strip().upper()
        return ans_key

    def parse_full_test_pdf(self, pdf_path: str) -> list[dict]:
        """
        Parses questions from a full test PDF.
        Extracts Q1 to Q90, their stems, options, and official answers.
        """
        doc = fitz.open(pdf_path)
        ans_key = self.extract_answer_key(doc)
        print(f"[FullTestIngestor] Extracted {len(ans_key)} official answer keys from PDF.")

        # Aggregate text from page 1 up to the answer key page
        full_text = ""
        total_pages = len(doc)
        end_page = max(1, total_pages - 2)
        
        for pno in range(1, end_page):
            full_text += doc[pno].get_text("text") + "\n"

        # Pre-clean known watermarks
        full_text = self.clean_boilerplate(full_text)

        # Split on Question boundaries
        blocks = re.split(r'\n(?=Q\d+\.)', full_text)
        parsed = []

        for b in blocks:
            b = b.strip()
            m = re.match(r'Q(\d+)\.\s*(.*?)(?=\n\([A-D]\)|\Z)', b, re.DOTALL)
            if not m:
                continue

            q_num = int(m.group(1))
            raw_stem = m.group(2).strip()

            # Clean stem
            is_numerical = "Numerical" in raw_stem
            stem = re.sub(r'^(MCQ\s*\([^)]*\)|Numerical)\s*', '', raw_stem).strip()
            stem = self.clean_boilerplate(stem)

            # Extract options (A)-(D)
            opt_matches = re.findall(r'\(([A-D])\)\s*([\s\S]*?)(?=\([A-D]\)|\Z)', b)
            options = []
            for letter, opt_val in opt_matches[:4]:
                cleaned_opt = self.clean_boilerplate(opt_val)
                options.append(cleaned_opt)

            # Determine subject
            if q_num <= 21:
                subject = "CHEMISTRY"
            elif q_num <= 43:
                subject = "MATHEMATICS"
            elif q_num <= 69:
                subject = "PHYSICS"
            else:
                # 70-90 in 2022 shifts are older syllabus / mixed
                # fallback by question number or default
                subject = "PHYSICS"

            official_ans = ans_key.get(q_num)
            q_type = "NUMERICAL" if is_numerical or len(options) < 4 else "SINGLE_CHOICE"

            parsed.append({
                "q_num": q_num,
                "subject": subject,
                "question_type": q_type,
                "stem": stem,
                "options": options,
                "official_ans": official_ans,
                "page_number": 1  # approximate
            })

        return parsed

    def ingest_full_test(
        self,
        pdf_path: str,
        limit_questions: Optional[int] = None,
        start_question: Optional[int] = None,
        auto_promote_matched: bool = True
    ) -> dict:
        """
        Runs the full automated pipeline on a full-length test PDF:
        - Only agrees and promotes when the blind solver passes.
        - Categorizes to unit and subtopic.
        - Tracks tokens.
        """
        filename = os.path.basename(pdf_path)
        print(f"\n=======================================================")
        print(f"AUTOMATED FULL-TEST INGESTION: {filename}")
        print(f"Auto-Promote Matched: {auto_promote_matched}")
        print(f"=======================================================")

        # Ensure manifest entry exists
        with get_db_cursor() as cur:
            cur.execute("""
                INSERT INTO public.pdf_ingestion_manifest (
                    pdf_filename, pdf_path, subject, status, started_at
                ) VALUES (%s, %s, 'FULL_TEST', 'IN_PROGRESS', NOW())
                ON CONFLICT (pdf_path) DO UPDATE
                SET status = 'IN_PROGRESS', started_at = NOW();
            """, (filename, pdf_path))

        parsed_questions = self.parse_full_test_pdf(pdf_path)
        if start_question:
            parsed_questions = [q for q in parsed_questions if q["q_num"] >= start_question]
        if limit_questions:
            parsed_questions = parsed_questions[:limit_questions]

        metrics = {
            "pdf_filename": filename,
            "total_extracted": len(parsed_questions),
            "passed_guardrails": 0,
            "rejected_guardrails": 0,
            "solver_matched": 0,
            "solver_discrepancy": 0,
            "auto_promoted": 0,
            "total_tokens_used": 0,
            "questions": []
        }

        for q in parsed_questions:
            q_num = q["q_num"]
            subject = q["subject"]
            stem = q["stem"]
            opts = q["options"]
            q_type = q["question_type"]
            official_ans = q["official_ans"]

            q_tokens = 0
            flaws = []

            # -------------------------------------------------------------
            # LAYER 1: ACADEMIC GUARDRAILS (0 TOKENS)
            # -------------------------------------------------------------
            is_valid, flaws = validate_question_guardrails(
                stem=stem,
                options=opts,
                has_diagram=False,
                diagram_s3_key=None,
                question_type=q_type
            )

            if not is_valid:
                metrics["rejected_guardrails"] += 1
                guardrail_status = "REJECTED"
                review_status = "REJECTED"
                solver_status = "SKIPPED"
                solver_opt = None
                solver_reasoning = ""
                # Default classification for rejected questions
                class_res = {
                    "subject": subject,
                    "unit_code": f"{subject[:4]}_U01",
                    "chapter_name": "General Fundamentals",
                    "primary_topic_code": f"{subject[:4]}_U01_T01",
                    "topic_name": "Fundamentals",
                    "tokens_used": {"total": 0, "prompt": 0, "completion": 0}
                }
                print(f"  [Q{q_num:02d} REJECTED] Guardrails failed: {flaws[0]}")
            else:
                metrics["passed_guardrails"] += 1
                guardrail_status = "PASSED"

                # ---------------------------------------------------------
                # LAYER 2: CURRICULUM CLASSIFIER (Subject -> Unit -> Subtopic)
                # ---------------------------------------------------------
                class_res = self.classifier.categorize_question(
                    stem=stem,
                    options=opts,
                    subject_hint=subject
                )
                c_tok = class_res.get("tokens_used", {}).get("total", 0)
                q_tokens += c_tok

                # ---------------------------------------------------------
                # LAYER 3: AIR-1 BLIND SOLVER PARITY ARBITER (GPT-OSS-120B)
                # Solves blind without knowing the official key
                # ---------------------------------------------------------
                solve_res = self.solver.solve_blind(
                    stem=stem,
                    options=opts,
                    question_type=q_type,
                    extracted_answer=official_ans
                )
                s_tok = solve_res.get("tokens_used", {}).get("total", 0)
                q_tokens += s_tok

                solver_status = solve_res.get("solver_status", "SKIPPED")
                solver_opt = solve_res.get("solver_option")
                solver_reasoning = solve_res.get("reasoning", "")

                if solver_status == "MATCHED":
                    metrics["solver_matched"] += 1
                    review_status = "APPROVED"
                    print(f"  [Q{q_num:02d} MATCHED ✓] Key: {official_ans} == Solver: {solver_opt} | Unit: {class_res['chapter_name']} ({class_res['primary_topic_code']}) | Tokens: {q_tokens}")
                else:
                    metrics["solver_discrepancy"] += 1
                    review_status = "PENDING_REVIEW"
                    print(f"  [Q{q_num:02d} DISCREPANCY ⚠] Key: {official_ans} vs Solver: {solver_opt} | Kept in Staging for Review | Tokens: {q_tokens}")

            metrics["total_tokens_used"] += q_tokens

            # -------------------------------------------------------------
            # LAYER 4: STAGING DATABASE WRITE
            # -------------------------------------------------------------
            staging_uid = f"stg_full_{uuid.uuid4().hex[:10]}"
            with get_db_cursor() as cur:
                cur.execute("""
                    INSERT INTO public.staged_questions (
                        staging_uid, source_pdf, page_number,
                        subject, unit_code, chapter_name, primary_topic_code, topic_name,
                        question_type, question_text_latex, options, correct_option,
                        guardrail_status, guardrail_notes,
                        solver_status, solver_option, solver_reasoning,
                        review_status,
                        prompt_tokens, completion_tokens, total_tokens, model_name
                    ) VALUES (
                        %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s,
                        %s, %s, %s,
                        %s,
                        %s, %s, %s, %s
                    ) RETURNING id;
                """, (
                    staging_uid, filename, 1,
                    class_res["subject"], class_res["unit_code"], class_res["chapter_name"],
                    class_res["primary_topic_code"], class_res["topic_name"],
                    q_type, stem, json.dumps(opts), official_ans,
                    guardrail_status, json.dumps(flaws),
                    solver_status, solver_opt, solver_reasoning,
                    review_status,
                    0, 0, q_tokens, "qwen3.8-27b + gpt-oss-120b"
                ))
                stg_id = cur.fetchone()["id"]

            # -------------------------------------------------------------
            # AUTO-PROMOTE ONLY IF BLIND TEST PASSES!
            # -------------------------------------------------------------
            if auto_promote_matched and review_status == "APPROVED":
                new_uid = f"pyq_full_{staging_uid}"
                num_target = None
                comp_correct_opt = str(official_ans)[:5] if official_ans else None
                if q_type == "NUMERICAL":
                    try:
                        clean_num = re.sub(r'[^0-9\.\-]', '', str(official_ans or ''))
                        num_target = float(clean_num) if clean_num else None
                    except (ValueError, TypeError):
                        num_target = None

                with get_db_cursor() as cur:
                    cur.execute("""
                        INSERT INTO public.completed_questions (
                            question_uid, subject, unit_code, chapter_name, primary_topic_code,
                            question_type, question_text_latex, options, correct_option, numerical_target,
                            assessment_status, academic_status, tags
                        ) VALUES (
                            %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s,
                            'ELIGIBLE', 'MODEL_REVIEWED',
                            jsonb_build_array('FULL_TEST_AUTO_VERIFIED', 'SOURCE_PDF: ' || %s)
                        )
                        ON CONFLICT (question_uid) DO UPDATE
                        SET question_text_latex = EXCLUDED.question_text_latex,
                            options = EXCLUDED.options,
                            correct_option = EXCLUDED.correct_option,
                            numerical_target = EXCLUDED.numerical_target,
                            assessment_status = 'ELIGIBLE',
                            academic_status = 'MODEL_REVIEWED',
                            tags = EXCLUDED.tags;
                    """, (
                        new_uid, class_res["subject"], class_res["unit_code"], class_res["chapter_name"], class_res["primary_topic_code"],
                        q_type, stem, json.dumps(opts), comp_correct_opt, num_target,
                        filename
                    ))

                    cur.execute("""
                        UPDATE public.staged_questions
                        SET review_status = 'PROMOTED', reviewed_at = NOW(), promoted_at = NOW()
                        WHERE id = %s;
                    """, (stg_id,))
                metrics["auto_promoted"] += 1
                print(f"    -> 🚀 Auto-Promoted to Production (question_uid={new_uid})")

        # Update Manifest
        with get_db_cursor() as cur:
            cur.execute("""
                UPDATE public.pdf_ingestion_manifest
                SET status = 'COMPLETED',
                    extracted_questions = %s,
                    passed_guardrails = %s,
                    rejected_guardrails = %s,
                    total_tokens_used = %s,
                    completed_at = NOW()
                WHERE pdf_path = %s;
            """, (
                metrics["total_extracted"],
                metrics["passed_guardrails"],
                metrics["rejected_guardrails"],
                metrics["total_tokens_used"],
                pdf_path
            ))

        print(f"\n=======================================================")
        print(f"FULL TEST INGESTION SUMMARY:")
        print(f"  - Extracted: {metrics['total_extracted']}")
        print(f"  - Passed Guardrails: {metrics['passed_guardrails']}")
        print(f"  - Rejected Guardrails: {metrics['rejected_guardrails']}")
        print(f"  - Solver Matched (Parity Verified): {metrics['solver_matched']}")
        print(f"  - Solver Discrepancy (Held in Staging): {metrics['solver_discrepancy']}")
        print(f"  - Auto-Promoted to Production: {metrics['auto_promoted']}")
        print(f"  - Total Tokens Consumed: {metrics['total_tokens_used']}")
        print(f"=======================================================\n")
        return metrics
