"""
Test Case: TC-E06
Name: NOOP – same value
Category: Entity Extraction
Input/Setup: Same message 'Đức nói email của nó là duc@gmail.com' sent twice
Expected Result: exactly 1 email entity fact for Đức (no duplicate created on re-send)
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper


def run_test():
    tenant_id, user_id, session_id = TestHelpers.generate_ids()
    msg = "Đức nói email của nó là duc@gmail.com"

    # Step 1: Send message first time
    print("Step 1: Sending message first time")
    success, _, _ = APIClient.append_message(
        tenant_id, user_id, session_id,
        role="user",
        content=msg,
    )
    Assertions.assert_http_code(success, context="Failed to append first message")

    print("Waiting for initial extraction (up to 90s)...")

    def has_email():
        ok, r, _ = APIClient.get_context(tenant_id, user_id, session_id, "email của Đức?")
        if not ok:
            return False
        return any(
            "đức" in f.get("entity_name", "").lower() and "email" in f.get("attribute", "").lower()
            for f in r.get("entity_facts", [])
        )

    TestHelpers.wait_for_condition(has_email, timeout_ms=180000, poll_interval_ms=2000)

    # Step 2: Send same message again
    print("Step 2: Sending same message a second time")
    success, _, _ = APIClient.append_message(
        tenant_id, user_id, session_id,
        role="user",
        content=msg,
    )
    Assertions.assert_http_code(success, context="Failed to append second message")

    # Brief wait for the second extraction to process
    time.sleep(5)

    # Step 3: Verify no duplicate fact created
    _, resp, _ = APIClient.get_context(tenant_id, user_id, session_id, "email của Đức?")
    email_facts = [
        f for f in resp.get("entity_facts", [])
        if "đức" in f.get("entity_name", "").lower()
        and "email" in f.get("attribute", "").lower()
        and "duc@gmail.com" in f.get("value", "")
    ]

    assert len(email_facts) == 1, (
        f"Expected exactly 1 email fact for Đức (no duplicate on same value), got {len(email_facts)}: {email_facts}"
    )
    print("PASS: No duplicate created — exactly 1 email fact for Đức/email=duc@gmail.com")


if __name__ == "__main__":
    run_test_wrapper("TC-E06", "NOOP – same value", run_test)
