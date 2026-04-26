"""
Test Case: TC-C03
Name: GetContext response latency within acceptable bound
Category: Context Retrieval
Input/Setup: 3 messages inserted; GetContext called; end-to-end latency measured
Expected Result: HTTP 200; is_partial=false; latency_ms < 2000
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper

LATENCY_THRESHOLD_MS = 2000


def run_test():
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    # Step 1: Insert messages
    messages = [
        "Đức nói email của nó là duc@gmail.com",
        "Sinh nhật Đức vào 15/8",
        "Đức đang làm việc tại Google",
    ]
    for msg in messages:
        APIClient.append_message(tenant_id, user_id, session_id, "user", msg)

    time.sleep(0.5)

    # Step 2: Call GetContext and measure latency
    success, resp, duration = APIClient.get_context(
        tenant_id, user_id, session_id, "Cho tôi biết thông tin về Đức"
    )

    Assertions.assert_http_code(success, context="GetContext failed")

    # Step 3: is_partial must be False (service always returns a complete bundle)
    is_partial = resp.get("is_partial")
    if is_partial is not False:
        raise AssertionError(f"Expected is_partial=false, got {is_partial!r}")

    # Step 4: latency_ms must be within threshold
    latency_ms = resp.get("latency_ms", duration)
    if latency_ms >= LATENCY_THRESHOLD_MS:
        raise AssertionError(
            f"Response latency {latency_ms:.0f}ms exceeds threshold {LATENCY_THRESHOLD_MS}ms"
        )

    print(f"PASS: is_partial=False, latency={latency_ms:.0f}ms (threshold={LATENCY_THRESHOLD_MS}ms)")


if __name__ == "__main__":
    run_test_wrapper("TC-C03", "GetContext response latency within acceptable bound", run_test)
