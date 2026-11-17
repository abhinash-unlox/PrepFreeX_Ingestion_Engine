-- ====================================================================
-- PREPFREEX CONTINUOUS PDF INGESTION & TRACKING REGISTRY (MIGRATION 0007)
-- ====================================================================

-- 1. Main PDF Processing Registry
CREATE TABLE IF NOT EXISTS pdf_processing_registry (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_doc_id uuid REFERENCES source_documents(id) ON DELETE SET NULL,
    relative_path text UNIQUE NOT NULL,
    filename text NOT NULL,
    category text NOT NULL,
    sha256 text NOT NULL,
    file_size_bytes bigint NOT NULL DEFAULT 0,
    page_count int NOT NULL DEFAULT 0,
    processing_status text NOT NULL DEFAULT 'DISCOVERED'
        CHECK (processing_status IN (
            'DISCOVERED', 'QUEUED', 'IN_PROGRESS', 'EXTRACTED', 
            'VALIDATING', 'PARTIALLY_COMPLETED', 'COMPLETED', 
            'COMPLETED_WITH_REVIEW', 'NEEDS_MANUAL_REVIEW', 
            'FAILED_RETRYABLE', 'BLOCKED_TOKEN_BUDGET', 'SOURCE_CHANGED'
        )),
    total_questions_detected int NOT NULL DEFAULT 0,
    questions_extracted int NOT NULL DEFAULT 0,
    questions_verified int NOT NULL DEFAULT 0,
    questions_rejected int NOT NULL DEFAULT 0,
    questions_needing_review int NOT NULL DEFAULT 0,
    questions_promoted int NOT NULL DEFAULT 0,
    failed_questions int NOT NULL DEFAULT 0,
    groq_requests int NOT NULL DEFAULT 0,
    prompt_tokens int NOT NULL DEFAULT 0,
    completion_tokens int NOT NULL DEFAULT 0,
    total_tokens int NOT NULL DEFAULT 0,
    current_page int NOT NULL DEFAULT 0,
    current_question_number int NOT NULL DEFAULT 0,
    current_attempt int NOT NULL DEFAULT 0,
    last_error text,
    locked_by text,
    locked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    completed_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_pdf_registry_status ON pdf_processing_registry(processing_status);
CREATE INDEX IF NOT EXISTS idx_pdf_registry_category ON pdf_processing_registry(category);
CREATE INDEX IF NOT EXISTS idx_pdf_registry_sha256 ON pdf_processing_registry(sha256);

-- 2. Append-only PDF Processing Audit Events
CREATE TABLE IF NOT EXISTS pdf_processing_events (
    id bigserial PRIMARY KEY,
    pdf_id uuid NOT NULL REFERENCES pdf_processing_registry(id) ON DELETE CASCADE,
    event_type text NOT NULL,
    message text,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_pdf_events_pdf_id ON pdf_processing_events(pdf_id);
CREATE INDEX IF NOT EXISTS idx_pdf_events_type ON pdf_processing_events(event_type);

-- 3. Enhance Ingestion Question Candidates for Registry Linkage
ALTER TABLE ingestion_question_candidates 
    ADD COLUMN IF NOT EXISTS pdf_registry_id uuid REFERENCES pdf_processing_registry(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS canonical_question_id uuid REFERENCES questions(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS verification_status text DEFAULT 'UNVERIFIABLE',
    ADD COLUMN IF NOT EXISTS academic_notes text;

CREATE INDEX IF NOT EXISTS idx_candidates_registry ON ingestion_question_candidates(pdf_registry_id);
CREATE INDEX IF NOT EXISTS idx_candidates_canonical ON ingestion_question_candidates(canonical_question_id);

