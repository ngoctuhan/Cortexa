"""
Test Case: TC-E14
Name: "Who am I" — LLM context contains correct user identity from self_facts
Category: Entity Extraction
Input/Setup: Message: 'Tôi tên là Phong, 30 tuổi, làm bác sĩ'
  Also add a third-party entity to pollute context: 'Bạn tôi Hà tên đầy đủ là Nguyễn Thị Hà'
Expected Result:
  - self_facts contains user's name 'Phong'
  - entity_facts does NOT contain entity_type='self' with name 'Phong'
  - self_facts appears in response (so LLM can correctly answer "who am I" = Phong, not Hà)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper


def run_test():
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    print("Step 1: Send self-identity message")
    success, _, _ = APIClient.append_message(
        tenant_id, user_id, session_id,
        role="user",
        content="Tôi tên là Phong, 30 tuổi, làm bác sĩ",
    )
    Assertions.assert_http_code(success, context="Failed to append self message")

    print("Step 2: Send third-party entity message (potential confusion source)")
    success, _, _ = APIClient.append_message(
        tenant_id, user_id, session_id,
        role="user",
        content="Bạn tôi Hà tên đầy đủ là Nguyễn Thị Hà",
    )
    Assertions.assert_http_code(success, context="Failed to append third-party message")

    print("Waiting for cognitive extraction (up to 120s)...")

    def has_phong_in_self():
        ok, r, _ = APIClient.get_context(tenant_id, user_id, session_id, "Tôi là ai? Tên tôi là gì?")
        if not ok:
            return False
        self_facts = r.get("self_facts", [])
        return any("phong" in f.get("value", "").lower() for f in self_facts)

    TestHelpers.wait_for_condition(has_phong_in_self, timeout_ms=240000, poll_interval_ms=2000)

    success, resp, _ = APIClient.get_context(
        tenant_id, user_id, session_id, "Tôi là ai? Tên tôi là gì?"
    )
    Assertions.assert_http_code(success, context="GetContext failed")

    self_facts = resp.get("self_facts", [])
    entity_facts = resp.get("entity_facts", [])

    print(f"self_facts: {[(f.get('attribute'), f.get('value'), f.get('entity_type')) for f in self_facts]}")

    # 1. self_facts must contain 'Phong'
    has_phong_self = any("phong" in f.get("value", "").lower() for f in self_facts)
    assert has_phong_self, (
        f"self_facts does not contain user name 'Phong'. Got: {[(f.get('attribute'), f.get('value')) for f in self_facts]}"
    )

    # 2. entity_facts must NOT contain entity_type='self' with 'Phong'
    phong_in_entity = [
        f for f in entity_facts
        if f.get("entity_type") == "self" and "phong" in f.get("value", "").lower()
    ]
    assert len(phong_in_entity) == 0, (
        f"'Phong' self-fact leaked into entity_facts: {phong_in_entity}"
    )

    # 3. Verify self_facts contains all entity_type='self'
    non_self = [f for f in self_facts if f.get("entity_type") != "self"]
    assert len(non_self) == 0, f"self_facts contains non-self entities: {non_self}"

    print("PASS: self_facts correctly identifies user as 'Phong'; not mixed with third-party 'Hà'")


if __name__ == "__main__":
    run_test_wrapper("TC-E14", "Who am I — user identity from self_facts", run_test)
