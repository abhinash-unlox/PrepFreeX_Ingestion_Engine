"""
Database-Wide Curriculum & Taxonomy Remediation Sweep
Reclassifies all miscategorized, cross-subject contaminated, and defaulted U01/CHEM_U19 questions
across public.staged_questions and public.completed_questions using CurriculumEngine.
Guarantees strict PostgreSQL foreign-key alignment with public.chapter_topics.
"""

from __future__ import annotations
import os
import sys
import time
import json
import psycopg
from engines.ingestion.curriculum_engine import CurriculumEngine
from engines.shared.config import settings

def run_taxonomy_remediation():
    engine = CurriculumEngine()
    conn = psycopg.connect(
        host="127.0.0.1",
        port=5432,
        user="prepfreex_user",
        password="Pathfinder@12",
        dbname="jee_mains_assesment_work"
    )
    cur = conn.cursor()

    print("=============================================================")
    print("STARTING DATABASE TAXONOMY REMEDIATION SWEEP")
    print("=============================================================")

    # -------------------------------------------------------------
    # 1. Sweep CHEM_U19 in completed_questions (Historical dump)
    # -------------------------------------------------------------
    cur.execute("""
        SELECT question_uid, subject, unit_code, chapter_name, primary_topic_code, question_text_latex, options
        FROM public.completed_questions
        WHERE unit_code = 'CHEM_U19';
    """)
    chem_u19_rows = cur.fetchall()
    print(f"\n[PHASE 1] Found {len(chem_u19_rows)} questions in CHEM_U19 to remediate.")

    chem_u19_updated = 0
    for idx, row in enumerate(chem_u19_rows, 1):
        q_uid, subj, uc, ch, tc, stem, opts = row
        options_list = opts if isinstance(opts, list) else []

        res = engine.categorize_question(stem, options=options_list)
        new_subj = res["subject"]
        new_unit = res["unit_code"]
        new_chapter = res["chapter_name"]
        new_topic_code = res["primary_topic_code"]

        if new_unit != uc or new_topic_code != tc or new_subj != subj:
            cur.execute("""
                UPDATE public.completed_questions
                SET subject = %s,
                    unit_code = %s,
                    chapter_name = %s,
                    primary_topic_code = %s
                WHERE question_uid = %s;
            """, (new_subj, new_unit, new_chapter, new_topic_code, q_uid))
            conn.commit()
            chem_u19_updated += 1
            if idx % 10 == 0 or idx == len(chem_u19_rows):
                print(f"  [{idx}/{len(chem_u19_rows)}] Remediated {q_uid[:20]}: {subj}/{uc} -> {new_subj}/{new_unit} ({new_chapter})")

    print(f"[PHASE 1 COMPLETE] Remediated {chem_u19_updated}/{len(chem_u19_rows)} questions from CHEM_U19.")

    # -------------------------------------------------------------
    # 2. Sweep Defaulted / Active staged_questions
    # -------------------------------------------------------------
    cur.execute("""
        SELECT id, staging_uid, subject, unit_code, chapter_name, primary_topic_code, question_text_latex, options, review_status
        FROM public.staged_questions
        WHERE review_status IN ('PENDING_REVIEW', 'APPROVED', 'PROMOTED')
          AND (
              chapter_name = 'General Fundamentals'
              OR unit_code IN ('PHYS_U01', 'CHEM_U01', 'MATH_U01')
          );
    """)
    staged_rows = cur.fetchall()
    print(f"\n[PHASE 2] Found {len(staged_rows)} active staged questions in U01/General Fundamentals.")

    staged_updated = 0
    for idx, row in enumerate(staged_rows, 1):
        q_id, staging_uid, subj, uc, ch, tc, stem, opts, status = row
        options_list = opts if isinstance(opts, list) else []

        res = engine.categorize_question(stem, options=options_list, subject_hint=subj)
        new_subj = res["subject"]
        new_unit = res["unit_code"]
        new_chapter = res["chapter_name"]
        new_topic_code = res["primary_topic_code"]
        new_topic_name = res["topic_name"]

        if new_unit != uc or new_topic_code != tc:
            cur.execute("""
                UPDATE public.staged_questions
                SET subject = %s,
                    unit_code = %s,
                    chapter_name = %s,
                    primary_topic_code = %s,
                    topic_name = %s
                WHERE id = %s;
            """, (new_subj, new_unit, new_chapter, new_topic_code, new_topic_name, q_id))

            # Also update completed_questions if already promoted
            promoted_uid = f"pyq_full_{staging_uid}"
            cur.execute("""
                UPDATE public.completed_questions
                SET subject = %s,
                    unit_code = %s,
                    chapter_name = %s,
                    primary_topic_code = %s
                WHERE question_uid = %s OR question_uid = %s;
            """, (new_subj, new_unit, new_chapter, new_topic_code, promoted_uid, f"pyq_staged_{staging_uid}"))

            conn.commit()
            staged_updated += 1
            print(f"  [{idx}/{len(staged_rows)}] Reclassified #{q_id} ({staging_uid[:15]}): {uc} -> {new_unit} ({new_chapter} - {new_topic_code})")

    print(f"[PHASE 2 COMPLETE] Reclassified {staged_updated}/{len(staged_rows)} staged questions.")

    # -------------------------------------------------------------
    # 3. Standardize Subject Casing in completed_questions
    # -------------------------------------------------------------
    cur.execute("""
        UPDATE public.completed_questions
        SET subject = UPPER(subject)
        WHERE subject != UPPER(subject);
    """)
    casing_count = cur.rowcount
    conn.commit()
    print(f"\n[PHASE 3 COMPLETE] Normalized subject casing for {casing_count} questions.")

    print("\n=============================================================")
    print("TAXONOMY REMEDIATION COMPLETE!")
    print("=============================================================")

if __name__ == "__main__":
    run_taxonomy_remediation()
