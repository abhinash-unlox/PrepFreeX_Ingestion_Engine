"""
CLI runner for automated full-length test ingestion.
Extracts questions, runs academic guardrails, categorizes via 3-tier taxonomy,
verifies via AIR-1 Blind Solver parity, and only promotes questions where the blind solver matches!
"""

import os
import glob
import argparse
from apps.api.db import get_db_cursor
from engines.ingestion.full_test_ingestor import FullTestIngestor

DEFAULT_PDF = "data/raw/jee_dataset/full_tests/JEE Main 2022 (Online) 24th June Evening Shift Question Paper with Answer Key.pdf"

def get_pending_full_tests(limit: int = 3) -> list[str]:
    pdf_pattern = "data/raw/jee_dataset/full_tests/*Question Paper with Answer Key.pdf"
    all_files = sorted(glob.glob(pdf_pattern))
    
    with get_db_cursor() as cur:
        cur.execute("SELECT pdf_path FROM public.pdf_ingestion_manifest WHERE status = 'COMPLETED';")
        completed = {r["pdf_path"] for r in cur.fetchall()}
    
    pending = [p for p in all_files if p not in completed and os.path.abspath(p) not in completed]
    return pending[:limit]

def main():
    parser = argparse.ArgumentParser(description="Automated Full-Length Test Ingestor")
    parser.add_argument("--pdf", type=str, default=None, help="Path to single full test PDF")
    parser.add_argument("--num-pdfs", type=int, default=3, help="Number of pending PDFs to process in sequence")
    parser.add_argument("--start", type=int, default=None, help="Start question number (e.g. 1 to 90)")
    parser.add_argument("--limit", type=int, default=None, help="Number of questions to process per PDF (default: all)")
    parser.add_argument("--no-auto-promote", action="store_true", help="Do not auto-promote matched questions")

    args = parser.parse_args()
    ingestor = FullTestIngestor()

    if args.pdf:
        targets = [args.pdf]
    else:
        targets = get_pending_full_tests(limit=args.num_pdfs)

    print(f"Selected {len(targets)} test papers for ingestion:")
    for idx, t in enumerate(targets, 1):
        print(f"  [{idx}] {os.path.basename(t)}")

    for idx, p in enumerate(targets, 1):
        if not os.path.exists(p):
            print(f"Error: File not found: {p}")
            continue
        print(f"\n=======================================================")
        print(f">>> [{idx}/{len(targets)}] INGESTING: {os.path.basename(p)}")
        print(f"=======================================================")
        ingestor.ingest_full_test(
            pdf_path=p,
            start_question=args.start,
            limit_questions=args.limit,
            auto_promote_matched=not args.no_auto_promote
        )

if __name__ == "__main__":
    main()

