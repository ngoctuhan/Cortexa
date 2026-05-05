"""
Test Case: TC-E15
Name: Entity fact relevance filtering — FTS resolves correct entity, top-K per entity
Category: Entity Extraction
Input/Setup:
  Three messages:
    (1) 'Bạn tôi Tuấn thích ăn bún bò'
    (2) 'Mẹ của Tuấn tên là Bà Ngọc'    ← different entity, should NOT appear in entity_facts
        when querying about Tuấn's food
    (3) 'Em trai Tuấn tên là Khải'       ← different entity, should NOT appear
Expected Result:
  - Query "Tuấn thích ăn gì?" → entity_facts contains Tuấn's food preference (bún bò)
  - entity_facts does NOT contain entity_name matching 'Ngọc' or 'Khải'
    (they are different entities, not matched by FTS on query "Tuấn thích ăn gì?")
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_utils import APIClient, TestHelpers, Assertions, run_test_wrapper


def run_test():
    tenant_id, user_id, session_id = TestHelpers.generate_ids()

    print("Step 1: Send food preference message for Tuấn")
    success, _, _ = APIClient.append_message(
        tenant_id, user_id, session_id,
        role="user",
        content="Bạn tôi Tuấn thích ăn bún bò",
    )
    Assertions.assert_http_code(success, context="Failed to append Tuấn food message")

    print("Step 2: Send relationship messages (different entities — potential noise)")
    success, _, _ = APIClient.append_message(
        tenant_id, user_id, session_id,
        role="user",
        content="Mẹ của Tuấn tên là Bà Ngọc",
    )
    Assertions.assert_http_code(success, context="Failed to append mother message")

    success, _, _ = APIClient.append_message(
        tenant_id, user_id, session_id,
        role="user",
        content="Em trai Tuấn tên là Khải",
    )
    Assertions.assert_http_code(success, context="Failed to append sibling message")

    print("Waiting for cognitive extraction (up to 180s)...")

    def has_tuan_food():
        ok, r, _ = APIClient.get_context(
            tenant_id, user_id, session_id,
            "Tuấn thích ăn gì?",
            memory_types=["entity_facts"],
        )
        if not ok:
            return False
        facts = r.get("entity_facts", [])
        return any(
            ("tuấn" in f.get("entity_name", "").lower() or "tuan" in f.get("entity_name", "").lower())
            and "bún bò" in f.get("value", "").lower()
            for f in facts
        )

    TestHelpers.wait_for_condition(has_tuan_food, timeout_ms=240000, poll_interval_ms=2000)

    success, resp, _ = APIClient.get_context(
        tenant_id, user_id, session_id,
        "Tuấn thích ăn gì?",
        memory_types=["entity_facts"],
    )
    Assertions.assert_http_code(success, context="GetContext failed")

    entity_facts = resp.get("entity_facts", [])
    print(f"entity_facts returned ({len(entity_facts)} facts):")
    for f in entity_facts:
        print(f"  - entity_name={f.get('entity_name')} attr={f.get('attribute')} val={f.get('value')}")

    # 1. Tuấn's food preference must be present
    tuan_food = [
        f for f in entity_facts
        if ("tuấn" in f.get("entity_name", "").lower() or "tuan" in f.get("entity_name", "").lower())
        and "bún bò" in f.get("value", "").lower()
    ]
    assert len(tuan_food) >= 1, (
        "entity_facts does not contain Tuấn's food preference (bún bò)"
    )

    # 2. Unrelated entities (Ngọc, Khải) should NOT appear — they are different entity names
    # that were not matched by FTS on "Tuấn thích ăn gì?"
    ngoc_facts = [f for f in entity_facts if "ngọc" in f.get("entity_name", "").lower() or "ngoc" in f.get("entity_name", "").lower()]
    khai_facts = [f for f in entity_facts if "khải" in f.get("entity_name", "").lower() or "khai" in f.get("entity_name", "").lower()]

    assert len(ngoc_facts) == 0, (
        f"entity_facts contains unrelated entity 'Ngọc' which should have been excluded by FTS: {ngoc_facts}"
    )
    assert len(khai_facts) == 0, (
        f"entity_facts contains unrelated entity 'Khải' which should have been excluded by FTS: {khai_facts}"
    )

    print("PASS: FTS resolved entity 'Tuấn', returned relevant food fact; unrelated entities (Ngọc, Khải) excluded")


if __name__ == "__main__":
    run_test_wrapper("TC-E15", "Entity fact relevance filtering — FTS entity resolution", run_test)
