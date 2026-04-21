-- nervus2 PostgreSQL schema
-- Requires: pgvector extension

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- -----------------------------------------------------------------------
-- Dimension Snapshots
-- Historical record of every Personal Model dimension update.
-- The semantic_embedding column enables vector-similarity retrieval
-- over past states.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dimension_snapshots (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    dim_id              TEXT NOT NULL,
    inferred_value      JSONB NOT NULL,
    confidence          FLOAT NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    source_event_ids    TEXT[] DEFAULT '{}',
    semantic_embedding  vector(1536),          -- Qwen3.5-4B embedding dim
    timestamp           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version             INT NOT NULL DEFAULT 1,
    correction_applied  BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_dim_snapshots_dim_id
    ON dimension_snapshots (dim_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_dim_snapshots_correction
    ON dimension_snapshots (correction_applied, timestamp DESC)
    WHERE correction_applied = TRUE;

-- Vector similarity index (IVFFlat — efficient on Jetson ARM)
-- Created after data is loaded (requires >= 100 rows for good cluster estimation)
-- Run manually post-load: CREATE INDEX ON dimension_snapshots
--   USING ivfflat (semantic_embedding vector_cosine_ops) WITH (lists = 50);

-- -----------------------------------------------------------------------
-- Insight Records
-- Cross-dimensional correlations discovered by the Insight Engine.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS insight_records (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    dimensions_involved TEXT[] NOT NULL,
    correlation_type    TEXT NOT NULL,
    description         TEXT NOT NULL,
    confidence          FLOAT NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    recommendation      TEXT,
    semantic_embedding  vector(1536),
    expires_at          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_insights_created
    ON insight_records (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_insights_expires
    ON insight_records (expires_at)
    WHERE expires_at IS NOT NULL;

-- -----------------------------------------------------------------------
-- Life Events (carried over from V1 for cross-service compatibility)
-- Apps that write biographical moments still use this table.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS life_events (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_type      TEXT NOT NULL,
    timestamp       TIMESTAMPTZ NOT NULL,
    title           TEXT NOT NULL,
    description     TEXT,
    metadata        JSONB DEFAULT '{}',
    embedding       vector(1536),
    tags            TEXT[] DEFAULT '{}',
    source_app      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_life_events_type
    ON life_events (event_type, timestamp DESC);

-- -----------------------------------------------------------------------
-- Knowledge Items (carried over from V1)
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS knowledge_items (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    content_type    TEXT NOT NULL,  -- 'article' | 'pdf' | 'note' | 'video' | 'rss'
    title           TEXT NOT NULL,
    content         TEXT,
    summary         TEXT,
    source_url      TEXT,
    tags            TEXT[] DEFAULT '{}',
    embedding       vector(1536),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_knowledge_items_type
    ON knowledge_items (content_type, created_at DESC);

-- -----------------------------------------------------------------------
-- App Registry (V2 — extended with model_subscriptions)
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS app_registry (
    app_id              TEXT PRIMARY KEY,
    manifest            JSONB NOT NULL,
    model_subscriptions TEXT[] DEFAULT '{}',  -- NEW in v2: dimension IDs subscribed
    endpoint            TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'active',
    registered_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at        TIMESTAMPTZ
);

-- -----------------------------------------------------------------------
-- Flow Executions (audit trail, carried over from V1)
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS flow_executions (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    flow_id     TEXT NOT NULL,
    trigger_event JSONB,
    status      TEXT NOT NULL,  -- 'success' | 'error' | 'partial'
    duration_ms INT,
    error       TEXT,
    executed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_flow_executions_flow
    ON flow_executions (flow_id, executed_at DESC);

-- -----------------------------------------------------------------------
-- Notifications (carried over from V1)
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notifications (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title       TEXT NOT NULL,
    body        TEXT,
    source_app  TEXT,
    metadata    JSONB DEFAULT '{}',
    file_path   TEXT,
    actions     JSONB DEFAULT '[]',
    read        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notifications_unread
    ON notifications (read, created_at DESC)
    WHERE read = FALSE;
