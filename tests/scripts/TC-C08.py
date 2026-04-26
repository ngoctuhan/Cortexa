"""
Test Case: TC-C08
Name: total_tokens field in context response
Category: Context Retrieval
Input/Setup: Empty session queried first; then 3 messages inserted and session queried again
             with memory_types=["recent_messages"]
Expected Result: total_tokens present; 0 for empty session; > 0 after messages added;
                 non-negative; matches sum of recent + semantic message tokens
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_utils import TestResult
import requests
import uuid

BASE_URL = "http://localhost:8080/v1"

TENANT_ID  = str(uuid.uuid4())
USER_ID    = str(uuid.uuid4())
SESSION_ID = str(uuid.uuid4())
EMPTY_SID  = str(uuid.uuid4())


def run_tests():
    results = []
    session = requests.Session()

    # ── TC-C08-01: total_tokens present on empty session ─────────────────────
    resp = session.post(f"{BASE_URL}/context", json={
        "tenant_id": TENANT_ID, "user_id": USER_ID,
        "session_id": EMPTY_SID, "query": "hello",
    })
    body = resp.json()
    results.append(TestResult(
        test_id="TC-C08-01",
        name="total_tokens field present in context response",
        passed=resp.status_code == 200 and "total_tokens" in body,
        details=f"status={resp.status_code} keys={list(body.keys())}",
    ))

    # ── TC-C08-02: empty session => total_tokens == 0 ────────────────────────
    results.append(TestResult(
        test_id="TC-C08-02",
        name="empty session returns total_tokens = 0",
        passed=resp.status_code == 200 and body.get("total_tokens") == 0,
        details=f"total_tokens={body.get('total_tokens')}",
    ))

    # ── TC-C08-03: total_tokens non-negative ─────────────────────────────────
    results.append(TestResult(
        test_id="TC-C08-03",
        name="total_tokens is non-negative",
        passed=body.get("total_tokens", -1) >= 0,
        details=f"total_tokens={body.get('total_tokens')}",
    ))

    # ── Seed messages ─────────────────────────────────────────────────────────
    for content in [
        "Hello my name is Alice",
        "I am planning a trip to Paris next month",
        "The weather has been lovely recently",
    ]:
        session.post(f"{BASE_URL}/messages", json={
            "tenant_id": TENANT_ID, "user_id": USER_ID,
            "session_id": SESSION_ID, "role": "user", "content": content,
        })

    # ── TC-C08-04: total_tokens > 0 after messages appended ──────────────────
    resp2 = session.post(f"{BASE_URL}/context", json={
        "tenant_id": TENANT_ID, "user_id": USER_ID,
        "session_id": SESSION_ID, "query": "hello",
        "memory_types": ["recent_messages"],
    })
    body2 = resp2.json()
    results.append(TestResult(
        test_id="TC-C08-04",
        name="total_tokens > 0 after messages seeded",
        passed=resp2.status_code == 200 and body2.get("total_tokens", 0) > 0,
        details=f"total_tokens={body2.get('total_tokens')} recent_messages={len(body2.get('recent_messages', []))}",
    ))

    # ── TC-C08-05: total_tokens matches sum of recent_message token_counts ────
    msgs = body2.get("recent_messages", [])
    sem_msgs = body2.get("semantic_messages", [])
    expected = sum(m.get("token_count", 0) for m in msgs) + \
               sum(len(sm.get("content", "")) // 4 for sm in sem_msgs)
    actual = body2.get("total_tokens", -1)
    results.append(TestResult(
        test_id="TC-C08-05",
        name="total_tokens matches sum of recent + semantic message tokens",
        passed=actual == expected,
        details=f"actual={actual} expected={expected} recent={len(msgs)} semantic={len(sem_msgs)}",
    ))

    return results


if __name__ == "__main__":
    results = run_tests()
    failed = [r for r in results if not r.passed]
    for r in results:
        r.print()
    sys.exit(1 if failed else 0)
