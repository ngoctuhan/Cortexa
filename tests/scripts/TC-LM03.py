"""
Test Case: TC-LM03
Name: Temporal update tracking
Category: LongMemEval Scenarios
Input/Setup: Insert 'Đức email là old@gmail.com', wait for extraction. Then 'Đức đổi email thành new@gmail.com', wait for update.
Expected Result: entity_facts returns new@ only (old@ superseded, valid_until set)
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper


def run_test():
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    print("Step 1: Insert old email fact")
    ok, _, _ = APIClient.append_message(
        tenant_id, user_id, session_id, "user", "Đức nói email của nó là old@gmail.com"
    )
    Assertions.assert_http_code(ok, context="append old email message failed")

    print("  Add 2 filler turns to push the above message out of the 2-message recent window")
    for role, text in [
        ("assistant", "Tôi đã ghi nhận thông tin của bạn."),
        ("user", "Cảm ơn bạn rất nhiều!"),
    ]:
        APIClient.append_message(tenant_id, user_id, session_id, role, text)

    print("Step 2: Wait for old@ to appear in entity_facts (up to 180s)")
    deadline = time.time() + 180
    while time.time() < deadline:
        ok, resp, _ = APIClient.get_context(
            tenant_id, user_id, session_id,
            query="Đức email",
            memory_types=["entity_facts"],
        )
        facts = resp.get("entity_facts", []) if ok else []
        if any("old@gmail.com" in str(f.get("value", "")) for f in facts):
            break
        time.sleep(2)
    else:
        raise AssertionError("CognitiveWorker did not extract old@ within 180s")

    print("Step 3: Insert email update")
    ok, _, _ = APIClient.append_message(
        tenant_id, user_id, session_id, "user", "Đức đổi email thành new@gmail.com"
    )
    Assertions.assert_http_code(ok, context="append update message failed")

    print("  Add 2 filler turns to push the above message out of the 2-message recent window")
    for role, text in [
        ("assistant", "Tôi đã ghi nhận thông tin của bạn."),
        ("user", "Cảm ơn bạn rất nhiều!"),
    ]:
        APIClient.append_message(tenant_id, user_id, session_id, role, text)

    print("Step 4: Wait for new@ to appear and old@ to be superseded (up to 180s)")
    deadline = time.time() + 180
    facts = []
    while time.time() < deadline:
        ok, resp, _ = APIClient.get_context(
            tenant_id, user_id, session_id,
            query="Đức email mới",
            memory_types=["entity_facts"],
        )
        facts = resp.get("entity_facts", []) if ok else []
        values = [str(f.get("value", "")).lower() for f in facts]
        if any("new@gmail.com" in v for v in values):
            break
        time.sleep(2)
    else:
        raise AssertionError(f"CognitiveWorker did not update email to new@ within 180s. Got: {facts}")

    print("Step 5: Assert new@ present, old@ absent from current entity_facts")
    values = [str(f.get("value", "")).lower() for f in facts]
    if not any("new@gmail.com" in v for v in values):
        raise AssertionError(f"new@gmail.com not found in entity_facts. Got: {facts}")
    if any("old@gmail.com" in v for v in values):
        raise AssertionError(f"old@gmail.com still present — supersede failed. Got: {facts}")

    print(f"entity_facts (current): {[(f.get('attribute'), f.get('value')) for f in facts]}")


if __name__ == "__main__":
    run_test_wrapper("TC-LM03", "Temporal update tracking", run_test)
