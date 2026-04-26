"""
Test Case: TC-V05
Name: Zero embeddings in DB
Category: Validation / Input
Input/Setup: Fresh session with no messages appended; embedder has never run for it.
Expected Result: GET /context returns HTTP 200; semantic_messages is an empty list; no crash.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper


def run_test():
    # Use a completely fresh session — no messages appended, so no vectors in DB.
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    print(f"Querying empty session (no messages, no embeddings)...")
    success, resp, _ = APIClient.get_context(
        tenant_id, user_id, session_id,
        "Tell me about Python programming language features",
    )

    Assertions.assert_http_code(success, context="GetContext on empty session must not crash")
    Assertions.assert_field_exists(resp, "semantic_messages", context="GetContext response")

    chunks = resp.get("semantic_messages", [])
    assert chunks == [], (
        f"Expected empty semantic_messages for a session with zero embeddings, got {len(chunks)} chunk(s)"
    )

    print("PASS: HTTP 200 returned; semantic_messages is empty list for zero-embedding session")


if __name__ == "__main__":
    run_test_wrapper("TC-V05", "Zero embeddings in DB", run_test)
