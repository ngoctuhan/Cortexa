"""
Test Case: TC-C01
Name: Full context bundle
Category: Context Retrieval
Input/Setup: 3 messages inserted for a user; GetContext called with a relevant query
Expected Result: All 5 fields present (recent_messages, entity_facts, semantic_messages,
                 persona_context, upcoming_events); is_partial=false; HTTP 200
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper


def run_test():
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    # Step 1: Insert messages
    messages = [
        "Đức nói email của nó là duc@gmail.com",
        "Sinh nhật Đức vào 15/8",
        "Đức đang làm việc tại Google",
    ]
    for msg in messages:
        APIClient.append_message(tenant_id, user_id, session_id, "user", msg)

    time.sleep(0.5)

    # Step 2: Call GetContext
    success, resp, duration = APIClient.get_context(
        tenant_id, user_id, session_id, "Cho tôi biết thông tin về Đức"
    )

    Assertions.assert_http_code(success, context="GetContext failed")

    # Step 3: All 5 bundle fields must be present
    for field in ("recent_messages", "entity_facts", "semantic_messages",
                  "persona_context", "upcoming_events"):
        Assertions.assert_field_exists(resp, field, context=f"Bundle missing '{field}'")

    # Step 4: is_partial must be False
    is_partial = resp.get("is_partial")
    if is_partial is not False:
        raise AssertionError(f"Expected is_partial=false, got {is_partial!r}")

    # Step 5: recent_messages must be non-empty (messages were just inserted)
    recent = resp.get("recent_messages", [])
    if len(recent) == 0:
        raise AssertionError("Expected recent_messages to be non-empty after inserting 3 messages")

    print(f"PASS: all 5 fields present, is_partial=False, "
          f"recent_messages={len(recent)}, latency={duration:.0f}ms")


if __name__ == "__main__":
    run_test_wrapper("TC-C01", "Full context bundle", run_test)
