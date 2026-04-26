-- LLM token usage tracking
-- Records every LLM Generate call with its token cost, allowing cost analysis per feature.

CREATE TABLE llm_usage (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID NOT NULL,
    user_id      UUID NOT NULL,
    session_id   UUID,
    feature      TEXT NOT NULL,   -- e.g. 'cognitive_extraction'
    model        TEXT NOT NULL,   -- e.g. 'gemini-2.5-flash-lite', 'gpt-4o-mini'
    total_tokens INT  NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ON llm_usage (tenant_id, user_id, created_at DESC);
CREATE INDEX ON llm_usage (tenant_id, feature, created_at DESC);
