-- Migration 0014: User Authentication and Assessment Engine Expansion
-- Schema: public
-- Database: jee_mains_assesment

-- 1. Users Table for Student Authentication and Profiles
CREATE TABLE IF NOT EXISTS public.users (
    id VARCHAR(64) PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    full_name VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(32) NOT NULL DEFAULT 'student',
    target_exam VARCHAR(64) NOT NULL DEFAULT 'JEE Main 2027',
    target_percentile NUMERIC(5, 2) NOT NULL DEFAULT 99.00,
    daily_goal_sessions INTEGER NOT NULL DEFAULT 6,
    study_streak_days INTEGER NOT NULL DEFAULT 1,
    preferences JSONB NOT NULL DEFAULT '{"study_reminders": true, "weekly_email": false, "show_explanations": true}'::jsonb,
    last_login_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_email ON public.users(email);

-- 2. Expand assessment_attempts table if needed
ALTER TABLE public.assessment_attempts
    ADD COLUMN IF NOT EXISTS title VARCHAR(255),
    ADD COLUMN IF NOT EXISTS subject VARCHAR(64),
    ADD COLUMN IF NOT EXISTS chapter_name VARCHAR(255),
    ADD COLUMN IF NOT EXISTS topic_code VARCHAR(64),
    ADD COLUMN IF NOT EXISTS total_questions INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS attempted_questions INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS correct_questions INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS incorrect_questions INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS unattempted_questions INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS accuracy_percentage NUMERIC(5, 2) DEFAULT 0.00;

-- 3. Expand attempt_responses table if needed
ALTER TABLE public.attempt_responses
    ADD COLUMN IF NOT EXISTS is_variant BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS variant_id INTEGER,
    ADD COLUMN IF NOT EXISTS question_snapshot JSONB,
    ADD COLUMN IF NOT EXISTS correct_answer_snapshot JSONB,
    ADD COLUMN IF NOT EXISTS explanation_snapshot TEXT;

-- 4. Create default demo student Arjun Sharma for seamless instant access
INSERT INTO public.users (id, email, full_name, password_hash, role, target_exam, target_percentile, daily_goal_sessions, study_streak_days)
VALUES (
    'usr_arjun_sharma_2026',
    'arjun.sharma@prepfreex.com',
    'Arjun Sharma',
    'pbkdf2_sha256$260000$prepfreex$e5e9fa1ba31ecd1ae84f75caaa474f3a663f05f4', -- default password: Password@123
    'student',
    'JEE Main 2027',
    99.50,
    6,
    7
)
ON CONFLICT (email) DO UPDATE SET
    full_name = EXCLUDED.full_name,
    target_percentile = EXCLUDED.target_percentile;

-- 5. Grant permissions to prepfreex_user
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'prepfreex_user') THEN
        GRANT ALL PRIVILEGES ON TABLE public.users TO prepfreex_user;
        GRANT ALL PRIVILEGES ON TABLE public.assessment_attempts TO prepfreex_user;
        GRANT ALL PRIVILEGES ON TABLE public.attempt_responses TO prepfreex_user;
    END IF;
END $$;
