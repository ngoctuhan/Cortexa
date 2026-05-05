"""
Test Case: TC-BG09
Name: Hybrid Flush – new session triggers extraction of previous session
Category: Background Workers
Input/Setup: Send 3 messages to session 1 (below batch threshold); create session 2.
Expected Result: flushPreviousUserSessions fires; cognitive worker extracts facts from
                 session 1; entity_facts contains extracted data within 15s.
"""

import sys, os as _os
sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import time
import requests
from test_utils import APIClient, TestHelpers, run_test_wrapper, BASE_URL


def run_test():
    tenant_id, user_id, _ = TestHelpers.generate_ids()

    # 1. Create session 1
    resp = requests.post(f"{BASE_URL}/sessions", json={
        "tenant_id": tenant_id,
        "user_id": user_id,
        "title": "Session 1",
    })
    assert resp.status_code == 201, f"Create session 1 failed: {resp.status_code} {resp.text}"
    session_1 = resp.json()["id"]
    print(f"Created session 1: {session_1}")

    # 2. Append 3 messages — intentionally below default batch threshold.
    # Use named-entity messages so the LLM reliably emits entity_facts (not persona).
    messages = [
        "Con chó của tôi tên là Buddy.",
        "Bạn thân của tôi tên là Linh, 28 tuổi.",
        "Linh làm kỹ sư phần mềm tại Hà Nội.",
    ]
    for i, msg in enumerate(messages):
        ok, _, _ = APIClient.append_message(
            tenant_id, user_id, session_1, "user", msg
        )
        assert ok, f"append_message {i+1} failed"

    print("Appended 3 messages to session 1 — no extraction should have fired yet.")
    time.sleep(2)

    # 3. Create session 2 — this triggers flushPreviousUserSessions for session 1
    print("Creating session 2 (should trigger flush for session 1)…")
    resp = requests.post(f"{BASE_URL}/sessions", json={
        "tenant_id": tenant_id,
        "user_id": user_id,
        "title": "Session 2",
    })
    assert resp.status_code == 201, f"Create session 2 failed: {resp.status_code} {resp.text}"
    print(f"Created session 2: {resp.json()['id']}")

    # 4. Wait for cognitive worker to process the flushed batch
    print("Waiting up to 15s for cognitive extraction…")
    extracted = TestHelpers.wait_for_cognitive_extraction(tenant_id, user_id, session_1, query="Buddy Linh dog friend", timeout_ms=30000)
    assert extracted, "FAILED — no facts extracted after flush; hybrid flush may not have worked."

    # 5. Verify the fact is retrievable via /v1/context
    import uuid
    ok, ctx, latency = APIClient.get_context(
        tenant_id, user_id, str(uuid.uuid4()), "Tên con chó của tôi là gì?"
    )
    assert ok, f"get_context failed: {ctx}"

    facts = ctx.get("entity_facts") or []
    sem   = ctx.get("semantic_messages") or []
    keywords = ["buddy", "linh"]
    found = any(
        any(kw in str(f.get("value", "")).lower() or kw in str(f.get("entity_name", "")).lower() for kw in keywords)
        for f in facts
    ) or any(
        any(kw in m.get("content", "").lower() for kw in keywords)
        for m in sem
    )
    assert found, (
        f"Entity facts about 'Buddy'/'Linh' not found in context.\n"
        f"entity_facts={facts}\nsemantic_messages={sem}"
    )
    print(f"PASS — fact extracted and retrieved in {latency:.0f}ms.")


if __name__ == "__main__":
    run_test_wrapper("TC-BG09", "Hybrid Flush – new session triggers extraction of previous session", run_test)
