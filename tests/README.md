# Cortexa Test Suite

Integration test suite for the Cortexa Memory Context Manager (MCM). All tests are Python-based and run against a live service on `http://localhost:8080`.

## Prerequisites

- Cortexa server running on `:8080`
- Cortexa background worker running
- PostgreSQL (with pgvector) and Redis up via Docker Compose
- `COGNITIVE_BATCH_SIZE=1` set in `cortexa/.env` so single messages trigger extraction immediately

```bash
# Start infrastructure
docker compose -f cortexa/docker-compose.yml up -d

# Build and start services
cd cortexa && go run ./cmd/server/main.go &
cd cortexa && go run ./cmd/worker/main.go &

# Or use the helper script
bash tests/scripts/start_services.sh
```

## Setup

```bash
cd tests
python3 -m venv .venv
source .venv/bin/activate
pip install requests psycopg2-binary cryptography python-dotenv
```

## Running Tests

```bash
# Activate venv
source tests/.venv/bin/activate

# Run full suite
python3 tests/run_all_tests.py

# Run a single test case
PYTHONPATH=tests python3 tests/scripts/TC-E01.py

# Run all tests in a group (e.g. entity extraction)
for f in tests/scripts/TC-E*.py; do PYTHONPATH=tests python3 "$f"; done
```

---

## Test Groups

| Prefix | Category | Count | Description |
|--------|----------|-------|-------------|
| `TC-S` | Session Management | 8 | Message append, session history, Redis cache, pagination |
| `TC-R` | Read-Your-Own-Writes | 3 | Immediate recall consistency after a write |
| `TC-E` | Entity Extraction | 16 | Cognitive worker: extract, upsert, supersede, edge cases, self-facts separation |
| `TC-L` | Entity Lookup | 6 | Retrieval accuracy for named entities and attributes |
| `TC-V` | Vector RAG & Rerank | 7 | Semantic search, reranking, decay, HNSW performance |
| `TC-C` | Context Retrieval | 8 | `GET /v1/context` bundle shape, latency, filtering |
| `TC-W` | Cache & Singleflight | 4 | Warm-up deduplication, Redis restart recovery |
| `TC-BG` | Background Workers | 9 | Embedder, cognitive flush (event-driven + time-driven) |
| `TC-SEC` | Security | 7 | PII encryption, tenant RLS isolation, input validation |
| `TC-LM` | LongMemEval Scenarios | 9 | End-to-end recall, cross-session, temporal updates, conflict, multi-session keyword recall |
| `TC-P` | Performance & Latency | 6 | p50/p95/p99 targets, 100-message burst benchmark |
| `TC-EXP` | Experience System | 4 | Learned behaviors: detection, feedback, soft-delete |

**Total: 87 test cases**

---

## Test Case Reference

### Session Management (`TC-S`)

| ID | Name |
|----|------|
| TC-S01 | AppendMessages basic |
| TC-S02 | GetSessionHistory – cache hit |
| TC-S03 | GetSessionHistory – cache miss |
| TC-S04 | Redis EXISTS guard – evicted key |
| TC-S05 | Sliding window trim |
| TC-S06 | Concurrent appends same session |
| TC-S07 | Invalid role value |
| TC-S08 | `total_tokens` field in GET `/v1/sessions/:id/messages` |

### Read-Your-Own-Writes (`TC-R`)

| ID | Name |
|----|------|
| TC-R01 | Immediate recall after write |
| TC-R02 | Last 2 messages always injected |
| TC-R03 | RYOW with empty session |

### Entity Extraction (`TC-E`)

| ID | Name |
|----|------|
| TC-E01 | Basic entity extraction |
| TC-E02 | Entity upsert – value supersede |
| TC-E03 | Self-reference pronoun – "Tôi" |
| TC-E04 | Name variant normalization |
| TC-E05 | Temporal update – supersede old value |
| TC-E06 | NOOP – same value not re-inserted |
| TC-E07 | No extractable entities in message |
| TC-E08 | Very long message (near max length) |
| TC-E09 | Prompt injection attempt in message content |
| TC-E10 | Injection via entity value field |
| TC-E11 | Time anchoring and extractor token/latency budget |
| TC-E12 | `self_facts` field exists in GetContext response |
| TC-E13 | `self_facts` and `entity_facts` are separated |
| TC-E14 | Who am I — user identity from self_facts |
| TC-E15 | Entity fact relevance filtering — FTS entity resolution |
| TC-E16 | UserProfile.CanonicalName derived from self-facts |

### Entity Lookup (`TC-L`)

| ID | Name |
|----|------|
| TC-L01 | Exact entity fact lookup |
| TC-L02 | Fuzzy name match |
| TC-L03 | Temporal query – current fact only (not superseded) |
| TC-L04 | Negative recall – entity never mentioned |
| TC-L05 | Multiple attributes for the same entity |
| TC-L06 | Entity name with Unicode / diacritics |

### Vector RAG & Rerank (`TC-V`)

| ID | Name |
|----|------|
| TC-V01 | Basic semantic search |
| TC-V02 | Rerank Top 200 → Top 15 |
| TC-V03 | Recency decay applied |
| TC-V04 | Importance score boost |
| TC-V05 | Zero embeddings in DB |
| TC-V06 | Query with no semantic match |
| TC-V07 | HNSW latency under load |

### Context Retrieval (`TC-C`)

| ID | Name |
|----|------|
| TC-C01 | Full context bundle (all 5 fields present) |
| TC-C02 | Entity facts take priority in ranking |
| TC-C03 | GetContext response latency within acceptable bound |
| TC-C04 | GetContext succeeds under concurrent load |
| TC-C05 | GetContext returns empty bundle for session with no data |
| TC-C06 | Unknown userID returns empty bundle |
| TC-C07 | `memory_types` and `time_range` filtering |
| TC-C08 | `total_tokens` field present in context response |

### Cache & Singleflight (`TC-W`)

| ID | Name |
|----|------|
| TC-W01 | Singleflight deduplication (50 concurrent callers → 1 DB query) |
| TC-W02 | Warm flag prevents re-warm |
| TC-W03 | Warm-up recovery after Redis restart |
| TC-W04 | Warm-up latency |

### Background Workers (`TC-BG`)

| ID | Name |
|----|------|
| TC-BG01 | Embedder – LISTEN/NOTIFY trigger |
| TC-BG02 | Embedder – batch processing (50 messages) |
| TC-BG03 | Summarizer – long session trigger (100+ messages) |
| TC-BG04 | Event Detector – birthday detection |
| TC-BG05 | Worker reconnect on DB drop |
| TC-BG06 | Embedder – LLM API timeout with retry |
| TC-BG07 | Hybrid Flush – event-driven cognitive extraction |
| TC-BG08 | Timeout Flush – time-driven cognitive extraction |
| TC-BG09 | Hybrid Flush – new session triggers extraction of previous session |

### Security (`TC-SEC`)

| ID | Name |
|----|------|
| TC-SEC01 | PII encryption at rest (AES-GCM, HKDF-derived key) |
| TC-SEC02 | Tenant isolation via Row-Level Security |
| TC-SEC03 | SQL injection via message content |
| TC-SEC04 | Oversized content rejected (> 100 KB) |
| TC-SEC05 | Malformed UUID inputs return 400 |
| TC-SEC06 | Cross-tenant context isolation |
| TC-SEC07 | Invalid role value rejected |

### LongMemEval Scenarios (`TC-LM`)

| ID | Name |
|----|------|
| TC-LM01 | Single-session recall |
| TC-LM02 | Cross-session recall |
| TC-LM03 | Temporal update tracking |
| TC-LM04 | Multi-hop reasoning |
| TC-LM05 | Negative recall |
| TC-LM06 | Long session (500+ turns) recall |
| TC-LM07 | Conflicting facts resolution |
| TC-LM08 | Proactive life event surfacing |
| TC-LM09 | Multi-session cross-topic recall with keyword verification (13 Q&A, easy → very_hard) |

### Performance & Latency (`TC-P`)

| ID | Name |
|----|------|
| TC-P01 | GetContext p99 < 100 ms |
| TC-P02 | Entity lookup p99 < 5 ms |
| TC-P03 | AppendMessages p99 < 10 ms |
| TC-P04 | Soft deadline hit rate < 1% |
| TC-P05 | HNSW vs IVFFlat comparison |
| TC-P06 | 100-message burst covering all system features |

### Experience System (`TC-EXP`)

| ID | Name |
|----|------|
| TC-EXP01 | List endpoint returns empty list for new user |
| TC-EXP02 | ExperienceWorker learns from correction conversation |
| TC-EXP03 | Feedback signals (positive / negative) update confidence |
| TC-EXP04 | Soft-delete removes experience from list |

---

## Utility Scripts

| Script | Purpose |
|--------|---------|
| `test_utils.py` | Shared helpers: `APIClient`, `TestHelpers`, `Assertions`, `run_test_wrapper` |
| `run_all_tests.py` | Discovers and runs all `TC-*.py` files; prints pass/fail summary |
| `scripts/start_services.sh` | Builds Go binaries and starts server + worker with env loaded from `cortexa/.env` |
| `scripts/ctx.py` | Interactive CLI to query `/v1/context` and send messages; supports `--format plain\|rich` |
| `scripts/import_conversation.py` | Import conversation CSV(s) from `tests/data/` into Cortexa via `POST /v1/messages` |
| `scripts/gen_test_data.py` | Regenerates all sample CSV files under `tests/data/` |
| `scripts/reset_db.py` | Truncates all DB tables and flushes Redis — use before a clean test run |
| `scripts/benchmark_retrieval.py` | Retrieval quality benchmark — 46 queries, reports hit@1/3/5 and MRR |

## Test Data

Sample conversations for end-to-end testing live under `tests/data/` in the layout:

```
tests/data/
  <tenant-id>/
    <user-id>/
      <session-id>.csv
```

Each CSV has `role,content` rows (header + alternating `user`/`assistant` turns).

The bundled dataset contains **3 users under 1 tenant** (12 sessions, ~230 messages total):

| User | Persona | Sessions |
|------|---------|----------|
| Minh | 28yr, software engineer @ Grab, Hà Nội | 3 |
| Lan | 23yr, HUST CS student, Federated Learning research | 4 |
| Hùng | 35yr, owner of Phở Bắc restaurant chain (3 locations) | 5 |

Conversations cover: persona extraction, named entities (family, colleagues, places), events with dates, task execution, and multi-turn technical/business reasoning — from simple to complex.

### Importing conversations

```bash
source tests/.venv/bin/activate

# Single session
python3 tests/scripts/import_conversation.py tests/data/<tenant>/<user>/<session>.csv

# All sessions for a user
python3 tests/scripts/import_conversation.py tests/data/<tenant>/<user>/

# Entire tenant (all users + all sessions)
python3 tests/scripts/import_conversation.py tests/data/<tenant>/

# Preview without calling the API
python3 tests/scripts/import_conversation.py tests/data/<tenant>/ --dry-run

# Add delay between messages (ms) to avoid overwhelming the worker
python3 tests/scripts/import_conversation.py tests/data/<tenant>/ --delay 200
```

The script infers `tenant_id`, `user_id`, and `session_id` from the directory path — no flags required.

### Resetting state before a new test run

```bash
# Truncate all data for a specific user
python3 tests/scripts/reset_db.py --user <UUID> --yes

# Truncate everything (all tenants)
python3 tests/scripts/reset_db.py --yes
```

### Regenerating the sample data files

```bash
python3 tests/scripts/gen_test_data.py
```

## Infrastructure

| Component | Docker service | Default port |
|-----------|---------------|-------------|
| PostgreSQL + pgvector | `cortexa_postgres` | 5433 |
| Redis | `cortexa_redis` | 6380 |
| Cortexa HTTP server | — | 8080 |
| Background worker | — | — |

## Key Environment Variables

| Variable | Default | Notes |
|----------|---------|-------|
| `COGNITIVE_BATCH_SIZE` | `3` | Set to `1` for tests so every message triggers extraction |
| `COGNITIVE_CONCURRENCY` | `5` | Worker parallelism |
| `CORTEXA_BASE_URL` | `http://localhost:8080/v1` | Override for `ctx.py` |
