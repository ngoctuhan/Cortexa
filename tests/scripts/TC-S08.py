"""
TC-S08 — total_tokens field in GET /v1/sessions/:session_id/messages

Tests:
  - total_tokens is present in response
  - total_tokens equals the sum of individual message token_counts
  - total_tokens is 0 for an empty session
  - total_tokens is non-negative
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_utils import APIClient, TestResult, TestHelpers
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

    # ── Seed two messages ─────────────────────────────────────────────────────
    msg1_content = "Hello world this is a test message"   # token_count = len/4 = 8
    msg2_content = "Sure, I understand you completely"    # token_count = len/4 = 7

    session.post(f"{BASE_URL}/messages", json={
        "tenant_id": TENANT_ID, "user_id": USER_ID, "session_id": SESSION_ID,
        "role": "user", "content": msg1_content,
    })
    session.post(f"{BASE_URL}/messages", json={
        "tenant_id": TENANT_ID, "user_id": USER_ID, "session_id": SESSION_ID,
        "role": "assistant", "content": msg2_content,
    })

    # ── TC-S08-01: total_tokens field present ─────────────────────────────────
    resp = session.get(f"{BASE_URL}/sessions/{SESSION_ID}/messages",
                       params={"tenant_id": TENANT_ID, "limit": 10})
    body = resp.json()
    results.append(TestResult(
        test_id="TC-S08-01",
        name="total_tokens field is present in history response",
        passed=resp.status_code == 200 and "total_tokens" in body,
        details=f"status={resp.status_code} keys={list(body.keys())}",
    ))

    # ── TC-S08-02: total_tokens equals sum of message token_counts ────────────
    msgs = body.get("messages", [])
    expected_total = sum(m.get("token_count", 0) for m in msgs)
    actual_total = body.get("total_tokens", -1)
    results.append(TestResult(
        test_id="TC-S08-02",
        name="total_tokens equals sum of message token_counts",
        passed=actual_total == expected_total,
        details=f"total_tokens={actual_total} sum_of_token_counts={expected_total}",
    ))

    # ── TC-S08-03: total_tokens is non-negative ───────────────────────────────
    results.append(TestResult(
        test_id="TC-S08-03",
        name="total_tokens is non-negative",
        passed=actual_total >= 0,
        details=f"total_tokens={actual_total}",
    ))

    # ── TC-S08-04: empty session returns total_tokens = 0 ────────────────────
    resp_empty = session.get(f"{BASE_URL}/sessions/{EMPTY_SID}/messages",
                             params={"tenant_id": TENANT_ID, "limit": 10})
    body_empty = resp_empty.json()
    results.append(TestResult(
        test_id="TC-S08-04",
        name="empty session returns total_tokens = 0",
        passed=resp_empty.status_code == 200 and body_empty.get("total_tokens") == 0,
        details=f"status={resp_empty.status_code} total_tokens={body_empty.get('total_tokens')}",
    ))

    # ── TC-S08-05: total_tokens consistent with message count ────────────────
    # Fetch with limit=1 — partial page; total_tokens should reflect only returned msgs
    resp_limited = session.get(f"{BASE_URL}/sessions/{SESSION_ID}/messages",
                               params={"tenant_id": TENANT_ID, "limit": 1})
    body_limited = resp_limited.json()
    msgs_limited = body_limited.get("messages", [])
    expected_limited = sum(m.get("token_count", 0) for m in msgs_limited)
    results.append(TestResult(
        test_id="TC-S08-05",
        name="total_tokens reflects only messages in the current page",
        passed=resp_limited.status_code == 200
               and body_limited.get("total_tokens") == expected_limited,
        details=f"page_size=1 total_tokens={body_limited.get('total_tokens')} expected={expected_limited}",
    ))

    return results


if __name__ == "__main__":
    results = run_tests()
    failed = [r for r in results if not r.passed]
    for r in results:
        r.print()
    sys.exit(1 if failed else 0)
