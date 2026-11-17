-- ====================================================================
-- PREPFREEX LLM EVALUATION EXPERIMENT LABEL (MIGRATION 0006)
-- Adds experiment_label to llm_evaluation_runs for easy comparison.
-- ====================================================================

ALTER TABLE llm_evaluation_runs 
ADD COLUMN IF NOT EXISTS experiment_label text;

