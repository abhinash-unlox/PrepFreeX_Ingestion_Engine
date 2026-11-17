-- Migration 0008: Taxonomy Review Audits
-- Provides append-only audit trail for manual question taxonomy accuracy review

CREATE TABLE IF NOT EXISTS taxonomy_review_audits (
    id BIGSERIAL PRIMARY KEY,
    question_id UUID NOT NULL REFERENCES questions(id) ON DELETE RESTRICT,
    existing_taxonomy_snapshot JSONB NOT NULL,
    proposed_taxonomy_snapshot JSONB,
    reviewer_decision TEXT NOT NULL CHECK (reviewer_decision IN ('CONFIRM_CORRECT', 'RECLASSIFY', 'NEEDS_TAXONOMY_PROPOSAL', 'UNCERTAIN', 'SOURCE_PROBLEM')),
    reviewer_notes TEXT,
    reviewer_id TEXT NOT NULL DEFAULT 'internal_reviewer',
    taxonomy_version TEXT NOT NULL DEFAULT 'jee_main_2027',
    is_applied BOOLEAN NOT NULL DEFAULT FALSE,
    reviewed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    applied_at TIMESTAMPTZ,
    applied_by TEXT
);

CREATE INDEX IF NOT EXISTS idx_tax_review_q_id ON taxonomy_review_audits(question_id);
CREATE INDEX IF NOT EXISTS idx_tax_review_decision ON taxonomy_review_audits(reviewer_decision);
CREATE INDEX IF NOT EXISTS idx_tax_review_applied ON taxonomy_review_audits(is_applied);
CREATE INDEX IF NOT EXISTS idx_tax_review_reviewed_at ON taxonomy_review_audits(reviewed_at);

