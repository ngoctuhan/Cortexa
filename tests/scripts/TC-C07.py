"""
Test Case: TC-C07
Name: Memory Types and Time Range filtering
Category: Context Retrieval
Input/Setup: 3 messages inserted; GetContext called with memory_types=["entity_facts"]
             and separately with time_range set to a past year (2020)
Expected Result: memory_types filter: recent_messages=[] and semantic_messages=[];
                 time_range filter: recent_messages=[]; HTTP 200 on both calls
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

    # ── Part A: memory_types=["entity_facts"] ────────────────────────────────
    success, resp, duration = APIClient.get_context(
        tenant_id, user_id, session_id,
        query="thông tin",
        memory_types=["entity_facts"],
    )
    Assertions.assert_http_code(success, context="GetContext with memory_types failed")
    Assertions.assert_field_exists(resp, "entity_facts", context="Bundle missing entity_facts")

    recent_msgs = resp.get("recent_messages", [])
    if len(recent_msgs) != 0:
        raise AssertionError(
            f"Expected recent_messages=[] with memory_types=['entity_facts'], "
            f"got {len(recent_msgs)} items"
        )

    semantic_msgs = resp.get("semantic_messages", [])
    if len(semantic_msgs) != 0:
        raise AssertionError(
            f"Expected semantic_messages=[] with memory_types=['entity_facts'], "
            f"got {len(semantic_msgs)} items"
        )

    # ── Part B: time_range entirely in the past ───────────────────────────────
    # Messages inserted today (2026) must not appear for a 2020 time window.
    success2, resp2, duration2 = APIClient.get_context(
        tenant_id, user_id, session_id,
        query="thông tin",
        time_range={
            "start": "2020-01-01T00:00:00Z",
            "end": "2020-12-31T23:59:59Z",
        },
    )
    Assertions.assert_http_code(success2, context="GetContext with time_range failed")

    recent_msgs2 = resp2.get("recent_messages", [])
    if len(recent_msgs2) != 0:
        raise AssertionError(
            f"Expected recent_messages=[] for past time_range (2020), "
            f"got {len(recent_msgs2)} items"
        )

    print(
        f"PASS: memory_types filter correct (recent={len(recent_msgs)}, "
        f"semantic={len(semantic_msgs)}); time_range filter correct "
        f"(recent={len(recent_msgs2)}); latencies: {duration:.0f}ms, {duration2:.0f}ms"
    )


if __name__ == "__main__":
    run_test_wrapper("TC-C07", "Memory Types and Time Range filtering", run_test)
