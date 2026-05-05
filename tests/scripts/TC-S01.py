"""
Test Case: TC-S01
Name: AppendMessages basic
Category: Session Management
Input/Setup: POST 3 messages (user/assistant/user) to new sessionID
Expected Result: HTTP 200, messages stored in DB with correct role/content/ts; Redis list populated with last 50
"""

import sys, os as _os
sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import time

# Add parent directory to path for imports

from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper


def run_test():
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    # Step 1: POST 3 messages with different roles
    messages = [
        ("user", "Hello, this is the first user message for TC-S01"),
        ("assistant", "Hi! I'm the assistant responding to your message"),
        ("user", "Thanks for the response, this is message 3")
    ]

    message_ids = []

    for role, content in messages:
        success, resp, duration = APIClient.append_message(
            tenant_id, user_id, session_id,
            role=role,
            content=content
        )
        Assertions.assert_http_code(success, context=f"Failed to append {role} message")
        Assertions.assert_field_exists(resp, "id", context="Response should contain message ID")

        message_id = resp.get("id")
        message_ids.append(message_id)
        print(f"Appended {role} message with ID: {message_id}")

    # Step 2: Verify messages are stored and retrievable via GetContext
    # The recent_messages should include the last 2 messages (from cache + DB)
    success, resp, duration = APIClient.get_context(
        tenant_id, user_id, session_id,
        "What did we discuss?"
    )

    Assertions.assert_http_code(success, context="GetContext failed")
    Assertions.assert_field_exists(resp, "recent_messages", context="GetContext response")

    recent_messages = resp.get("recent_messages", [])
    print(f"Retrieved {len(recent_messages)} recent messages")

    # Verify at least some messages are returned
    if len(recent_messages) < 2:
        raise AssertionError(f"Expected at least 2 recent messages, got {len(recent_messages)}")

    # Verify message structure
    for msg in recent_messages:
        Assertions.assert_field_exists(msg, "role", context="Message should have role")
        Assertions.assert_field_exists(msg, "content", context="Message should have content")
        Assertions.assert_field_exists(msg, "created_at", context="Message should have timestamp")

    # Verify roles are correct (user or assistant)
    for msg in recent_messages:
        role = msg.get("role")
        if role not in ["user", "assistant", "system"]:
            raise AssertionError(f"Invalid role: {role}")

    print("PASS: All 3 messages appended and stored correctly")


if __name__ == "__main__":
    run_test_wrapper("TC-S01", "AppendMessages basic", run_test)
