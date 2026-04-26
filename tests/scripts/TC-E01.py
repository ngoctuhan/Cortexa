"""
Test Case: TC-E01
Name: Basic entity extraction
Category: Entity Extraction
Input/Setup: Message: 'Đức nói email của nó là duc@gmail.com'
Expected Result: entity_facts contains entity_name='Đức', attribute='email', value='duc@gmail.com'; confidence>=0.9
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper


def run_test():
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    print("Step 1: Sending message")
    success, _, _ = APIClient.append_message(
        tenant_id, user_id, session_id,
        role="user",
        content="Đức nói email của nó là duc@gmail.com",
    )
    Assertions.assert_http_code(success, context="Failed to append message with entity")

    print("Waiting for entity extraction (up to 120s)...")

    def has_duc_email():
        ok, r, _ = APIClient.get_context(tenant_id, user_id, session_id, "email của Đức là gì?")
        if not ok:
            return False
        for fact in r.get("entity_facts", []):
            name = fact.get("entity_name", "")
            attr = fact.get("attribute", "").lower()
            val  = fact.get("value", "").lower()
            if ("đức" in name.lower() or "duc" in name.lower()) and "email" in attr and "duc@gmail.com" in val:
                return True
        return False

    TestHelpers.wait_for_condition(has_duc_email, timeout_ms=240000, poll_interval_ms=2000)

    success, resp, _ = APIClient.get_context(tenant_id, user_id, session_id, "email của Đức là gì?")
    Assertions.assert_http_code(success, context="GetContext failed")
    Assertions.assert_field_exists(resp, "entity_facts", context="GetContext response")

    entity_facts = resp.get("entity_facts", [])
    found = False
    for fact in entity_facts:
        name = fact.get("entity_name", "")
        attr = fact.get("attribute", "").lower()
        val  = fact.get("value", "").lower()
        if ("đức" in name.lower() or "duc" in name.lower()) and "email" in attr and "duc@gmail.com" in val:
            confidence = fact.get("confidence", 0)
            print(f"Found entity: {name}/{fact['attribute']}={fact['value']} (confidence={confidence})")
            assert confidence >= 0.9, f"Confidence {confidence} < required 0.9"
            found = True
            break

    assert found, "Entity 'Đức/email/duc@gmail.com' not found in entity_facts after waiting"
    print("PASS: Entity extracted with confidence >= 0.9")


if __name__ == "__main__":
    run_test_wrapper("TC-E01", "Basic entity extraction", run_test)
