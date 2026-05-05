"""
Test Case: TC-E13
Name: self_facts and entity_facts are separated — self not in entity_facts
Category: Entity Extraction
Input/Setup: Two messages:
  (1) 'Tôi tên là Lan'  → entity_type='self'
  (2) 'Bạn tôi Hùng làm kỹ sư'  → entity_type='person'
Expected Result:
  - self_facts contains Lan (entity_type='self')
  - entity_facts does NOT contain any entity_type='self' entry
  - entity_facts contains Hùng (entity_type='person')
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper


def run_test():
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    print("Step 1: Sending self-identity message")
    success, _, _ = APIClient.append_message(
        tenant_id, user_id, session_id,
        role="user",
        content="Tôi tên là Lan",
    )
    Assertions.assert_http_code(success, context="Failed to append self message")

    print("Step 2: Sending third-party entity message")
    success, _, _ = APIClient.append_message(
        tenant_id, user_id, session_id,
        role="user",
        content="Bạn tôi Hùng làm kỹ sư phần mềm",
    )
    Assertions.assert_http_code(success, context="Failed to append third-party message")

    print("Waiting for cognitive extraction (up to 120s)...")

    def has_both():
        ok, r, _ = APIClient.get_context(tenant_id, user_id, session_id, "Hùng làm gì?")
        if not ok:
            return False
        self_facts = r.get("self_facts", [])
        entity_facts = r.get("entity_facts", [])
        has_self = any("lan" in f.get("value", "").lower() for f in self_facts)
        has_hung = any("hùng" in f.get("entity_name", "").lower() or "hung" in f.get("entity_name", "").lower()
                       for f in entity_facts)
        return has_self and has_hung

    TestHelpers.wait_for_condition(has_both, timeout_ms=240000, poll_interval_ms=2000)

    success, resp, _ = APIClient.get_context(tenant_id, user_id, session_id, "Hùng làm gì?")
    Assertions.assert_http_code(success, context="GetContext failed")

    self_facts = resp.get("self_facts", [])
    entity_facts = resp.get("entity_facts", [])

    print(f"self_facts: {[(f.get('entity_type'), f.get('attribute'), f.get('value')) for f in self_facts]}")
    print(f"entity_facts: {[(f.get('entity_name'), f.get('entity_type'), f.get('attribute')) for f in entity_facts]}")

    # entity_facts must not contain any entity_type='self' entry
    self_in_entity = [f for f in entity_facts if f.get("entity_type") == "self"]
    assert len(self_in_entity) == 0, (
        f"entity_facts contains entity_type='self' entries that should be in self_facts: {self_in_entity}"
    )

    # self_facts should contain user's name
    has_lan = any("lan" in f.get("value", "").lower() for f in self_facts)
    assert has_lan, "self_facts does not contain user name 'Lan'"

    # entity_facts should contain Hùng
    has_hung = any(
        "hùng" in f.get("entity_name", "").lower() or "hung" in f.get("entity_name", "").lower()
        for f in entity_facts
    )
    assert has_hung, "entity_facts does not contain third-party entity 'Hùng'"

    print("PASS: self_facts and entity_facts correctly separated — no self entries in entity_facts")


if __name__ == "__main__":
    run_test_wrapper("TC-E13", "self_facts and entity_facts are separated", run_test)
