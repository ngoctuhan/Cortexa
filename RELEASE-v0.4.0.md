# Release v0.4.0 — Hybrid Cognitive Flush

## 🚀 Features & Enhancements

### 1. Event-driven Session Flush (New Chat Trigger)
- **Problem:** Previously, users who sent fewer than 10 messages in a session and then clicked "New Chat" would lose all cognitive context from that session because the batch limit was never reached.
- **Solution:** Added a background check to the `POST /v1/sessions` API. When a user creates a new session, Cortexa now automatically scans their 5 most recent sessions. If any previous session has pending unextracted messages, Cortexa immediately forces a cognitive extraction flush for that session.
- **Impact:** Zero context loss when switching contexts. New sessions instantly benefit from the knowledge gathered in the immediately preceding session.

### 2. Time-driven Session Flush (Timeout Scanner)
- **Problem:** Users who close the app or walk away from a session with pending messages (without creating a new session) would have their data stuck in Redis indefinitely.
- **Solution:** Introduced a new `FlusherWorker` that runs in the background every 1 minute. It uses a Redis Sorted Set (`global:active_sessions`) to track the last activity time of all active sessions. If a session has been inactive for 30 minutes and has pending messages, the worker forces a cognitive flush.
- **Impact:** Guaranteed *At-Least-Once* processing for all messages, regardless of user behavior or client disconnections.

### 3. Kubernetes / Cloud-Native Readiness
- **Enhancement:** Implemented a **Redis Distributed Lock** (`SETNX`) for the new `FlusherWorker`.
- **Impact:** Prevents race conditions and duplicate LLM API calls when scaling Cortexa to multiple Pods in Kubernetes. Only one worker instance per minute is elected as the "Leader" to perform the timeout scan.

### 4. Database Consistency Fix
- **Bug Fix:** Fixed an issue where the Cognitive Worker would fail to save extracted persona traits due to a strict Postgres `CHECK CONSTRAINT` on the `memory_records` table.
- **Solution:** Enforced strict typing in `repository/memory.go` to always use the `'persona'` type when saving traits, matching the SQL schema exactly.

## 🧪 Testing & Validation
- **New Automated Tests:**
  - `TC-BG07`: Validates the Event-driven flush mechanism when creating new sessions.
  - `TC-BG08`: Validates the Time-driven flush mechanism by manipulating Redis time-scores.
- Both test suites pass 100% locally and confirm that Google Gemini successfully extracts the forced batches.

## 🛠 File Changes Summary
- `cortexa/internal/api/rest.go`: Added `flushPreviousUserSessions` logic.
- `cortexa/internal/repository/cache.go`: Added Sorted Set tracking and Distributed Lock methods.
- `cortexa/internal/worker/flusher.go`: **[NEW]** Background scanner logic.
- `cortexa/cmd/worker/main.go`: Registered and started the `FlusherWorker`.
- `tests/scripts/TC-BG07.py` & `TC-BG08.py`: **[NEW]** Integration test cases.
- `docs/FEAT_ETC/hybrid_flush_strategy.md` & `flusher_scaling.md`: **[NEW]** Architecture documentation.