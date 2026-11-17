CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS source_documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    sha256 text UNIQUE NOT NULL CHECK (length(sha256) = 64),
    title text NOT NULL,
    publisher text,
    exam text,
    exam_year int,
    file_path text,
    license_status text NOT NULL DEFAULT 'unverified'
        CHECK (license_status IN ('unverified','cleared','restricted')),
    notes text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ingestion_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_doc_id uuid REFERENCES source_documents(id) ON DELETE SET NULL,
    original_filename text NOT NULL,
    sha256 text,
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued','processing','needs_review','completed','failed')),
    document_type text NOT NULL DEFAULT 'auto',
    page_count int,
    extracted_question_count int NOT NULL DEFAULT 0,
    taxonomy_version text,
    classifier_provider text,
    error_message text,
    started_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS document_pages (
    id bigserial PRIMARY KEY,
    ingestion_job_id uuid NOT NULL REFERENCES ingestion_jobs(id) ON DELETE CASCADE,
    page_number int NOT NULL CHECK (page_number > 0),
    extracted_text text,
    extraction_method text NOT NULL,
    text_char_count int NOT NULL DEFAULT 0,
    image_count int NOT NULL DEFAULT 0,
    has_drawings boolean NOT NULL DEFAULT false,
    rendered_image_path text,
    processing_status text NOT NULL DEFAULT 'extracted',
    UNIQUE (ingestion_job_id, page_number)
);

CREATE TABLE IF NOT EXISTS taxonomy (
    id bigserial PRIMARY KEY,
    taxonomy_version text NOT NULL,
    code text NOT NULL,
    parent_id bigint REFERENCES taxonomy(id),
    level text NOT NULL CHECK (level IN ('subject','area','unit','topic','subtopic')),
    name text NOT NULL,
    syllabus_text text,
    sort_order int,
    is_reviewed boolean NOT NULL DEFAULT false,
    is_active boolean NOT NULL DEFAULT true,
    UNIQUE (taxonomy_version, code)
);
CREATE INDEX IF NOT EXISTS idx_taxonomy_parent ON taxonomy(parent_id);
CREATE INDEX IF NOT EXISTS idx_taxonomy_version_level ON taxonomy(taxonomy_version, level);

CREATE SEQUENCE IF NOT EXISTS question_public_seq;

CREATE TABLE IF NOT EXISTS questions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    public_id text UNIQUE NOT NULL DEFAULT ('Q' || lpad(nextval('question_public_seq')::text, 8, '0')),
    version int NOT NULL DEFAULT 1,
    source_doc_id uuid NOT NULL REFERENCES source_documents(id),
    source_q_label text NOT NULL,
    source_question_key text NOT NULL,
    source_part text,
    source_section text,
    source_local_number int,
    source_global_number int,
    source_page_start int,
    source_page_end int,
    figure_source_page int,
    origin text NOT NULL CHECK (origin IN ('pyq','coaching','ai_generated','original')),
    exam_name text,
    exam_year int,
    exam_date date,
    exam_shift smallint,
    subject text NOT NULL CHECK (subject IN ('mathematics','physics','chemistry')),
    question_type text NOT NULL CHECK (question_type IN ('mcq_single','mcq_multi','numerical','assertion_reason','statement_based','match_list')),
    language text NOT NULL DEFAULT 'en',
    stem_md text NOT NULL,
    stem_plain text,
    answer jsonb NOT NULL,
    explanation_md text,
    explanation_source text CHECK (explanation_source IN ('source','ai','human')),
    source_explanation_md text,
    answer_key_verified boolean NOT NULL DEFAULT false,
    explanation_verified boolean NOT NULL DEFAULT false,
    answer_verification_notes text,
    explanation_verification_notes text,
    difficulty smallint CHECK (difficulty BETWEEN 1 AND 5),
    difficulty_source text CHECK (difficulty_source IN ('source','ai_estimated','empirical')),
    cognitive_level text CHECK (cognitive_level IN ('recall','understand','apply','analyze')),
    estimated_time_sec int CHECK (estimated_time_sec IS NULL OR estimated_time_sec > 0),
    formulas_used text[] NOT NULL DEFAULT '{}',
    keywords text[] NOT NULL DEFAULT '{}',
    common_mistakes text,
    has_figure boolean NOT NULL DEFAULT false,
    figure_status text NOT NULL DEFAULT 'none' CHECK (figure_status IN ('none','pending','attached')),
    figure_description text,
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','needs_review','verified','rejected','retired')),
    extraction_method text,
    extraction_confidence real CHECK (extraction_confidence IS NULL OR extraction_confidence BETWEEN 0 AND 1),
    flags jsonb NOT NULL DEFAULT '{}',
    content_hash text NOT NULL,
    reviewed_by text,
    reviewed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_doc_id, source_question_key),
    CHECK (has_figure = (figure_status <> 'none')),
    CHECK (source_page_start IS NULL OR source_page_start > 0),
    CHECK (source_page_end IS NULL OR source_page_start IS NULL OR source_page_end >= source_page_start)
);
CREATE INDEX IF NOT EXISTS idx_questions_content_hash ON questions(content_hash);
CREATE INDEX IF NOT EXISTS idx_questions_subject_status ON questions(subject,status);
CREATE INDEX IF NOT EXISTS idx_questions_source ON questions(source_doc_id);
CREATE INDEX IF NOT EXISTS idx_questions_exam ON questions(exam_name,exam_year,exam_date,exam_shift);
CREATE INDEX IF NOT EXISTS idx_questions_type ON questions(question_type);
CREATE INDEX IF NOT EXISTS idx_questions_search ON questions USING gin(to_tsvector('english',coalesce(stem_plain,stem_md)));

CREATE TABLE IF NOT EXISTS question_options (
    question_id uuid NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    position smallint NOT NULL CHECK (position > 0),
    label_printed text,
    text_md text NOT NULL,
    PRIMARY KEY (question_id,position)
);

CREATE TABLE IF NOT EXISTS question_match_items (
    question_id uuid NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    side text NOT NULL CHECK (side IN ('left','right')),
    item_key text NOT NULL,
    position smallint NOT NULL CHECK (position > 0),
    text_md text NOT NULL,
    PRIMARY KEY (question_id,side,item_key),
    UNIQUE (question_id,side,position)
);

CREATE TABLE IF NOT EXISTS question_tags (
    question_id uuid NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    taxonomy_id bigint NOT NULL REFERENCES taxonomy(id),
    is_primary boolean NOT NULL DEFAULT false,
    confidence real CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    source text NOT NULL CHECK (source IN ('human','llm','rule')),
    tagger_version text,
    reviewed_by text,
    reviewed_at timestamptz,
    PRIMARY KEY (question_id,taxonomy_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_primary_tag ON question_tags(question_id) WHERE is_primary=true;
CREATE INDEX IF NOT EXISTS idx_question_tags_taxonomy ON question_tags(taxonomy_id);

CREATE TABLE IF NOT EXISTS question_assets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    question_id uuid NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    role text NOT NULL CHECK (role IN ('stem','option','solution','source_snapshot')),
    option_position smallint,
    storage_backend text NOT NULL DEFAULT 'local' CHECK (storage_backend IN ('local','r2')),
    storage_key text NOT NULL,
    mime text,
    width int,
    height int,
    alt_text text,
    sha256 text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS question_sources (
    question_id uuid NOT NULL REFERENCES questions(id) ON DELETE RESTRICT,
    source_doc_id uuid NOT NULL REFERENCES source_documents(id) ON DELETE RESTRICT,
    source_q_label text,
    source_page_start int,
    source_page_end int,
    relationship text NOT NULL DEFAULT 'origin',
    PRIMARY KEY (question_id,source_doc_id,relationship)
);

CREATE TABLE IF NOT EXISTS classification_runs (
    id bigserial PRIMARY KEY,
    ingestion_job_id uuid REFERENCES ingestion_jobs(id) ON DELETE SET NULL,
    source_question_key text NOT NULL,
    taxonomy_version text NOT NULL,
    provider text NOT NULL,
    model text,
    prompt_version text,
    result_json jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (ingestion_job_id, source_question_key, taxonomy_version, prompt_version)
);

CREATE TABLE IF NOT EXISTS review_records (
    id bigserial PRIMARY KEY,
    question_id uuid NOT NULL REFERENCES questions(id) ON DELETE RESTRICT,
    reviewer text,
    action text NOT NULL CHECK (action IN ('approved','corrected','rejected','reclassified','returned_for_review')),
    previous_state jsonb,
    new_state jsonb,
    notes text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ingestion_errors (
    id bigserial PRIMARY KEY,
    ingestion_job_id uuid NOT NULL REFERENCES ingestion_jobs(id) ON DELETE CASCADE,
    page_number int,
    source_question_key text,
    stage text NOT NULL,
    error_code text,
    message text NOT NULL,
    details jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS question_revisions (
    id bigserial PRIMARY KEY,
    question_id uuid NOT NULL REFERENCES questions(id) ON DELETE RESTRICT,
    version int NOT NULL,
    snapshot jsonb NOT NULL,
    changed_by text,
    reason text,
    changed_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(question_id,version)
);

CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_questions_updated_at ON questions;
CREATE TRIGGER trg_questions_updated_at
BEFORE UPDATE ON questions
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE OR REPLACE VIEW v_test_eligible_questions AS
SELECT q.*
FROM questions q
JOIN source_documents d ON d.id=q.source_doc_id
WHERE q.status='verified'
  AND q.answer_key_verified=true
  AND (q.explanation_md IS NULL OR q.explanation_verified=true)
  AND q.figure_status IN ('none','attached')
  AND d.license_status='cleared';

-- Staging area: extracted candidates are not yet canonical/publishable questions.
CREATE TABLE IF NOT EXISTS ingestion_question_candidates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ingestion_job_id uuid NOT NULL REFERENCES ingestion_jobs(id) ON DELETE CASCADE,
    source_question_key text NOT NULL,
    source_q_label text,
    source_part text,
    source_section text,
    source_local_number int,
    source_global_number int,
    source_page_start int,
    source_page_end int,
    subject_guess text,
    question_type_guess text,
    stem_md text,
    options_json jsonb NOT NULL DEFAULT '[]',
    answer_json jsonb,
    classification_json jsonb NOT NULL DEFAULT '{}',
    extraction_json jsonb NOT NULL DEFAULT '{}',
    review_status text NOT NULL DEFAULT 'needs_review'
        CHECK (review_status IN ('needs_review','approved','rejected','imported')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (ingestion_job_id, source_question_key)
);
CREATE INDEX IF NOT EXISTS idx_ingestion_candidates_review
    ON ingestion_question_candidates(review_status);

DROP TRIGGER IF EXISTS trg_ingestion_candidates_updated_at ON ingestion_question_candidates;
CREATE TRIGGER trg_ingestion_candidates_updated_at
BEFORE UPDATE ON ingestion_question_candidates
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
