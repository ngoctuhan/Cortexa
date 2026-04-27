# Cortexa v0.3.0 — Release Notes

> **Released:** April 27, 2026
> **Go version:** 1.25+
> **Status:** Stability release — Worker Reliability & Redis Streams Migration

---

## What's New in v0.3.0

This release focuses entirely on **production stability** for the background worker pipeline introduced in v0.1.0 and v0.2.0. No new user-facing endpoints are added. The changes address four root-cause categories discovered during load testing:

| Category | Problem | Fix |
|---|---|---|
| **Silent message loss** | ExperienceWorker ACKed all messages regardless of error | Per-message ACK only on success; PEL reclaim with 3-retry cap |
| **Worker starvation** | Thousands of tenant streams overwhelmed `XReadGroup` | `discoverStreams` capped at 100 per tick (SCAN breaks early) |
| **LLM output fragility** | CognitiveWorker crashed on markdown-fenced or partial JSON | Regex extraction + retry classification; crypto singleton |
| **Fact correctness** | Race condition in concurrent upserts; stale `ORDER BY` | CTE-based atomic upsert; `QueryCurrent ORDER BY created_at ASC` |

All 78 integration tests pass cleanly after this release.

---

## Breaking Changes

None. All API endpoints and response shapes are unchanged.

**Migration required:** Run `migrations/005_drop_listen_notify.sql` to remove the now-unused PostgreSQL LISTEN/NOTIFY trigger (the EmbedderWorker no longer uses it).

```bash
psql $DATABASE_URL -f migrations/005_drop_listen_notify.sql
```

---

## What Changed

### 1. EmbedderWorker — Redis Streams (replaces PostgreSQL NOTIFY)

Previously the EmbedderWorker used `LISTEN new_message` (PostgreSQL pub/sub). This had two problems: it required a dedicated long-lived DB connection per worker instance, and there was no durable delivery guarantee — if the worker was down when the `NOTIFY` fired, the event was lost.

The worker now reads from a Redis Stream (`global:stream:embedder`) in consumer group mode. Every call to `POST /v1/messages` publishes one entry to this stream alongside the cache write. The worker reads up to 32 entries per tick (200 ms window) and bulk-updates embeddings via `pgx.Batch`.

```
BEFORE  DB NOTIFY new_message  →  EmbedderWorker
AFTER   API → global:stream:embedder (Redis Stream)  →  EmbedderWorker
```

Key properties now:
- **Durable delivery** — messages remain in the stream PEL until ACKed
- **Bulk processing** — up to 32 embeddings per LLM batch call (was 1-at-a-time)
- **One less DB connection** — worker reconnects on demand, not on startup

### 2. CognitiveWorker — Full Reliability Overhaul (P0–P3)

Four incremental hardening passes were applied:

#### P0 — JSON parsing + crypto singleton
- LLM responses sometimes include markdown code fences (` ```json ... ``` `). The worker now uses `reJsonBlockCognitive` regex to extract the outermost `{...}` block regardless of surrounding text.
- `security.Crypto` is now instantiated **once** at worker startup and reused across all goroutines. Previously a new crypto instance was derived per fact, causing redundant HKDF calls under load.

#### P1 — Cache-first context + DLQ classification
- `processBatchPayload` now calls `cache.GetRawMessagesUntil(anchorMsgID, count)` first, falling back to DB only on cache miss. The anchor message ID (from the stream payload `last_message_id`) ensures the worker processes exactly the messages that triggered the batch, not the newest N messages.
- Errors are now classified into two tiers:
  - `errUnrecoverable` — bad JSON, empty tenant, validation failure: goes straight to DLQ + ACK (no retry)
  - Transient errors — LLM timeout, DB connection drop: message stays in PEL for reclaim

#### P2 — Atomic CTE upsert; persona race condition fix
- `UpsertFact` and `UpsertFactBatch` now use a single CTE that covers the full supersede/dedup/insert path in one round-trip. The previous `SELECT ... FOR UPDATE` + `UPDATE` + `INSERT` sequence had a window for concurrent duplicates. The CTE runs atomically:

```sql
WITH existing AS (
    SELECT id FROM entity_mentions
    WHERE tenant_id=$1 AND user_id=$2 AND entity_name=$3 AND attribute=$4
      AND valid_until IS NULL
    FOR UPDATE
),
supersede AS (
    UPDATE entity_mentions SET valid_until=NOW() WHERE id IN (SELECT id FROM existing)
      AND value_hash <> $5  -- skip if same value
    RETURNING id
)
INSERT INTO entity_mentions (...) SELECT ... WHERE NOT EXISTS (
    SELECT 1 FROM existing WHERE (SELECT COUNT(*) FROM supersede) = 0
)
```

- `UpsertPersona` wraps its read-modify-write in a `BEGIN ... FOR UPDATE ... COMMIT` transaction to prevent persona string duplication under concurrent workers.
- `UpsertEventBatch` uses `pgx.Batch` to insert all extracted life events in one round-trip.

#### P3 — XAUTOCLAIM retry with PEL reclaim
- A `reclaimPending(ctx)` goroutine runs every 30 seconds.
- It calls `XPendingExt(Idle: 60s)` to find messages idle in the PEL, then `XClaim` to take ownership.
- `RetryCount` from `XPendingExt` is used as the authoritative retry counter (not a value stored in the stream message itself — that field was removed).
- After 3 reclaims, the message is ACKed without processing (skip-after-max). A `[DLQ SKIP]` log line records the skipped message ID and stream for observability.

```
Message delivered → handleStreamMessage
  └─ success         → XAck
  └─ unrecoverable   → [DLQ SKIP] + XAck immediately
  └─ transient error → do NOT Ack (stays in PEL)
                         ↑
         reclaimPending (30s tick) reclaims idle messages
           RetryCount ≥ 3 → [DLQ SKIP] + XAck
           RetryCount < 3 → reprocess via handleStreamMessage
```

### 3. ExperienceWorker — Reliability (matches CognitiveWorker pattern)

Prior to this release, `ExperienceWorker` always ACKed messages — meaning any `processPayload` error silently dropped the message with no retry. The worker now follows the same pattern as `CognitiveWorker`:

- Only ACK on success
- Transient errors leave the message in PEL
- `reclaimPending(ctx)` goroutine (30s tick, 60s idle threshold, 3-retry cap)
- `discoverStreams` capped at 100 streams per tick

### 4. Worker Fairness — Stream Discovery Cap

Both `CognitiveWorker` and `ExperienceWorker` call `SCAN` to discover all `*:stream:cognitive` keys in Redis. After long test runs, thousands of tenant streams accumulate. Passing all of them to `XReadGroup` overwhelmed the semaphore and new tenant streams were starved.

The SCAN loop now breaks as soon as 100 streams are collected (`cognitiveMaxStreamsPerTick = 100`). The cursor advances each tick, so all streams are eventually served in a round-robin fashion.

### 5. Entity Fact Correctness

**`QueryCurrent` ordering:** The `SELECT` query that powers `GET /v1/context → entity_facts` lacked `ORDER BY`. PostgreSQL heap order is non-deterministic after updates, so the "newest" fact for an attribute could appear anywhere in the result slice. Added `ORDER BY created_at ASC` so the last element in any attribute group is always the most recent fact — consistent with the `email_facts[-1]` pattern used in tests and by callers.

**Validator allowlist:** `age` and `name` were missing from the `allowedAttributes` map in `security/validator.go`, causing the CognitiveWorker to silently discard facts with those attributes.

### 6. Cognitive Prompt Improvements

Two extraction rules were added to `prompts/cognitive.j2`:

**Self-reference rule (TC-E03 / TC-LM01):**
```
Self-reference patterns using "Tôi", "I", "mình", "em" referring to the USER THEMSELVES
must be extracted as facts with entity_type="self" and entity_name="user".
  "Tôi đang làm ở Grab"  → {attribute:"works_at", value:"Grab"}
  "Email của tôi là x@y" → {attribute:"email",    value:"x@y"}
```

**Age vs birthday rule (TC-LM07):**
```
"X tuổi" / "X years old" → ALWAYS attribute="age", value="X" (the number as string).
NEVER compute or infer birth year from age.
"birthday" attribute is ONLY for explicit birth dates like "sinh ngày 15/8/1998".
```

Previously the LLM would convert "Đức năm nay 28 tuổi" into `{attribute:"birthday", value:"1998 (implied)"}`, which prevented the supersede CTE from matching a later "Đức 29 tuổi" update because the attribute keys differed.

---

## Test Results

```
✅ PASSED: 78
❌ FAILED: 0
   Total:   78
```

---

## Files Changed

| File | Change |
|---|---|
| `cortexa/internal/worker/embedder.go` | Redis Streams consumer; pgx.Batch bulk embed; removed dead `dsn` field |
| `cortexa/internal/worker/cognitive.go` | P0–P3 reliability overhaul (see above) |
| `cortexa/internal/worker/experience.go` | Retry logic; reclaimPending; discoverStreams cap |
| `cortexa/internal/repository/entity.go` | CTE upsert; `UpsertFactBatch`; `GetRecentMessagesUntil`; `QueryCurrent ORDER BY` |
| `cortexa/internal/repository/memory.go` | `UpsertPersona` SELECT FOR UPDATE tx; `UpsertEventBatch` pgx.Batch |
| `cortexa/internal/repository/cache.go` | `GetRawMessagesUntil` anchor-aware window; `XAddEmbedderTask` |
| `cortexa/internal/security/validator.go` | Added `age`, `name` to `allowedAttributes` |
| `cortexa/prompts/cognitive.j2` | Self-reference rules; age-vs-birthday rule |
| `cortexa/migrations/005_drop_listen_notify.sql` | Remove `notify_new_message` trigger |

---

## Migration Steps (from v0.2.0)

```bash
# 1. Drop the now-unused LISTEN/NOTIFY trigger
psql $DATABASE_URL -f migrations/005_drop_listen_notify.sql

# 2. Rebuild images
docker build -t cortexa-app -f cortexa/Dockerfile cortexa/

# 3. Restart containers
docker restart cortexa_server cortexa_worker
```

No schema changes to `entity_mentions`, `memory_records`, `experiences`, or `messages` tables.

---

## Known Limitations

- **DLQ is log-only** — skipped messages after 3 retries are recorded in the worker log (`[DLQ SKIP]`) but not persisted to a dead-letter table. A persistent DLQ table is planned for v0.4.0.
- **`discoverStreams` is SCAN-based** — streams are served in a non-deterministic SCAN order; very-high-traffic tenants may be served less often than others. A priority queue based on stream lag is planned.
- Items carried forward from v0.2.0:
  - `EXPERIENCE_SIMILARITY_THRESHOLD` (0.85) not yet config-tunable
  - No experience decay/expiry mechanism
  - Minimum confidence threshold (0.4) not per-user tunable
