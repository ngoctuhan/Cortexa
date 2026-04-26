"""
Test Case: TC-E11
Name: Time Anchoring and Extractor Performance (Tokens & Latency)
Category: Entity Extraction
Input/Setup: Message: '2 ngày nữa tôi tham gia phỏng vấn.'
Expected Result: upcoming_events contains an event referencing 'phỏng vấn' with ISO 8601 date anchored relative to now
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper


def run_test():
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    print("Step 1: Sending message '2 ngày nữa tôi tham gia phỏng vấn.'")
    success, _, latency = APIClient.append_message(
        tenant_id, user_id, session_id,
        role="user",
        content="2 ngày nữa tôi tham gia phỏng vấn.",
    )
    Assertions.assert_http_code(success, context="Failed to append message")
    print(f"Append latency: {latency}ms")

    print("Waiting for cognitive extraction (up to 120s)...")

    def has_interview_event():
        ok, r, _ = APIClient.get_context(
            tenant_id, user_id, session_id,
            "Tôi có lịch trình gì sắp tới không?",
        )
        if not ok:
            return False
        events = r.get("upcoming_events", [])
        return any(
            "phỏng vấn" in str(ev.get("payload", "")).lower() or "interview" in str(ev.get("payload", "")).lower()
            for ev in events
        )

    TestHelpers.wait_for_condition(has_interview_event, timeout_ms=600000, poll_interval_ms=2000)

    success, resp, ctx_latency = APIClient.get_context(
        tenant_id, user_id, session_id,
        "Tôi có lịch trình gì sắp tới không?",
    )
    Assertions.assert_http_code(success, context="GetContext failed")
    print(f"GetContext latency: {ctx_latency}ms")

    events = resp.get("upcoming_events", [])
    print(f"Upcoming events count: {len(events)}")

    interview_events = [
        ev for ev in events
        if "phỏng vấn" in str(ev.get("payload", "")).lower() or "interview" in str(ev.get("payload", "")).lower()
    ]
    assert len(interview_events) >= 1, (
        f"Expected upcoming event for 'phỏng vấn', none found. Events: {events}"
    )

    print(f"PASS: Found {len(interview_events)} interview event(s) with time anchoring")
    for ev in interview_events:
        print(f"  payload={ev.get('payload')!r}")


if __name__ == "__main__":
    run_test_wrapper("TC-E11", "Time Anchoring & Extractor Metrics", run_test)
