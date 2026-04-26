-- Experiences: user-scoped learned behaviors derived from real interactions.
-- Each record captures a task type the AI has learned to handle in a specific way
-- for a specific user, based on guidance extracted from conversation windows.

CREATE TABLE experiences (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL,
    user_id             UUID NOT NULL,

    -- Human-readable fingerprint, embedded for semantic search
    description         TEXT NOT NULL,
    trigger_embedding   VECTOR(1536),

    -- Structured guidance injected into system prompt on retrieval
    steps               JSONB NOT NULL DEFAULT '[]',

    -- Source tracking for debugging / audit
    source_session_id   UUID,
    source_message_ids  UUID[] NOT NULL DEFAULT '{}',

    -- Quality signals
    confidence          FLOAT NOT NULL DEFAULT 0.5,
    usage_count         INT   NOT NULL DEFAULT 0,
    success_count       INT   NOT NULL DEFAULT 0,

    -- Soft-delete: set false instead of DELETE
    is_active           BOOLEAN NOT NULL DEFAULT true,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- HNSW index for fast vector similarity search
CREATE INDEX ON experiences USING hnsw (trigger_embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Lookup index: active experiences by user, ordered by confidence
CREATE INDEX ON experiences (tenant_id, user_id, is_active, confidence DESC);
