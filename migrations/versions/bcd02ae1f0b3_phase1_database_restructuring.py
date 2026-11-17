"""phase1_database_restructuring

Revision ID: bcd02ae1f0b3
Revises: 
Create Date: 2026-11-14 07:37:54.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'bcd02ae1f0b3'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Subjects reference table
    op.execute("""
        CREATE TABLE IF NOT EXISTS public.subjects (
            id SERIAL PRIMARY KEY,
            code VARCHAR(100) UNIQUE NOT NULL,
            name VARCHAR(100) NOT NULL,
            total_canonical_chapters INT NOT NULL,
            total_canonical_topics INT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        
        INSERT INTO public.subjects (code, name, total_canonical_chapters, total_canonical_topics)
        VALUES 
            ('PHYSICS', 'Physics', 20, 80),
            ('CHEMISTRY', 'Chemistry', 28, 112),
            ('MATHEMATICS', 'Mathematics', 16, 64)
        ON CONFLICT (code) DO NOTHING;
    """)

    # 2. First-class dedicated generated_questions table
    op.execute("""
        CREATE TABLE IF NOT EXISTS public.generated_questions (
            id SERIAL PRIMARY KEY,
            generated_question_uid VARCHAR(255) UNIQUE NOT NULL,
            source_question_id INT REFERENCES public.questions(id) ON DELETE SET NULL,
            source_question_uid VARCHAR(255),
            subject VARCHAR(100) NOT NULL,
            chapter_id INT,
            chapter_name VARCHAR(255),
            topic_code VARCHAR(255),
            topic_name VARCHAR(255),
            question_type VARCHAR(50) NOT NULL DEFAULT 'SINGLE_CHOICE',
            generated_stem_latex TEXT NOT NULL,
            generated_options JSONB NOT NULL DEFAULT '[]'::jsonb,
            correct_answer VARCHAR(100),
            numerical_target NUMERIC,
            numerical_tolerance NUMERIC DEFAULT 0.0,
            explanation_latex TEXT NOT NULL,
            model_name VARCHAR(500),
            model_version VARCHAR(100),
            prompt_version VARCHAR(100),
            generation_timestamp TIMESTAMPTZ DEFAULT NOW(),
            input_tokens INT DEFAULT 0,
            output_tokens INT DEFAULT 0,
            validation_results JSONB DEFAULT '{}'::jsonb,
            duplicate_check_result JSONB DEFAULT '{}'::jsonb,
            approval_status VARCHAR(50) NOT NULL DEFAULT 'APPROVED',
            rejection_reason TEXT,
            provenance JSONB DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );

        -- Migrate data from generated_question_mappings into generated_questions
        INSERT INTO public.generated_questions (
            generated_question_uid,
            source_question_id,
            source_question_uid,
            subject,
            chapter_name,
            topic_code,
            topic_name,
            question_type,
            generated_stem_latex,
            generated_options,
            correct_answer,
            numerical_target,
            explanation_latex,
            model_name,
            approval_status,
            provenance,
            created_at
        )
        SELECT 
            gqm.generated_question_uid,
            gqm.parent_question_id,
            gqm.parent_question_uid,
            COALESCE(gqm.subject, 'Physics'),
            gqm.chapter_name,
            gqm.subtopic_id,
            gqm.subtopic_title,
            COALESCE(gqm.generated_question_type, 'SINGLE_CHOICE'),
            COALESCE(gqm.generated_question_text_latex, ''),
            COALESCE(gqm.generated_options, '[]'::jsonb),
            gqm.generated_correct_option,
            gqm.generated_numerical_target,
            COALESCE(gqm.generated_solution_latex, ''),
            COALESCE(gqm.generator_type, 'qwen/qwen3.8-27b'),
            'APPROVED',
            jsonb_build_object(
                'migrated_from', 'generated_question_mappings',
                'parent_pdf', gqm.parent_source_pdf,
                'generator_type', gqm.generator_type
            ),
            COALESCE(gqm.created_at, NOW())
        FROM public.generated_question_mappings gqm
        ON CONFLICT (generated_question_uid) DO NOTHING;
    """)

    # 3. Validation results audit table
    op.execute("""
        CREATE TABLE IF NOT EXISTS public.validation_results (
            id SERIAL PRIMARY KEY,
            target_type VARCHAR(50) NOT NULL,
            question_uid VARCHAR(255) NOT NULL,
            validator_name VARCHAR(100) NOT NULL,
            is_valid BOOLEAN NOT NULL,
            validation_errors JSONB DEFAULT '[]'::jsonb,
            validation_metadata JSONB DEFAULT '{}'::jsonb,
            verified_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)

    # 4. Question exposure and student cooldown table
    op.execute("""
        CREATE TABLE IF NOT EXISTS public.question_exposure (
            id SERIAL PRIMARY KEY,
            user_id VARCHAR(100) NOT NULL,
            question_uid VARCHAR(255) NOT NULL,
            assessment_id VARCHAR(100) NOT NULL,
            exposure_type VARCHAR(50) NOT NULL DEFAULT 'CANONICAL',
            first_seen_at TIMESTAMPTZ DEFAULT NOW(),
            last_seen_at TIMESTAMPTZ DEFAULT NOW(),
            times_seen INT DEFAULT 1,
            CONSTRAINT uq_question_exposure_user_q UNIQUE (user_id, question_uid)
        );
    """)

    # 5. Audit log table
    op.execute("""
        CREATE TABLE IF NOT EXISTS public.audit_log (
            id SERIAL PRIMARY KEY,
            entity_type VARCHAR(50) NOT NULL,
            entity_id VARCHAR(255) NOT NULL,
            action VARCHAR(50) NOT NULL,
            old_status VARCHAR(50),
            new_status VARCHAR(50),
            reason_code VARCHAR(100),
            reason_detail TEXT,
            performed_by VARCHAR(100) DEFAULT 'system',
            timestamp TIMESTAMPTZ DEFAULT NOW()
        );
    """)

    # 6. High-performance Justified Indexes
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_questions_assessment_status_topic 
        ON public.questions(assessment_status, primary_topic_code);

        CREATE INDEX IF NOT EXISTS idx_questions_subject_chapter 
        ON public.questions(subject, chapter_name);

        CREATE INDEX IF NOT EXISTS idx_gen_questions_topic_status 
        ON public.generated_questions(topic_code, approval_status);

        CREATE INDEX IF NOT EXISTS idx_gen_questions_source_uid 
        ON public.generated_questions(source_question_uid);

        CREATE INDEX IF NOT EXISTS idx_question_exposure_user_q 
        ON public.question_exposure(user_id, question_uid);

        CREATE INDEX IF NOT EXISTS idx_attempt_responses_attempt_q 
        ON public.attempt_responses(attempt_id, question_uid);
    """)


def downgrade() -> None:
    # Safe rollback
    op.execute("""
        DROP INDEX IF EXISTS idx_attempt_responses_attempt_q;
        DROP INDEX IF EXISTS idx_question_exposure_user_q;
        DROP INDEX IF EXISTS idx_gen_questions_source_uid;
        DROP INDEX IF EXISTS idx_gen_questions_topic_status;
        DROP INDEX IF EXISTS idx_questions_subject_chapter;
        DROP INDEX IF EXISTS idx_questions_assessment_status_topic;

        DROP TABLE IF EXISTS public.audit_log CASCADE;
        DROP TABLE IF EXISTS public.question_exposure CASCADE;
        DROP TABLE IF EXISTS public.validation_results CASCADE;
        DROP TABLE IF EXISTS public.generated_questions CASCADE;
        DROP TABLE IF EXISTS public.subjects CASCADE;
    """)
