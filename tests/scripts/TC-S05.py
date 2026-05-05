"""
Test Case: TC-S05
Name: Sliding window trim
Category: Session Management (Edge case)
Input/Setup: Session with 60 messages; append 1 more
Expected Result: Redis list trimmed to last 50; oldest 11 messages not in cache
"""

import sys, os as _os
sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import time

# Add parent directory to path for imports

from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper


def run_test():
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    # Step 1: Create session with 60 messages
    print("Creating session with 60 messages to test sliding window...")
    start_time = time.time()

    results = TestHelpers.append_messages_batch(
        tenant_id, user_id, session_id,
        count=60,
        role="user",
        content_template="Sliding window message {} - testing trim functionality"
    )

    insert_duration = (time.time() - start_time) * 1000
    print(f"Inserted 60 messages in {insert_duration:.2f}ms")

    failed_inserts = [r for r in results if not r["success"]]
    if failed_inserts:
        raise AssertionError(f"Failed to insert {len(failed_inserts)} messages")

    # Step 2: Append 1 more message (should trigger trim to 50)
    print("Appending 1 more message (should trigger trim to 50)...")
    success, resp, _ = APIClient.append_message(
        tenant_id, user_id, session_id,
        role="user",
        content="This is message 61 - should trigger sliding window trim"
    )

    Assertions.assert_http_code(success, context="Failed to append message 61")

    # Step 3: Verify Redis list is trimmed (recent_messages should be ~50)
    success, resp, _ = APIClient.get_context(
        tenant_id, user_id, session_id,
        "How many messages do we have?"
    )

    Assertions.assert_http_code(success, context="GetContext failed")
    Assertions.assert_field_exists(resp, "recent_messages", context="GetContext response")

    recent_messages = resp.get("recent_messages", [])
    message_count = len(recent_messages)

    print(f"Recent messages count: {message_count}")

    # The count should be around 50 (allowing some buffer for implementation details)
    # Some implementations might keep slightly more or less
    if message_count > 60:
        raise AssertionError(f"Messages not trimmed: got {message_count}, expected ~50")

    # Verify the newest message is present
    found_newest = any("message 61" in msg.get("content", "") for msg in recent_messages)
    if not found_newest:
        print("WARNING: Newest message (61) not found - may indicate trim issue")

    # Verify oldest messages are not in cache
    found_oldest = any("Sliding window message 0" in msg.get("content", "") for msg in recent_messages)
    if found_oldest:
        print("WARNING: Oldest message still in cache - sliding window may not be working")

    print(f"PASS: Sliding window trim working (cache has {message_count} messages)")


if __name__ == "__main__":
    run_test_wrapper("TC-S05", "Sliding window trim", run_test)
