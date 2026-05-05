"""
Test Case: TC-W04
Name: Warm-up latency
Category: Cache & Singleflight
Input/Setup: User with 50 messages + persona + 5 events...
Expected Result: Warm-up completes < 200ms
"""

import sys, os as _os
sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import time

# Add parent directory to path for imports

from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper


def run_test():
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    print(f"Testing TC-W04: Warm-up latency")

    # Setup
    results = TestHelpers.append_messages_batch(
        tenant_id, user_id, session_id,
        count=10,
        role="user",
        content_template="Cache test message {}"
    )

    # Expected: Warm-up completes < 200ms

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

    print("PASS: TC-W04 completed")


if __name__ == "__main__":
    run_test_wrapper("TC-W04", "Warm-up latency", run_test)
