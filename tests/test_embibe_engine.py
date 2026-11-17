import sys
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)
import json
import time
from apps.api.db import get_db_cursor
from engines.synthesis.embibe_variant_engine import verify_and_ingest_variant

def test_single_seed_variant():
    print("--- 1. FETCHING HIGH-QUALITY SEED QUESTION ---")
    with get_db_cursor() as cur:
        # Fetch a clean seed from Physics & Measurement (Errors in Measurement - PHYS_U01_T02)
        cur.execute("""
            SELECT id, question_uid, subject, unit_code, chapter_name, primary_topic_code,
                   question_type, question_text_latex, options, correct_option, solution_text_latex,
                   subtopic_id, difficulty_tier
            FROM public.completed_questions
            WHERE primary_topic_code = 'PHYS_U01_T02' 
              AND assessment_status = 'ELIGIBLE' 
              AND is_synthetic = false
              AND question_text_latex NOT ILIKE '%\\begin{array}%'
            ORDER BY id
            LIMIT 1;
        """)
        seed = cur.fetchone()

    assert seed, "No seed question found!"
    print(f"Seed ID: {seed['id']} | Topic: {seed['primary_topic_code']}")
    print(f"Seed Question: {seed['question_text_latex'][:120]}...")
    print(f"Seed Correct Option: {seed['correct_option']}")

    print("\n--- 2. RUNNING DUAL-AGENT PIPELINE (GENERATOR + BLIND SOLVER) ---")
    t0 = time.perf_counter()
    res = verify_and_ingest_variant(seed, dry_run=False)
    elapsed = time.perf_counter() - t0

    print(f"\nExecution Time: {elapsed:.2f}s")
    print(f"Parity Passed: {res['parity_passed']}")
    print(f"Arbiter Reason: {res['reason']}")

    if res["generator_candidate"]:
        cand = res["generator_candidate"]
        print(f"\n[Generator Candidate]")
        print(f"  Stem: {cand['stem'][:140]}...")
        print(f"  Options: {cand['options']}")
        print(f"  Generator Claimed Answer: Option {cand['correct_option']}")

    if res["blind_solver_result"]:
        solv = res["blind_solver_result"]
        print(f"\n[Blind Solver (No key shown)]")
        print(f"  Derived Option: Option {solv.get('selected_option')}")
        print(f"  Derivation: {solv.get('derivation', '')[:160]}...")

    if res["parity_passed"]:
        new_id = res["ingested_id"]
        print(f"\n--- 3. DATABASE VERIFICATION ---")
        print(f"Successfully ingested variant into completed_questions! New DB ID: {new_id}")
        with get_db_cursor() as cur:
            cur.execute("""
                SELECT id, question_uid, primary_topic_code, question_text_latex, correct_option,
                       academic_status, is_synthetic, tags
                FROM public.completed_questions
                WHERE id = %s;
            """, (new_id,))
            row = cur.fetchone()
            print("DB Row:", row)
    else:
        print("\n[Hallucination Blocked]: Engine successfully prevented unverified variant from entering DB!")

if __name__ == "__main__":
    test_single_seed_variant()
