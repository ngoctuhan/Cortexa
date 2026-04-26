"""
Test Case: TC-C04
Name: GetContext succeeds under concurrent load
Category: Context Retrieval
Input/Setup: 3 messages inserted; 10 concurrent GetContext calls fired via ThreadPoolExecutor
Expected Result: All 10 calls return HTTP 200 and is_partial=false
"""

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper

CONCURRENCY = 10


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

    # Step 2: Fire CONCURRENCY calls simultaneously
    def call():
        return APIClient.get_context(
            tenant_id, user_id, session_id, "Cho tôi biết thông tin về Đức"
        )

    results = []
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        futures = [ex.submit(call) for _ in range(CONCURRENCY)]
        for f in as_completed(futures):
            results.append(f.result())

    # Step 3: All calls must have succeeded (HTTP 200)
    failures = [(i, r) for i, r in enumerate(results) if not r[0]]
    if failures:
        raise AssertionError(
            f"{len(failures)}/{CONCURRENCY} calls failed: {[r[1] for _, r in failures]}"
        )

    # Step 4: All responses must have is_partial=False
    partial_count = sum(1 for r in results if r[1].get("is_partial") is not False)
    if partial_count > 0:
        raise AssertionError(f"{partial_count}/{CONCURRENCY} responses had is_partial!=False")

    latencies = sorted(r[2] for r in results)
    p99 = latencies[int(len(latencies) * 0.99)]
    print(f"PASS: {CONCURRENCY}/{CONCURRENCY} calls succeeded, "
          f"p99={p99:.0f}ms, is_partial=False on all")


if __name__ == "__main__":
    run_test_wrapper("TC-C04", "GetContext succeeds under concurrent load", run_test)
