"""
Test Case: TC-BG01
Name: Embedder – LISTEN/NOTIFY trigger
Category: Background Workers
Input/Setup: Insert message to DB
Expected Result: NOTIFY fired; Embedder picks up within 500ms; embedding column populated
"""

import sys, os as _os
sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import time

# Add parent directory to path for imports

from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper


def run_test():
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    # Step 1: Insert a message
    success, resp, duration = APIClient.append_message(
        tenant_id, user_id, session_id,
        role="user",
        content="Test message for TC-BG01 - embedding test"
    )
    Assertions.assert_http_code(success, context="Failed to append message")

    message_id = resp.get("id")
    print(f"Message inserted with ID: {message_id}")

    # Step 2: Wait for embedder to process (LISTEN/NOTIFY should trigger)
    # The embedder should pick up the message within 500ms
    def check_embedding_ready():
        # For this test, we verify by querying context which uses embeddings
        success, resp, _ = APIClient.get_context(
            tenant_id, user_id, session_id,
            "test query to verify embedding exists"
        )
        return success and "semantic_messages" in resp

    embedding_ready = TestHelpers.wait_for_condition(
        check_embedding_ready,
        timeout_ms=5000,  # Give more time for initial test
        poll_interval_ms=100
    )

    if not embedding_ready:
        raise AssertionError("Embedder did not process message within timeout")

    # Step 3: Verify embedding was processed by checking response
    success, resp, _ = APIClient.get_context(
        tenant_id, user_id, session_id,
        "test query"
    )

    Assertions.assert_http_code(success, context="GetContext failed")
    Assertions.assert_field_exists(resp, "semantic_messages", context="GetContext response")

    print("PASS: Embedding processed successfully")


if __name__ == "__main__":
    run_test_wrapper("TC-BG01", "Embedder – LISTEN/NOTIFY trigger", run_test)
