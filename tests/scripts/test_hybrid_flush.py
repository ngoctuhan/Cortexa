import sys
import os
import time
import requests
import uuid

# Set COGNITIVE_BATCH_SIZE=10 in environment if not already set,
# or assume the default is 10. We will test sending < 10 messages,
# then creating a new session to trigger the flush.

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_utils import APIClient, BASE_URL

def test_hybrid_flush():
    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    session_1 = str(uuid.uuid4())

    print(f"Tenant ID: {tenant_id}")
    print(f"User ID: {user_id}")
    
    # 1. Create Session 1
    resp = requests.post(f"{BASE_URL}/sessions", json={
        "tenant_id": tenant_id,
        "user_id": user_id,
        "title": "Session 1"
    })
    session_1 = resp.json()["id"]
    print(f"Created Session 1: {session_1}")

    # 2. Append 3 messages to Session 1 (less than the default batch size of 10)
    for i in range(3):
        APIClient.append_message(
            tenant_id, user_id, session_1, "user",
            f"My favorite color is blue. This is message {i+1}."
        )
    print("Appended 3 messages to Session 1. No cognitive extraction should have happened yet.")

    # Wait a bit to ensure it didn't flush
    time.sleep(2)

    # 3. Create Session 2
    # This should trigger the flushPreviousUserSessions for Session 1
    print("Creating Session 2 (should trigger flush for Session 1)...")
    resp = requests.post(f"{BASE_URL}/sessions", json={
        "tenant_id": tenant_id,
        "user_id": user_id,
        "title": "Session 2"
    })
    session_2 = resp.json()["id"]
    print(f"Created Session 2: {session_2}")

    print("Waiting 5 seconds for the async cognitive worker to process the flushed batch...")
    time.sleep(5)

    # 4. Check Context to see if the fact "favorite color is blue" was extracted
    success, resp_data, _ = APIClient.get_context(
        tenant_id, user_id, str(uuid.uuid4()), "What is my favorite color?"
    )
    
    if success:
        facts = resp_data.get("entity_facts", []) or []
        persona = resp_data.get("persona_context", []) or []
        
        print("\n--- Extracted Data ---")
        print(f"Facts: {facts}")
        print(f"Persona: {persona}")
        
        if len(facts) > 0 or len(persona) > 0:
            print("\nSUCCESS! The data was successfully flushed and extracted.")
        else:
            print("\nFAILED! No data was extracted. The flush may not have worked.")
    else:
        print(f"Failed to get context: {resp_data}")

if __name__ == "__main__":
    test_hybrid_flush()
