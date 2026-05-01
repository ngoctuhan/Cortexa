"""
Test Case: TC-E02
Name: Entity upsert – value supersede
Category: Entity Extraction
Input/Setup: Two messages: (1) 'Đức email là: xyz@gmail.com', (2) 'Đức vừa đổi email, email mới của anh ấy là ghz@xyz'
Expected Result: After second message, entity_facts for Đức/email reflects ghz@xyz (old xyz@gmail.com superseded)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper


def run_test():
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    # Step 1: Send initial email
    print("Step 1: Sending initial email message")
    success, _, _ = APIClient.append_message(
        tenant_id, user_id, session_id,
        role="user",
        content="Đức email là : xyz@gmail.com",
    )
    Assertions.assert_http_code(success, context="Failed to append initial message")

    print("Waiting for initial entity extraction (up to 120s)...")

    def has_any_email():
        ok, r, _ = APIClient.get_context(tenant_id, user_id, session_id, "Email của Đức là gì?", memory_types=["entity_facts"])
        if not ok:
            return False
        facts = r.get("entity_facts", [])
        return any(f.get("entity_name") == "Đức" and f.get("attribute") == "email" for f in facts)

    TestHelpers.wait_for_condition(has_any_email, timeout_ms=240000, poll_interval_ms=1500)

    # Step 2: Send updated email
    print("Step 2: Sending updated email message")
    success, _, _ = APIClient.append_message(
        tenant_id, user_id, session_id,
        role="user",
        content="Đức vừa đổi email, email mới của anh ấy là ghz@xyz",
    )
    Assertions.assert_http_code(success, context="Failed to append update message")

    print("Waiting for upsert extraction (up to 120s)...")

    def has_new_email():
        ok, r, _ = APIClient.get_context(tenant_id, user_id, session_id, "Email của Đức là gì?", memory_types=["entity_facts"])
        if not ok:
            return False
        facts = r.get("entity_facts", [])
        email_facts = [f for f in facts if f.get("entity_name") == "Đức" and f.get("attribute") == "email"]
        return len(email_facts) >= 1 and "ghz@xyz" in email_facts[-1].get("value", "")

    TestHelpers.wait_for_condition(has_new_email, timeout_ms=240000, poll_interval_ms=1500)

    # Step 3: Verify new email is in context
    _, resp, _ = APIClient.get_context(tenant_id, user_id, session_id, "Email của Đức là gì?")
    email_facts = [
        f for f in resp.get("entity_facts", [])
        if f.get("entity_name") == "Đức" and f.get("attribute") == "email"
    ]
    assert len(email_facts) >= 1, f"Expected at least 1 email fact for Đức, got {len(email_facts)}"
    assert "ghz@xyz" in email_facts[-1].get("value", ""), (
        f"Expected new email 'ghz@xyz' in latest fact, got: {email_facts[-1].get('value')}"
    )
    print("PASS: Entity upserted successfully — old email superseded by ghz@xyz")


if __name__ == "__main__":
    run_test_wrapper("TC-E02", "Entity upsert – value supersede", run_test)
