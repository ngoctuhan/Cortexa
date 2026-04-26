"""
Test Case: TC-C06
Name: Unknown userID returns empty bundle
Category: Context Retrieval
Input/Setup: GetContext called for a user UUID that has never had any messages or data
Expected Result: HTTP 200; all list fields empty; is_partial=false
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper


def run_test():
    # Use a fresh UUID that has never had any data — the "unknown user"
    # Do NOT insert any messages for this user
    tenant_id, unknown_user_id, unknown_session_id = TestHelpers.generate_ids()

    # Step 1: Call GetContext for the unknown user (no prior data)
    success, resp, duration = APIClient.get_context(
        tenant_id, unknown_user_id, unknown_session_id,
        "Cho tôi biết thông tin về người dùng không tồn tại"
    )

    Assertions.assert_http_code(success, context="GetContext for unknown user failed")

    # Step 2: All list fields must be empty
    for field in ("recent_messages", "entity_facts", "semantic_messages", "upcoming_events"):
        val = resp.get(field, [])
        if not isinstance(val, list):
            raise AssertionError(f"'{field}' should be a list, got {type(val)}")
        if len(val) != 0:
            raise AssertionError(
                f"Expected '{field}' to be empty for unknown user, got {len(val)} items"
            )

    # Step 3: is_partial must be False
    is_partial = resp.get("is_partial")
    if is_partial is not False:
        raise AssertionError(f"Expected is_partial=false, got {is_partial!r}")

    print(f"PASS: unknown user returns empty bundle, HTTP 200, latency={duration:.0f}ms")


if __name__ == "__main__":
    run_test_wrapper("TC-C06", "Unknown userID returns empty bundle", run_test)
