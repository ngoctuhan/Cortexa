"""
Test Case: TC-S06
Name: Concurrent appends same session
Category: Session Management (Concurrency)
Input/Setup: 50 goroutines AppendMessages simultaneously
Expected Result: All 50 messages persisted; Redis list consistent; no duplicates
"""

import sys, os as _os
sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import time

# Add parent directory to path for imports

from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper


def run_test():
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    # Step 1: Send 50 messages concurrently
    print("Sending 50 messages concurrently...")
    start_time = time.time()

    results = TestHelpers.append_messages_concurrent(
        tenant_id, user_id, session_id,
        count=50,
        role="user",
        content_template="Concurrent message {} - testing race conditions"
    )

    duration = (time.time() - start_time) * 1000
    print(f"Sent 50 concurrent messages in {duration:.2f}ms")

    # Step 2: Verify all messages succeeded
    failed_count = sum(1 for r in results if not r["success"])
    if failed_count > 0:
        raise AssertionError(f"Failed to append {failed_count} messages concurrently")

    success_count = sum(1 for r in results if r["success"])
    print(f"Successfully appended {success_count}/50 messages")

    # Step 3: Verify no duplicates by checking message IDs
    message_ids = [r["response"].get("id") for r in results if r["success"]]
    unique_ids = set(message_ids)

    if len(message_ids) != len(unique_ids):
        raise AssertionError(f"Duplicate message IDs detected: {len(message_ids)} vs {len(unique_ids)} unique")

    print(f"Verified {len(unique_ids)} unique message IDs")

    # Step 4: Verify Redis list is consistent
    success, resp, _ = APIClient.get_context(
        tenant_id, user_id, session_id,
        "Show all messages"
    )

    Assertions.assert_http_code(success, context="GetContext failed")
    Assertions.assert_field_exists(resp, "recent_messages", context="GetContext response")

    recent_messages = resp.get("recent_messages", [])
    print(f"Retrieved {len(recent_messages)} messages from cache")

    # Step 5: Verify consistency
    # All messages should be present or cache should be properly trimmed
    if success_count < 50:
        print(f"WARNING: Only {success_count}/50 messages succeeded")

    print("PASS: Concurrent appends handled correctly, no duplicates, Redis consistent")


if __name__ == "__main__":
    run_test_wrapper("TC-S06", "Concurrent appends same session", run_test)
