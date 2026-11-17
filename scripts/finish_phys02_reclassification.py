import sys
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

import json
import re
import time
from apps.api.db import get_db_cursor
from engines.shared.groq_rotation import chat_with_rotation

def robust_json_loads(text: str):
    if "```" in text:
        parts = text.split("```")
        for p in parts:
            p_clean = p.strip()
            if p_clean.startswith("json"):
                p_clean = p_clean[4:].strip()
            if (p_clean.startswith("[") and p_clean.endswith("]")) or (p_clean.startswith("{") and p_clean.endswith("}")):
                text = p_clean
                break
    text = text.strip()
    try:
        return json.loads(text, strict=False)
    except Exception:
        pass
    match = re.search(r"\[\s*\{.*?\}\s*\]", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0), strict=False)
        except Exception:
            pass
    clean_text = re.sub(r'\\(?![/"\\bfnrtu])', r'\\\\', text)
    return json.loads(clean_text, strict=False)

def main():
    with open("v0-prepfreex-frontend/lib/canonical-taxonomy.json", "r", encoding="utf-8") as f:
        canon = json.load(f)

    chaps = {}
    topic_by_unit = {}
    for subj, chs in canon.items():
        for ch in chs:
            u_code = ch["unit_code"]
            chaps[u_code] = ch
            topic_by_unit[u_code] = ch.get("topics", [])

    unit_code = "PHYS_U02"
    unit_topics = topic_by_unit.get(unit_code, [])
    unit_topic_codes = [t["topic_code"] for t in unit_topics]
    topics_list_str = "\n".join([f"  - {t['topic_code']}: {t['topic_name']}" for t in unit_topics])

    with get_db_cursor() as cur:
        cur.execute("""
            SELECT id, question_text_latex, options
            FROM public.completed_questions
            WHERE unit_code = 'PHYS_U02' 
              AND primary_topic_code = 'PHYS_U02_T01'
              AND assessment_status = 'ELIGIBLE'
            ORDER BY id;
        """)
        questions = cur.fetchall()

    print(f"Loaded {len(questions)} remaining PHYS_U02_T01 questions to reclassify.")
    batch_size = 5
    grand_up = 0
    grand_brk = 0

    for i in range(0, len(questions), batch_size):
        batch = questions[i:i + batch_size]
        payload = []
        for q in batch:
            opts = q.get("options") or []
            if isinstance(opts, str):
                try: opts = json.loads(opts)
                except: opts = []
            clean_opts = [o.get("text") if isinstance(o, dict) else str(o) for o in opts]
            text = (q["question_text_latex"] or "").strip()
            payload.append({
                "id": q["id"],
                "text": text[:350].replace("\n", " ").strip(),
                "options": clean_opts[:4]
            })

        system_msg = (
            "You are an authoritative Indian JEE Main syllabus classifier and data auditor.\n"
            "Your job is to assign the question to its EXACT canonical topic_code.\n"
            "If the question belongs to this chapter, choose from the chapter's topics.\n"
            "If the question was accidentally placed in the wrong chapter, identify its TRUE unit_code and topic_code.\n"
            "If the question is unreadable or has missing essential equations/options, mark is_broken: true."
        )

        user_prompt = f"""Target Chapter Topics for {unit_code}:
{topics_list_str}

Instructions:
1. If the question belongs to {unit_code}, pick topic_code from {unit_topic_codes}.
2. If the question belongs to ANOTHER chapter (e.g. chemistry question inside kinematics, or solutions inside thermodynamics), set target_unit_code (e.g. 'CHEM_U06' or 'PHYS_U10') and assign topic_code accordingly.
3. If the question is unsolvable due to OCR corruption, missing reaction diagram, or missing equations, set is_broken: true.
4. Keep 'reason' concise (< 8 words).

Questions:
{json.dumps(payload, indent=2)}

Output strictly JSON array:
[
  {{"id": 123, "target_unit_code": "{unit_code}", "topic_code": "{unit_topic_codes[0]}", "is_broken": false, "reason": "ok"}}
]"""

        success = False
        for attempt in range(5):
            try:
                t0 = time.perf_counter()
                resp = chat_with_rotation(
                    messages=[
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.0,
                    max_tokens=600,
                    max_retries=32
                )
                elapsed = time.perf_counter() - t0
                raw = resp["choices"][0]["message"]["content"]
                results = robust_json_loads(raw)

                batch_up = 0
                batch_brk = 0
                with get_db_cursor() as cur:
                    for item in results:
                        qid = item.get("id")
                        t_unit = item.get("target_unit_code") or unit_code
                        t_code = item.get("topic_code")
                        is_brk = item.get("is_broken", False)
                        rsn = item.get("reason", "Broken stem")

                        if is_brk:
                            cur.execute("""
                                UPDATE public.completed_questions
                                SET assessment_status = 'BROKEN',
                                    academic_status = 'QUARANTINED',
                                    tags = COALESCE(tags, '[]'::jsonb) || jsonb_build_array('BROKEN_REASON: ' || %s)
                                WHERE id = %s;
                            """, (str(rsn), qid))
                            batch_brk += 1
                            grand_brk += 1
                        else:
                            target_chap = chaps.get(t_unit)
                            if target_chap:
                                new_unit = target_chap["unit_code"]
                                new_chap = target_chap["chapter_name"]
                                new_subj = target_chap["subject"]
                            else:
                                new_unit = unit_code
                                new_chap = chaps[unit_code]["chapter_name"]
                                new_subj = chaps[unit_code]["subject"]

                            valid_topics_for_unit = [t["topic_code"] for t in topic_by_unit.get(new_unit, [])]
                            if not t_code or t_code not in valid_topics_for_unit:
                                t_code = f"{new_unit}_T01"

                            cur.execute("""
                                UPDATE public.completed_questions
                                SET unit_code = %s,
                                    chapter_name = %s,
                                    subject = %s,
                                    primary_topic_code = %s
                                WHERE id = %s;
                            """, (new_unit, new_chap, new_subj, t_code, qid))
                            batch_up += 1
                            grand_up += 1

                print(f"  Batch {i//batch_size + 1}/{(len(questions)-1)//batch_size + 1} ({len(batch)} qs) -> {batch_up} classified, {batch_brk} broken ({elapsed:.2f}s)")
                time.sleep(1.0)
                success = True
                break
            except Exception as e:
                print(f"  Batch {i//batch_size + 1} attempt {attempt+1} failed: {e}. Cooling 5s...")
                time.sleep(5.0)

        if not success:
            print(f"  Batch {i//batch_size + 1} completely skipped after retries.")

    print("\n" + "=" * 60)
    print("FINISH PHYS_U02 RECLASSIFICATION COMPLETE!")
    print(f"Reclassified: {grand_up}")
    print(f"Quarantined: {grand_brk}")
    print("=" * 60)

if __name__ == "__main__":
    main()

