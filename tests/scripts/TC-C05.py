"""
Test Case: TC-C05
Name: GetContext returns empty bundle for session with no data
Category: Context Retrieval
Input/Setup: Fresh session with no messages inserted; GetContext called immediately
Expected Result: HTTP 200; all list fields empty; is_partial=false
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper


def run_test():
    # Fresh session — no messages inserted
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    # Step 1: Call GetContext on an empty session
    success, resp, duration = APIClient.get_context(
        tenant_id, user_id, session_id, "Cho tôi biết thông tin về Đức"
    )

    Assertions.assert_http_code(success, context="GetContext on empty session failed")

    # Step 2: All list fields must be empty
    for field in ("recent_messages", "entity_facts", "semantic_messages", "upcoming_events"):
        val = resp.get(field, [])
        if not isinstance(val, list):
            raise AssertionError(f"'{field}' should be a list, got {type(val)}")
        if len(val) != 0:
            raise AssertionError(
                f"Expected '{field}' to be empty for new session, got {len(val)} items"
            )

    # Step 3: is_partial must be False
    is_partial = resp.get("is_partial")
    if is_partial is not False:
        raise AssertionError(f"Expected is_partial=false, got {is_partial!r}")

    print(f"PASS: empty session returns all empty fields, is_partial=False, "
          f"latency={duration:.0f}ms")


if __name__ == "__main__":
    run_test_wrapper("TC-C05", "GetContext returns empty bundle for session with no data", run_test)
