-- ====================================================================
-- PREPFREEX ISOLATED LLM EVALUATION TABLES (MIGRATION 0005)
-- Purpose: Store experimental LLM model benchmarks (e.g. Qwen3-VL 8B)
-- completely isolated from canonical question bank tables.
-- ====================================================================

CREATE TABLE IF NOT EXISTS llm_evaluation_runs (
    run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider text NOT NULL DEFAULT 'ollama',
    model text NOT NULL,
    model_digest text,
    ollama_version text,
    prompt_version text NOT NULL DEFAULT 'v1',
    schema_version text NOT NULL DEFAULT 'v1',
    evaluation_type text NOT NULL DEFAULT 'isolated_experiment',
    started_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    total_questions int NOT NULL DEFAULT 0,
    completed_questions int NOT NULL DEFAULT 0,
    failed_questions int NOT NULL DEFAULT 0,
    status text NOT NULL DEFAULT 'in_progress'
        CHECK (status IN ('in_progress', 'completed', 'failed', 'stopped')),
    aggregate_metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS llm_evaluation_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id uuid NOT NULL REFERENCES llm_evaluation_runs(run_id) ON DELETE CASCADE,
    source_doc_id uuid REFERENCES source_documents(id) ON DELETE SET NULL,
    source_pdf_path text NOT NULL,
    source_sha256 text NOT NULL,
    source_page_start int,
    source_page_end int,
    subject text NOT NULL,
    source_question_number int NOT NULL,
    question_type text,
    has_figure boolean NOT NULL DEFAULT false,
    model_input text,
    reference_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    model_output jsonb NOT NULL DEFAULT '{}'::jsonb,
    raw_response text,
    validation_results jsonb NOT NULL DEFAULT '{}'::jsonb,
    extraction_status text NOT NULL DEFAULT 'UNVERIFIABLE'
        CHECK (extraction_status IN ('CORRECT', 'INCORRECT', 'UNVERIFIABLE', 'NEEDS_HUMAN_REVIEW')),
    answer_status text NOT NULL DEFAULT 'UNVERIFIABLE'
        CHECK (answer_status IN ('CORRECT', 'INCORRECT', 'UNVERIFIABLE', 'NEEDS_HUMAN_REVIEW')),
    taxonomy_status text NOT NULL DEFAULT 'UNVERIFIABLE'
        CHECK (taxonomy_status IN ('CORRECT', 'INCORRECT', 'UNVERIFIABLE', 'NEEDS_HUMAN_REVIEW')),
    human_review_status text NOT NULL DEFAULT 'pending'
        CHECK (human_review_status IN ('pending', 'approved', 'rejected')),
    latency_ms int,
    prompt_tokens int,
    completion_tokens int,
    ram_usage_mb real,
    cpu_percent real,
    error_details text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, source_sha256, source_question_number)
);

CREATE INDEX IF NOT EXISTS idx_llm_eval_items_run ON llm_evaluation_items(run_id);
CREATE INDEX IF NOT EXISTS idx_llm_eval_items_subject ON llm_evaluation_items(subject);

