-- Migration 0010: Validation Hardening & Status Segregation
-- Expands status checks to support rigorous multi-tier verification statuses

ALTER TABLE generated_questions DROP CONSTRAINT IF EXISTS generated_questions_status_check;
ALTER TABLE generated_questions ADD CONSTRAINT generated_questions_status_check 
    CHECK (status IN (
        'EXPERIMENTAL',
        'STRUCTURALLY_VALID',
        'MACHINE_VERIFIED',
        'LLM_REVIEWED',
        'HUMAN_APPROVED',
        'NEEDS_REVIEW',
        'REJECTED',
        'APPROVED'  -- backward compatibility with Phase 1
    ));

-- Add validation tier metadata columns to generated_question_experiments if not present
ALTER TABLE generated_question_experiments 
    ADD COLUMN IF NOT EXISTS deterministic_validation JSONB,
    ADD COLUMN IF NOT EXISTS difficulty_analysis JSONB,
    ADD COLUMN IF NOT EXISTS validation_status TEXT DEFAULT 'EXPERIMENTAL';

