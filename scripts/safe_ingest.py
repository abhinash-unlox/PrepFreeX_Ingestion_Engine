"""
Safe Ingest CLI Batch Runner
Usage:
  python -m scripts.safe_ingest --input data/raw/jee_dataset/physics/Kinematics...pdf
  python -m scripts.safe_ingest --next-pending --limit-pdfs 1 --max-pages 2
"""

from __future__ import annotations
import sys
sys.path.append('.')
import argparse
from pathlib import Path
from apps.api.db import get_db_cursor
from engines.ingestion.safe_ingestor import SafeIngestionPipeline

def main():
    parser = argparse.ArgumentParser(description="PrepFreeX Safe Ingestion Pipeline CLI")
    parser.add_argument("--input", type=str, help="Path to single PDF file or directory")
    parser.add_argument("--next-pending", action="store_true", help="Picks next pending PDF from manifest")
    parser.add_argument("--subject", type=str, help="Subject override (PHYSICS, CHEMISTRY, MATHEMATICS)")
    parser.add_argument("--chapter", type=str, help="Chapter name override")
    parser.add_argument("--limit-pdfs", type=int, default=1, help="Max PDFs to process in this run")
    parser.add_argument("--max-pages", type=int, default=None, help="Max pages to extract per PDF")
    parser.add_argument("--no-solver", action="store_true", help="Skip Blind Solver arbitration step")

    args = parser.parse_args()
    pipeline = SafeIngestionPipeline()

    pdf_targets = []

    if args.input:
        inp = Path(args.input)
        if inp.is_file() and inp.suffix.lower() == ".pdf":
            pdf_targets.append({
                "path": str(inp.as_posix()),
                "subject": args.subject,
                "chapter": args.chapter
            })
        elif inp.is_dir():
            for p in list(inp.glob("**/*.pdf"))[:args.limit_pdfs]:
                pdf_targets.append({
                    "path": str(p.as_posix()),
                    "subject": args.subject,
                    "chapter": args.chapter
                })
    elif args.next_pending:
        with get_db_cursor() as cur:
            cur.execute("""
                SELECT pdf_path, subject, chapter_guess
                FROM public.pdf_ingestion_manifest
                WHERE status = 'PENDING' AND subject IN ('PHYSICS', 'CHEMISTRY', 'MATHEMATICS')
                ORDER BY id ASC
                LIMIT %s;
            """, (args.limit_pdfs,))
            rows = cur.fetchall()
            for r in rows:
                pdf_targets.append({
                    "path": r["pdf_path"],
                    "subject": r["subject"],
                    "chapter": r["chapter_guess"]
                })
    else:
        print("Please specify --input <path> or --next-pending")
        return

    print(f"Loaded {len(pdf_targets)} target PDF(s) to process.")
    for idx, target in enumerate(pdf_targets, 1):
        print(f"\n[{idx}/{len(pdf_targets)}] Processing: {target['path']}")
        pipeline.process_pdf(
            pdf_path=target["path"],
            subject_hint=target["subject"],
            chapter_hint=target["chapter"],
            max_pages=args.max_pages,
            run_solver=not args.no_solver
        )

if __name__ == "__main__":
    main()

