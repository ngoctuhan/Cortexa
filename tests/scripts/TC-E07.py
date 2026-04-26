"""
Test Case: TC-E07
Name: No extractable entities
Category: Entity Extraction
Input/Setup: Message: 'Hôm nay trời đẹp quá'
Expected Result: no entity_facts extracted (message has no named entities or attributes)
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper


def run_test():
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    print("Step 1: Sending message 'Hôm nay trời đẹp quá'")
    success, _, _ = APIClient.append_message(
        tenant_id, user_id, session_id,
        role="user",
        content="Hôm nay trời đẹp quá",
    )
    Assertions.assert_http_code(success, context="Failed to append message")

    # Wait long enough for the cognitive worker to attempt extraction,
    # then assert no entity facts were produced.
    print("Waiting 20s for worker to process message...")
    time.sleep(20)

    success, resp, _ = APIClient.get_context(
        tenant_id, user_id, session_id,
        "What entities were mentioned?",
    )
    Assertions.assert_http_code(success, context="GetContext failed")
    Assertions.assert_field_exists(resp, "entity_facts", context="GetContext response")

    entity_facts = resp.get("entity_facts", [])
    print(f"Entity facts count: {len(entity_facts)}")
    for fact in entity_facts:
        print(f"  - {fact.get('entity_name')}/{fact.get('attribute')}={fact.get('value')}")

    assert len(entity_facts) == 0, (
        f"Expected no entity facts for a weather message, got {len(entity_facts)}: {entity_facts}"
    )
    print("PASS: No entity facts extracted from weather message")


if __name__ == "__main__":
    run_test_wrapper("TC-E07", "No extractable entities", run_test)
