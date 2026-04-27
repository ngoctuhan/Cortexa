<div align="center">

# Cortexa

### Open-source Memory & Context Manager for AI Chat Systems

[![Go Version](https://img.shields.io/badge/Go-1.25+-00ADD8?style=flat&logo=go)](https://go.dev/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15+-4169E1?style=flat&logo=postgresql)](https://www.postgresql.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![p99 Latency](https://img.shields.io/badge/p99%20Latency-%3C100ms-brightgreen.svg)]()

*Drop-in memory layer for any AI chat system — RAG, entity extraction, and structured memory in one service*

</div>

---

## Overview

Cortexa is a self-hosted **Memory and Context Manager (MCM)** you can integrate with any AI chat system. Rather than building memory from scratch, you point your chat backend at Cortexa's two REST endpoints and get rich, multi-layered context back in under 100ms.

It combines three retrieval strategies in a single service:

- **Vector RAG** — Semantic search through conversation history using embeddings
- **Entity Fact Extraction** — Automatically extracts and deduplicates structured knowledge (names, emails, preferences, etc.)
- **Structured Memory** — Stores life events and persona context that persists across sessions

### Key Features

| Feature | Description |
|---------|-------------|
| **Sub-100ms p99 Latency** | Parallel queries with a soft timeout ensure fast responses |
| **PII Encryption** | AES-GCM encryption with per-tenant derived keys |
| **Atomic Fact Upsert** | CTE-based supersede prevents duplicate entity facts under concurrent writes |
| **Tenant Isolation** | Row-Level Security (RLS) enforces strict data separation |
| **Cognitive Extraction** | Single LLM call extracts entities, events, and persona updates together |
| **Learned Behaviors** | ExperienceWorker detects user corrections and stores procedural memory |
| **Vector Search** | HNSW indexing via pgvector for fast similarity search |
| **Redis Streams Workers** | All workers use Redis Streams consumer groups — durable, at-least-once delivery |
| **3-Retry PEL Reclaim** | Workers reclaim idle messages from the Pending Entry List; skip-after-3 prevents infinite loops |
| **LLM-Agnostic** | Pluggable client supports Azure OpenAI, OpenAI, and Google Gemini out of the box |

---

## Architecture

![Architecture Diagram](docs/architecture.png)



---

### Data Flow

#### Write path

```mermaid
sequenceDiagram
    participant Client
    participant API as REST API
    participant DB as PostgreSQL
    participant Cache as Redis
    participant EMB as Embedder Worker
    participant COG as Cognitive Worker
    participant EXP as Experience Worker
    participant LLM

    Client->>API: POST /v1/messages
    API->>DB: INSERT message
    API->>Cache: cache message in session list
    API->>Cache: XAdd to global:stream:embedder

    Cache-->>EMB: XReadGroup up to 32 msgs per 200 ms
    EMB->>LLM: EmbedBatch
    EMB->>DB: pgx.Batch UPDATE embedding
    EMB->>Cache: XAck

    Note over API,Cache: every N messages - COGNITIVE_BATCH_SIZE
    API->>Cache: XAdd to tenant:stream:cognitive with last_message_id
    Cache-->>COG: XReadGroup consumer group workers
    COG->>Cache: GetRawMessagesUntil anchorMsgID
    COG->>LLM: extract entities, events, persona
    COG->>DB: CTE UPSERT encrypted facts and events
    COG->>Cache: XAck on success or leave in PEL on error

    Cache-->>EXP: XReadGroup consumer group exp-workers
    EXP->>Cache: GetRawMessagesUntil anchorMsgID
    EXP->>LLM: detect learning signal and extract behavior
    EXP->>DB: UPSERT experience vector and steps
    EXP->>Cache: XAck on success or leave in PEL on error

    Note over COG,EXP: reclaimPending every 30s - reclaim PEL idle over 60s - skip after 3 retries
```

#### Read path

```mermaid
sequenceDiagram
    participant Client
    participant API as REST API
    participant Cache as Redis
    participant DB as PostgreSQL
    participant LLM

    Client->>API: POST /v1/context
    API->>Cache: GET recent messages newest-first up to RECENT_MESSAGES_LIMIT

    par parallel 150 ms soft timeout
        API->>LLM: Embed query
        LLM-->>API: query embedding
        API->>DB: vector search pgvector HNSW
        API->>DB: entity facts valid_until IS NULL ORDER BY created_at ASC
        API->>DB: persona and upcoming events
        API->>DB: experiences cosine sim above 0.4 top 3
    end

    API->>API: merge and decrypt PII and rerank
    API-->>Client: Context Bundle
```

---

## Quick Start

### Prerequisites

- **Go 1.25+**
- **PostgreSQL 15+** with [pgvector](https://github.com/pgvector/pgvector) extension
- **Redis 7+**
- **One of:** Azure OpenAI, OpenAI, or Google Gemini API key

### 1. Clone & setup

```bash
git clone https://github.com/cortexa/cortexa.git
cd cortexa/cortexa

cp .env.example .env
```

### 2. Generate a master encryption key

```bash
openssl rand -hex 32
```

Add the output as `MASTER_KEY` in your `.env`.

### 3. Configure environment

Edit `.env`:

```bash
# Required
DATABASE_URL=postgres://user:password@localhost:5432/cortexa?sslmode=require
MASTER_KEY=<output from step 2>

# Required: choose one LLM provider

# Option A — Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com
AZURE_OPENAI_KEY=<your-azure-key>
AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-4o-mini
AZURE_OPENAI_EMBED_DEPLOYMENT=text-embedding-3-small
# AZURE_OPENAI_API_VERSION=2024-02-01  # optional, defaults to 2024-02-01

# Option B — OpenAI
OPENAI_API_KEY=sk-...

# Option C — Google Gemini
GEMINI_API_KEY=AI...
```

### 4. Start infrastructure

```bash
docker-compose up -d postgres redis
```

### 5. Run migrations

```bash
psql $DATABASE_URL -f migrations/001_init.sql
```

### 6. Start services

```bash
# Terminal 1: API server
go run cmd/server/main.go

# Terminal 2: Background workers
go run cmd/worker/main.go
```

### 7. Try the API

```bash
# Store a message
curl -X POST http://localhost:8080/v1/messages \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "01234567-89ab-cdef-0123-456789abcdef",
    "user_id": "01234567-89ab-cdef-0123-456789abcdef",
    "session_id": "01234567-89ab-cdef-0123-456789abcdef",
    "role": "user",
    "content": "My email is john@example.com and I work at Acme Corp"
  }'

# Retrieve context
curl -X POST http://localhost:8080/v1/context \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "01234567-89ab-cdef-0123-456789abcdef",
    "user_id": "01234567-89ab-cdef-0123-456789abcdef",
    "session_id": "01234567-89ab-cdef-0123-456789abcdef",
    "query": "What is the user'\''s email?"
  }'
```

---

## API Reference

### Store a message

```http
POST /v1/messages
Content-Type: application/json

{
  "tenant_id": "uuid",
  "user_id":   "uuid",
  "session_id":"uuid",
  "role":      "user|assistant|system",
  "content":   "message text (max 100KB)"
}
```

**Response**
```json
{
  "status":  "success",
  "message": "messages appended",
  "id":      "message-uuid"
}
```

### Retrieve context

```http
POST /v1/context
Content-Type: application/json

{
  "tenant_id":   "uuid",
  "user_id":     "uuid",
  "session_id":  "uuid",
  "query":       "search query (max 5000 chars)",
  "memory_types": ["recent_messages", "entity_facts", "semantic_messages", "persona", "events"],
  "time_range":  { "start": "2024-01-01T00:00:00Z", "end": "2024-12-31T23:59:59Z" }
}
```

`memory_types` and `time_range` are optional. Omitting `memory_types` returns all sources.

**Response**
```json
{
  "recent_messages": [...],
  "entity_facts": [
    {
      "entity_name": "John",
      "entity_type": "person",
      "attribute":   "email",
      "value":       "john@example.com",
      "confidence":  0.95
    }
  ],
  "relevant_chunks":  [...],
  "persona_context":  {...},
  "upcoming_events":  [...],
  "latency_ms":       87,
  "is_partial":       false
}
```

---

## Configuration

| Environment Variable | Required | Default | Description |
|---------------------|----------|---------|-------------|
| `DATABASE_URL` | Yes | — | PostgreSQL connection string |
| `MASTER_KEY` | Yes | — | 64-char hex key for PII encryption |
| `AZURE_OPENAI_ENDPOINT` | One of¹ | — | Azure OpenAI resource endpoint |
| `AZURE_OPENAI_KEY` | With Azure | — | Azure OpenAI API key |
| `AZURE_OPENAI_CHAT_DEPLOYMENT` | With Azure | — | Deployment name for chat (e.g. `gpt-4o-mini`) |
| `AZURE_OPENAI_EMBED_DEPLOYMENT` | With Azure | — | Deployment name for embeddings |
| `AZURE_OPENAI_API_VERSION` | No | `2024-02-01` | Azure OpenAI API version |
| `OPENAI_API_KEY` | One of¹ | — | OpenAI API key |
| `GEMINI_API_KEY` | One of¹ | — | Google Gemini API key |
| `REDIS_ADDR` | No | `localhost:6379` | Redis address |
| `PORT` | No | `8080` | API server port |
| `DB_MAX_CONNS` | No | `100` | PostgreSQL max connections (max 1000) |
| `REDIS_POOL_SIZE` | No | `100` | Redis connection pool size (max 1000) |
| `COGNITIVE_BATCH_SIZE` | No | `10` | Messages to batch before triggering extraction |
| `COGNITIVE_PROMPT_PATH` | No | `prompts/cognitive.j2` | Path to the Jinja2 extraction prompt |

> ¹ At least one LLM provider must be configured. Azure OpenAI takes priority when `AZURE_OPENAI_ENDPOINT` is set.

---

## Project Structure

```
cortexa/
├── cmd/
│   ├── server/           # REST API server entry point
│   └── worker/           # Background workers entry point
├── internal/
│   ├── api/              # HTTP handlers and request validation
│   ├── config/           # Configuration loading (env vars + .env)
│   ├── llm/              # LLM client abstraction (Azure OpenAI, OpenAI, Gemini)
│   ├── model/            # Shared data models
│   ├── repository/       # Data access layer (PostgreSQL + Redis)
│   ├── security/         # AES-GCM encryption and input validation
│   ├── service/          # Parallel context retrieval and reranking
│   └── worker/           # Embedder and cognitive extraction workers
├── migrations/           # PostgreSQL schema (with pgvector + RLS)
├── prompts/              # Jinja2 prompt template for extraction
├── docker-compose.yml    # Local development infrastructure
└── .env.example          # Environment variable template
```

---

## Security

### Encryption

- **Algorithm**: AES-GCM (Galois/Counter Mode)
- **Key Derivation**: HKDF-SHA256 per tenant
- **Encrypted Fields**: `entity_mentions.value_encrypted` — all extracted PII values

### Tenant isolation

- **Row-Level Security**: PostgreSQL RLS policies are applied in `migrations/001_init.sql`
- **Tenant context**: Every query is scoped by `tenant_id`

### Production checklist

```bash
# Use SSL for the database connection
DATABASE_URL="postgres://...?sslmode=require"

# Generate a unique MASTER_KEY per deployment
openssl rand -hex 32

# Run the API server behind a reverse proxy (nginx, Caddy) with TLS
```

---

## Development

### Running tests

```bash
go test ./...
go test -cover ./...
```

### Building

```bash
go build -o bin/cortexa-server ./cmd/server
go build -o bin/cortexa-worker ./cmd/worker
```

### Docker

```bash
docker-compose up -d
```

---

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Commit your changes (`git commit -m 'Add my feature'`)
4. Push to the branch (`git push origin feature/my-feature`)
5. Open a Pull Request

Please follow the [Code of Conduct](CODE_OF_CONDUCT.md).

---

## License

MIT — see [LICENSE](LICENSE) for details.

- 💬 [Discussions](https://github.com/cortexa/cortexa/discussions)

---

<div align="center">

**Built with ❤️ for the AI community**

[⭐ Star us on GitHub](https://github.com/cortexa/cortexa) • [🐛 Report Issues](https://github.com/cortexa/cortexa/issues) • [📖 Read the Docs](docs/)

</div>
