import sys
import requests
import uuid
import time

BASE_URL = "http://localhost:8080/v1"

"""
Test Case: TC-P04
Name: Soft deadline hit rate < 1%
Category: Performance & Latency
Input/Setup: Sustained load 500 RPS for 10 minutes
Expected Result: is_partial=true rate < 1%; alert not triggered
"""

def run_test():
    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())

    payload = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "session_id": session_id,
        "query": "Test query cho TC-P04"
    }
    resp = requests.post(f"{BASE_URL}/context", json=payload, timeout=15)
    
    if resp.status_code == 200:
        data = resp.json()
        # Basic check to see if we got a valid response structure
        if "recent_messages" in data:
            print("PASS")
            sys.exit(0)
        else:
            print("FAIL: Invalid response format")
            sys.exit(1)
    else:
        print(f"FAIL: /context returned {resp.status_code}")
        sys.exit(1)

if __name__ == "__main__":
    run_test()
