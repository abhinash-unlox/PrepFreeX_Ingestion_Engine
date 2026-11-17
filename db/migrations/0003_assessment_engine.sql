-- ====================================================================
-- PREPFREEX ASSESSMENT ENGINE SCHEMA PROPOSAL (MIGRATION 0003)
-- Status: PROPOSAL / DESIGN STAGE (Do NOT execute until review is complete)
-- ====================================================================

CREATE TABLE IF NOT EXISTS assessment_definitions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug text UNIQUE NOT NULL,
    title text NOT NULL,
    assessment_type text NOT NULL CHECK (
        assessment_type IN ('diagnostic','dpp','chapter_test','part_test','full_mock','revision_drill','adaptive')
    ),
    subject text CHECK (subject IN ('mathematics','physics','chemistry','composite')),
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS assessment_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    assessment_def_id uuid NOT NULL REFERENCES assessment_definitions(id) ON DELETE RESTRICT,
    version_number int NOT NULL CHECK (version_number > 0),
    duration_minutes int NOT NULL CHECK (duration_minutes > 0),
    total_marks int NOT NULL CHECK (total_marks > 0),
    instructions_md text,
    is_published boolean NOT NULL DEFAULT false,
    scoring_rules jsonb NOT NULL DEFAULT '{"correct": 4, "incorrect": -1, "unattempted": 0}'::jsonb,
    published_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (assessment_def_id, version_number)
);
CREATE INDEX IF NOT EXISTS idx_assessment_versions_def ON assessment_versions(assessment_def_id);

CREATE TABLE IF NOT EXISTS assessment_sections (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    assessment_version_id uuid NOT NULL REFERENCES assessment_versions(id) ON DELETE CASCADE,
    section_order int NOT NULL CHECK (section_order > 0),
    name text NOT NULL,
    subject text NOT NULL CHECK (subject IN ('mathematics','physics','chemistry','composite')),
    section_type text NOT NULL CHECK (section_type IN ('mandatory','optional_choice')),
    questions_to_attempt int NOT NULL CHECK (questions_to_attempt > 0),
    total_questions int NOT NULL CHECK (total_questions >= questions_to_attempt),
    scoring_policy jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (assessment_version_id, section_order)
);
CREATE INDEX IF NOT EXISTS idx_assessment_sections_version ON assessment_sections(assessment_version_id);

CREATE TABLE IF NOT EXISTS assessment_selection_rules (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    assessment_section_id uuid NOT NULL REFERENCES assessment_sections(id) ON DELETE CASCADE,
    rule_order int NOT NULL CHECK (rule_order > 0),
    taxonomy_code text,
    difficulty_target smallint CHECK (difficulty_target BETWEEN 1 AND 5),
    question_type text CHECK (
        question_type IN ('mcq_single','mcq_multi','numerical','assertion_reason','statement_based','match_list')
    ),
    count int NOT NULL CHECK (count > 0),
    fixed_question_id uuid REFERENCES questions(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_assessment_rules_section ON assessment_selection_rules(assessment_section_id);

CREATE TABLE IF NOT EXISTS assessment_attempts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    learner_id uuid NOT NULL,
    assessment_version_id uuid NOT NULL REFERENCES assessment_versions(id) ON DELETE RESTRICT,
    status text NOT NULL DEFAULT 'in_progress' CHECK (
        status IN ('in_progress','submitted','expired','interrupted','cancelled')
    ),
    started_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    submitted_at timestamptz,
    submission_idempotency_key text UNIQUE,
    time_spent_sec int NOT NULL DEFAULT 0,
    score_obtained real,
    total_possible_marks real,
    percentage real,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_assessment_attempts_learner ON assessment_attempts(learner_id, status);
CREATE INDEX IF NOT EXISTS idx_assessment_attempts_version ON assessment_attempts(assessment_version_id);

CREATE TABLE IF NOT EXISTS assessment_attempt_questions (
    id bigserial PRIMARY KEY,
    attempt_id uuid NOT NULL REFERENCES assessment_attempts(id) ON DELETE CASCADE,
    question_id uuid NOT NULL REFERENCES questions(id) ON DELETE RESTRICT,
    section_id uuid NOT NULL REFERENCES assessment_sections(id) ON DELETE RESTRICT,
    display_order int NOT NULL CHECK (display_order > 0),
    question_snapshot jsonb NOT NULL,
    correct_answer_snapshot jsonb NOT NULL,
    marks_correct real NOT NULL DEFAULT 4.0,
    marks_incorrect real NOT NULL DEFAULT -1.0,
    marks_unattempted real NOT NULL DEFAULT 0.0,
    UNIQUE (attempt_id, display_order),
    UNIQUE (attempt_id, question_id)
);
CREATE INDEX IF NOT EXISTS idx_attempt_questions_attempt ON assessment_attempt_questions(attempt_id);

CREATE TABLE IF NOT EXISTS attempt_responses (
    id bigserial PRIMARY KEY,
    attempt_question_id bigint UNIQUE NOT NULL REFERENCES assessment_attempt_questions(id) ON DELETE CASCADE,
    attempt_id uuid NOT NULL REFERENCES assessment_attempts(id) ON DELETE CASCADE,
    response_data jsonb,
    is_answered boolean NOT NULL DEFAULT false,
    is_marked_for_review boolean NOT NULL DEFAULT false,
    time_spent_seconds int NOT NULL DEFAULT 0,
    is_evaluated boolean NOT NULL DEFAULT false,
    is_correct boolean,
    score_awarded real,
    evaluated_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_attempt_responses_attempt ON attempt_responses(attempt_id);

CREATE TABLE IF NOT EXISTS assessment_results (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    attempt_id uuid UNIQUE NOT NULL REFERENCES assessment_attempts(id) ON DELETE CASCADE,
    learner_id uuid NOT NULL,
    total_questions int NOT NULL,
    attempted_count int NOT NULL,
    correct_count int NOT NULL,
    incorrect_count int NOT NULL,
    unattempted_count int NOT NULL,
    score real NOT NULL,
    max_score real NOT NULL,
    accuracy_percentage real NOT NULL,
    percentile real,
    subject_breakdown jsonb NOT NULL DEFAULT '{}'::jsonb,
    unit_breakdown jsonb NOT NULL DEFAULT '{}'::jsonb,
    time_breakdown jsonb NOT NULL DEFAULT '{}'::jsonb,
    generated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_assessment_results_learner ON assessment_results(learner_id);

CREATE TABLE IF NOT EXISTS question_exposures (
    id bigserial PRIMARY KEY,
    learner_id uuid NOT NULL,
    question_id uuid NOT NULL REFERENCES questions(id) ON DELETE RESTRICT,
    attempt_id uuid NOT NULL REFERENCES assessment_attempts(id) ON DELETE CASCADE,
    exposed_at timestamptz NOT NULL DEFAULT now(),
    was_correct boolean,
    response_time_sec int
);
CREATE INDEX IF NOT EXISTS idx_question_exposures_learner ON question_exposures(learner_id, question_id);

CREATE TABLE IF NOT EXISTS learner_topic_mastery (
    id bigserial PRIMARY KEY,
    learner_id uuid NOT NULL,
    taxonomy_code text NOT NULL,
    taxonomy_level text NOT NULL CHECK (taxonomy_level IN ('unit','topic','subtopic')),
    mastery_score real NOT NULL DEFAULT 0.0 CHECK (mastery_score BETWEEN 0.0 AND 1.0),
    attempts_count int NOT NULL DEFAULT 0,
    correct_count int NOT NULL DEFAULT 0,
    last_attempted_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (learner_id, taxonomy_code)
);
CREATE INDEX IF NOT EXISTS idx_topic_mastery_learner ON learner_topic_mastery(learner_id);

CREATE TABLE IF NOT EXISTS adaptive_decisions (
    id bigserial PRIMARY KEY,
    attempt_id uuid NOT NULL REFERENCES assessment_attempts(id) ON DELETE CASCADE,
    learner_id uuid NOT NULL,
    step_number int NOT NULL,
    previous_mastery_estimate real,
    selected_difficulty smallint CHECK (selected_difficulty BETWEEN 1 AND 5),
    target_taxonomy_code text,
    chosen_question_id uuid REFERENCES questions(id) ON DELETE SET NULL,
    decision_rationale text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_adaptive_decisions_attempt ON adaptive_decisions(attempt_id, step_number);

