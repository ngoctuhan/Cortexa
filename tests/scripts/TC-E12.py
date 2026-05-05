"""
Test Case: TC-E12
Name: self_facts field exists in GetContext response
Category: Entity Extraction
Input/Setup: Message: 'Tôi tên là Minh, năm nay 28 tuổi'
Expected Result: GetContext response contains 'self_facts' field (list); after extraction
  self_facts contains at least one fact with entity_type='self' (e.g. name or age)
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
        content="Tôi tên là Minh, năm nay 28 tuổi",
    )
    Assertions.assert_http_code(success, context="Failed to append message")

    print("Waiting for cognitive extraction (up to 120s)...")

    def has_self_fact():
        ok, r, _ = APIClient.get_context(tenant_id, user_id, session_id, "Tôi là ai?")
        if not ok:
            return False
        self_facts = r.get("self_facts", None)
        if self_facts is None:
            return False
        return len(self_facts) > 0

    TestHelpers.wait_for_condition(has_self_fact, timeout_ms=240000, poll_interval_ms=2000)

    success, resp, _ = APIClient.get_context(tenant_id, user_id, session_id, "Tôi là ai?")
    Assertions.assert_http_code(success, context="GetContext failed")

    # self_facts field must exist in the response
    assert "self_facts" in resp, "Response missing 'self_facts' field"
    self_facts = resp["self_facts"]
    assert isinstance(self_facts, list), f"'self_facts' must be a list, got: {type(self_facts)}"

    print(f"self_facts count: {len(self_facts)}")
    for f in self_facts:
        print(f"  - entity_type={f.get('entity_type')} {f.get('attribute')}={f.get('value')}")

    # All self_facts must be entity_type='self'
    non_self = [f for f in self_facts if f.get("entity_type") != "self"]
    assert len(non_self) == 0, f"self_facts contains non-self entity_type entries: {non_self}"

    # At least one fact for name or age
    has_identity = any(
        f.get("attribute") in ("name", "age") for f in self_facts
    )
    assert has_identity, "Expected at least one self_fact with attribute 'name' or 'age'"

    print("PASS: self_facts field present, contains only entity_type='self' facts with identity attributes")


if __name__ == "__main__":
    run_test_wrapper("TC-E12", "self_facts field exists in GetContext response", run_test)
