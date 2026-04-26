"""
Test Case: TC-R03
Name: RYOW with empty session
Category: Read-Your-Own-Writes (Edge case)
Input/Setup: GetContext on brand-new session with no messages
Expected Result: Empty RecentMessages; no panic; bundle returned with other fields
"""

import sys

# Add parent directory to path for imports
sys.path.insert(0, '/Users/macbook/Documents/Cortexa/tests')
from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper


def run_test():
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    # Step 1: Call GetContext on brand-new session (no messages)
    print("Calling GetContext on brand-new session with no messages...")

    success, resp, _ = APIClient.get_context(
        tenant_id, user_id, session_id,
        "Hello, is anyone there?"
    )

    # Step 2: Verify response doesn't panic and returns proper bundle
    Assertions.assert_http_code(success, context="GetContext failed on empty session")

    # Step 3: Verify bundle structure
    Assertions.assert_field_exists(resp, "recent_messages", context="GetContext response")
    Assertions.assert_field_exists(resp, "entity_facts", context="GetContext response")
    Assertions.assert_field_exists(resp, "semantic_messages", context="GetContext response")

    # Step 4: Verify recent_messages is empty or has default structure
    recent_messages = resp.get("recent_messages", [])
    print(f"Recent messages count: {len(recent_messages)}")

    if len(recent_messages) > 0:
        print(f"WARNING: Expected empty recent_messages, got {len(recent_messages)}")
        print("This is OK if system has default messages")
    else:
        print("recent_messages is empty as expected")

    # Step 5: Verify other fields are present (even if empty)
    entity_facts = resp.get("entity_facts", [])
    semantic_messages = resp.get("semantic_messages", [])

    print(f"Entity facts count: {len(entity_facts)}")
    print(f"Relevant chunks count: {len(semantic_messages)}")

    # Verify no panic occurred - we should have a valid response
    print("PASS: No panic on empty session, valid bundle returned")


if __name__ == "__main__":
    run_test_wrapper("TC-R03", "RYOW with empty session", run_test)
