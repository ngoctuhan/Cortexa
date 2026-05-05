"""
Test Case: TC-LM09
Name: Multi-session cross-topic recall with keyword verification
Category: LongMemEval Scenarios
Input/Setup: Ingest 7 sessions covering identity, work, finances, events, planning.
             Each new session creation triggers event-driven flush of the previous one.
             After ingestion, query across 13 questions at easy/medium/hard/very_hard levels.
Expected Result: All 13 questions return context containing the expected keywords.
                 Pass threshold: 13/13 (100%).

Questions and difficulty:
  easy      — direct single-fact recall (university, employer, phone model, order ID)
  medium    — requires combining 2 facts (total cost, monthly spend, price delta)
  hard      — requires arithmetic over extracted facts (savings, months-to-buy)
  very_hard — identity of a third party; multi-hop reasoning over time
"""

import sys, os as _os
sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import json
import time
import uuid
import requests
from test_utils import APIClient, run_test_wrapper, BASE_URL

# ── Conversation data ─────────────────────────────────────────────────────────
MESSAGES = [
    # SESSION 1 — basic profile
    {"session_id": "s1", "role": "user",      "content": "Tôi tên là Hoàng Trung."},
    {"session_id": "s1", "role": "assistant", "content": "Chào Trung, bạn đang làm gì?"},
    {"session_id": "s1", "role": "user",      "content": "Tôi là kỹ sư AI, vừa tốt nghiệp đại học Harvard."},
    {"session_id": "s1", "role": "user",      "content": "Tôi đang sống ở Hà Nội."},
    {"session_id": "s1", "role": "user",      "content": "Tôi thích cà phê sữa đá."},

    # SESSION 2 — work & salary
    {"session_id": "s2", "role": "user",      "content": "Hiện tại tôi làm việc tại công ty ABC Tech."},
    {"session_id": "s2", "role": "assistant", "content": "Mức lương của bạn thế nào?"},
    {"session_id": "s2", "role": "user",      "content": "Khoảng 3000 USD mỗi tháng."},
    {"session_id": "s2", "role": "user",      "content": "Tôi có thêm thu nhập freelance khoảng 500 USD."},
    {"session_id": "s2", "role": "user",      "content": "Tôi làm remote 3 ngày mỗi tuần."},
    {"session_id": "s2", "role": "assistant", "content": "Bạn có dự định đổi việc không?"},
    {"session_id": "s2", "role": "user",      "content": "Có thể trong năm 2027."},

    # SESSION 3 — purchase & finance
    {"session_id": "s3", "role": "user",      "content": "Tôi đã mua iPhone 15 giá 25 triệu vào ngày 10/03/2026."},
    {"session_id": "s3", "role": "user",      "content": "Mã đơn hàng là ORD-998877."},
    {"session_id": "s3", "role": "assistant", "content": "Bạn có mua bảo hành không?"},
    {"session_id": "s3", "role": "user",      "content": "Có, gói bảo hành 2 năm giá 2 triệu."},
    {"session_id": "s3", "role": "user",      "content": "Tôi cũng mua tai nghe AirPods giá 5 triệu."},
    {"session_id": "s3", "role": "user",      "content": "Bạn tôi Nam mua iPhone 14 giá 18 triệu."},
    {"session_id": "s3", "role": "assistant", "content": "Bạn chi tiêu mỗi tháng thế nào?"},
    {"session_id": "s3", "role": "user",      "content": "Khoảng 10 triệu cho sinh hoạt."},
    {"session_id": "s3", "role": "user",      "content": "Tiền thuê nhà là 6 triệu."},
    {"session_id": "s3", "role": "user",      "content": "Ăn uống khoảng 3 triệu."},
    {"session_id": "s3", "role": "user",      "content": "Còn lại là giải trí."},
    {"session_id": "s3", "role": "assistant", "content": "Bạn có tiết kiệm không?"},
    {"session_id": "s3", "role": "user",      "content": "Có, tôi tiết kiệm khoảng 15 triệu mỗi tháng."},

    # SESSION 4 — future goals
    {"session_id": "s4", "role": "user",      "content": "Tôi dự định mua xe máy giá 45 triệu vào cuối năm."},
    {"session_id": "s4", "role": "user",      "content": "Tôi muốn mua laptop mới giá 30 triệu."},
    {"session_id": "s4", "role": "assistant", "content": "Bạn có ngân sách cho du lịch không?"},
    {"session_id": "s4", "role": "user",      "content": "Có, tôi dành khoảng 10 triệu cho du lịch mỗi năm."},
    {"session_id": "s4", "role": "user",      "content": "Tôi muốn đi Nhật Bản vào tháng 12/2026."},

    # SESSION 5 — health & hobbies
    {"session_id": "s5", "role": "user",      "content": "Tôi tập gym 3 lần một tuần."},
    {"session_id": "s5", "role": "user",      "content": "Tôi đang học tiếng Anh để nâng cao kỹ năng."},
    {"session_id": "s5", "role": "assistant", "content": "Bạn có mục tiêu sức khỏe cụ thể không?"},
    {"session_id": "s5", "role": "user",      "content": "Tôi muốn chạy marathon vào năm sau."},

    # SESSION 6 — relationships
    {"session_id": "s6", "role": "user",      "content": "Tôi có bạn gái tên Minh Anh."},
    {"session_id": "s6", "role": "user",      "content": "Minh Anh làm bác sĩ tại bệnh viện Bạch Mai."},
    {"session_id": "s6", "role": "assistant", "content": "Bạn đã hẹn hò bao lâu rồi?"},
    {"session_id": "s6", "role": "user",      "content": "Được 2 năm rồi."},

    # SESSION 7 — work update
    {"session_id": "s7", "role": "user",      "content": "Tôi vừa được thăng chức lên Senior Engineer."},
    {"session_id": "s7", "role": "user",      "content": "Lương tăng thêm 500 USD."},
    {"session_id": "s7", "role": "assistant", "content": "Chúc mừng! Bạn sẽ dùng số tiền đó như thế nào?"},
    {"session_id": "s7", "role": "user",      "content": "Tôi sẽ tăng tiết kiệm và mua xe sớm hơn."},
]

# ── Questions ─────────────────────────────────────────────────────────────────
QUESTIONS = [
    {"id": "q01", "level": "easy",      "q": "User tốt nghiệp trường nào?",                          "kw": ["harvard"]},
    {"id": "q02", "level": "easy",      "q": "User làm việc ở đâu?",                                 "kw": ["abc tech"]},
    {"id": "q03", "level": "easy",      "q": "User mua điện thoại gì?",                              "kw": ["iphone 15"]},
    {"id": "q04", "level": "easy",      "q": "Mã đơn hàng iPhone là gì?",                            "kw": ["ord-998877"]},
    {"id": "q05", "level": "medium",    "q": "Tổng chi phí iPhone kèm bảo hành là bao nhiêu?",       "kw": ["25", "2", "triệu"]},
    {"id": "q06", "level": "medium",    "q": "User chi tiêu sinh hoạt mỗi tháng bao nhiêu?",         "kw": ["10", "sinh hoạt"]},
    {"id": "q07", "level": "medium",    "q": "Giá iPhone của user và Nam chênh lệch bao nhiêu?",     "kw": ["25", "18"]},
    {"id": "q08", "level": "hard",      "q": "Mỗi tháng user tiết kiệm được bao nhiêu?",             "kw": ["15"]},
    {"id": "q09", "level": "hard",      "q": "User cần bao nhiêu tháng để mua xe máy?",              "kw": ["15", "45"]},
    {"id": "q10", "level": "hard",      "q": "Nếu mua laptop thì còn lại bao nhiêu tiền tiết kiệm?", "kw": ["5 triệu"]},
    {"id": "q11", "level": "very_hard", "q": "Ai là người mua iPhone 14?",                           "kw": ["nam", "iphone 14"]},
    {"id": "q12", "level": "very_hard", "q": "User có đủ tiền mua xe vào tháng 12/2026 không?",      "kw": ["xe máy", "45"]},
    {"id": "q13", "level": "very_hard", "q": "Tổng chi tiêu lớn của user gồm những gì?",             "kw": ["iphone", "airpods"]},
]


def _has_keywords(context_str: str, keywords: list) -> tuple:
    low = context_str.lower()
    for kw in keywords:
        if kw.lower() not in low:
            return False, kw
    return True, None


def run_test():
    tenant_id = str(uuid.uuid4())
    user_id   = str(uuid.uuid4())
    session_map: dict = {}

    print(f"Tenant: {tenant_id}  User: {user_id}")

    # ── Phase 1: ingest data across 7 sessions ───────────────────────────────
    print("\n[1] Ingesting 7 sessions…")
    for msg in MESSAGES:
        s_key = msg["session_id"]
        if s_key not in session_map:
            resp = requests.post(f"{BASE_URL}/sessions", json={
                "tenant_id": tenant_id,
                "user_id":   user_id,
                "title":     f"Session {s_key}",
            })
            assert resp.status_code == 201, f"Create {s_key} failed: {resp.text}"
            session_map[s_key] = resp.json()["id"]
            print(f"  Created {s_key} → {session_map[s_key]}")

        ok, _, _ = APIClient.append_message(
            tenant_id, user_id, session_map[s_key], msg["role"], msg["content"]
        )
        assert ok, f"append_message failed for {s_key}: {msg['content'][:40]}"

    # Flush last session by creating a dummy session
    resp = requests.post(f"{BASE_URL}/sessions", json={
        "tenant_id": tenant_id, "user_id": user_id, "title": "flush",
    })
    assert resp.status_code == 201

    # ── Phase 2: wait for cognitive workers ──────────────────────────────────
    print("\n[2] Waiting 20s for LLM workers to extract facts and embeddings…")
    time.sleep(20)

    # ── Phase 3: query ───────────────────────────────────────────────────────
    print("\n[3] Running 13 recall queries…")
    passed = 0
    results = []

    for q in QUESTIONS:
        ok, ctx, latency = APIClient.get_context(
            tenant_id, user_id, str(uuid.uuid4()), q["q"]
        )
        if not ok:
            results.append(f"  ERROR  {q['id']} — API error")
            continue

        ctx_str = json.dumps(ctx, ensure_ascii=False)
        hit, missing = _has_keywords(ctx_str, q["kw"])

        if hit:
            passed += 1
            results.append(f"  PASS   {q['id']} [{q['level']}] {q['q']} ({latency:.0f}ms)")
        else:
            results.append(f"  FAIL   {q['id']} [{q['level']}] {q['q']}")
            results.append(f"           missing keyword: '{missing}'")

    print("\n".join(results))
    print(f"\nResult: {passed}/{len(QUESTIONS)} passed")
    assert passed == len(QUESTIONS), (
        f"TC-LM09 FAILED: only {passed}/{len(QUESTIONS)} recall questions answered correctly."
    )
    print("PASS")


if __name__ == "__main__":
    run_test_wrapper("TC-LM09", "Multi-session cross-topic recall with keyword verification", run_test)
