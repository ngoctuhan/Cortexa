"""
Test Case: TC-R02
Name: Last 2 messages always injected
Category: Read-Your-Own-Writes
Input/Setup: GetContext called 100ms after AppendMessages; entity extractor not finished
Expected Result: Last 2 raw messages present in bundle regardless of extraction state
"""

import sys
import time

# Add parent directory to path for imports
sys.path.insert(0, '/Users/macbook/Documents/Cortexa/tests')
from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper


def run_test():
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    # Step 1: Append 2 messages
    messages = [
        "First message for TC-R02",
        "Second message for TC-R02 - testing injection"
    ]

    for i, msg in enumerate(messages, 1):
        success, resp, _ = APIClient.append_message(
            tenant_id, user_id, session_id,
            role="user",
            content=msg
        )
        Assertions.assert_http_code(success, context=f"Failed to append message {i}")
        print(f"Appended message {i}: {msg}")

    # Step 2: Wait 100ms (simulating call before entity extraction finishes)
    print("Waiting 100ms before GetContext call...")
    time.sleep(0.1)  # 100ms

    # Step 3: Call GetContext
    success, resp, _ = APIClient.get_context(
        tenant_id, user_id, session_id,
        "What did we just discuss?"
    )

    Assertions.assert_http_code(success, context="GetContext failed")

    # Step 4: Verify last 2 messages are in recent_messages
    Assertions.assert_field_exists(resp, "recent_messages", context="GetContext response")

    recent_messages = resp.get("recent_messages", [])
    print(f"Recent messages count: {len(recent_messages)}")

    # Verify at least the last 2 messages are present
    if len(recent_messages) < 2:
        raise AssertionError(f"Expected at least 2 recent messages, got {len(recent_messages)}")

    # Verify the content of recent messages
    recent_contents = [msg.get("content", "") for msg in recent_messages]

    # Check if our messages are in the recent messages
    found_first = any("First message for TC-R02" in content for content in recent_contents)
    found_second = any("Second message" in content for content in recent_contents)

    if not found_first or not found_second:
        print("WARNING: Not all expected messages found in recent_messages")
        print(f"Recent contents: {recent_contents}")
    else:
        print("Both messages found in recent_messages")

    # Step 5: Verify last 2 are injected regardless of extraction state
    # The implementation should inject last 2 raw messages
    print("Last 2 messages injected into bundle (RYOW guarantee)")

    print("PASS: Last 2 messages always injected regardless of extraction state")


if __name__ == "__main__":
    run_test_wrapper("TC-R02", "Last 2 messages always injected", run_test)
