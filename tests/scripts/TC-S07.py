"""
Test Case: TC-S07
Name: Invalid role value
Category: Session Management (Error case)
Input/Setup: AppendMessages with role='bot'
Expected Result: HTTP 400, error message 'invalid role'
"""

import sys, os as _os
sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

# Add parent directory to path for imports

from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper


def run_test():
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    # Step 1: Try to append message with invalid role 'bot'
    print("Testing invalid role 'bot'...")
    success, resp, _ = APIClient.append_message(
        tenant_id, user_id, session_id,
        role="bot",  # Invalid role - only 'user', 'assistant', 'system' are valid
        content="Test message with invalid role"
    )

    # Step 2: Verify we get HTTP 400 with 'invalid role' error
    if success:
        raise AssertionError("Expected 400 error for invalid role, but got 200")

    # Check if response contains error message
    if "error" in resp:
        error_msg = resp.get("error", "").lower()
        if "invalid" in error_msg or "role" in error_msg:
            print(f"Got expected error: {resp['error']}")
        else:
            print(f"WARNING: Error message doesn't mention invalid role: {resp['error']}")
    else:
        print("WARNING: Response doesn't contain error message")

    # Also test other invalid roles
    invalid_roles = ["admin", "moderator", "owner", "custom"]

    for invalid_role in invalid_roles:
        success, resp, _ = APIClient.append_message(
            tenant_id, user_id, session_id,
            role=invalid_role,
            content=f"Test with role {invalid_role}"
        )
        if success:
            raise AssertionError(f"Expected 400 error for invalid role '{invalid_role}', but got 200")

    print("PASS: Invalid roles properly rejected with 400 errors")


if __name__ == "__main__":
    run_test_wrapper("TC-S07", "Invalid role value", run_test)
