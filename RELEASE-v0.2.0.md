# Cortexa v0.2.0 — Release Notes

> **Released:** April 25, 2026
> **Go version:** 1.25+
> **Status:** Feature release — Experience System (Beta)

---

## What's New in v0.2.0

### Experience System — User-Scoped Learned Behaviors

Cortexa can now learn how a specific user wants the AI to handle particular types of tasks. When a user corrects or guides the AI during a conversation, the system automatically detects the learning signal, extracts structured behavior guidance, and stores it as an **experience** record scoped to that user.

On subsequent interactions, relevant experiences are retrieved via semantic similarity and injected into the context bundle, allowing the AI to behave according to what it has learned from that user — without the host application needing to manage any of this explicitly.

This closes the gap between static persona memory (who the user is) and dynamic procedural memory (how the AI should act for this user).

---

## Architecture Changes

```
Redis Stream (:stream:cognitive)
         │
         ├──► consumer group: workers       → CognitiveWorker (unchanged)
         │
         └──► consumer group: exp-workers   → ExperienceWorker (NEW)
                   │
                   │  fetch window(20 msgs) from DB
                   │  Tier 1: keyword scan — 0 LLM tokens (~85% cases skipped)
                   │  Tier 2: smart boundary slice + LLM extraction (~500 tokens avg)
                   │
                   ▼
              experiences table (PostgreSQL + HNSW vector index)
                   │
                   ▼
         ContextRetriever.GetContext() — parallel Task 4
              → SearchByVector → inject top-3 into ContextBundle.Experiences
```

---

## New Features

### 1. ExperienceWorker — Automatic Learning Detection

A new background worker subscribes to the same Redis Streams as `CognitiveWorker` using a separate consumer group (`exp-workers`). It processes every batch trigger asynchronously without affecting the existing cognitive pipeline.

**Two-tier detection (token-efficient):**

| Tier | Mechanism | Cost |
|---|---|---|
| Tier 1 | Keyword scan on last 8 messages (Vietnamese + English) | 0 LLM tokens |
| Tier 2 | Smart boundary slice (5–8 msgs) → LLM extraction | ~500 tokens avg |

Typical overhead: **~75 tokens per batch** (vs. CognitiveWorker's ~600 tokens).

**Detection keywords include:** `lần sau`, `nhớ là`, `luôn luôn`, `từ nay`, `next time`, `always`, `remember`, `from now on`, `going forward`, and more.

When a learning signal is detected, the worker:
1. Finds the correction boundary by scanning backward through the window
2. Builds a tight slice of the relevant messages
3. Calls the LLM with `prompts/experience_extractor.j2` to extract `description` + `steps`
4. Embeds `description` for vector similarity lookup
5. Merges with an existing similar experience (`cosine_sim > 0.85`) or inserts a new one

### 2. Experience Records — Structured Behavior Guidance

Each experience has:

```json
{
  "id":           "<uuid>",
  "description":  "When the user asks about SQL query optimization",
  "steps":        ["Start with EXPLAIN ANALYZE", "Identify sequential scans", "..."],
  "confidence":   0.5,
  "usage_count":  0,
  "success_count": 0,
  "is_active":    true
}
```

- `description` is the semantic trigger — what type of task activates this experience
- `steps` are the concrete actions injected into the AI's context
- `confidence` is driven by feedback (`POST /v1/experiences/:id/feedback`)

### 3. Experience Retrieval in ContextBundle

`POST /v1/context` and `POST /v1/context/formatted` now support the `"experiences"` memory type.

When requested with a `query`, the retriever embeds the query and runs a vector search against the user's experiences, returning the top 3 with `confidence ≥ 0.4`. Usage is tracked automatically.

```json
{
  "memory_types": ["recent_messages", "entity_facts", "experiences"]
}
```

Formatted output (for system prompt injection):
```
## Learned behaviors:
[SQL optimization] When the user asks about SQL query optimization:
  1. Start with EXPLAIN ANALYZE to get the execution plan
  2. Identify sequential scans on large tables
  3. Suggest appropriate indexes
```

### 4. New Migration: `004_experiences.sql`

```sql
CREATE TABLE experiences (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL,
    user_id             UUID NOT NULL,
    description         TEXT NOT NULL,
    trigger_embedding   VECTOR(1536),
    steps               JSONB NOT NULL DEFAULT '[]',
    source_session_id   UUID,
    source_message_ids  UUID[] NOT NULL DEFAULT '{}',
    confidence          FLOAT NOT NULL DEFAULT 0.5,
    usage_count         INT   NOT NULL DEFAULT 0,
    success_count       INT   NOT NULL DEFAULT 0,
    is_active           BOOLEAN NOT NULL DEFAULT true,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Indexed with HNSW for fast vector retrieval and a composite index on `(tenant_id, user_id, is_active, confidence DESC)`.

---

## API Reference — New Endpoints

### GET /v1/experiences

Returns all active experiences for a user, ordered by confidence.

```
GET /v1/experiences?tenant_id=<uuid>&user_id=<uuid>
```

**Response 200**

```json
{
  "experiences": [
    {
      "id": "...",
      "description": "When the user asks about SQL query optimization",
      "steps": ["Start with EXPLAIN ANALYZE", "..."],
      "confidence": 0.72,
      "usage_count": 4,
      "success_count": 3,
      "is_active": true,
      "created_at": "..."
    }
  ]
}
```

---

### POST /v1/experiences/:experience_id/feedback

Record a positive or negative signal for an experience. Adjusts `confidence` accordingly.

```http
POST /v1/experiences/<uuid>/feedback
Content-Type: application/json

{
  "tenant_id": "<uuid>",
  "user_id":   "<uuid>",
  "signal":    "positive"
}
```

- `positive` — increments `success_count`, recalculates confidence
- `negative` — decreases confidence; deactivates if confidence drops below 0.1

**Response 200**

```json
{ "status": "feedback recorded" }
```

---

### DELETE /v1/experiences/:experience_id

Soft-deletes an experience (`is_active = false`). The record is preserved for audit and history.

```
DELETE /v1/experiences/<uuid>?tenant_id=<uuid>&user_id=<uuid>
```

**Response 200**

```json
{ "status": "experience deactivated" }
```

---

## Configuration

One new environment variable:

| Variable | Description | Default |
|---|---|---|
| `EXPERIENCE_PROMPT_PATH` | Path to `experience_extractor.j2` | `prompts/experience_extractor.j2` |

---

## Migration Steps (from v0.1.0)

```bash
# Run the new migration
docker exec -i cortexa_postgres psql -U postgres -d cortexa < migrations/004_experiences.sql

# Rebuild and restart (ExperienceWorker is wired into cmd/worker)
docker compose build server worker
docker compose up -d server worker
```

---

## Test Coverage

4 new test cases added to `tests/scripts/`:

| TC ID | Description |
|---|---|
| `TC-EXP01` | GET /v1/experiences — empty list for new user, invalid ID validation |
| `TC-EXP02` | Auto-detection: ExperienceWorker creates experience from correction conversation |
| `TC-EXP03` | Feedback signals — positive/negative, invalid signal validation |
| `TC-EXP04` | Soft-delete — experience absent from list after deactivation |

New helpers added to `test_utils.py`: `ExperienceClient`, `ExperienceHelpers`.

---

## Known Limitations (Beta)

- **Merge deduplication threshold (0.85)** is not yet tunable via config — hardcoded in `ExperienceWorker`. Will be exposed as `EXPERIENCE_SIMILARITY_THRESHOLD` in v0.3.0.
- **No experience expiry / decay** — experiences currently persist indefinitely unless manually deleted. A decay mechanism similar to `DecayWorker` for `memory_records` is planned.
- **Minimum confidence threshold (0.4)** for retrieval is not yet per-user tunable.
- **Window size (20 messages) and Tier-1 scan depth (8 messages)** are constants, not config. Will be configurable in a future release.
- **English and Vietnamese keywords only** for Tier-1 detection. Other languages will require extending `tier1Keywords`.

---

## Changelog

### v0.2.0

- `feat(worker)`: ExperienceWorker — async behavior learning from conversation windows
- `feat(repository)`: experience.go — UpsertExperience, SearchSimilar, SearchByVector, ListByUser, RecordUsage, RecordFeedback, Deactivate
- `feat(api)`: GET /v1/experiences, POST /v1/experiences/:id/feedback, DELETE /v1/experiences/:id
- `feat(service)`: Experiences field in ContextBundle, parallel fetch Task 4 with vector search
- `feat(config)`: ExperiencePrompt field, EXPERIENCE_PROMPT_PATH env var
- `feat(model)`: Experience struct
- `feat(migrations)`: 004_experiences.sql — experiences table with HNSW index
- `feat(prompts)`: experience_extractor.j2 — tight extraction prompt with has_signal guard
- `test`: TC-EXP01–04, ExperienceClient + ExperienceHelpers in test_utils.py
