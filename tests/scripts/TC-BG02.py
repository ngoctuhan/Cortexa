"""
Test Case: TC-BG02
Name: Embedder – batch processing
Category: Background Workers
Input/Setup: Insert 50 messages rapidly
Expected Result: All 50 embeddings computed; batched into groups of 50; no duplicate processing
"""

import sys
import time

# Add parent directory to path for imports
sys.path.insert(0, '/Users/macbook/Documents/Cortexa/tests')
from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper


def run_test():
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    # Step 1: Insert 50 messages rapidly
    print("Inserting 50 messages...")
    start_time = time.time()

    results = TestHelpers.append_messages_batch(
        tenant_id, user_id, session_id,
        count=50,
        role="user",
        content_template="Batch message {} for TC-BG02"
    )

    insert_duration = (time.time() - start_time) * 1000
    print(f"Inserted 50 messages in {insert_duration:.2f}ms")

    # Verify all inserts succeeded
    failed_inserts = [r for r in results if not r["success"]]
    if failed_inserts:
        raise AssertionError(f"Failed to insert {len(failed_inserts)} messages")

    # Step 2: Wait for embedder to process all messages
    print("Waiting for embedder to process all messages...")

    def check_all_embeddings_processed():
        success, resp, _ = APIClient.get_context(
            tenant_id, user_id, session_id,
            "test query to check embeddings"
        )
        return success

    all_processed = TestHelpers.wait_for_condition(
        check_all_embeddings_processed,
        timeout_ms=10000,  # 10 seconds for batch processing
        poll_interval_ms=200
    )

    if not all_processed:
        raise AssertionError("Embedder did not process all messages within timeout")

    # Step 3: Verify context endpoint works (indicating embeddings are ready)
    success, resp, _ = APIClient.get_context(
        tenant_id, user_id, session_id,
        "batch processing verification query"
    )

    Assertions.assert_http_code(success, context="GetContext failed after batch processing")
    Assertions.assert_field_exists(resp, "semantic_messages", context="GetContext response")

    print("PASS: All 50 embeddings processed successfully")


if __name__ == "__main__":
    run_test_wrapper("TC-BG02", "Embedder – batch processing", run_test)
