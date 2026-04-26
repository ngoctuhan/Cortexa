"""
Test Case: TC-E05
Name: Temporal update – supersede
Category: Entity Extraction
Input/Setup: Two messages: (1) establish Đức email as old@gmail.com, (2) 'Đức đổi email thành newemail@gmail.com'
Expected Result: entity_facts reflect newemail@gmail.com (old fact superseded)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper


def run_test():
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    # Step 1: Establish initial email
    print("Step 1: Sending initial email message")
    success, _, _ = APIClient.append_message(
        tenant_id, user_id, session_id,
        role="user",
        content="Đức nói email của anh ấy là old@gmail.com",
    )
    Assertions.assert_http_code(success, context="Failed to append initial message")

    print("Waiting for initial extraction (up to 90s)...")

    def has_old_email():
        ok, r, _ = APIClient.get_context(tenant_id, user_id, session_id, "email của Đức?")
        if not ok:
            return False
        return any(
            "đức" in f.get("entity_name", "").lower() and "email" in f.get("attribute", "").lower()
            for f in r.get("entity_facts", [])
        )

    TestHelpers.wait_for_condition(has_old_email, timeout_ms=180000, poll_interval_ms=2000)

    # Step 2: Send update – supersede the email
    print("Step 2: Sending email update message")
    success, _, _ = APIClient.append_message(
        tenant_id, user_id, session_id,
        role="user",
        content="Đức đổi email thành newemail@gmail.com",
    )
    Assertions.assert_http_code(success, context="Failed to append update message")

    print("Waiting for supersede extraction (up to 90s)...")

    def has_new_email():
        ok, r, _ = APIClient.get_context(tenant_id, user_id, session_id, "email của Đức?")
        if not ok:
            return False
        facts = [
            f for f in r.get("entity_facts", [])
            if "đức" in f.get("entity_name", "").lower() and "email" in f.get("attribute", "").lower()
        ]
        return any("newemail@gmail.com" in f.get("value", "") for f in facts)

    TestHelpers.wait_for_condition(has_new_email, timeout_ms=180000, poll_interval_ms=2000)

    # Step 3: Verify latest email fact reflects the new value
    _, resp, _ = APIClient.get_context(tenant_id, user_id, session_id, "email của Đức?")
    email_facts = [
        f for f in resp.get("entity_facts", [])
        if "đức" in f.get("entity_name", "").lower() and "email" in f.get("attribute", "").lower()
    ]

    assert any("newemail@gmail.com" in f.get("value", "") for f in email_facts), (
        f"Expected 'newemail@gmail.com' in entity_facts after supersede, got: {email_facts}"
    )
    print("PASS: Email superseded — new value 'newemail@gmail.com' confirmed")
    for f in email_facts:
        print(f"  - {f.get('entity_name')}/{f.get('attribute')}={f.get('value')}")


if __name__ == "__main__":
    run_test_wrapper("TC-E05", "Temporal update – supersede", run_test)
