-- Migration 0012: Enhancements for Unclassified Extraction Pipeline
-- Adds direct indexing columns for content hash, figure status, and provenance on candidates

BEGIN;

ALTER TABLE ingestion_question_candidates
    ADD COLUMN IF NOT EXISTS content_hash TEXT,
    ADD COLUMN IF NOT EXISTS has_figure BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS figure_status TEXT DEFAULT 'none',
    ADD COLUMN IF NOT EXISTS source_pdf_filename TEXT,
    ADD COLUMN IF NOT EXISTS source_pdf_sha256 TEXT,
    ADD COLUMN IF NOT EXISTS classification_status TEXT NOT NULL DEFAULT 'PENDING';

CREATE INDEX IF NOT EXISTS idx_iqc_content_hash ON ingestion_question_candidates(content_hash);
CREATE INDEX IF NOT EXISTS idx_iqc_class_status ON ingestion_question_candidates(classification_status);
CREATE INDEX IF NOT EXISTS idx_iqc_source_pdf ON ingestion_question_candidates(source_pdf_sha256);

COMMIT;

