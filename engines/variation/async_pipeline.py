import os
import sys
import json
import uuid
import time
import re
import psycopg
from psycopg.rows import dict_row

from engines.shared.config import settings
from engines.variation.generator import generate_variant_with_groq
from engines.variation.validator import run_comprehensive_validation

def upgrade_attempt_slots(attempt_id: str):
    """Background worker that sequentially mutates un-upgraded slots for an assessment."""
    print(f"[Async Pipeline] Starting background slot generation for attempt: {attempt_id}")
    
    conn = psycopg.connect(settings.database_url, row_factory=dict_row)
    cur = conn.cursor()

    try:
        # 1. Fetch un-upgraded slots for this attempt
        cur.execute("""
            SELECT ar.mock_question_number, ar.question_uid, ar.question_snapshot,
                   q.id as parent_id, q.question_uid as parent_uid, q.subject, q.unit_code,
                   q.chapter_name, q.primary_topic_code, q.question_type,
                   q.question_text_latex, q.options, q.correct_option, q.numerical_target,
                   q.solution_text_latex
            FROM public.attempt_responses ar
            JOIN public.questions q ON (ar.question_snapshot->>'id')::int = q.id
            WHERE ar.attempt_id = %s AND ar.is_variant = false
            ORDER BY ar.mock_question_number ASC;
        """, (attempt_id,))
        slots = cur.fetchall()
        print(f"[Async Pipeline] Found {len(slots)} un-upgraded slots to process.")

        for slot in slots:
            slot_num = slot['mock_question_number']
            parent_id = slot['parent_id']
            parent_uid = slot['parent_uid']
            subj = slot['subject']
            unit = slot['unit_code']
            chap = slot['chapter_name']
            
            # Pacing between background slots to prevent rate limits
            time.sleep(2.5)

            print(f"[Async Pipeline] Processing Slot #{slot_num} (Parent ID: {parent_id})...")

            # Check if an approved variant already exists in generated_questions or legacy mappings
            cur.execute("""
                SELECT id, generated_question_uid, generated_stem_latex as generated_question_text_latex,
                       generated_options, correct_answer as generated_correct_option, numerical_target as generated_numerical_target,
                       explanation_latex as generated_solution_latex, model_name as generator_type
                FROM public.generated_questions
                WHERE (source_question_id = %s OR source_question_uid = %s)
                  AND approval_status = 'APPROVED'
                ORDER BY RANDOM()
                LIMIT 1;
            """, (parent_id, parent_uid))
            existing_var = cur.fetchone()

            if not existing_var:
                cur.execute("""
                    SELECT id, generated_question_uid, generated_question_text_latex,
                           generated_options, generated_correct_option, generated_numerical_target,
                           generated_solution_latex, generator_type
                    FROM public.generated_question_mappings
                    WHERE parent_question_id = %s OR parent_question_uid = %s
                    ORDER BY RANDOM()
                    LIMIT 1;
                """, (parent_id, parent_uid))
                existing_var = cur.fetchone()

            if existing_var:
                # Use existing verified variant
                var_id = existing_var['id']
                gen_uid = existing_var['generated_question_uid']
                gen_text = existing_var['generated_question_text_latex']
                gen_opts = existing_var['generated_options']
                gen_corr = existing_var['generated_correct_option']
                gen_num = existing_var['generated_numerical_target']
                gen_sol = existing_var['generated_solution_latex']
                print(f"[Async Pipeline] Slot #{slot_num}: Found existing pre-verified variant #{var_id}")
            else:
                # Check parent question integrity before generation
                p_text = slot['question_text_latex'] or ""
                if re.search(r"has dimensions\s*(?:\n|$|\.|\bB\.)", p_text, flags=re.IGNORECASE):
                    print(f"[Async Pipeline] Slot #{slot_num}: Parent question #{parent_id} has truncated dimensions. Keeping verified canonical.")
                    continue

                # Generate new variant on-the-fly via Groq
                orig_q = {
                    "stem_md": slot['question_text_latex'],
                    "question_type": "numerical" if slot['question_type'] == 'NUMERICAL_VALUE' else "mcq_single",
                    "subject": subj,
                    "options": slot['options'] if isinstance(slot['options'], list) else [],
                    "answer": {
                        "type": "numeric" if slot['question_type'] == 'NUMERICAL_VALUE' else "option",
                        "positions": [int(slot['correct_option'])] if str(slot['correct_option']).isdigit() else [1],
                        "value": float(slot['numerical_target']) if slot['numerical_target'] is not None else None
                    },
                    "explanation_md": slot['solution_text_latex'] or ""
                }

                try:
                    t0 = time.time()
                    var_res = generate_variant_with_groq(orig_q)
                    gen_lat = time.time() - t0

                    # Run strict validation gate on newly generated variant
                    val_res = run_comprehensive_validation(var_res, orig_q)
                    if val_res.get("status") == "REJECTED":
                        print(f"[Async Pipeline] Slot #{slot_num}: Variant REJECTED by quality gate: {val_res.get('errors')}. Discarding and keeping canonical.")
                        continue
                    
                    gen_uid = f"var_groq_{uuid.uuid4().hex[:12]}"
                    gen_text = var_res.get('stem_md') or slot['question_text_latex']
                    
                    # Normalize options
                    raw_gen_opts = var_res.get('options', [])
                    gen_opts = []
                    if isinstance(raw_gen_opts, list):
                        for o in raw_gen_opts:
                            if isinstance(o, dict):
                                gen_opts.append(o.get('text_md') or o.get('text', ''))
                            else:
                                gen_opts.append(str(o))
                    if not gen_opts or len(gen_opts) < 4:
                        gen_opts = [o.get('text', '') if isinstance(o, dict) else str(o) for o in (slot['options'] or [])]

                    corr_ans = var_res.get('correct_answer', {})
                    if corr_ans.get('type') == 'numeric':
                        gen_corr = None
                        gen_num = float(corr_ans.get('value', 0.0))
                    else:
                        pos_list = corr_ans.get('positions', [1])
                        gen_corr = str(pos_list[0]) if pos_list else '1'
                        gen_num = None

                    gen_sol = var_res.get('explanation_md') or slot['solution_text_latex']

                    # Persist new variant into dedicated generated_questions table
                    cur.execute("""
                        INSERT INTO public.generated_questions (
                            generated_question_uid, source_question_id, source_question_uid,
                            subject, chapter_name, topic_code, topic_name,
                            question_type, generated_stem_latex, generated_options,
                            correct_answer, numerical_target, explanation_latex,
                            model_name, approval_status, validation_results, provenance, created_at
                        ) VALUES (
                            %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s,
                            %s, %s, %s,
                            %s, 'APPROVED', %s, %s, NOW()
                        ) ON CONFLICT (generated_question_uid) DO NOTHING
                        RETURNING id;
                    """, (
                        gen_uid, parent_id, parent_uid,
                        subj, chap, slot.get('primary_topic_code'), chap,
                        slot['question_type'], gen_text, json.dumps(gen_opts),
                        gen_corr, gen_num, gen_sol,
                        settings.groq_model, json.dumps(val_res),
                        json.dumps({'parent_uid': parent_uid, 'latency_seconds': round(gen_lat, 2), 'model': settings.groq_model})
                    ))
                    gen_row = cur.fetchone()
                    var_id = gen_row['id'] if gen_row else 1

                    # Also persist into legacy generated_question_mappings for backward compatibility
                    cur.execute("""
                        INSERT INTO public.generated_question_mappings (
                            parent_question_id, parent_question_uid, unit_code, subject, chapter_name,
                            parent_question_text_latex, parent_question_type, parent_options, parent_correct_option,
                            parent_numerical_target, parent_solution_latex,
                            generated_question_uid, generated_question_text_latex, generated_question_type,
                            generated_options, generated_correct_option, generated_numerical_target,
                            generated_solution_latex, generator_type, created_at
                        ) VALUES (
                            %s, %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s,
                            %s, %s, %s,
                            %s, %s, %s,
                            %s, %s, NOW()
                        ) ON CONFLICT (generated_question_uid) DO NOTHING;
                    """, (
                        parent_id, parent_uid, unit, subj, chap,
                        slot['question_text_latex'], slot['question_type'], json.dumps(slot['options']), str(slot['correct_option']),
                        slot['numerical_target'], slot['solution_text_latex'],
                        gen_uid, gen_text, slot['question_type'],
                        json.dumps(gen_opts), gen_corr, gen_num,
                        gen_sol, f"Groq On-the-Fly ({settings.groq_model})"
                    ))
                    conn.commit()
                    print(f"[Async Pipeline] Slot #{slot_num}: Generated & validated variant #{var_id} ({val_res.get('status')}) in {gen_lat:.2f}s")
                except Exception as e:
                    print(f"[Async Pipeline] Slot #{slot_num}: Groq generation failed ({e}), keeping canonical.")
                    continue

            # Update attempt_responses for this slot
            q_snap = slot['question_snapshot']
            if isinstance(q_snap, str):
                q_snap = json.loads(q_snap)
            q_snap.update({
                "question_uid": gen_uid,
                "is_variant": True,
                "variant_id": var_id,
                "text": gen_text,
                "options": gen_opts
            })

            ans_snap = {
                "correct_option": gen_corr,
                "numerical_target": float(gen_num) if gen_num is not None else None
            }

            cur.execute("""
                UPDATE public.attempt_responses
                SET question_snapshot = %s,
                    correct_answer_snapshot = %s,
                    explanation_snapshot = %s,
                    is_variant = true,
                    variant_id = %s,
                    question_uid = %s
                WHERE attempt_id = %s AND mock_question_number = %s;
            """, (
                json.dumps(q_snap),
                json.dumps(ans_snap),
                gen_sol,
                var_id,
                gen_uid,
                attempt_id,
                slot_num
            ))
            conn.commit()
            print(f"[Async Pipeline] Slot #{slot_num}: Successfully upgraded in DB.")

    except Exception as e:
        print(f"[Async Pipeline] Error in background worker: {e}")
    finally:
        conn.close()
        print(f"[Async Pipeline] Finished background slot generation for attempt: {attempt_id}")

