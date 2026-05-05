# Release v0.5.0 — Context Retrieval v2: Smart Entity Resolution

## Overview

This release replaces the previous vector-similarity approach for context retrieval with a smarter, structured entity-aware pipeline. The core idea: instead of treating all past messages as a blob to search through, Cortexa now understands **who** was mentioned and retrieves **what is known** about them directly — much faster and with higher precision.

---

## What Changed

### 1. Entity-Aware Context Retrieval (New Pipeline)

Previously, finding relevant facts about people/places relied on cosine similarity over all stored messages — slow, noisy, and dependent on embedding quality.

The new pipeline is a three-phase funnel:

- **Phase 1 — Entity Resolution:** The user's query is matched against known entity names using full-text search + trigram similarity. This runs with zero LLM cost.
- **Phase 2a — Vector Reranking per Entity:** For each resolved entity, facts are ranked by cosine distance to the query. Only runs when embeddings are available.
- **Phase 2b — FTS Fallback:** If no embeddings exist (cold start), facts are ranked by `ts_rank` instead.
- **Fallback — Semantic Broadening:** When no named entity is resolved at all (e.g. the query is vague), the system falls back to a semantic search across *all* embedded facts — still query-aware, no longer a blind confidence sort.

This means relevant facts about "Minh (boss)", "Lan (sister)", etc. surface reliably regardless of how the query is phrased.

### 2. Self-Facts Separation (`self_facts` field)

User identity facts (name, age, job, birthday, etc.) are now stored and retrieved separately from third-party entity facts. They appear as a dedicated `self_facts` field in the context response, always pinned at the top of the context string so the LLM grounds on "who the user is" before reading facts about other people.

Previously, user identity was mixed into the general entity pool and could be ranked out of context.

### 3. Dynamic User Profile from Extracted Facts

The user profile (name, aliases) used to be a hardcoded stub (`CanonicalName = "User"`), meaning the cognitive prompt never knew the real user's name when extracting new facts.

Now, the profile is derived in real-time from the user's own `self_facts` — as soon as the user's name is extracted from a conversation, all future cognitive prompts use it. This improves extraction accuracy for follow-up sessions.

### 4. Cognitive Batch Counter Fix

The batch trigger (`COGNITIVE_BATCH_SIZE`) previously counted every message — including assistant and system turns. This meant `COGNITIVE_BATCH_SIZE=10` would fire after only 5 real user turns.

Now, only user turns increment the counter. `COGNITIVE_BATCH_SIZE=10` means exactly 10 user messages (≈ 10 conversation exchanges) before extraction fires. The batch window sent to the cognitive worker is adjusted accordingly to capture both sides of each exchange.

Default changed from 20 → 10.

### 5. Duplicate LLM Call Prevention

Long LLM calls (60+ seconds on the Azure endpoint) were occasionally triggering a second extraction attempt because the PEL idle timeout was shorter than the actual call duration. This caused duplicate fact writes.

Two guards added: an in-process tracking map that blocks re-delivery of any message already being processed, and the PEL reclaim timeout raised to 2 minutes to comfortably exceed worst-case LLM latency.

### 6. Events Retrieval Fix

Upcoming events (birthdays, anniversaries) were broken for records where the cognitive worker stored `"unspecified"` as the date string — causing Postgres to throw a `timestamptz` cast error and returning zero events.

Events now sort by query relevance (FTS on event name) first, then date proximity, replacing the previous creation-time ordering. A 7-day lookback filter also prevents stale past events from surfacing.

### 7. Removed: Semantic Message Search + Message Embedding

The `semantic_messages` field — which retrieved past messages via HNSW vector search and applied recency-decay reranking — has been removed from the context pipeline.

**Rationale:** The cognitive worker already distills message content into structured entity facts, persona traits, and experiences. Returning raw past messages via vector search on top of that is redundant, adds LLM cost (embedding every message), and increases retrieval latency. The same information is represented more cleanly in `entity_facts`, `self_facts`, and `persona_context`.

The message embedder worker (`EmbedderWorker`) is also removed as it no longer serves any purpose.

### 8. New DB Indexes (Migration 007)

Two GIN full-text search indexes added on the entity mentions table — one on entity names, one on fact content — so Phase 1 entity resolution hits an index instead of a sequential scan.

### 9. Mock LLM Provider for Testing

A new `LLM_PROVIDER=mock` option returns instant zero-fact JSON responses and synthetic embeddings. Useful for testing batch processing, retry logic, and worker behavior without spending API tokens.

---

## New Tests

| ID | Description |
|----|-------------|
| TC-E12 | `self_facts` field present in GetContext response |
| TC-E13 | `self_facts` and `entity_facts` are correctly separated |
| TC-E14 | User identity ("who am I") answered from `self_facts` |
| TC-E15 | Entity fact relevance filtering via FTS entity resolution |
| TC-E16 | `UserProfile.CanonicalName` derived from self-facts, not hardcoded |
