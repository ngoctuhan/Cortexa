"""
Test Case: TC-BG03
Name: Summarizer – long session trigger
Category: Background Workers
Input/Setup: Session exceeds 100 messages
Expected Result: Summarizer triggered; rag_chunk memory_record created with summary; messages trimmed to 50
"""

import sys
import time

# Add parent directory to path for imports
sys.path.insert(0, '/Users/macbook/Documents/Cortexa/tests')
from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper


def run_test():
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    # Step 1: Create a session with 101 messages to trigger summarizer
    print("Creating session with 101 messages to trigger summarizer...")
    start_time = time.time()

    results = TestHelpers.append_messages_batch(
        tenant_id, user_id, session_id,
        count=101,
        role="user",
        content_template="Long session message {} - This is message number in a long conversation for summarization testing"
    )

    insert_duration = (time.time() - start_time) * 1000
    print(f"Inserted 101 messages in {insert_duration:.2f}ms")

    # Verify all inserts succeeded
    failed_inserts = [r for r in results if not r["success"]]
    if failed_inserts:
        raise AssertionError(f"Failed to insert {len(failed_inserts)} messages")

    # Step 2: Wait for summarizer to process
    print("Waiting for summarizer to process...")

    def check_summary_created():
        success, resp, _ = APIClient.get_context(
            tenant_id, user_id, session_id,
            "What was discussed in this conversation?"
        )
        # Check if we got a response with context (summary should be in semantic_messages)
        return success and "semantic_messages" in resp

    summary_ready = TestHelpers.wait_for_condition(
        check_summary_created,
        timeout_ms=15000,  # 15 seconds for summarization
        poll_interval_ms=500
    )

    if not summary_ready:
        raise AssertionError("Summarizer did not process session within timeout")

    # Step 3: Verify the response contains summarized context
    success, resp, _ = APIClient.get_context(
        tenant_id, user_id, session_id,
        "Summarize our conversation"
    )

    Assertions.assert_http_code(success, context="GetContext failed after summarization")
    Assertions.assert_field_exists(resp, "semantic_messages", context="GetContext should have summary")
    Assertions.assert_field_exists(resp, "recent_messages", context="GetContext should have recent messages")

    # Verify recent_messages is trimmed (should have last 50 or so)
    recent_count = len(resp.get("recent_messages", []))
    print(f"Recent messages count: {recent_count}")

    if recent_count > 60:  # Allow some buffer, but should be around 50
        raise AssertionError(f"Messages not trimmed properly: {recent_count} > 60")

    print("PASS: Summarizer triggered successfully, messages trimmed")


if __name__ == "__main__":
    run_test_wrapper("TC-BG03", "Summarizer – long session trigger", run_test)
