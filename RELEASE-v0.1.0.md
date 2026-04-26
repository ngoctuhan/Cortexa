# Cortexa v0.1.0 — Release Notes

> **Released:** April 25, 2026  
> **Go version:** 1.25+  
> **Status:** Initial public release

---

## What is Cortexa?

Cortexa is a **Memory Context Manager (MCM)** — a sidecar service that gives any LLM-powered application persistent, structured memory without requiring the host app to manage it. Instead of passing entire raw conversation histories into every prompt, your app calls Cortexa to receive a ranked, multi-layer context bundle that is ready to inject directly into a system prompt.

This is conceptually analogous to how humans operate:

| Human memory type | Cortexa equivalent | Where it lives |
|---|---|---|
| **Short-term** (working memory) | `recent_messages` | Redis cache (TTL 2 h, max 50 msgs/session) |
| **Semantic** (facts & knowledge) | `entity_facts` | PostgreSQL `entity_mentions` table |
| **Episodic** (past experiences) | `semantic_messages` | pgvector similarity search + reranking |
| **Procedural** (how to act) | `persona`, `upcoming_events` | PostgreSQL `memory_records` table |

> Reference: [LangChain Memory Concepts](https://docs.langchain.com/oss/python/concepts/memory)

---

## Architecture at a Glance

```
Host Application
      │
      │  POST /v1/messages    ← write conversation turns
      │  POST /v1/context     ← read ranked context bundle
      ▼
┌─────────────────┐
│  Cortexa :8080  │   Go / Gin
└────────┬────────┘
         │
  ┌──────┴───────────────────┐
  ▼                          ▼
Redis                   PostgreSQL + pgvector
(working memory cache    (long-term memory store,
 & event streams)         HNSW ANN indexes)
         ▲                          ▲
         └──────────────────────────┘
                   Workers
        ┌──────────────────────────┐
        │  EmbedderWorker          │  pg_notify → embed → vector write
        │  CognitiveWorker         │  Redis Streams → LLM → facts/persona
        │  DecayWorker             │  Periodic importance decay
        └──────────────────────────┘
```

---

## Features in v0.1.0

### 1. Short-term Memory (Working Memory)

- Messages are immediately cached in Redis (`{tenantID}:sess:{sessionID}:msgs`) on every write.
- Cache is capped at **50 messages** with a **2-hour TTL**, preventing unbounded growth.
- The retriever reads from cache first — zero additional DB latency for the hot path.
- Cold-start sessions receive an empty recent messages list; the DB is the durable source of truth.

### 2. Long-term Semantic Memory (Entity Facts)

- The **CognitiveWorker** consumes batches of messages from Redis Streams.
- It calls an LLM (Azure OpenAI) with a Jinja2 prompt (`prompts/cognitive.j2`) to extract structured facts about entities (people, organisations, locations).
- Facts are stored with **temporal tracking** (`valid_from` / `valid_until`) — outdated facts are superseded rather than deleted, preserving history.
- Fact _values_ are **AES-GCM encrypted** at rest; deduplication uses a SHA-256 `value_hash` so comparisons never require decryption.
- At retrieval time, the most recent, highest-confidence facts are returned.

### 3. Long-term Episodic Memory (Semantic Search)

- The **EmbedderWorker** listens on PostgreSQL `LISTEN new_message` and asynchronously generates 1536-dimensional embeddings for every message.
- At retrieval time, the query string is embedded and a cosine similarity search is run against `messages.embedding` via an **HNSW index**.
- Results are reranked by a composite score:

  $$\text{score} = \cos\_sim \times e^{-\lambda \cdot \Delta t} \times \text{importance}$$

  where $\lambda = 0.05$ (configurable) and $\Delta t$ is time in days since the message was created.

- Top-K results (default 5) after reranking are returned as `semantic_messages`.

### 4. Long-term Procedural Memory (Persona & Events)

- The CognitiveWorker also extracts **persona** updates (personality traits, preferences) and **life events** from conversations, stored as typed records in `memory_records`.
- The retriever returns the active `persona` record and up to 3 `upcoming_events` on every context call, grounding the LLM in who the user is.

### 5. Context Retrieval API

Two retrieval endpoints are provided:

| Endpoint | Output format |
|---|---|
| `POST /v1/context` | Structured JSON bundle |
| `POST /v1/context/formatted` | Plain text, ready for LLM system prompt injection |

Both support selective retrieval via the `memory_types` filter so callers pay only for what they need.

### 6. Session Management

Full CRUD lifecycle for conversation sessions:

- `POST /v1/sessions` — create a session
- `GET /v1/sessions` — list sessions for a user (offset pagination)
- `GET /v1/sessions/:id/messages` — fetch session history (cursor-based pagination via `before_id`)
- `DELETE /v1/sessions/:id` — delete a session and cascade to its messages

### 7. Feedback Loop

- `POST /v1/feedback` — records a `positive` or `negative` signal against any memory item (`item_id`).
- Positive signals increase `importance` and `access_count`; negative signals lower importance.
- This directly influences the reranker score on subsequent retrievals, creating a reinforcement loop.

### 8. Memory Decay

- The **DecayWorker** runs on a configurable schedule (`DECAY_INTERVAL_HOURS`, default 24 h).
- Any memory record not accessed within `DECAY_AFTER_DAYS` (default 30 days) has its importance multiplied by `(1 - rate)` each cycle (rate = 0.05), floored at `0.01`.
- Ensures stale facts fade naturally rather than permanently polluting retrieval results — analogous to human forgetting curves.

### 9. Multi-tenant Isolation

- Every table has Row-Level Security (RLS) policies enforced by `app.tenant_id` (set per connection via `BeforeAcquire`).
- All IDs are validated as UUIDs at the HTTP boundary; malformed IDs return HTTP 400 before any DB query.
- Message content is bounded at **100 KB** (`MaxContentLength`) to prevent payload-based DoS.

### 10. Observability

- `GET /health` — liveness/readiness probe for container orchestrators.
- `GET /metrics` — Prometheus metrics endpoint.
- Structured request logging with request-ID propagation via middleware.

---

## API Reference

### POST /v1/messages

Persist a single conversation turn.

```http
POST /v1/messages
Content-Type: application/json

{
  "tenant_id":  "550e8400-e29b-41d4-a716-446655440000",
  "user_id":    "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
  "session_id": "6ba7b811-9dad-11d1-80b4-00c04fd430c8",
  "role":       "user",
  "content":    "My name is Alice and I prefer concise answers."
}
```

**Response 200**

```json
{ "status": "success", "message": "messages appended", "id": "<uuid>" }
```

**Validation rules**

- `role` must be one of: `user`, `assistant`, `system`
- `content` ≤ 100 000 bytes
- All `*_id` fields must be valid UUIDs

---

### POST /v1/context

Retrieve the ranked context bundle for a user session.

```http
POST /v1/context
Content-Type: application/json

{
  "tenant_id":    "550e8400-e29b-41d4-a716-446655440000",
  "user_id":      "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
  "session_id":   "6ba7b811-9dad-11d1-80b4-00c04fd430c8",
  "query":        "What does Alice prefer?",
  "memory_types": ["recent_messages", "entity_facts", "persona"],
  "time_range": {
    "start": "2026-01-01T00:00:00Z",
    "end":   "2026-04-25T23:59:59Z"
  }
}
```

`query` (optional, max 5 KB) — drives semantic/vector search over episodic memory.  
`memory_types` (optional) — filter to specific memory layers; omit to retrieve all.  
`time_range` (optional) — restrict retrieval to a specific time window.

**Response 200**

```json
{
  "recent_messages":   [ { "id": "...", "role": "user", "content": "...", "created_at": "..." } ],
  "entity_facts":      [ { "entity_name": "Alice", "attribute": "preference", "value": "concise" } ],
  "semantic_messages": [ { "id": "...", "content": "...", "cosine_sim": 0.91, "score": 0.87 } ],
  "persona_context":   { "type": "persona", "payload": { ... } },
  "upcoming_events":   [],
  "total_tokens":      312,
  "latency_ms":        43,
  "is_partial":        false
}
```

---

### POST /v1/context/formatted

Identical to `POST /v1/context` but returns a single plain-text string suitable for direct injection into an LLM system prompt.

---

### POST /v1/sessions

Create a new conversation session.

```http
POST /v1/sessions
Content-Type: application/json

{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id":   "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
  "title":     "Support chat #42"
}
```

**Response 201** — returns the full `Session` object.

---

### GET /v1/sessions

List sessions for a user.

```
GET /v1/sessions?tenant_id=<uuid>&user_id=<uuid>&limit=20&offset=0
```

---

### GET /v1/sessions/:session_id/messages

Fetch message history with cursor-based pagination.

```
GET /v1/sessions/<uuid>/messages?tenant_id=<uuid>&limit=50&before_id=<uuid>
```

Pass `next_cursor` from a previous response as `before_id` to load older pages.

---

### DELETE /v1/sessions/:session_id

```
DELETE /v1/sessions/<uuid>?tenant_id=<uuid>
```

Cascades to all messages in the session.

---

### POST /v1/feedback

```http
POST /v1/feedback
Content-Type: application/json

{
  "tenant_id": "...",
  "user_id":   "...",
  "item_id":   "<memory_record uuid>",
  "signal":    "positive"
}
```

`signal` must be `positive` or `negative`.

---

## Quick-start Guide

### Prerequisites

- Docker & Docker Compose
- Go 1.25+
- An Azure OpenAI resource with a chat deployment and an embedding deployment

### 1. Clone and configure

```bash
git clone https://github.com/cortexa/cortexa.git
cd cortexa/cortexa
cp .env.example .env   # edit with your credentials
```

Minimum required `.env`:

```env
DATABASE_URL=postgres://user:pass@localhost:5432/cortexa
REDIS_ADDR=localhost:6379
MASTER_KEY=<32-byte hex string>
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/
AZURE_OPENAI_KEY=<api-key>
AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-4o
AZURE_OPENAI_EMBED_DEPLOYMENT=text-embedding-3-small
```

### 2. Start infrastructure

```bash
docker compose up -d   # starts PostgreSQL + pgvector and Redis
```

### 3. Run migrations

```bash
psql $DATABASE_URL -f migrations/001_init.sql
psql $DATABASE_URL -f migrations/002_llm_usage.sql
psql $DATABASE_URL -f migrations/003_rls_force.sql
```

### 4. Start the server

```bash
go run ./cmd/server/main.go
# HTTP server listening on :8080
```

### 5. Start the workers

```bash
go run ./cmd/worker/main.go
# EmbedderWorker + CognitiveWorker + DecayWorker
```

### 6. Smoke test

```bash
# Create a session
SESSION=$(curl -s -X POST localhost:8080/v1/sessions \
  -H 'Content-Type: application/json' \
  -d '{"tenant_id":"00000000-0000-0000-0000-000000000001",
       "user_id":"00000000-0000-0000-0000-000000000002",
       "title":"test"}' | jq -r '.id')

# Write a message
curl -s -X POST localhost:8080/v1/messages \
  -H 'Content-Type: application/json' \
  -d "{\"tenant_id\":\"00000000-0000-0000-0000-000000000001\",
       \"user_id\":\"00000000-0000-0000-0000-000000000002\",
       \"session_id\":\"$SESSION\",
       \"role\":\"user\",
       \"content\":\"My name is Alice and I love short answers.\"}"

# Retrieve context
curl -s -X POST localhost:8080/v1/context \
  -H 'Content-Type: application/json' \
  -d "{\"tenant_id\":\"00000000-0000-0000-0000-000000000001\",
       \"user_id\":\"00000000-0000-0000-0000-000000000002\",
       \"session_id\":\"$SESSION\",
       \"query\":\"user preferences\"}" | jq .
```

---

## Configuration Reference

| Environment variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection string | **required** |
| `REDIS_ADDR` | Redis address | `localhost:6379` |
| `MASTER_KEY` | AES-GCM key (hex, 32 bytes) | **required** |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint URL | **required** |
| `AZURE_OPENAI_KEY` | Azure OpenAI API key | **required** |
| `AZURE_OPENAI_CHAT_DEPLOYMENT` | Chat model deployment name | **required** |
| `AZURE_OPENAI_EMBED_DEPLOYMENT` | Embedding model deployment name | **required** |
| `COGNITIVE_BATCH_SIZE` | Messages accumulated before triggering extraction | `1` |
| `COGNITIVE_CONCURRENCY` | Max concurrent LLM extraction calls | `4` |
| `DECAY_INTERVAL_HOURS` | How often the DecayWorker runs | `24` |
| `DECAY_AFTER_DAYS` | Days of inactivity before decay starts | `30` |
| `SERVER_PORT` | HTTP listen address | `:8080` |
| `DB_MAX_CONNS` | PostgreSQL connection pool size | `100` |
| `REDIS_POOL` | Redis connection pool size | `100` |

---

## Known Limitations

- **Embedding latency**: The LLM embedding call issued during `POST /v1/context` (semantic search) typically exceeds the 150 ms soft timeout, so `semantic_messages` may often return empty. Embeddings are generated asynchronously after writes; query-time embedding is on a separate, longer timeout (800 ms).
- **RLS**: Row-Level Security policies are defined in the schema but enforcement is only active when `app.tenant_id` is correctly propagated. Verify your deployment with `SET app.tenant_id = '...'` tests.
- **CognitiveWorker concurrency**: Goroutine spawning per batch is bounded by `COGNITIVE_CONCURRENCY` but stream discovery is currently O(n tenants) per poll cycle.
- **No authentication**: The HTTP API has no built-in auth. Place Cortexa behind an API gateway or service mesh that handles mTLS / JWT before exposing it.

---

## Security Notes

- All SQL queries use parameterised placeholders via `pgx` — no string interpolation.
- UUIDs are parsed with `uuid.Parse()` at the HTTP boundary; malformed input is rejected with HTTP 400 before touching the database.
- Entity fact values are encrypted with AES-GCM using `MASTER_KEY`; store this key in a secrets manager (e.g. Vault, AWS Secrets Manager).
- Message bodies are limited to 100 KB to prevent memory exhaustion.
- Do **not** commit `.env` files or any secret values to source control.

---

## What's Next (Roadmap)

- `v0.2.0` — Authentication middleware (API keys / JWT), rate limiting
- `v0.3.0` — Streaming context endpoint (`text/event-stream`)
- `v0.4.0` — Pluggable embedding backends (OpenAI, Cohere, local Ollama)
- `v1.0.0` — Stable API contract, multi-region replication guide

See [docs/roadmap.md](docs/roadmap.md) for the full roadmap.

---

## Changelog

### v0.1.0

- Initial release
- `POST /v1/messages` — write conversation turns to durable store + Redis cache
- `POST /v1/context` and `POST /v1/context/formatted` — multi-layer context retrieval
- Full session CRUD (`POST`, `GET`, `DELETE /v1/sessions`)
- Cursor-based pagination for session message history
- `POST /v1/feedback` — importance feedback loop
- EmbedderWorker: async vector generation via PostgreSQL `LISTEN`
- CognitiveWorker: LLM-driven entity/persona extraction via Redis Streams with consumer groups, at-least-once delivery, and dead-letter queue
- DecayWorker: periodic importance decay with configurable rate and age threshold
- AES-GCM encryption for entity fact values
- Row-Level Security schema for tenant isolation
- HNSW indexes on all embedding columns (`m=16`, `ef_construction=64`)
- Prometheus metrics endpoint
- Structured request logging with request-ID middleware
