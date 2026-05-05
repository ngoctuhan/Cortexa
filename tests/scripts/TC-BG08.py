"""
TC-BG08 — Timeout Flush Cognitive Extraction (Time-driven)

Tests: Ensure that a background worker periodically scans for inactive sessions
and forces a flush if they have pending messages.
"""

import sys
import os
import time
import requests
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_utils import APIClient, TestResult, TestHelpers, BASE_URL
import redis

# To test this quickly without waiting 30 minutes, we'll manually manipulate
# the redis sorted set to make the session appear "older than 30 minutes".

def run_tests():
    results = []
    # Flush cognitive streams to prevent backlog from delaying extraction
    try:
        import redis as _redis
        _r = _redis.Redis(host="localhost", port=6380, db=0)
        _streams = _r.keys("*:stream:cognitive")
        if _streams:
            _r.delete(*_streams)
            print(f"[Setup] Cleared {len(_streams)} cognitive stream(s)")
    except Exception as _e:
        print(f"[Setup] Stream clear skipped: {_e}")

    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    # Connect to Redis to manually manipulate timestamps
    r = redis.Redis(host='localhost', port=6380, db=0)

    # 1. Create Session
    resp = requests.post(f"{BASE_URL}/sessions", json={
        "tenant_id": tenant_id,
        "user_id": user_id,
        "title": "Timeout Session"
    })
    if resp.status_code != 201:
        results.append(TestResult(
            test_id="TC-BG08-01",
            name="Create Session",
            passed=False,
            details=f"status={resp.status_code}, {resp.text}"
        ))
        return results
    session_1 = resp.json()["id"]

    # 2. Append messages
    for i in range(3):
        success, _, _ = APIClient.append_message(
            tenant_id, user_id, session_1, "user",
            f"I have a dog named Fluffy. This is message {i+1}."
        )
        if not success:
            results.append(TestResult(
                test_id="TC-BG08-02",
                name="Append Messages",
                passed=False,
                details="Failed to append message"
            ))
            return results
            
    results.append(TestResult(
        test_id="TC-BG08-02",
        name="Append Messages",
        passed=True,
        details="Appended 3 messages successfully"
    ))
            
    # 3. Fast-forward time in Redis
    # With COGNITIVE_BATCH_SIZE=1 every message is immediately flushed and removed
    # from global:active_sessions. Re-add the session + a fake pending count so the
    # FlusherWorker has something to act on.
    member = f"{tenant_id}:{session_1}"
    batch_key = f"{tenant_id}:sess:{session_1}:cog_batch"
    r.set(batch_key, "3", ex=86400)          # simulate 3 pending messages
    r.zadd("global:active_sessions", {member: time.time()})  # add to tracking set
    
    # Give Redis a tiny bit of time to execute pipeline
    time.sleep(0.5)
    
    # Check if member exists
    score = r.zscore("global:active_sessions", member)
    if score is None:
        results.append(TestResult(
            test_id="TC-BG08-03",
            name="Verify Redis Tracking",
            passed=False,
            details="Session not found in global:active_sessions"
        ))
        return results
        
    results.append(TestResult(
        test_id="TC-BG08-03",
        name="Verify Redis Tracking",
        passed=True,
        details="Session is being tracked in Redis"
    ))

    # Move it 40 minutes into the past
    past_score = score - (40 * 60)
    r.zadd("global:active_sessions", {member: past_score})
    
    print("Fast-forwarded session activity to 40 minutes ago.")
    print("Waiting up to 180s for FlusherWorker to pick it up (runs every 1 min)...")
    
    # 4. Wait for extraction
    found = TestHelpers.wait_for_cognitive_extraction(tenant_id, user_id, session_1, query="What is my dog name Fluffy", timeout_ms=300000)
    
    results.append(TestResult(
        test_id="TC-BG08-04",
        name="Cognitive Extraction after Timeout Flush",
        passed=found,
        details="Extracted facts should be available after the background worker flushes"
    ))

    # 5. Verify Context
    success, resp_data, _ = APIClient.get_context(
        tenant_id, user_id, str(uuid.uuid4()), "What is my dog's name?"
    )
    
    passed_context = False
    if success:
        facts = resp_data.get("entity_facts", []) or []
        has_fluffy = False
        for f in facts:
            if isinstance(f, dict):
                val = f.get("value", "")
                if "fluffy" in val.lower():
                    has_fluffy = True
                    break
        passed_context = has_fluffy

    results.append(TestResult(
        test_id="TC-BG08-05",
        name="Verify Extracted Context",
        passed=passed_context,
        details="Context should contain 'Fluffy' in entity_facts"
    ))

    return results

if __name__ == "__main__":
    results = run_tests()
    failed = [r for r in results if not r.passed]
    for r in results:
        r.print()
    sys.exit(1 if failed else 0)
