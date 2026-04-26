"""
Test Case: TC-LM01
Name: Single-session recall
Category: LongMemEval Scenarios
Input/Setup: Session turn 1: 'Tôi tên An'. Turn 2: assistant reply. Wait for extraction.
Expected Result: entity_facts contains a fact with value 'An' for the session user
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper


def run_test():
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    print("Step 1: Insert user introduction and assistant reply")
    ok, _, _ = APIClient.append_message(tenant_id, user_id, session_id, "user", "Tôi tên An")
    Assertions.assert_http_code(ok, context="append user message failed")
    ok, _, _ = APIClient.append_message(tenant_id, user_id, session_id, "assistant", "Xin chào An! Tôi có thể giúp gì cho bạn?")
    Assertions.assert_http_code(ok, context="append assistant message failed")

    print("Step 1b: Add 2 filler turns so key facts are outside the 2-message recent window")
    for role, text in [
        ("user", "Hôm nay trời đẹp nhỉ?"),
        ("assistant", "Vâng, thời tiết hôm nay rất dễ chịu."),
    ]:
        APIClient.append_message(tenant_id, user_id, session_id, role, text)

    print("Step 2: Wait for CognitiveWorker to extract entities (up to 180s)")
    extracted = TestHelpers.wait_for_cognitive_extraction(
        tenant_id, user_id, session_id,
        query="Tên tôi là gì?",
        timeout_ms=180000,
        poll_interval_ms=2000,
    )
    if not extracted:
        raise AssertionError("CognitiveWorker did not extract entities within 180s")

    print("Step 3: Assert entity_facts contains name=An")
    ok, resp, _ = APIClient.get_context(
        tenant_id, user_id, session_id,
        query="Tên tôi là gì?",
        memory_types=["entity_facts"],
    )
    Assertions.assert_http_code(ok, context="GetContext failed")
    facts = resp.get("entity_facts", [])
    values = [str(f.get("value", "")).lower() for f in facts]
    if not any("an" in v for v in values):
        raise AssertionError(f"entity_facts does not contain name=An. Got: {[(f.get('attribute'), f.get('value')) for f in facts]}")

    print(f"entity_facts: {[(f.get('attribute'), f.get('value')) for f in facts]}")


if __name__ == "__main__":
    run_test_wrapper("TC-LM01", "Single-session recall", run_test)
