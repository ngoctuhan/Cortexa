"""
Test Case: TC-R01
Name: Immediate recall after write
Category: Read-Your-Own-Writes
Input/Setup: User says 'email Đức là duc@gmail.com'; immediately asks 'email Đức?'
Expected Result: ContextBundle.RecentMessages contains the fact; entity_mentions extraction may not be done yet but answer is still correct
"""

import sys, os as _os
sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import time

# Add parent directory to path for imports

from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper


def run_test():
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    # Step 1: User says 'email Đức là duc@gmail.com'
    print("Step 1: User says 'email Đức là duc@gmail.com'")
    success, resp, _ = APIClient.append_message(
        tenant_id, user_id, session_id,
        role="user",
        content="email Đức là duc@gmail.com"
    )

    Assertions.assert_http_code(success, context="Failed to append message about email")

    # Step 2: Immediately ask 'email Đức?' (before entity extraction finishes)
    print("Step 2: Immediately ask 'email Đức?' (testing RYOW)")

    # Wait a very short time (simulating immediate query)
    time.sleep(0.01)  # 10ms

    success, resp, duration = APIClient.get_context(
        tenant_id, user_id, session_id,
        "email Đức?"
    )

    Assertions.assert_http_code(success, context="GetContext failed")

    # Step 3: Verify recent_messages contains the fact
    Assertions.assert_field_exists(resp, "recent_messages", context="GetContext response")

    recent_messages = resp.get("recent_messages", [])
    print(f"Recent messages count: {len(recent_messages)}")

    # Verify the message is in recent_messages
    found = False
    for msg in recent_messages:
        content = msg.get("content", "")
        if "duc@gmail.com" in content.lower():
            found = True
            print(f"Found email in recent_messages: {content}")
            break

    if not found:
        raise AssertionError("Email fact not found in recent_messages (RYOW failed)")

    # Step 4: The answer should be correct even if entity extraction isn't done
    # entity_facts may or may not be populated yet, but recent_messages should have it
    entity_facts = resp.get("entity_facts", [])
    print(f"Entity facts count: {len(entity_facts)}")

    if len(entity_facts) == 0:
        print("Entity extraction not complete yet (expected for RYOW)")
    else:
        print("Entity extraction completed quickly")

    print("PASS: Immediate recall works - fact available in recent_messages")


if __name__ == "__main__":
    run_test_wrapper("TC-R01", "Immediate recall after write", run_test)
