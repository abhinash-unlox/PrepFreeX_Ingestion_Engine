-- Migration 0013: MinIO Image Assets, Question Links, and Analysis Ledger
-- Schema: public

-- 1. Canonical Image Asset Table
CREATE TABLE IF NOT EXISTS public.image_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bucket_name VARCHAR(128) NOT NULL DEFAULT 'prepfreex-question-assets',
    object_key VARCHAR(512) NOT NULL UNIQUE,
    object_version_id VARCHAR(128),
    etag VARCHAR(128),
    sha256 VARCHAR(64) NOT NULL,
    md5_prefix VARCHAR(8),
    duplicate_group_id VARCHAR(64),
    is_canonical_duplicate BOOLEAN NOT NULL DEFAULT FALSE,
    original_filename VARCHAR(256),
    file_extension VARCHAR(16),
    file_size_bytes BIGINT NOT NULL,
    declared_content_type VARCHAR(128),
    detected_mime_type VARCHAR(128) NOT NULL DEFAULT 'application/octet-stream',
    width_px INTEGER,
    height_px INTEGER,
    aspect_ratio NUMERIC(8, 4),
    resolution_mp NUMERIC(8, 4),
    color_mode VARCHAR(32),
    color_profile VARCHAR(128),
    has_transparency BOOLEAN NOT NULL DEFAULT FALSE,
    exif_orientation INTEGER DEFAULT 1,
    dpi NUMERIC(8, 2),
    frame_count INTEGER NOT NULL DEFAULT 1,
    perceptual_hash VARCHAR(64),
    sharpness_score NUMERIC(16, 4),
    contrast_score NUMERIC(12, 4),
    brightness_score NUMERIC(12, 4),
    quality_grade VARCHAR(32) NOT NULL DEFAULT 'UNKNOWN',
    quality_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
    diagram_category VARCHAR(64) NOT NULL DEFAULT 'unknown',
    image_description TEXT,
    extracted_text TEXT,
    mathematical_symbols TEXT,
    labels JSONB NOT NULL DEFAULT '[]'::jsonb,
    language VARCHAR(16) DEFAULT 'en',
    candidate_id VARCHAR(64),
    source_pdf VARCHAR(512),
    source_page INTEGER,
    asset_role VARCHAR(32) NOT NULL DEFAULT 'stem',
    lifecycle_status VARCHAR(32) NOT NULL DEFAULT 'DISCOVERED',
    review_status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    is_production_ready BOOLEAN NOT NULL DEFAULT FALSE,
    last_analyzed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for image_assets
CREATE INDEX IF NOT EXISTS idx_image_assets_sha256 ON public.image_assets(sha256);
CREATE INDEX IF NOT EXISTS idx_image_assets_md5_prefix ON public.image_assets(md5_prefix);
CREATE INDEX IF NOT EXISTS idx_image_assets_candidate_id ON public.image_assets(candidate_id);
CREATE INDEX IF NOT EXISTS idx_image_assets_quality_grade ON public.image_assets(quality_grade);
CREATE INDEX IF NOT EXISTS idx_image_assets_lifecycle_status ON public.image_assets(lifecycle_status);
CREATE INDEX IF NOT EXISTS idx_image_assets_is_production_ready ON public.image_assets(is_production_ready);
CREATE INDEX IF NOT EXISTS idx_image_assets_diagram_category ON public.image_assets(diagram_category);

-- 2. Question Image Links Relationship Table (Polymorphic FK support)
DO $$
DECLARE
    q_id_type text;
    has_opt_id boolean;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_schema = 'public' AND table_name = 'question_image_links'
    ) THEN
        SELECT data_type INTO q_id_type 
        FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = 'questions' AND column_name = 'id';

        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_schema = 'public' AND table_name = 'question_options' AND column_name = 'id'
        ) INTO has_opt_id;

        IF q_id_type = 'uuid' THEN
            EXECUTE 'CREATE TABLE public.question_image_links (
                id BIGSERIAL PRIMARY KEY,
                asset_id UUID NOT NULL REFERENCES public.image_assets(id) ON DELETE RESTRICT,
                question_id UUID NOT NULL REFERENCES public.questions(id) ON DELETE CASCADE,
                question_option_id BIGINT,
                usage_role VARCHAR(32) NOT NULL DEFAULT ''stem'',
                placement VARCHAR(32) NOT NULL DEFAULT ''inline'',
                display_order INTEGER NOT NULL DEFAULT 1,
                caption TEXT,
                alt_text TEXT,
                association_confidence NUMERIC(5, 4) NOT NULL DEFAULT 1.0000,
                association_source VARCHAR(64) NOT NULL DEFAULT ''EXACT_REFERENCE'',
                association_status VARCHAR(32) NOT NULL DEFAULT ''EXACT_REFERENCE'',
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_question_asset_role UNIQUE (question_id, asset_id, usage_role)
            )';
        ELSE
            IF has_opt_id THEN
                EXECUTE 'CREATE TABLE public.question_image_links (
                    id BIGSERIAL PRIMARY KEY,
                    asset_id UUID NOT NULL REFERENCES public.image_assets(id) ON DELETE RESTRICT,
                    question_id INTEGER NOT NULL REFERENCES public.questions(id) ON DELETE CASCADE,
                    question_option_id INTEGER REFERENCES public.question_options(id) ON DELETE CASCADE,
                    usage_role VARCHAR(32) NOT NULL DEFAULT ''stem'',
                    placement VARCHAR(32) NOT NULL DEFAULT ''inline'',
                    display_order INTEGER NOT NULL DEFAULT 1,
                    caption TEXT,
                    alt_text TEXT,
                    association_confidence NUMERIC(5, 4) NOT NULL DEFAULT 1.0000,
                    association_source VARCHAR(64) NOT NULL DEFAULT ''EXACT_REFERENCE'',
                    association_status VARCHAR(32) NOT NULL DEFAULT ''EXACT_REFERENCE'',
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT uq_question_asset_role UNIQUE (question_id, asset_id, usage_role)
                )';
            ELSE
                EXECUTE 'CREATE TABLE public.question_image_links (
                    id BIGSERIAL PRIMARY KEY,
                    asset_id UUID NOT NULL REFERENCES public.image_assets(id) ON DELETE RESTRICT,
                    question_id INTEGER NOT NULL REFERENCES public.questions(id) ON DELETE CASCADE,
                    question_option_id BIGINT,
                    usage_role VARCHAR(32) NOT NULL DEFAULT ''stem'',
                    placement VARCHAR(32) NOT NULL DEFAULT ''inline'',
                    display_order INTEGER NOT NULL DEFAULT 1,
                    caption TEXT,
                    alt_text TEXT,
                    association_confidence NUMERIC(5, 4) NOT NULL DEFAULT 1.0000,
                    association_source VARCHAR(64) NOT NULL DEFAULT ''EXACT_REFERENCE'',
                    association_status VARCHAR(32) NOT NULL DEFAULT ''EXACT_REFERENCE'',
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT uq_question_asset_role UNIQUE (question_id, asset_id, usage_role)
                )';
            END IF;
        END IF;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_qil_asset_id ON public.question_image_links(asset_id);
CREATE INDEX IF NOT EXISTS idx_qil_question_id ON public.question_image_links(question_id);
CREATE INDEX IF NOT EXISTS idx_qil_option_id ON public.question_image_links(question_option_id);
CREATE INDEX IF NOT EXISTS idx_qil_association_status ON public.question_image_links(association_status);

-- 3. Image Analysis Runs Audit Table
CREATE TABLE IF NOT EXISTS public.image_analysis_runs (
    id BIGSERIAL PRIMARY KEY,
    asset_id UUID NOT NULL REFERENCES public.image_assets(id) ON DELETE CASCADE,
    engine_name VARCHAR(64) NOT NULL,
    analysis_version VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL, -- SUCCESS, FAILED, PARTIAL, SKIPPED
    output_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message TEXT,
    duration_ms INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_iar_asset_id ON public.image_analysis_runs(asset_id);
CREATE INDEX IF NOT EXISTS idx_iar_engine_status ON public.image_analysis_runs(engine_name, status);

-- 4. Backward Compatibility View for legacy s3_images
CREATE OR REPLACE VIEW public.v_s3_images_compatibility AS
SELECT 
    id,
    object_key AS s3_key,
    bucket_name AS s3_bucket,
    diagram_category AS image_type,
    source_pdf,
    source_page AS page_number,
    detected_mime_type AS mime_type,
    width_px,
    height_px,
    file_size_bytes,
    created_at AS uploaded_at
FROM public.image_assets;

-- 5. Grant read access to prepfreex_user if role exists
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'prepfreex_user') THEN
        GRANT SELECT ON public.image_assets TO prepfreex_user;
        GRANT SELECT ON public.question_image_links TO prepfreex_user;
        GRANT SELECT ON public.image_analysis_runs TO prepfreex_user;
        GRANT SELECT ON public.v_s3_images_compatibility TO prepfreex_user;
    END IF;
END $$;
