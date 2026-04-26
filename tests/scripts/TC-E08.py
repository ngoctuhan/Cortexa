"""
Test Case: TC-E08
Name: Very long message
Category: Entity Extraction
Input/Setup: Message of >=2500 characters
Expected Result: service returns HTTP 200 and handles the long message without error
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper

_PADDING = "A" * 2500
input_msg = f"Long message: {_PADDING}"
assert len(input_msg) >= 2500, f"Test setup error: message length {len(input_msg)} < 2500"


def run_test():
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    print(f"Step 1: Sending message of {len(input_msg)} characters")
    success, resp, _ = APIClient.append_message(
        tenant_id, user_id, session_id,
        role="user",
        content=input_msg,
    )
    Assertions.assert_http_code(success, context="Failed to append long message")

    time.sleep(1)

    success, resp, _ = APIClient.get_context(
        tenant_id, user_id, session_id,
        "What entities were mentioned?",
    )
    Assertions.assert_http_code(success, context="GetContext failed after long message")
    Assertions.assert_field_exists(resp, "entity_facts", context="GetContext response")

    print(f"Entity facts count: {len(resp.get('entity_facts', []))}")
    print("PASS: Service handled long message without error")


if __name__ == "__main__":
    run_test_wrapper("TC-E08", "Very long message", run_test)
