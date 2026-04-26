"""
Test Case: TC-C02
Name: Entity facts take priority
Category: Context Retrieval
Input/Setup: 3 messages with entity-rich content inserted; GetContext called
Expected Result: entity_facts field present as a list; recent_messages non-empty; HTTP 200
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper


def run_test():
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    # Step 1: Insert entity-rich messages
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

    # Step 3: entity_facts field must be present and must be a list
    Assertions.assert_field_exists(resp, "entity_facts", context="Bundle missing entity_facts")
    entity_facts = resp.get("entity_facts")
    if not isinstance(entity_facts, list):
        raise AssertionError(f"entity_facts should be a list, got {type(entity_facts)}")

    # Step 4: recent_messages must be non-empty (messages were just inserted)
    Assertions.assert_field_exists(resp, "recent_messages", context="Bundle missing recent_messages")
    recent = resp.get("recent_messages", [])
    if len(recent) == 0:
        raise AssertionError("Expected recent_messages to be non-empty after inserting 3 messages")

    print(f"PASS: entity_facts present (count={len(entity_facts)}), "
          f"recent_messages={len(recent)}, latency={duration:.0f}ms")


if __name__ == "__main__":
    run_test_wrapper("TC-C02", "Entity facts take priority", run_test)
