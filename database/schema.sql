CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TYPE pipeline_status AS ENUM ('draft', 'active', 'archived');
CREATE TYPE source_type AS ENUM ('scans', 'document');
CREATE TYPE ocr_provider AS ENUM ('litellm', 'service');
CREATE TYPE extraction_mode AS ENUM ('prompt', 'fields');
CREATE TYPE run_status AS ENUM ('queued', 'processing', 'completed', 'failed');

CREATE TABLE pipelines (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  status pipeline_status NOT NULL DEFAULT 'draft',
  source source_type NOT NULL,
  ocr_provider ocr_provider,
  ocr_model text,
  ocr_service_url text,
  ocr_prompt text,
  extraction_enabled boolean NOT NULL DEFAULT true,
  extraction_mode extraction_mode,
  llm_model text,
  prompt text,
  max_tokens integer CHECK (max_tokens IS NULL OR max_tokens BETWEEN 1 AND 128000),
  version integer NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (
    (source = 'document' AND ocr_provider IS NULL AND ocr_model IS NULL AND ocr_service_url IS NULL AND ocr_prompt IS NULL)
    OR
    (source = 'scans' AND (
      (ocr_provider = 'litellm' AND ocr_model IS NOT NULL AND ocr_prompt IS NOT NULL AND ocr_service_url IS NULL)
      OR
      (ocr_provider = 'service' AND ocr_service_url IS NOT NULL AND ocr_model IS NULL AND ocr_prompt IS NULL)
    ))
  ),
  CHECK (
    (extraction_enabled = false AND extraction_mode IS NULL AND llm_model IS NULL AND prompt IS NULL AND max_tokens IS NULL)
    OR
    (extraction_enabled = true AND extraction_mode IS NOT NULL AND llm_model IS NOT NULL AND max_tokens IS NOT NULL AND (
      (extraction_mode = 'prompt' AND prompt IS NOT NULL)
      OR extraction_mode = 'fields'
    ))
  ),
  CHECK (
    extraction_enabled = true
    OR (source = 'scans' AND ocr_provider = 'litellm')
  )
);

CREATE TABLE extraction_fields (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  pipeline_id uuid NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
  name text NOT NULL,
  description text NOT NULL,
  data_type text NOT NULL DEFAULT 'string',
  required boolean NOT NULL DEFAULT false,
  position integer NOT NULL,
  UNIQUE (pipeline_id, name),
  UNIQUE (pipeline_id, position)
);

CREATE TABLE documents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  original_name text NOT NULL,
  object_key text NOT NULL UNIQUE,
  mime_type text NOT NULL,
  size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE pipeline_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  pipeline_id uuid NOT NULL REFERENCES pipelines(id) ON DELETE RESTRICT,
  document_id uuid NOT NULL REFERENCES documents(id) ON DELETE RESTRICT,
  status run_status NOT NULL DEFAULT 'queued',
  result jsonb,
  error_message text,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX extraction_fields_pipeline_idx ON extraction_fields (pipeline_id, position);
CREATE INDEX pipeline_runs_pipeline_idx ON pipeline_runs (pipeline_id, created_at DESC);
CREATE INDEX pipeline_runs_status_idx ON pipeline_runs (status) WHERE status IN ('queued', 'processing');
