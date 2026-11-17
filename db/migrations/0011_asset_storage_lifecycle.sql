-- Migration 0011: Asset Storage Lifecycle & Object Storage Metadata
-- Enhances question_assets with ingestion/validation lifecycle and introduces generated_question_assets

BEGIN;

-- 1. Upgrade question_assets table
ALTER TABLE question_assets ALTER COLUMN question_id DROP NOT NULL;

ALTER TABLE question_assets
    ADD COLUMN IF NOT EXISTS candidate_id TEXT,
    ADD COLUMN IF NOT EXISTS source_document_id TEXT,
    ADD COLUMN IF NOT EXISTS source_page_number INTEGER,
    ADD COLUMN IF NOT EXISTS extraction_method TEXT,
    ADD COLUMN IF NOT EXISTS file_size_bytes BIGINT,
    ADD COLUMN IF NOT EXISTS upload_status TEXT NOT NULL DEFAULT 'VERIFIED',
    ADD COLUMN IF NOT EXISTS validation_status TEXT NOT NULL DEFAULT 'MACHINE_VERIFIED',
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- Status constraint for upload lifecycle
DO $$
BEGIN
    -- Update storage backend constraint to support minio and aws_s3
    ALTER TABLE question_assets DROP CONSTRAINT IF EXISTS question_assets_storage_backend_check;
    ALTER TABLE question_assets ADD CONSTRAINT question_assets_storage_backend_check
        CHECK (storage_backend IN ('local', 'minio', 'aws_s3', 's3', 'r2'));

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'check_question_assets_upload_status'
    ) THEN
        ALTER TABLE question_assets
            ADD CONSTRAINT check_question_assets_upload_status
            CHECK (upload_status IN ('EXTRACTED', 'ASSOCIATED', 'VALIDATED', 'UPLOAD_PENDING', 'UPLOADING', 'UPLOADED', 'VERIFIED', 'FAILED'));
    END IF;
END $$;

-- Status constraint for validation
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'check_question_assets_val_status'
    ) THEN
        ALTER TABLE question_assets
            ADD CONSTRAINT check_question_assets_val_status
            CHECK (validation_status IN ('MACHINE_VERIFIED', 'STRUCTURALLY_VALID', 'NEEDS_REVIEW', 'HUMAN_APPROVED', 'REJECTED'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_question_assets_candidate ON question_assets(candidate_id);
CREATE INDEX IF NOT EXISTS idx_question_assets_storage_key ON question_assets(storage_key);
CREATE INDEX IF NOT EXISTS idx_question_assets_sha256 ON question_assets(sha256);

-- 2. Create generated_question_assets table for variant figures/diagrams
CREATE TABLE IF NOT EXISTS generated_question_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    generated_question_id UUID NOT NULL REFERENCES generated_questions(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'stem',
    option_position SMALLINT,
    storage_backend TEXT NOT NULL DEFAULT 'minio',
    storage_bucket TEXT NOT NULL DEFAULT 'prepfreex-question-assets',
    storage_key TEXT NOT NULL,
    mime TEXT,
    width INTEGER,
    height INTEGER,
    file_size_bytes BIGINT,
    sha256 TEXT,
    alt_text TEXT,
    upload_status TEXT NOT NULL DEFAULT 'VERIFIED'
        CHECK (upload_status IN ('EXTRACTED', 'ASSOCIATED', 'VALIDATED', 'UPLOAD_PENDING', 'UPLOADING', 'UPLOADED', 'VERIFIED', 'FAILED')),
    validation_status TEXT NOT NULL DEFAULT 'MACHINE_VERIFIED'
        CHECK (validation_status IN ('MACHINE_VERIFIED', 'STRUCTURALLY_VALID', 'NEEDS_REVIEW', 'HUMAN_APPROVED', 'REJECTED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gen_q_assets_gen_qid ON generated_question_assets(generated_question_id);
CREATE INDEX IF NOT EXISTS idx_gen_q_assets_storage_key ON generated_question_assets(storage_key);

COMMIT;
