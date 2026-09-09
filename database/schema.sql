CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TYPE pipeline_status AS ENUM ('draft', 'active', 'archived');
CREATE TYPE run_status AS ENUM ('queued', 'processing', 'completed', 'failed');

CREATE TABLE document_types (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL UNIQUE,
  description text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE pipelines (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  description text,
  document_type_id uuid REFERENCES document_types(id) ON DELETE SET NULL,
  status pipeline_status NOT NULL DEFAULT 'draft',
  version integer NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE pipeline_steps (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  pipeline_id uuid NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
  step_type text NOT NULL CHECK (step_type IN ('start','ocr','extract','llm','output')),
  position integer NOT NULL,
  config jsonb NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (pipeline_id, position)
);

CREATE TABLE extraction_fields (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  step_id uuid NOT NULL REFERENCES pipeline_steps(id) ON DELETE CASCADE,
  name text NOT NULL,
  description text NOT NULL,
  data_type text NOT NULL DEFAULT 'string',
  required boolean NOT NULL DEFAULT false,
  position integer NOT NULL,
  UNIQUE (step_id, name)
);

CREATE TABLE documents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_type_id uuid REFERENCES document_types(id) ON DELETE SET NULL,
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

CREATE INDEX pipeline_steps_pipeline_idx ON pipeline_steps (pipeline_id, position);
CREATE INDEX pipeline_runs_pipeline_idx ON pipeline_runs (pipeline_id, created_at DESC);
CREATE INDEX pipeline_runs_status_idx ON pipeline_runs (status) WHERE status IN ('queued','processing');
