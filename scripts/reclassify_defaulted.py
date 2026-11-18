"""
Batch reclassifies staged and promoted questions that defaulted to PHYS_U01 or CHEM_U01 due to transient rate limits.
"""

from apps.api.db import get_db_cursor
from engines.ingestion.hierarchical_classifier import HierarchicalClassifier

def reclassify_defaulted_questions():
    classifier = HierarchicalClassifier()

    with get_db_cursor() as cur:
        # Find questions where unit was defaulted to U01
        cur.execute("""
            SELECT id, staging_uid, subject, question_text_latex, options, unit_code, primary_topic_code
            FROM public.staged_questions
            WHERE unit_code IN ('PHYS_U01', 'CHEM_U01', 'MATH_U01')
              AND review_status IN ('PENDING_REVIEW', 'APPROVED', 'PROMOTED');
        """)
        candidates = cur.fetchall()

    print(f"Found {len(candidates)} questions to evaluate for reclassification.")
    updated_count = 0

    for idx, q in enumerate(candidates, 1):
        stem = q["question_text_latex"]
        opts = q["options"] or []
        subj = q["subject"]

        res = classifier.classify_question(stem, opts, subject_hint=subj)
        new_unit = res["unit_code"]
        new_chapter = res["chapter_name"]
        new_topic_code = res["primary_topic_code"]
        new_topic_name = res["topic_name"]

        # If it changed from default to a more specific unit
        if new_unit != q["unit_code"] or new_topic_code != q["primary_topic_code"]:
            with get_db_cursor() as cur:
                cur.execute("""
                    UPDATE public.staged_questions
                    SET unit_code = %s,
                        chapter_name = %s,
                        primary_topic_code = %s,
                        topic_name = %s
                    WHERE id = %s;
                """, (new_unit, new_chapter, new_topic_code, new_topic_name, q["id"]))

                # Also update in completed_questions if already promoted
                promoted_uid = f"pyq_full_{q['staging_uid']}"
                cur.execute("""
                    UPDATE public.completed_questions
                    SET unit_code = %s,
                        chapter_name = %s,
                        primary_topic_code = %s
                    WHERE question_uid = %s OR question_uid = %s;
                """, (new_unit, new_chapter, new_topic_code, promoted_uid, f"pyq_staged_{q['staging_uid']}"))

            updated_count += 1
            print(f"[{idx}/{len(candidates)}] Reclassified #{q['id']}: {q['unit_code']} -> {new_unit} ({new_chapter} - {new_topic_code})")
        else:
            print(f"[{idx}/{len(candidates)}] Kept #{q['id']}: {new_unit}")

    print(f"\nDone! Reclassified {updated_count} questions.")

if __name__ == "__main__":
    reclassify_defaulted_questions()
