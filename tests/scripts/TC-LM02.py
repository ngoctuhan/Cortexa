"""
Test Case: TC-LM02
Name: Cross-session recall
Category: LongMemEval Scenarios
Input/Setup: Session 1: 'Đức làm ở Shopee'. Session 2 (new session, same user): Query 'Đức làm ở đâu?'
Expected Result: entity_facts in session 2 contains works_at=Shopee extracted from session 1
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper


def run_test():
    tenant_id, user_id, session_id_1 = TestHelpers.generate_ids()
    _, _, session_id_2 = TestHelpers.generate_ids()

    print("Step 1: Session 1 — insert 'Đức làm ở Shopee'")
    ok, _, _ = APIClient.append_message(
        tenant_id, user_id, session_id_1, "user", "Đức làm ở Shopee"
    )
    Assertions.assert_http_code(ok, context="append session 1 message failed")

    print("Step 1b: Add 3 filler turns in session 1 so fact is outside the 2-message recent window")
    for role, text in [
        ("assistant", "Tôi đã ghi nhận thông tin đó."),
        ("user", "Cảm ơn bạn!"),
        ("assistant", "Không có gì, tôi luôn sẵn sàng giúp đỡ."),
    ]:
        APIClient.append_message(tenant_id, user_id, session_id_1, role, text)

    print("Step 2: Wait for CognitiveWorker to extract works_at fact (up to 180s)")
    deadline = time.time() + 180
    facts = []
    while time.time() < deadline:
        ok, resp, _ = APIClient.get_context(
            tenant_id, user_id, session_id_1,
            query="Đức làm ở đâu?",
            memory_types=["entity_facts"],
        )
        facts = resp.get("entity_facts", []) if ok else []
        if any("shopee" in str(f.get("value", "")).lower() for f in facts):
            break
        time.sleep(2)
    else:
        raise AssertionError(f"CognitiveWorker did not extract works_at=Shopee within 180s. Got: {facts}")

    print("Step 3: Session 2 — query 'Đức làm ở đâu?' and assert cross-session recall")
    ok, resp, _ = APIClient.get_context(
        tenant_id, user_id, session_id_2,
        query="Đức làm ở đâu?",
        memory_types=["entity_facts"],
    )
    Assertions.assert_http_code(ok, context="GetContext session 2 failed")
    facts = resp.get("entity_facts", [])
    if not any("shopee" in str(f.get("value", "")).lower() for f in facts):
        raise AssertionError(f"Cross-session recall failed: works_at=Shopee not in session 2 entity_facts. Got: {facts}")

    print(f"entity_facts in session 2: {[(f.get('attribute'), f.get('value')) for f in facts]}")


if __name__ == "__main__":
    run_test_wrapper("TC-LM02", "Cross-session recall", run_test)
