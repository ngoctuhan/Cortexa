"""
Test Case: TC-LM04
Name: Multi-hop reasoning
Category: LongMemEval Scenarios
Input/Setup: Insert 'Minh thích Go'. Insert 'Bạn thân Minh là Đức'. Wait for extraction.
Expected Result: entity_facts contains both Minh's hobby=Go and Minh's relationship=Đức
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper


def run_test():
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    print("Step 1: Insert fact 1 — Minh's hobby")
    ok, _, _ = APIClient.append_message(
        tenant_id, user_id, session_id, "user", "Minh thích lập trình Go"
    )
    Assertions.assert_http_code(ok, context="append fact 1 failed")

    print("Step 2: Insert fact 2 — Minh's relationship")
    ok, _, _ = APIClient.append_message(
        tenant_id, user_id, session_id, "user", "Bạn thân nhất của Minh là Đức"
    )
    Assertions.assert_http_code(ok, context="append fact 2 failed")

    print("Step 1b: Add 2 filler turns so key facts are outside the 2-message recent window")
    for role, text in [
        ("user", "Hôm nay trời đẹp nhỉ?"),
        ("assistant", "Vâng, thời tiết hôm nay rất dễ chịu."),
    ]:
        APIClient.append_message(tenant_id, user_id, session_id, role, text)

    print("Step 3: Wait for both facts to be extracted (up to 180s)")
    deadline = time.time() + 180
    facts = []
    while time.time() < deadline:
        ok, resp, _ = APIClient.get_context(
            tenant_id, user_id, session_id,
            query="Bạn của người thích Go là ai?",
            memory_types=["entity_facts"],
        )
        facts = resp.get("entity_facts", []) if ok else []
        values_lower = [str(f.get("value", "")).lower() for f in facts]
        has_go = any("go" in v for v in values_lower)
        has_duc = any("đức" in v or "duc" in v for v in values_lower)
        if has_go and has_duc:
            break
        time.sleep(2)
    else:
        raise AssertionError(
            f"Multi-hop facts not extracted within 180s. "
            f"Got: {[(f.get('entity'), f.get('attribute'), f.get('value')) for f in facts]}"
        )

    print("Step 4: Assert both Minh/hobby=Go and Minh/relationship=Đức present")
    values_lower = [str(f.get("value", "")).lower() for f in facts]
    if not any("go" in v for v in values_lower):
        raise AssertionError(f"Minh hobby=Go not found. Got: {facts}")
    if not any("đức" in v or "duc" in v for v in values_lower):
        raise AssertionError(f"Minh relationship=Đức not found. Got: {facts}")

    print(f"entity_facts: {[(f.get('entity'), f.get('attribute'), f.get('value')) for f in facts]}")


if __name__ == "__main__":
    run_test_wrapper("TC-LM04", "Multi-hop reasoning", run_test)
