-- Migration 0009: Generated Questions and Experiments Storage
-- Stored separately from canonical questions to guarantee canonical integrity.

CREATE TABLE IF NOT EXISTS generated_questions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    public_id TEXT NOT NULL UNIQUE,
    source_question_id UUID NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    subject TEXT NOT NULL,
    question_type TEXT NOT NULL CHECK (question_type IN ('mcq_single', 'mcq_multiple', 'numerical')),
    stem_md TEXT NOT NULL,
    stem_plain TEXT NOT NULL,
    answer JSONB NOT NULL,
    explanation_md TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'EXPERIMENTAL' CHECK (status IN ('EXPERIMENTAL', 'NEEDS_REVIEW', 'APPROVED', 'REJECTED')),
    difficulty SMALLINT NOT NULL DEFAULT 3 CHECK (difficulty BETWEEN 1 AND 5),
    cognitive_level TEXT DEFAULT 'application',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gen_q_source ON generated_questions(source_question_id);
CREATE INDEX IF NOT EXISTS idx_gen_q_status ON generated_questions(status);
CREATE INDEX IF NOT EXISTS idx_gen_q_public_id ON generated_questions(public_id);
CREATE INDEX IF NOT EXISTS idx_gen_q_subject ON generated_questions(subject);

CREATE TABLE IF NOT EXISTS generated_question_options (
    generated_question_id UUID NOT NULL REFERENCES generated_questions(id) ON DELETE CASCADE,
    position SMALLINT NOT NULL,
    label_printed TEXT NOT NULL,
    text_md TEXT NOT NULL,
    PRIMARY KEY (generated_question_id, position)
);

CREATE TABLE IF NOT EXISTS generated_question_experiments (
    id BIGSERIAL PRIMARY KEY,
    generated_question_id UUID NOT NULL REFERENCES generated_questions(id) ON DELETE CASCADE,
    source_question_id UUID NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    source_snapshot JSONB NOT NULL,
    transformation_spec JSONB NOT NULL,
    validation_results JSONB NOT NULL,
    groq_review JSONB,
    model_name TEXT NOT NULL,
    tokens_consumed INTEGER DEFAULT 0,
    reviewer_feedback TEXT,
    human_verdict TEXT CHECK (human_verdict IN ('GOOD', 'INCORRECT', 'NEEDS_EDIT')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_gen_exp_gen_q ON generated_question_experiments(generated_question_id);
CREATE INDEX IF NOT EXISTS idx_gen_exp_src_q ON generated_question_experiments(source_question_id);
CREATE INDEX IF NOT EXISTS idx_gen_exp_verdict ON generated_question_experiments(human_verdict);

