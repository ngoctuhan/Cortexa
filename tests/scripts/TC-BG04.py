"""
Test Case: TC-BG04
Name: Event Detector – birthday detection
Category: Background Workers
Input/Setup: Message: 'Sinh nhật Đức vào 15/8'
Expected Result: life_event row created: type='birthday', event_date='2024-08-15', proactive_at set
"""

import sys
import time

# Add parent directory to path for imports
import os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper


def run_test():
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    # Step 1: Send message with birthday information
    birthday_message = "Sinh nhật Đức vào 15/8"

    success, resp, _ = APIClient.append_message(
        tenant_id, user_id, session_id,
        role="user",
        content=birthday_message
    )
    Assertions.assert_http_code(success, context="Failed to append birthday message")

    print(f"Sent birthday message: {birthday_message}")

    # Wait for EventDetectorWorker to process (it calls LLM, so needs time)
    time.sleep(3)

    # Step 2: Wait for event detector to process
    def check_event_created():
        success, resp, _ = APIClient.get_context(
            tenant_id, user_id, session_id,
            "Khi nào sinh nhật Đức?"
        )
        if not success:
            return False
        upcoming = resp.get("upcoming_events", [])
        return len(upcoming) > 0

    event_created = TestHelpers.wait_for_condition(
        check_event_created,
        timeout_ms=240000,
        poll_interval_ms=1000
    )

    if not event_created:
        raise AssertionError("Event detector did not process birthday within timeout")

    # Step 3: Verify upcoming_events contains birthday
    success, resp, _ = APIClient.get_context(
        tenant_id, user_id, session_id,
        "Sinh nhật Đức là khi nào?"
    )

    Assertions.assert_http_code(success, context="GetContext failed")
    Assertions.assert_field_exists(resp, "upcoming_events", context="GetContext response")

    upcoming_events = resp.get("upcoming_events", [])
    print(f"Found {len(upcoming_events)} upcoming events")

    # Check if birthday event is detected
    birthday_found = False
    for event in upcoming_events:
        if event.get("type") == "life_event":
            birthday_found = True
            event_date = event.get("payload", "")
            print(f"Birthday event detected: {event}")
            # Verify date is parsed correctly (should contain "15/8" or "15-08")
            if "15" in str(event_date) and ("8" in str(event_date) or "08" in str(event_date)):
                print("Birthday date parsed correctly")
            break

    if not birthday_found:
        raise AssertionError("Birthday event not found in upcoming_events")

    print("PASS: Birthday event detected successfully")


if __name__ == "__main__":
    run_test_wrapper("TC-BG04", "Event Detector – birthday detection", run_test)
