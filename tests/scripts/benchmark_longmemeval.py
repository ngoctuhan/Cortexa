#!/usr/bin/env python3
import json
import uuid
import time
import os
import sys

# Add the parent directory to the path so we can import test_utils
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_utils import APIClient, TestHelpers

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'data', 'longmemeval_s_cleaned.json')

def run_benchmark(num_records=2):
    print(f"Loading dataset from {DATA_FILE}...")
    try:
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error loading dataset: {e}")
        return

    print(f"Dataset loaded. Total records: {len(data)}")
    records = data[:num_records]

    for i, rec in enumerate(records):
        print(f"\n--- Processing Record {i+1}/{num_records} ---")
        q_id = rec.get('question_id', 'unknown')
        question = rec.get('question', '')
        answer = rec.get('answer', '')
        sessions = rec.get('haystack_sessions', [])
        session_ids = rec.get('haystack_session_ids', [])

        tenant_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())

        print(f"Question ID: {q_id}")
        print(f"Tenant ID: {tenant_id}")
        print(f"User ID: {user_id}")
        print(f"Total sessions in haystack: {len(sessions)}")

        # Create a mapping for session IDs to UUIDs
        session_id_map = {}
        for s_id in session_ids:
            session_id_map[s_id] = str(uuid.uuid4())

        # Ingest messages
        total_messages = 0
        for s_idx, session in enumerate(sessions):
            orig_s_id = session_ids[s_idx] if s_idx < len(session_ids) else f"sess_{s_idx}"
            cortexa_s_id = session_id_map.get(orig_s_id, str(uuid.uuid4()))
            
            print(f"  Ingesting session {s_idx+1}/{len(sessions)} (ID: {cortexa_s_id}) with {len(session)} messages...")
            for m_idx, msg in enumerate(session):
                role = msg.get('role', 'user')
                content = msg.get('content', '')
                
                # Some messages might be very large, limit content if necessary or let Cortexa handle it
                success, resp, _ = APIClient.append_message(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    session_id=cortexa_s_id,
                    role=role,
                    content=content
                )
                if not success:
                    print(f"    Failed to append message {m_idx}: {resp}")
                total_messages += 1
                
        print(f"Finished ingesting {total_messages} messages for this record.")
        
        # Wait for Cortexa workers to process (embedder & cognitive)
        # Note: Depending on the load, this could take a while. We sleep to give it a chance.
        print("Waiting for async workers to process memories (sleeping 30 seconds)...")
        time.sleep(30)
        
        # Query context
        print("\nQuerying context...")
        success, resp, duration = APIClient.get_context(
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=str(uuid.uuid4()), # Use a new session for the query
            query=question
        )
        
        if success:
            print(f"Context retrieved in {duration:.2f}ms")
            context_text = resp.get("context", "")
            print(f"\n[Question]: {question}")
            print(f"[Expected Answer]: {answer[:200]}...")
            print(f"[Retrieved Context Snippet]:\n{context_text}\n")
            
            # Here we could pass the context_text + question to an LLM to generate the final answer
            # and evaluate it against the expected answer.
        else:
            print(f"Failed to retrieve context: {resp}")

if __name__ == "__main__":
    # Ensure cortexa is running before executing this
    run_benchmark(num_records=1)
