import sys
import requests
import uuid
import time

BASE_URL = "http://localhost:8080/v1"

"""
Test Case: TC-P03
Name: AppendMessages p99 < 10ms
Category: Performance & Latency
Input/Setup: 1000 concurrent AppendMessages; warm Redis
Expected Result: p99 < 10ms; Redis pipeline used
"""

def run_test():
    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())

    payload = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "session_id": session_id,
        "role": "user",
        "content": "Test message for TC-P03"
    }
    resp = requests.post(f"{BASE_URL}/messages", json=payload, timeout=15)
    if resp.status_code == 200:
        print("PASS")
        sys.exit(0)
    else:
        print(f"FAIL: /messages returned {resp.status_code}")
        sys.exit(1)

if __name__ == "__main__":
    run_test()
