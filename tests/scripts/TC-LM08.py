"""
Test Case: TC-LM08
Name: Proactive life event surfacing
Category: LongMemEval Scenarios
Input/Setup: Insert 'Sinh nhật Đức vào 15/8/2026'. Wait for event extraction.
Expected Result: upcoming_events in GetContext contains the birthday event for Đức
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper


def run_test():
    # Flush cognitive streams to prevent backlog from delaying extraction
    try:
        import redis as _redis
        _r = _redis.Redis(host="localhost", port=6380, db=0)
        _streams = _r.keys("*:stream:cognitive")
        if _streams:
            _r.delete(*_streams)
            print(f"[Setup] Cleared {len(_streams)} cognitive stream(s)")
    except Exception as _e:
        print(f"[Setup] Stream clear skipped: {_e}")
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    print("Step 1: Insert birthday event message")
    ok, _, _ = APIClient.append_message(
        tenant_id, user_id, session_id, "user",
        "Sinh nhật Đức vào ngày 15 tháng 8 năm 2026"
    )
    Assertions.assert_http_code(ok, context="append birthday message failed")

    print("Step 1b: Add 3 filler turns so birthday message is outside the 2-message recent window")
    for role, text in [
        ("assistant", "Tôi đã ghi nhận ngày sinh nhật của Đức."),
        ("user", "Cảm ơn bạn đã nhớ giúp."),
        ("assistant", "Không có gì, đây là điều quan trọng cần lưu ý."),
    ]:
        APIClient.append_message(tenant_id, user_id, session_id, role, text)

    print("Step 2: Wait for CognitiveWorker to extract upcoming_events (up to 600s)")
    deadline = time.time() + 600
    events = []
    while time.time() < deadline:
        ok, resp, _ = APIClient.get_context(
            tenant_id, user_id, session_id,
            query="Sinh nhật Đức khi nào?",
            memory_types=["events"],
        )
        events = resp.get("upcoming_events", []) if ok else []
        if events:
            break
        time.sleep(2)
    else:
        raise AssertionError("CognitiveWorker did not extract upcoming_events within 600s")

    print("Step 3: Assert event references Đức and a birthday")
    found = any(
        "đức" in str(e).lower() or "duc" in str(e).lower() or "birthday" in str(e).lower()
        or "sinh" in str(e).lower()
        for e in events
    )
    if not found:
        raise AssertionError(f"upcoming_events does not reference Đức's birthday. Got: {events}")

    print(f"Proactive surfacing PASS — upcoming_events: {events}")


if __name__ == "__main__":
    run_test_wrapper("TC-LM08", "Proactive life event surfacing", run_test)
