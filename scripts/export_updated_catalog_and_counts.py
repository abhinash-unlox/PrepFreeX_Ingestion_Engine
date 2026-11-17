import os
import csv
import json
from apps.api.db import get_db_cursor

def export_all():
    # 1. Load canonical taxonomy
    with open("v0-prepfreex-frontend/lib/canonical-taxonomy.json", "r", encoding="utf-8") as f:
        canon = json.load(f)

    topic_meta = {}
    for subj, chs in canon.items():
        for ch in chs:
            u_code = ch["unit_code"]
            ch_name = ch["chapter_name"]
            for t in ch.get("topics", []):
                t_code = t["topic_code"]
                t_name = t["topic_name"]
                topic_meta[t_code] = {
                    "subject": subj,
                    "chapter": ch_name,
                    "unit_code": u_code,
                    "topic_code": t_code,
                    "topic_name": t_name
                }

    # 2. Query all clean, eligible questions from completed_questions
    print("Querying eligible questions from database...")
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT 
                id,
                question_uid,
                subject,
                chapter_name,
                unit_code,
                primary_topic_code,
                question_type,
                question_text_latex,
                options,
                correct_option,
                numerical_target,
                solution_text_latex,
                has_diagram,
                diagram_s3_key,
                source_year,
                source_shift,
                difficulty_tier,
                academic_status,
                assessment_status
            FROM public.completed_questions
            WHERE assessment_status = 'ELIGIBLE'
            ORDER BY subject, unit_code, primary_topic_code, id;
        """)
        eligible_rows = cur.fetchall()

    print(f"Loaded {len(eligible_rows)} eligible questions.")

    # 3. Export PrepFreeX_Ready_Questions_Review.csv
    ready_csv_path = "PrepFreeX_Ready_Questions_Review.csv"
    ready_headers = [
        "ID", "Question UID", "Subject", "Chapter", "Unit Code", "Topic Code", "Topic Title",
        "Question Type", "Question Text (LaTeX)", "Option A", "Option B", "Option C", "Option D",
        "Correct Answer", "Correct Option Content", "Numerical Target", "Solution / Explanation",
        "Has Diagram", "Diagram S3 Key", "Exam Shift", "Difficulty Tier", "Academic Status"
    ]

    topic_counts = {}

    with open(ready_csv_path, "w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.writer(fp)
        writer.writerow(ready_headers)

        for r in eligible_rows:
            t_code = r.get("primary_topic_code") or ""
            topic_counts[t_code] = topic_counts.get(t_code, 0) + 1

            meta = topic_meta.get(t_code, {})
            ch_title = meta.get("chapter") or r.get("chapter_name") or ""
            u_code = meta.get("unit_code") or r.get("unit_code") or ""
            t_title = meta.get("topic_name") or ""
            subj = meta.get("subject") or r.get("subject") or ""

            opts = r.get("options") or []
            if isinstance(opts, str):
                try: opts = json.loads(opts)
                except: opts = []
            
            clean_opts = []
            for o in opts:
                if isinstance(o, dict):
                    clean_opts.append(o.get("text", ""))
                else:
                    clean_opts.append(str(o))
            while len(clean_opts) < 4:
                clean_opts.append("")

            correct_opt = (r.get("correct_option") or "").strip().upper()
            correct_content = ""
            opt_idx_map = {"A": 0, "B": 1, "C": 2, "D": 3}
            if correct_opt in opt_idx_map and opt_idx_map[correct_opt] < len(clean_opts):
                correct_content = clean_opts[opt_idx_map[correct_opt]]

            shift_str = ""
            if r.get("source_year"):
                shift_str = f"JEE Main {r['source_year']} {r.get('source_shift') or ''}".strip()

            writer.writerow([
                r["id"],
                r["question_uid"],
                subj,
                ch_title,
                u_code,
                t_code,
                t_title,
                r.get("question_type") or "SINGLE_CHOICE",
                r.get("question_text_latex") or "",
                clean_opts[0],
                clean_opts[1],
                clean_opts[2],
                clean_opts[3],
                correct_opt,
                correct_content,
                r.get("numerical_target") if r.get("numerical_target") is not None else "",
                r.get("solution_text_latex") or "",
                "YES" if r.get("has_diagram") else "NO",
                r.get("diagram_s3_key") or "",
                shift_str,
                r.get("difficulty_tier") or "Tier 2",
                r.get("academic_status") or "ELIGIBLE"
            ])

    print(f"Successfully generated {ready_csv_path} with {len(eligible_rows)} rows.")

    # 4. Export PrepFreeX_Subtopic_Question_Counts.csv
    counts_csv_path = "PrepFreeX_Subtopic_Question_Counts.csv"
    counts_headers = ["Subject", "Chapter", "Unit Code", "Topic Code", "Topic Title", "Eligible Questions"]

    with open(counts_csv_path, "w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.writer(fp)
        writer.writerow(counts_headers)

        for subj, chs in canon.items():
            for ch in chs:
                u_code = ch["unit_code"]
                ch_name = ch["chapter_name"]
                for t in ch.get("topics", []):
                    t_code = t["topic_code"]
                    t_name = t["topic_name"]
                    cnt = topic_counts.get(t_code, 0)
                    writer.writerow([subj, ch_name, u_code, t_code, t_name, cnt])

    print(f"Successfully generated {counts_csv_path} with 256 subtopics.")

    # 5. Also copy/sync into reports/
    import shutil
    shutil.copyfile(ready_csv_path, "reports/eligible_questions_database_export.csv")
    shutil.copyfile(counts_csv_path, "reports/05_subtopic_question_distribution.csv")
    print("Synced updated files to reports/ directory.")

if __name__ == "__main__":
    export_all()

