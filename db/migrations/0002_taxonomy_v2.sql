ALTER TABLE taxonomy ADD COLUMN IF NOT EXISTS description text;
ALTER TABLE taxonomy ADD COLUMN IF NOT EXISTS example_stems text[] DEFAULT '{}';
ALTER TABLE taxonomy ADD COLUMN IF NOT EXISTS replaced_by bigint REFERENCES taxonomy(id);

CREATE INDEX IF NOT EXISTS idx_taxonomy_replaced_by ON taxonomy(replaced_by);

CREATE TABLE IF NOT EXISTS taxonomy_proposals (
    id bigserial PRIMARY KEY,
    taxonomy_version text NOT NULL,
    parent_code text NOT NULL,
    proposed_name text NOT NULL,
    rationale text,
    example_question_keys text[] NOT NULL DEFAULT '{}',
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','accepted','rejected')),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_taxonomy_proposals_status ON taxonomy_proposals(status);

CREATE OR REPLACE VIEW v_test_eligible_questions AS
SELECT q.*
FROM questions q
JOIN source_documents d ON d.id=q.source_doc_id
WHERE q.status='verified'
  AND q.answer_key_verified=true
  AND (q.explanation_md IS NULL OR q.explanation_verified=true)
  AND q.figure_status IN ('none','attached')
  AND d.license_status='cleared'
  AND COALESCE((q.flags->>'needs_subtopic')::boolean,false)=false;

