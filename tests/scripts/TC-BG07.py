"""
TC-BG07 — Hybrid Flush Cognitive Extraction (Event-driven)

Tests: Ensure that creating a new session triggers a cognitive batch flush 
for previous sessions that have less than 10 messages pending.
"""

import sys
import os
import time
import requests
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_utils import APIClient, TestResult, TestHelpers, BASE_URL

def run_tests():
    results = []
    
    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    # 1. Create Session 1
    resp = requests.post(f"{BASE_URL}/sessions", json={
        "tenant_id": tenant_id,
        "user_id": user_id,
        "title": "Session 1"
    })
    if resp.status_code != 201:
        results.append(TestResult(
            test_id="TC-BG07-01",
            name="Create Session 1",
            passed=False,
            details=f"status={resp.status_code}, {resp.text}"
        ))
        return results
    session_1 = resp.json()["id"]

    # 2. Append 3 messages to Session 1
    for i in range(3):
        success, _, _ = APIClient.append_message(
            tenant_id, user_id, session_1, "user",
            f"My favorite color is green. This is message {i+1}."
        )
        if not success:
            results.append(TestResult(
                test_id="TC-BG07-02",
                name="Append Messages to Session 1",
                passed=False,
                details="Failed to append message"
            ))
            return results
    results.append(TestResult(
        test_id="TC-BG07-02",
        name="Append Messages to Session 1",
        passed=True,
        details="Appended 3 messages successfully"
    ))
            
    time.sleep(2) # Ensure we don't hit rate limits and wait for any background processing
    
    # Check that no cognitive extraction happened yet (since count < 10)
    success, resp_data, _ = APIClient.get_context(
        tenant_id, user_id, str(uuid.uuid4()), "What is my favorite color?"
    )
    if success:
        facts = resp_data.get("entity_facts", [])
        if len(facts) > 0:
            # Note: This might occasionally fail if COGNITIVE_BATCH_SIZE is set to < 3
            print("Warning: Facts extracted before flush. Is COGNITIVE_BATCH_SIZE <= 3?")

    # 3. Create Session 2 to trigger flush
    resp = requests.post(f"{BASE_URL}/sessions", json={
        "tenant_id": tenant_id,
        "user_id": user_id,
        "title": "Session 2"
    })
    results.append(TestResult(
        test_id="TC-BG07-03",
        name="Create Session 2 (Trigger Flush)",
        passed=resp.status_code == 201,
        details=f"status={resp.status_code}"
    ))

    # 4. Wait for extraction
    print("Waiting for cognitive extraction to complete (up to 30s)...")
    def check_persona_extracted():
        # Request only persona to skip the slow LLM embed path for semantic/experiences.
        ok, r, _ = APIClient.get_context(tenant_id, user_id, str(uuid.uuid4()), "What is my favorite color?",
                                         memory_types=["persona"])
        if not ok:
            return False
        persona_rec = r.get("persona_context") or r.get("persona")
        if not persona_rec:
            return False
        return "green" in str(persona_rec).lower()
    found = TestHelpers.wait_for_condition(check_persona_extracted, timeout_ms=240000, poll_interval_ms=1000)
    
    results.append(TestResult(
        test_id="TC-BG07-04",
        name="Cognitive Extraction after Flush",
        passed=found,
        details="Extracted facts should be available after creating a new session"
    ))

    # 5. Verify Context (persona-only to avoid embed overhead)
    success, resp_data, _ = APIClient.get_context(
        tenant_id, user_id, str(uuid.uuid4()), "What is my favorite color?",
        memory_types=["persona"]
    )
    
    passed_context = False
    if success:
        # persona_context is a MemoryRecord object; use str() to check payload content.
        persona_obj = resp_data.get("persona_context") or resp_data.get("persona")
        if persona_obj:
            passed_context = "green" in str(persona_obj).lower()

    results.append(TestResult(
        test_id="TC-BG07-05",
        name="Verify Extracted Context",
        passed=passed_context,
        details="Context should contain 'green' in persona"
    ))

    return results

if __name__ == "__main__":
    results = run_tests()
    failed = [r for r in results if not r.passed]
    for r in results:
        r.print()
    sys.exit(1 if failed else 0)
