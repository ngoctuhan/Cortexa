"""
Test Case: TC-E04
Name: Name variant normalization
Category: Entity Extraction
Input/Setup: Message: 'Số điện thoại anh Đức là 0912345678'
Expected Result: entity_name='Đức' (honorific 'anh' stripped), not 'anh Đức'
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper


def run_test():
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    print("Step 1: Sending message 'Số điện thoại anh Đức là 0912345678'")
    success, _, _ = APIClient.append_message(
        tenant_id, user_id, session_id,
        role="user",
        content="Số điện thoại anh Đức là 0912345678",
    )
    Assertions.assert_http_code(success, context="Failed to append message")

    print("Waiting for entity extraction (up to 90s)...")

    def has_phone_entity():
        ok, r, _ = APIClient.get_context(tenant_id, user_id, session_id, "Số điện thoại Đức là gì?")
        if not ok:
            return False
        facts = r.get("entity_facts", [])
        return any("0912345678" in f.get("value", "") for f in facts)

    TestHelpers.wait_for_condition(has_phone_entity, timeout_ms=180000, poll_interval_ms=2000)

    success, resp, _ = APIClient.get_context(tenant_id, user_id, session_id, "Số điện thoại Đức là gì?")
    Assertions.assert_http_code(success, context="GetContext failed")
    Assertions.assert_field_exists(resp, "entity_facts", context="GetContext response")

    entity_facts = resp.get("entity_facts", [])
    phone_facts = [f for f in entity_facts if "0912345678" in f.get("value", "")]

    assert len(phone_facts) >= 1, "Expected at least one fact with value '0912345678'"

    for fact in phone_facts:
        entity_name = fact.get("entity_name", "")
        print(f"  - entity_name={entity_name!r}, attribute={fact.get('attribute')}, value={fact.get('value')}")
        assert "anh" not in entity_name.lower(), (
            f"Honorific 'anh' not stripped: got '{entity_name}', expected 'Đức'"
        )
        assert "đức" in entity_name.lower() or "duc" in entity_name.lower(), (
            f"Expected entity_name to contain 'Đức', got '{entity_name}'"
        )

    print("PASS: entity_name normalised — honorific stripped correctly")


if __name__ == "__main__":
    run_test_wrapper("TC-E04", "Name variant normalization", run_test)
