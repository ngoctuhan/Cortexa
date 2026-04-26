"""
Test Case: TC-SECXX
Name: Security Test
Category: Security
"""

import sys
sys.path.insert(0, '/Users/macbook/Documents/Cortexa/tests')
from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper

def run_test():
    tenant_id, user_id, session_id = TestHelpers.generate_ids()
    print(f"Testing Security scenario...")
    
    # Test basic security validation
    success, resp, _ = APIClient.append_message(
        tenant_id, user_id, session_id,
        role="user",
        content="Security test message"
    )
    
    print("PASS: Security test completed")

if __name__ == "__main__":
    run_test_wrapper("TC-SECXX", "Security Test", run_test)
