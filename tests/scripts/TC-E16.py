"""
Test Case: TC-E16
Name: UserProfile.CanonicalName derived from self-facts (not hardcoded 'User')
Category: Entity / Profile
Input/Setup:
  - Send message "Tôi tên là Quân, tôi 25 tuổi, tôi làm lập trình viên"
  - Wait for cognitive extraction
  - GET /v1/context with query "Tôi là ai?"
Expected Result:
  - self_facts contains attribute='name' with value containing 'Quân' (real name, not hardcoded)
  - self_facts contains attribute='age' with value '25'
  - self_facts contains attribute='job' or similar
  - No fact has value = 'User' (the old hardcoded stub)
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
        content="Tôi tên là Quân, tôi 25 tuổi, tôi làm lập trình viên",
    )
    Assertions.assert_http_code(success, context="Failed to append message")

    print("Waiting for cognitive extraction (up to 120s)...")

    def has_name_fact():
        ok, r, _ = APIClient.get_context(tenant_id, user_id, session_id, "Tôi là ai?")
        if not ok:
            return False
        self_facts = r.get("self_facts", [])
        return any(f.get("attribute") == "name" for f in self_facts)

    TestHelpers.wait_for_condition(has_name_fact, timeout_ms=240000, poll_interval_ms=2000)

    success, resp, _ = APIClient.get_context(tenant_id, user_id, session_id, "Tôi là ai?")
    Assertions.assert_http_code(success, context="GetContext failed")

    self_facts = resp.get("self_facts", [])
    assert len(self_facts) > 0, "self_facts must not be empty after extraction"

    # Name must be real user name, not the hardcoded 'User' stub
    name_facts = [f for f in self_facts if f.get("attribute") == "name"]
    assert len(name_facts) > 0, "Expected a self_fact with attribute='name'"
    canonical_name = name_facts[0].get("value", "")
    print(f"  canonical_name: '{canonical_name}'")
    assert canonical_name.strip() != "", "CanonicalName must not be empty"
    assert canonical_name.lower() != "user", (
        f"CanonicalName must not be the hardcoded stub 'User', got: '{canonical_name}'"
    )
    assert "qu" in canonical_name.lower() or "quân" in canonical_name.lower(), (
        f"Expected name to contain 'Quân', got: '{canonical_name}'"
    )

    # Age fact
    age_facts = [f for f in self_facts if f.get("attribute") == "age"]
    assert len(age_facts) > 0, "Expected a self_fact with attribute='age'"
    assert "25" in age_facts[0].get("value", ""), (
        f"Expected age to contain '25', got: '{age_facts[0].get('value')}'"
    )

    print(f"  self_facts ({len(self_facts)} total):")
    for f in self_facts:
        print(f"    attribute={f.get('attribute')} value={f.get('value')}")

    print("PASS: UserProfile.CanonicalName is real user name from self-facts, not hardcoded 'User'")


if __name__ == "__main__":
    run_test_wrapper("TC-E16", "UserProfile.CanonicalName derived from self-facts", run_test)
