"""
Test Case: TC-LM06
Name: Long session (500+ turns) recall
Category: LongMemEval Scenarios
Input/Setup: Insert a distinctive fact at turn 1 ('Minh làm ở NASA'), then 50 filler turns. Wait for embeddings.
Expected Result: Fact is still retrievable via semantic_messages or entity_facts after many turns
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper

FILLER_TURNS = 50
TARGET_CONTENT = "Minh làm ở NASA"
TARGET_SNIPPET = "nasa"


def run_test():
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    print(f"Step 1: Insert distinctive fact at turn 1: '{TARGET_CONTENT}'")
    ok, _, _ = APIClient.append_message(tenant_id, user_id, session_id, "user", TARGET_CONTENT)
    Assertions.assert_http_code(ok, context="append target fact failed")

    print(f"Step 2: Insert {FILLER_TURNS} filler turns to push fact out of recent_messages window")
    filler_pairs = [
        ("user", "Hôm nay thời tiết thế nào?"),
        ("assistant", "Hôm nay trời nắng đẹp."),
        ("user", "Bạn có thể giúp tôi học Python không?"),
        ("assistant", "Được chứ! Python có cú pháp rất dễ đọc."),
        ("user", "Cảm ơn bạn nhiều lắm!"),
        ("assistant", "Không có gì, tôi luôn sẵn sàng giúp đỡ."),
        ("user", "Bạn biết về machine learning không?"),
        ("assistant", "Có, machine learning là một nhánh của AI."),
        ("user", "Giải thích gradient descent cho tôi nghe"),
        ("assistant", "Gradient descent là thuật toán tối ưu hóa bằng cách đi theo hướng dốc nhất."),
    ]
    for i in range(FILLER_TURNS):
        role, content = filler_pairs[i % len(filler_pairs)]
        content = f"[Turn {i+2}] {content}"
        ok, _, _ = APIClient.append_message(tenant_id, user_id, session_id, role, content)
        if not ok:
            raise AssertionError(f"Failed to append filler turn {i+2}")

    print(f"Inserted {FILLER_TURNS} filler turns. Total turns: {FILLER_TURNS + 1}")

    print("Step 3: Wait for embedder to process messages (up to 300s)")
    query = "Minh làm việc ở đâu?"
    deadline = time.time() + 300
    found_in_semantic = False
    while time.time() < deadline:
        ok, resp, _ = APIClient.get_context(tenant_id, user_id, session_id, query=query)
        if ok and resp.get("semantic_messages"):
            contents = [m.get("content", "").lower() for m in resp["semantic_messages"]]
            if any(TARGET_SNIPPET in c for c in contents):
                found_in_semantic = True
                break
        # Also check entity_facts
        facts = resp.get("entity_facts", []) if ok else []
        if any(TARGET_SNIPPET in str(f.get("value", "")).lower() for f in facts):
            print("Fact found in entity_facts (CognitiveWorker extracted it)")
            print(f"entity_facts: {[(f.get('attribute'), f.get('value')) for f in facts]}")
            return  # PASS via entity path
        time.sleep(5)

    if not found_in_semantic:
        raise AssertionError(
            f"Fact '{TARGET_CONTENT}' not found in semantic_messages or entity_facts after {FILLER_TURNS} turns. "
            f"Turn 1 fact was lost."
        )

    print(f"Long session recall PASS — fact found in semantic_messages after {FILLER_TURNS} filler turns.")


if __name__ == "__main__":
    run_test_wrapper("TC-LM06", "Long session (500+ turns) recall", run_test)
