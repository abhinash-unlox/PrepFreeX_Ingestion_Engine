-- ====================================================================
-- PREPFREEX CANONICAL QUESTION BANK SCHEMA ENHANCEMENTS (MIGRATION 0004)
-- Status: PROPOSAL / DESIGN STAGE (Do NOT execute until review is complete)
-- ====================================================================

-- 1. Concept and Skill Tags on Questions
ALTER TABLE questions ADD COLUMN IF NOT EXISTS concept_tags text[] NOT NULL DEFAULT '{}';
ALTER TABLE questions ADD COLUMN IF NOT EXISTS skill_tags text[] NOT NULL DEFAULT '{}';

-- 2. IRT / Empirical Metrics for Cognitive Calibration
ALTER TABLE questions ADD COLUMN IF NOT EXISTS empirical_p_value real; -- percentage of learners answering correctly
ALTER TABLE questions ADD COLUMN IF NOT EXISTS discrimination_index real; -- point-biserial correlation

-- 3. Enhanced Storage Bucket Support for Question Assets
ALTER TABLE question_assets ADD COLUMN IF NOT EXISTS storage_bucket text NOT NULL DEFAULT 'question-diagrams';

-- 4. Multi-Source Provenance Enhancements
ALTER TABLE question_sources ADD COLUMN IF NOT EXISTS source_notes text;
ALTER TABLE question_sources ADD COLUMN IF NOT EXISTS detected_similarity real;

-- 5. Explicit Question-to-Question Relations (Prevents Silent Merging of Near-Duplicates)
CREATE TABLE IF NOT EXISTS question_relations (
    id bigserial PRIMARY KEY,
    question_id_a uuid NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    question_id_b uuid NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    relationship_type text NOT NULL CHECK (
        relationship_type IN ('exact_duplicate','numerical_variant','rephrased','conceptual_sibling','superset')
    ),
    similarity_score real CHECK (similarity_score BETWEEN 0.0 AND 1.0),
    rationale text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (question_id_a, question_id_b, relationship_type),
    CHECK (question_id_a <> question_id_b)
);
CREATE INDEX IF NOT EXISTS idx_question_relations_a ON question_relations(question_id_a);
CREATE INDEX IF NOT EXISTS idx_question_relations_b ON question_relations(question_id_b);

