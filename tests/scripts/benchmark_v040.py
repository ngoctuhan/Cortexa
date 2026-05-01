import sys
import os
import time
import requests
import uuid
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_utils import APIClient, BASE_URL

data = [
   # ================= SESSION 1 (SHORT - BASIC PROFILE) ================= 
   { "tenant_id": "t1", "user_id": "u1", "session_id": "s1", "role": "user", "content": "Tôi tên là Hoàng Trung." }, 
   { "role": "assistant", "content": "Chào Trung, bạn đang làm gì?" }, 
   { "role": "user", "content": "Tôi là kỹ sư AI, vừa tốt nghiệp đại học Harvard." }, 
   { "role": "user", "content": "Tôi đang sống ở Hà Nội." }, 
   { "role": "user", "content": "Tôi thích cà phê sữa đá." }, 
 
   # ================= SESSION 2 (MEDIUM - WORK & SALARY) ================= 
   { "tenant_id": "t1", "user_id": "u1", "session_id": "s2", "role": "user", "content": "Hiện tại tôi làm việc tại công ty ABC Tech." }, 
   { "role": "assistant", "content": "Mức lương của bạn thế nào?" }, 
   { "role": "user", "content": "Khoảng 3000 USD mỗi tháng." }, 
   { "role": "user", "content": "Tôi có thêm thu nhập freelance khoảng 500 USD." }, 
   { "role": "user", "content": "Tôi làm remote 3 ngày mỗi tuần." }, 
   { "role": "assistant", "content": "Bạn có dự định đổi việc không?" }, 
   { "role": "user", "content": "Có thể trong năm 2027." }, 
 
   # ================= SESSION 3 (LONG - PURCHASE & FINANCE) ================= 
   { "tenant_id": "t1", "user_id": "u1", "session_id": "s3", "role": "user", "content": "Tôi đã mua iPhone 15 giá 25 triệu vào ngày 10/03/2026." }, 
   { "role": "user", "content": "Mã đơn hàng là ORD-998877." }, 
   { "role": "assistant", "content": "Bạn có mua bảo hành không?" }, 
   { "role": "user", "content": "Có, gói bảo hành 2 năm giá 2 triệu." }, 
   { "role": "user", "content": "Tôi cũng mua tai nghe AirPods giá 5 triệu." }, 
   { "role": "user", "content": "Bạn tôi Nam mua iPhone 14 giá 18 triệu." }, 
   { "role": "assistant", "content": "Bạn chi tiêu mỗi tháng thế nào?" }, 
   { "role": "user", "content": "Khoảng 10 triệu cho sinh hoạt." }, 
   { "role": "user", "content": "Tiền thuê nhà là 6 triệu." }, 
   { "role": "user", "content": "Ăn uống khoảng 3 triệu." }, 
   { "role": "user", "content": "Còn lại là giải trí." }, 
   { "role": "assistant", "content": "Bạn có tiết kiệm không?" }, 
   { "role": "user", "content": "Tôi tiết kiệm khoảng 15 triệu mỗi tháng." }, 
   { "role": "user", "content": "Tôi muốn mua xe máy giá 45 triệu." }, 
   { "role": "assistant", "content": "Bạn định mua khi nào?" }, 
   { "role": "user", "content": "Tháng 12 năm 2026." }, 
 
   # ================= SESSION 4 (NOISE + MULTI ENTITY) ================= 
   { "tenant_id": "t1", "user_id": "u1", "session_id": "s4", "role": "user", "content": "Công ty XYZ đang tuyển AI Engineer lương 5000 USD." }, 
   { "role": "assistant", "content": "Bạn có quan tâm không?" }, 
   { "role": "user", "content": "Có nhưng chưa apply." }, 
   { "role": "user", "content": "Bạn tôi Linh làm ở đó lương 4800 USD." }, 
   { "role": "user", "content": "Cô ấy làm onsite." }, 
   { "role": "assistant", "content": "Bạn thích remote hay onsite?" }, 
   { "role": "user", "content": "Tôi thích hybrid." }, 
 
   # ================= SESSION 5 (TEMPORAL + EVENTS) ================= 
   { "tenant_id": "t1", "user_id": "u1", "session_id": "s5", "role": "user", "content": "Tháng 1/2026 tôi có 20 triệu tiết kiệm." }, 
   { "role": "user", "content": "Tháng 2 tôi tiết kiệm thêm 15 triệu." }, 
   { "role": "user", "content": "Tháng 3 tôi mua iPhone nên giảm còn 10 triệu." }, 
   { "role": "assistant", "content": "Hiện tại bạn có bao nhiêu?" }, 
   { "role": "user", "content": "Khoảng 25 triệu." }, 
 
   # ================= SESSION 6 (RANDOM FACT + DISTRACTION) ================= 
   { "tenant_id": "t1", "user_id": "u1", "session_id": "s6", "role": "user", "content": "Tôi thích đi du lịch Đà Nẵng." }, 
   { "role": "user", "content": "Năm ngoái tôi đi 2 lần." }, 
   { "role": "assistant", "content": "Bạn chi bao nhiêu cho mỗi chuyến?" }, 
   { "role": "user", "content": "Khoảng 8 triệu mỗi chuyến." }, 
   { "role": "user", "content": "Bạn tôi Nam đi 1 lần hết 5 triệu." }, 
 
   # ================= SESSION 7 (LONG - MIX EVERYTHING) ================= 
   { "tenant_id": "t1", "user_id": "u1", "session_id": "s7", "role": "user", "content": "Tôi đang cân nhắc mua laptop mới giá 30 triệu." }, 
   { "role": "assistant", "content": "Bạn có đủ tiền không?" }, 
   { "role": "user", "content": "Nếu mua thì sẽ giảm tiền tiết kiệm xuống còn 5 triệu." }, 
   { "role": "user", "content": "Tôi đang phân vân giữa MacBook và Dell." }, 
   { "role": "assistant", "content": "Bạn dùng cho mục đích gì?" }, 
   { "role": "user", "content": "Chủ yếu là training model và coding." }, 
   { "role": "user", "content": "Công ty có hỗ trợ 10 triệu nếu mua laptop." }, 
   { "role": "assistant", "content": "Vậy chi phí thực tế là bao nhiêu?" }, 
   { "role": "user", "content": "Khoảng 20 triệu." }, 
   { "role": "user", "content": "Tôi dự định mua vào tháng 6/2026." } 
]

questions = [
   { "id": "q1", "level": "easy", "question": "User tốt nghiệp trường nào?", "answer": "Harvard", "keywords": ["harvard"] }, 
   { "id": "q2", "level": "easy", "question": "User làm việc ở đâu?", "answer": "ABC Tech", "keywords": ["abc tech"] }, 
   { "id": "q3", "level": "easy", "question": "User mua điện thoại gì?", "answer": "iPhone 15", "keywords": ["iphone 15"] }, 
   { "id": "q4", "level": "easy", "question": "Mã đơn hàng là gì?", "answer": "ORD-998877", "keywords": ["ord-998877"] }, 
   { "id": "q5", "level": "medium", "question": "Tổng chi phí iPhone + bảo hành là bao nhiêu?", "answer": "27 triệu", "keywords": ["25", "2", "triệu"] }, 
   { "id": "q6", "level": "medium", "question": "User chi tiêu mỗi tháng bao nhiêu?", "answer": "10 triệu", "keywords": ["10", "sinh hoạt"] }, 
   { "id": "q7", "level": "medium", "question": "Giá iPhone của user và Nam chênh lệch bao nhiêu?", "answer": "7 triệu", "keywords": ["25", "18"] }, 
   { "id": "q8", "level": "hard", "question": "Mỗi tháng user tiết kiệm được bao nhiêu (sau chi tiêu)?", "answer": "khoảng 15 triệu", "keywords": ["15"] }, 
   { "id": "q9", "level": "hard", "question": "User cần bao nhiêu tháng để mua xe máy?", "answer": "3 tháng", "keywords": ["15", "45"] }, 
   { "id": "q10", "level": "hard", "question": "Nếu mua laptop thì còn lại bao nhiêu tiền tiết kiệm?", "answer": "5 triệu", "keywords": ["5 triệu"] }, 
   { "id": "q11", "level": "very_hard", "question": "Ai là người mua iPhone 14?", "answer": "Nam", "keywords": ["nam", "iphone 14"] }, 
   { "id": "q12", "level": "very_hard", "question": "User có đủ tiền mua xe vào tháng 12/2026 không?", "answer": "Có", "keywords": ["xe máy", "45", "12"] }, 
   { "id": "q13", "level": "very_hard", "question": "Tổng chi tiêu lớn của user gồm những gì?", "answer": "iPhone, bảo hành, AirPods, sinh hoạt, du lịch", "keywords": ["iphone", "airpods"] } 
]

def check_keywords_in_context(context_str, keywords):
    context_lower = context_str.lower()
    for kw in keywords:
        if kw.lower() not in context_lower:
            return False, kw
    return True, None

def run_benchmark():
    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    
    print(f"--- RUNNING CORTEXA V0.4.0 BENCHMARK ---")
    print(f"Tenant ID: {tenant_id}")
    print(f"User ID: {user_id}")
    
    # 1. Ingest Data
    print("\n[1] Ingesting 7 Sessions of Data...")
    session_map = {}
    
    for msg in data:
        # Determine which session this belongs to based on data order
        s_key = msg.get("session_id", "current")
        if "session_id" in msg:
            s_key = msg["session_id"]
            
            if s_key not in session_map:
                # Create a new session in DB. This will trigger Event-Driven flush for the previous one!
                new_sess_id = str(uuid.uuid4())
                session_map[s_key] = new_sess_id
                requests.post(f"{BASE_URL}/sessions", json={
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "title": f"Session {s_key}"
                })
                print(f"  -> Created {s_key} (ID: {new_sess_id})")
                
        # Use the mapped session ID, or the last one created
        actual_session_id = session_map.get(s_key)
        
        APIClient.append_message(
            tenant_id, user_id, actual_session_id, 
            msg["role"], msg["content"]
        )

    # Create one final dummy session to flush session 7
    print("  -> Creating dummy session to trigger flush for s7")
    requests.post(f"{BASE_URL}/sessions", json={
        "tenant_id": tenant_id,
        "user_id": user_id,
        "title": "Dummy Flush Session"
    })
    
    # 2. Wait for Cognitive Workers to process everything
    print("\n[2] Waiting 20 seconds for LLM Workers to extract facts and embeddings...")
    time.sleep(20)
    
    # 3. Query Phase
    print("\n[3] Testing Questions against Retrieved Context...")
    
    passed_count = 0
    results_log = []
    
    for q in questions:
        # We use a random session_id for querying to simulate a new chat
        query_session_id = str(uuid.uuid4())
        success, context_data, latency = APIClient.get_context(
            tenant_id, user_id, query_session_id, q["question"]
        )
        
        if not success:
            results_log.append(f"❌ {q['id']} ({q['level']}): API Error")
            continue
        
        # Convert context data to a single string for keyword searching
        context_str = json.dumps(context_data, ensure_ascii=False)
        
        # Check if context contains necessary information
        has_info, missing_kw = check_keywords_in_context(context_str, q["keywords"])
        
        if has_info:
            passed_count += 1
            results_log.append(f"✅ {q['id']} [{q['level'].upper()}]: {q['question']} ({latency:.0f}ms)")
            
        else:
            print(context_str)
            results_log.append(f"❌ {q['id']} [{q['level'].upper()}]: {q['question']}")
            results_log.append(f"    Expected answer: {q['answer']}")
            results_log.append(f"    Missing keyword in context: '{missing_kw}'")
            # results_log.append(f"    Context Dump: {context_str[:200]}...") # truncate for display

    print("\n" + "="*50)
    print(f"BENCHMARK RESULTS: {passed_count}/{len(questions)} PASSED")
    print("="*50)
    for res in results_log:
        print(res)

if __name__ == "__main__":
    run_benchmark()