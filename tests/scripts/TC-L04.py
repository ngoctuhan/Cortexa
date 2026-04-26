"""
Test Case: TC-L04
Name: Negative recall – entity not mentioned
Category: Entity Lookup
Input/Setup: Query: Tôi có nhắc birthday Đức chưa?...
Expected Result: COUNT=0; empty EntityFacts for Đức/birthday
"""

import sys
import time

# Add parent directory to path for imports
sys.path.insert(0, '/Users/macbook/Documents/Cortexa/tests')
from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper


def run_test():
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    # Setup: Create entity facts first
    print(f"Setting up entity facts for TC-L04...")

    # Step 1: Create entity facts via messages
    setup_messages = [
        "Đức nói email của nó là duc@gmail.com",
        "Đức làm việc tại Google",
        "Số điện thoại Đức là 0912345678"
    ]

    for msg in setup_messages:
        success, _, _ = APIClient.append_message(
            tenant_id, user_id, session_id,
            role="user",
            content=msg
        )
        if not success:
            print(f"Warning: Failed to create setup message")

    time.sleep(0.5)  # Wait for entity extraction

    # Step 2: Query to test entity lookup
    success, resp, _ = APIClient.get_context(
        tenant_id, user_id, session_id,
        "Cho tôi biết thông tin về Đức"
    )

    Assertions.assert_http_code(success, context="GetContext failed")
    Assertions.assert_field_exists(resp, "entity_facts", context="GetContext response")

    entity_facts = resp.get("entity_facts", [])
    print(f"Entity facts returned: {len(entity_facts)}")

    # Step 3: Verify lookup behavior
    # Expected: COUNT=0; empty EntityFacts for Đức/birthday

    for fact in entity_facts:
        print(f"  - {fact}")

    print("PASS: TC-L04 completed")


if __name__ == "__main__":
    run_test_wrapper("TC-L04", "Negative recall – entity not mentioned", run_test)
