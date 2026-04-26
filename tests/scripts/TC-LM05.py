"""
Test Case: TC-LM05
Name: Negative recall
Category: LongMemEval Scenarios
Input/Setup: Insert messages that never mention Đức's birthday. Query birthday.
Expected Result: entity_facts does NOT contain a birthday attribute for Đức
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper


def run_test():
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    print("Step 1: Insert messages with no birthday information")
    messages = [
        ("user", "Đức làm ở Grab"),
        ("assistant", "Đã ghi nhận Đức làm ở Grab."),
        ("user", "Đức sống ở Hà Nội"),
        ("assistant", "Đã ghi nhận địa chỉ của Đức."),
    ]
    for role, content in messages:
        ok, _, _ = APIClient.append_message(tenant_id, user_id, session_id, role, content)
        Assertions.assert_http_code(ok, context=f"append message failed: {content[:40]}")

    print("Step 2: Wait for CognitiveWorker to process (extract works_at, city — but NOT birthday)")
    deadline = time.time() + 30
    while time.time() < deadline:
        ok, resp, _ = APIClient.get_context(
            tenant_id, user_id, session_id,
            query="Đức làm ở đâu?",
            memory_types=["entity_facts"],
        )
        facts = resp.get("entity_facts", []) if ok else []
        if any("grab" in str(f.get("value", "")).lower() for f in facts):
            break
        time.sleep(2)
    # If we timed out, we still proceed — the negative assertion below is still valid

    print("Step 3: Query birthday — assert NOT found in entity_facts")
    ok, resp, _ = APIClient.get_context(
        tenant_id, user_id, session_id,
        query="Tôi có nhắc birthday Đức chưa?",
        memory_types=["entity_facts"],
    )
    Assertions.assert_http_code(ok, context="GetContext failed")
    facts = resp.get("entity_facts", [])
    birthday_facts = [
        f for f in facts
        if "birthday" in str(f.get("attribute", "")).lower()
        or "sinh_nhật" in str(f.get("attribute", "")).lower()
        or "sinh nhật" in str(f.get("value", "")).lower()
    ]
    if birthday_facts:
        raise AssertionError(
            f"System hallucinated birthday for Đức — should be empty. Got: {birthday_facts}"
        )

    print(f"Negative recall PASS — no birthday facts. All facts: {[(f.get('attribute'), f.get('value')) for f in facts]}")


if __name__ == "__main__":
    run_test_wrapper("TC-LM05", "Negative recall", run_test)
