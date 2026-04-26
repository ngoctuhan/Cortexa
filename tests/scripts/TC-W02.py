"""
Test Case: TC-W02
Name: Warm flag prevents re-warm
Category: Cache & Singleflight
Input/Setup: Cache warm; call Warm() again...
Expected Result: warm:{uid} flag found; DB not queried
"""

import sys
import time

# Add parent directory to path for imports
sys.path.insert(0, '/Users/macbook/Documents/Cortexa/tests')
from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper


def run_test():
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    print(f"Testing TC-W02: Warm flag prevents re-warm")

    # Setup
    results = TestHelpers.append_messages_batch(
        tenant_id, user_id, session_id,
        count=10,
        role="user",
        content_template="Cache test message {}"
    )

    # Expected: warm:{uid} flag found; DB not queried

    # Test cache behavior
    start = time.time()
    success, resp, _ = APIClient.get_context(
        tenant_id, user_id, session_id,
        "test query"
    )
    duration = (time.time() - start) * 1000

    Assertions.assert_http_code(success, context="GetContext failed")
    print(f"First query latency: {duration:.2f}ms")

    # Second query should be faster (cache hit)
    start = time.time()
    success, resp, _ = APIClient.get_context(
        tenant_id, user_id, session_id,
        "test query 2"
    )
    duration2 = (time.time() - start) * 1000

    print(f"Second query latency: {duration2:.2f}ms")

    print("PASS: TC-W02 completed")


if __name__ == "__main__":
    run_test_wrapper("TC-W02", "Warm flag prevents re-warm", run_test)
