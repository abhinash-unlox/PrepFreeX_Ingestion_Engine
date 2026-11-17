#!/usr/bin/env python3
"""
PrepFreeX Embibe Synthesis Engine - Batch Runner
=================================================
Automates parametric question variant synthesis with dual-agent verification:
  1. SME Variant Generator (creates candidate with mutated parameters)
  2. AIR-1 Blind Solver (independently solves candidate without seeing author's key)
  3. Parity Arbiter (ensures strict congruence before DB insertion)

Usage:
    python -m scripts.run_embibe_synthesis_batch --topic PHYS_U01_T01 --count 5
    python -m scripts.run_embibe_synthesis_batch --fill-sparse --min-count 5
"""

import argparse
import sys
from engines.synthesis.embibe_variant_engine import generate_verified_variant, BlindSolveParityError
from apps.api.db import get_db_cursor

def synthesize_for_topic(topic_code: str, count: int = 5):
    print(f"\n==================================================")
    print(f"Targeting Topic: {topic_code} (Goal: {count} verified variants)")
    print(f"==================================================")

    # 1. Fetch seed questions from database for this topic or chapter
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT id, question_text_latex, options, correct_option, solution_text_latex,
                   subject, unit_code, primary_topic_code, difficulty_tier
            FROM public.completed_questions
            WHERE primary_topic_code = %s AND assessment_status = 'ELIGIBLE'
            ORDER BY id
            LIMIT 10;
        """, (topic_code,))
        seeds = cur.fetchall()

        if not seeds:
            # Fallback to same chapter seeds
            chap = "_".join(topic_code.split("_")[:2])
            cur.execute("""
                SELECT id, question_text_latex, options, correct_option, solution_text_latex,
                       subject, unit_code, primary_topic_code, difficulty_tier
                FROM public.completed_questions
                WHERE unit_code = %s AND assessment_status = 'ELIGIBLE'
                ORDER BY id
                LIMIT 10;
            """, (chap,))
            seeds = cur.fetchall()

    if not seeds:
        print(f"❌ No eligible seed questions found for topic {topic_code} or unit.")
        return 0

    print(f"Loaded {len(seeds)} seed questions for parametric mutation.")
    success_count = 0
    seed_idx = 0

    for i in range(count):
        seed = seeds[seed_idx % len(seeds)]
        seed_idx += 1
        print(f"\n[{i+1}/{count}] Synthesizing variant from Seed #{seed['id']}...")

        seed_dict = {
            "id": seed["id"],
            "question_text_latex": seed["question_text_latex"],
            "options": seed["options"],
            "correct_option": seed["correct_option"],
            "solution_text_latex": seed["solution_text_latex"],
            "subject": seed["subject"],
            "unit_code": seed["unit_code"],
            "primary_topic_code": topic_code,
            "difficulty_tier": seed.get("difficulty_tier") or "MEDIUM"
        }

        try:
            res = generate_verified_variant(seed_dict, target_subtopic=topic_code, auto_ingest=True)
            print(f"  ✅ SUCCESS: Variant ingested into DB as ID {res.get('inserted_db_id')} (Variant UID: {res.get('variant_uid')})")
            print(f"     Congruence Verified: Author Key '{res.get('candidate', {}).get('correct_option')}' == Blind Key '{res.get('blind_solution', {}).get('derived_correct_option')}'")
            success_count += 1
        except BlindSolveParityError as bse:
            print(f"  ⚠️ PARITY REJECTED (Embibe Gatekeeper Caught Mismatch): {bse}")
        except Exception as e:
            print(f"  ❌ Generation Error: {e}")

    print(f"\nFinished batch for {topic_code}: {success_count}/{count} variants successfully verified and ingested.")
    return success_count

def fill_sparse_topics(min_count: int = 5):
    print(f"\nScanning for all topics with fewer than {min_count} eligible questions...")
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT primary_topic_code, count(*) as cnt
            FROM public.completed_questions
            WHERE assessment_status = 'ELIGIBLE' AND primary_topic_code IS NOT NULL
            GROUP BY primary_topic_code
            HAVING count(*) < %s
            ORDER BY count(*) ASC;
        """, (min_count,))
        sparse = cur.fetchall()

    print(f"Found {len(sparse)} sparse topics in current curriculum.")
    for s in sparse:
        top = s["primary_topic_code"]
        current_cnt = s["cnt"]
        needed = min_count - current_cnt
        print(f"\nTopic {top}: currently has {current_cnt} questions. Generating {needed} verified variants...")
        synthesize_for_topic(top, count=needed)

def main():
    parser = argparse.ArgumentParser(description="PrepFreeX Embibe Parametric Variant Generator")
    parser.add_argument("--topic", type=str, help="Target topic code (e.g. PHYS_U01_T01)")
    parser.add_argument("--count", type=int, default=5, help="Number of variants to synthesize")
    parser.add_argument("--fill-sparse", action="store_true", help="Automatically backfill all sparse topics to min count")
    parser.add_argument("--min-count", type=int, default=5, help="Minimum questions per topic for backfill")

    args = parser.parse_args()

    if args.fill_sparse:
        fill_sparse_topics(min_count=args.min_count)
    elif args.topic:
        synthesize_for_topic(args.topic, count=args.count)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()

