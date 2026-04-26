-- Enable necessary extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Sessions
CREATE TABLE sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL,
    user_id     UUID NOT NULL,
    title       TEXT,
    meta        JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ON sessions (tenant_id, user_id, updated_at DESC);

-- Messages
CREATE TABLE messages (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL,
    session_id  UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('user','assistant','system')),
    content     TEXT NOT NULL,
    token_count INT,
    embedding   VECTOR(1536),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ON messages (tenant_id, session_id, created_at DESC);
CREATE INDEX ON messages (tenant_id, user_id, created_at DESC);

-- HNSW Index for messages
CREATE INDEX ON messages USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Entity Mentions
CREATE TABLE entity_mentions (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL,
    user_id        UUID NOT NULL,
    session_id     UUID NOT NULL,
    message_id     UUID NOT NULL REFERENCES messages(id),

    entity_name    TEXT NOT NULL,
    entity_type    TEXT NOT NULL,
    attribute      TEXT NOT NULL,
    value_encrypted BYTEA NOT NULL,
    value_hash     TEXT NOT NULL,

    valid_from     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valid_until    TIMESTAMPTZ,
    superseded_by  UUID REFERENCES entity_mentions(id),

    confidence     FLOAT DEFAULT 1.0,
    source_quote   TEXT,
    embedding      VECTOR(1536),

    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ON entity_mentions (tenant_id, user_id, entity_name, attribute, valid_until NULLS FIRST);
CREATE INDEX ON entity_mentions USING gin (entity_name gin_trgm_ops);
CREATE INDEX ON entity_mentions USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Memory Records
CREATE TABLE memory_records (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID NOT NULL,
    user_id      UUID NOT NULL,
    session_id   UUID,

    type         TEXT NOT NULL CHECK (
                     type IN ('rag_chunk','life_event','user_character','persona','persona_context')),
    payload      JSONB NOT NULL DEFAULT '{}',
    embedding    VECTOR(1536),
    importance   FLOAT DEFAULT 0.5,
    access_count INT DEFAULT 0,
    last_accessed_at TIMESTAMPTZ,

    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ON memory_records (tenant_id, user_id, type, importance DESC);
CREATE INDEX ON memory_records USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
CREATE INDEX ON memory_records USING gin (payload jsonb_path_ops);

-- Row-Level Security (tenant isolation)
ALTER TABLE sessions        ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages        ENABLE ROW LEVEL SECURITY;
ALTER TABLE entity_mentions ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_records  ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_sessions ON sessions
    USING (tenant_id = current_setting('app.tenant_id', true)::UUID);

CREATE POLICY tenant_isolation_messages ON messages
    USING (tenant_id = current_setting('app.tenant_id', true)::UUID);

CREATE POLICY tenant_isolation_entities ON entity_mentions
    USING (tenant_id = current_setting('app.tenant_id', true)::UUID);

CREATE POLICY tenant_isolation_memories ON memory_records
    USING (tenant_id = current_setting('app.tenant_id', true)::UUID);

-- Trigger for new message notification
CREATE OR REPLACE FUNCTION notify_new_message() RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify(
        'new_message',
        json_build_object(
            'message_id', NEW.id,
            'user_id',    NEW.user_id,
            'tenant_id',  NEW.tenant_id,
            'session_id', NEW.session_id
        )::text
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER message_inserted
    AFTER INSERT ON messages
    FOR EACH ROW EXECUTE FUNCTION notify_new_message();
