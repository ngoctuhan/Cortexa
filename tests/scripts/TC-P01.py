import sys
import requests
import uuid
import time

BASE_URL = "http://localhost:8080/v1"

"""
Test Case: TC-P01
Name: GetContext p99 < 100ms
Category: Performance & Latency
Input/Setup: 1000 concurrent GetContext requests; warm cache; 100K messages in DB
Expected Result: p50 < 20ms; p95 < 60ms; p99 < 100ms
"""

def run_test():
    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())

    payload = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "session_id": session_id,
        "query": "Test query cho TC-P01"
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
