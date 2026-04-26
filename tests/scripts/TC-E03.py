"""
Test Case: TC-E03
Name: Self-reference pronoun – Tôi
Category: Entity Extraction
Input/Setup: Message: 'Tôi đang làm ở Grab'
Expected Result: entity_facts contain a workplace entity with value 'Grab'
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper


def run_test():
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    print("Step 1: Sending message 'Tôi đang làm ở Grab'")
    success, _, _ = APIClient.append_message(
        tenant_id, user_id, session_id,
        role="user",
        content="Tôi đang làm ở Grab",
    )
    Assertions.assert_http_code(success, context="Failed to append message")

    print("Waiting for entity extraction (up to 90s)...")

    def has_grab_entity():
        ok, r, _ = APIClient.get_context(tenant_id, user_id, session_id, "Tôi làm ở đâu?")
        if not ok:
            return False
        facts = r.get("entity_facts", [])
        return any("grab" in f.get("value", "").lower() for f in facts)

    TestHelpers.wait_for_condition(has_grab_entity, timeout_ms=180000, poll_interval_ms=2000)

    success, resp, _ = APIClient.get_context(tenant_id, user_id, session_id, "Tôi làm ở đâu?")
    Assertions.assert_http_code(success, context="GetContext failed")
    Assertions.assert_field_exists(resp, "entity_facts", context="GetContext response")

    entity_facts = resp.get("entity_facts", [])
    grab_facts = [f for f in entity_facts if "grab" in f.get("value", "").lower()]
    assert len(grab_facts) >= 1, "Expected at least one entity fact with value containing 'Grab'"

    for fact in grab_facts:
        print(f"  - {fact.get('entity_name')}/{fact.get('attribute')}={fact.get('value')}")

    print("PASS: Workplace entity 'Grab' extracted")


if __name__ == "__main__":
    run_test_wrapper("TC-E03", "Self-reference pronoun – Tôi", run_test)
