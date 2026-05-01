"""
Test Case: TC-LM07
Name: Conflicting facts resolution
Category: LongMemEval Scenarios
Input/Setup: Insert 'Đức 28 tuổi', wait for extraction. Then 'Đức vừa sinh nhật, 29 tuổi rồi', wait for supersede.
Expected Result: entity_facts returns age=29 only; age=28 is superseded (not present in current facts)
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper


def run_test():
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    print("Step 1: Insert old age fact — Đức 28 tuổi")
    ok, _, _ = APIClient.append_message(
        tenant_id, user_id, session_id, "user", "Đức năm nay 28 tuổi"
    )
    Assertions.assert_http_code(ok, context="append old age failed")

    print("  Add 2 filler turns to push the above message out of the 2-message recent window")
    for role, text in [
        ("assistant", "Tôi đã ghi nhận thông tin của bạn."),
        ("user", "Cảm ơn bạn rất nhiều!"),
    ]:
        APIClient.append_message(tenant_id, user_id, session_id, role, text)

    print("Step 2: Wait for age=28 to appear in entity_facts (up to 240s)")
    deadline = time.time() + 240
    while time.time() < deadline:
        ok, resp, _ = APIClient.get_context(
            tenant_id, user_id, session_id,
            query="Đức bao nhiêu tuổi?",
            memory_types=["entity_facts"],
        )
        facts = resp.get("entity_facts", []) if ok else []
        if any("28" in str(f.get("value", "")) for f in facts):
            break
        time.sleep(2)
    else:
        raise AssertionError("CognitiveWorker did not extract age=28 within 240s")

    print("Step 3: Insert conflicting fact — Đức 29 tuổi")
    ok, _, _ = APIClient.append_message(
        tenant_id, user_id, session_id, "user", "Đức vừa sinh nhật, 29 tuổi rồi"
    )
    Assertions.assert_http_code(ok, context="append new age failed")

    print("  Add 2 filler turns to push the above message out of the 2-message recent window")
    for role, text in [
        ("assistant", "Tôi đã ghi nhận thông tin của bạn."),
        ("user", "Cảm ơn bạn rất nhiều!"),
    ]:
        APIClient.append_message(tenant_id, user_id, session_id, role, text)

    print("Step 4: Wait for age=29 to supersede age=28 (up to 240s)")
    deadline = time.time() + 240
    facts = []
    while time.time() < deadline:
        ok, resp, _ = APIClient.get_context(
            tenant_id, user_id, session_id,
            query="Đức bao nhiêu tuổi?",
            memory_types=["entity_facts"],
        )
        facts = resp.get("entity_facts", []) if ok else []
        values = [str(f.get("value", "")) for f in facts]
        if any("29" in v for v in values):
            break
        time.sleep(2)
    else:
        raise AssertionError(f"CognitiveWorker did not update age to 29 within 240s. Got: {facts}")

    print("Step 5: Assert age=29 present, age=28 absent (superseded)")
    values = [str(f.get("value", "")) for f in facts]
    if not any("29" in v for v in values):
        raise AssertionError(f"age=29 not found in entity_facts. Got: {facts}")
    if any(v.strip() == "28" for v in values):
        raise AssertionError(f"age=28 still present — supersede failed. Got: {facts}")

    print(f"Conflicting facts resolved. entity_facts: {[(f.get('attribute'), f.get('value')) for f in facts]}")


if __name__ == "__main__":
    run_test_wrapper("TC-LM07", "Conflicting facts resolution", run_test)
